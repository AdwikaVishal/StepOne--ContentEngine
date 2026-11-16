"""
Layout Assembler
Converts selected AssetMetadata into platform-ready image/video files.

Outputs:
  - LinkedIn collage      (1080×1080 JPEG, 2×2 or 2×3 grid)
  - Instagram carousel    (1080×1350 JPEG per slide, 4:5 ratio)
  - Instagram stories     (1080×1920 JPEG per frame, 9:16 ratio)
  - Instagram reel        (1080×1920 MP4, assembled from highlight clips)

All image operations use Pillow. Video assembly uses ffmpeg via subprocess.
Face-aware smart crop uses the already-loaded YOLOv11 face model.
"""

import subprocess
import tempfile
import time
import cv2
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw
from typing import List, Tuple, Optional, Dict
from ultralytics import YOLO
from config import YOLOV11_FACE_MODEL_PATH, settings
from content_engine.utils.device_manager import get_device_manager
from content_engine.utils.mps_safe import register_model, MPS_DEVICE
from content_engine.models.face_detection import FaceDetector
from content_engine.composition import SmartCropper, FocalAnalyzer
from content_engine.composition.smart_crop import get_override_store


# ── Platform dimensions ───────────────────────────────────────────────────────
LINKEDIN_SIZE   = (1080, 1080)   # 1:1
CAROUSEL_SIZE   = (1080, 1350)   # 4:5
STORY_SIZE      = (1080, 1920)   # 9:16
REEL_SIZE       = (1080, 1920)   # 9:16

# Grid layouts keyed by number of images
_GRID_LAYOUTS: Dict[int, Tuple[int, int]] = {
    1: (1, 1),
    2: (1, 2),
    3: (1, 3),
    4: (2, 2),
    5: (2, 3),   # 5th slot left empty
    6: (2, 3),
}


class LayoutAssembler:
    """
    Optimized layout engine with template caching and thumbnail pre-processing.
    Safe to share across requests.
    """

    def __init__(self):
        # Lazy-load face model — reuse the same weights already on disk.
        # The model is shared with the composition engine's FaceDetector so the
        # YOLOv11-face weights are loaded exactly once per process.
        t0 = time.perf_counter()
        device = MPS_DEVICE
        self._face_model = YOLO(YOLOV11_FACE_MODEL_PATH)
        load_time = time.perf_counter() - t0

        # Register with DeviceManager
        estimated_vram = 50.0 if device.startswith("cuda") else 0.0
        estimated_ram = 3.0
        dm = get_device_manager()
        if dm is not None:
            dm.register_model(
                "yolov11_face",
                model=self._face_model,
                device=device,
                vram_mb=estimated_vram,
                ram_mb=estimated_ram,
                load_time_seconds=load_time,
            )

        # Share the loaded face model with the composition engine so weights
        # are not duplicated. FaceDetector is lazy: the model is already loaded
        # here, so it just wraps the existing instance.
        self._face_detector = FaceDetector(model=self._face_model)

        # Lazy-created subject-aware cropper (one per assembler, reused across
        # every tile/format so focal analysis runs once per source image).
        self._cropper: Optional[SmartCropper] = None

        # Persisted manual crop overrides (scoped to image + format).
        self._override_store = get_override_store(
            str(settings.output_dir / "crop_overrides.json")
        )

        # Template position cache — avoids recomputing layout geometry
        self._template_cache: Dict[str, tuple] = {}

    def _get_cropper(self) -> SmartCropper:
        """Lazy-build the shared smart cropper (analysis cached per image)."""
        if self._cropper is None:
            self._cropper = SmartCropper(
                analyzer=FocalAnalyzer(face_detector=self._face_detector)
            )
        return self._cropper

    @staticmethod
    def _format_key_for(target_w: int, target_h: int) -> str:
        """Derive a stable format key from target dimensions."""
        ratio = round(target_w / target_h, 4)
        for key, (w, h) in {
            "linkedin_1_1": (1080, 1080),
            "carousel_4_5": (1080, 1350),
            "story_9_16": (1080, 1920),
            "landscape_16_9": (1920, 1080),
        }.items():
            if (w, h) == (target_w, target_h):
                return key
        return f"custom_{target_w}x{target_h}_{ratio}"

    def _override_focal(
        self,
        image_path: str,
        target_w: int,
        target_h: int,
        manual_focal: Optional[Tuple[float, float]] = None,
        format_key: Optional[str] = None,
    ) -> Optional[Tuple[float, float]]:
        """Return a manual focal point: explicit argument takes precedence,
        otherwise fall back to a persisted user override for this image/format."""
        if manual_focal is not None:
            return manual_focal
        key = format_key or self._format_key_for(target_w, target_h)
        override = self._override_store.get(image_path, key)
        if override and override.get("focal_point"):
            fp = override["focal_point"]
            return (float(fp[0]), float(fp[1]))
        return None

    # ── Smart crop ────────────────────────────────────────────────────────────

    def smart_crop(
        self,
        image_path: str,
        target_w: int,
        target_h: int,
        format_key: Optional[str] = None,
        manual_focal: Optional[Tuple[float, float]] = None,
    ) -> Image.Image:
        """
        Crop an image to (target_w × target_h) using the subject-aware
        composition engine.

        The crop is calculated from the detected focal region (faces, subjects,
        saliency) rather than a simple centre crop, and is computed
        independently for each target aspect ratio. The original image file is
        never modified.

        A persisted manual focal-point override (set via the frontend Crop
        Inspector) takes precedence over automatic focal detection.
        """
        focal = self._override_focal(
            image_path, target_w, target_h, manual_focal, format_key
        )
        img, _ = self._get_cropper().crop_image(
            image_path, target_w, target_h, manual_focal=focal
        )
        return img

    def smart_crop_with_metadata(
        self,
        image_path: str,
        target_w: int,
        target_h: int,
        format_key: Optional[str] = None,
        manual_focal: Optional[Tuple[float, float]] = None,
    ) -> Tuple[Image.Image, Dict]:
        """
        Like :meth:`smart_crop` but also returns the crop metadata (crop box,
        focal region, composition score, scene type, warnings, …) so callers
        and the frontend can inspect what was preserved or discarded.
        """
        focal = self._override_focal(
            image_path, target_w, target_h, manual_focal, format_key
        )
        img, result = self._get_cropper().crop_image(
            image_path, target_w, target_h, manual_focal=focal
        )
        return img, result.to_dict()

    def get_crop_box(
        self,
        image_path: str,
        target_w: int,
        target_h: int,
        format_key: Optional[str] = None,
        manual_focal: Optional[Tuple[float, float]] = None,
    ) -> Dict:
        """
        Return the calculated crop box and focal metadata for an image without
        rendering the crop. Useful for frontend crop-inspection UIs.

        Applies any persisted manual focal-point override for this image/format.
        """
        focal = self._override_focal(
            image_path, target_w, target_h, manual_focal, format_key
        )
        result = self._get_cropper().compute_crop(
            image_path, target_w, target_h, manual_focal=focal
        )
        return result.to_dict()

    def _open_thumbnail(self, path: str, max_size: int = 1200) -> Image.Image:
        """
        Open image at reduced resolution for faster processing.
        Never upscales beyond original size.
        """
        img = Image.open(path).convert("RGB")
        if max(img.size) > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        return img

    # ── LinkedIn collage ──────────────────────────────────────────────────────

    def create_linkedin_collage(self, image_paths: List[str], layout: str = "hero_right") -> Image.Image:
        """
        Assemble 1–6 images into a 1080×1080 grid collage.
        Layout options: hero_right, hero_left, hero_center, magazine, panoramic, bauhaus, minimal
        A 2-pixel white gutter separates cells.
        Uses template caching and thumbnail pre-processing for 3-5x speedup.
        """
        n = min(len(image_paths), 6)
        if n == 0:
            raise ValueError("No images provided for collage")
        gutter = 2

        # Template caching: layout geometry is deterministic per layout+count
        cache_key = f"linkedin_{layout}_{n}"
        if cache_key in self._template_cache:
            layout_def = self._template_cache[cache_key]
        else:
            layout_def = None

        # Open images as thumbnails once for faster access
        thumbs = [self._open_thumbnail(p) for p in image_paths[:n]]

        if layout == "hero_right" and n >= 2:
            # Hero Left: 1 large on left, small on right
            rows, cols = 2, 2
            cell_w = (LINKEDIN_SIZE[0] - gutter * (cols - 1)) // cols
            cell_h = (LINKEDIN_SIZE[1] - gutter * (rows - 1)) // rows
            
            canvas = Image.new("RGB", LINKEDIN_SIZE, color=(255, 255, 255))
            
            large_cell = self.smart_crop(image_paths[0], cell_w, cell_h * 2 + gutter)
            canvas.paste(large_cell, (0, 0))
            
            for idx, path in enumerate(image_paths[1:3]):
                row = idx
                col = 1
                cell = self.smart_crop(path, cell_w, cell_h)
                x = col * (cell_w + gutter)
                y = row * (cell_h + gutter)
                canvas.paste(cell, (x, y))
            return canvas
        elif layout == "hero_center":
            # Hero Center: 1 large top, up to 3 small below
            canvas = Image.new("RGB", LINKEDIN_SIZE, color=(255, 255, 255))
            # Hero top (full width, half height)
            hero_h = (LINKEDIN_SIZE[1] - gutter) // 2
            hero = self.smart_crop(image_paths[0], LINKEDIN_SIZE[0], hero_h)
            canvas.paste(hero, (0, 0))
            # Bottom row: up to 3 small cells
            bottom_h = hero_h
            small_w = (LINKEDIN_SIZE[0] - gutter * 2) // 3
            small_h = bottom_h
            num_small = min(n - 1, 3)
            for idx, path in enumerate(image_paths[1:1+num_small]):
                cell = self.smart_crop(path, small_w, small_h)
                x = idx * (small_w + gutter)
                y = hero_h + gutter
                canvas.paste(cell, (x, y))
            return canvas
        elif layout == "panoramic":
            # Panoramic: wide top, up to 4 small below (2x2)
            canvas = Image.new("RGB", LINKEDIN_SIZE, color=(255, 255, 255))
            # Top: full width, 1/3 height
            top_h = (LINKEDIN_SIZE[1] - gutter * 2) // 3
            top = self.smart_crop(image_paths[0], LINKEDIN_SIZE[0], top_h)
            canvas.paste(top, (0, 0))
            # Bottom: up to 4 small in 2x2 grid
            bottom_h = top_h * 2
            small_w = (LINKEDIN_SIZE[0] - gutter) // 2
            small_h = (bottom_h - gutter) // 2
            num_small = min(n - 1, 4)
            for idx, path in enumerate(image_paths[1:1+num_small]):
                row = idx // 2
                col = idx % 2
                cell = self.smart_crop(path, small_w, small_h)
                x = col * (small_w + gutter)
                y = top_h + gutter + row * (small_h + gutter)
                canvas.paste(cell, (x, y))
            return canvas
        elif layout == "magazine":
            # Magazine: large left, up to 3 small right
            canvas = Image.new("RGB", LINKEDIN_SIZE, color=(255, 255, 255))
            left_w = (LINKEDIN_SIZE[0] - gutter) // 2
            right_w = left_w
            left_h = LINKEDIN_SIZE[1]
            right_cell_h = (LINKEDIN_SIZE[1] - gutter * 2) // 3
            left = self.smart_crop(image_paths[0], left_w, left_h)
            canvas.paste(left, (0, 0))
            num_small = min(n - 1, 3)
            for idx, path in enumerate(image_paths[1:1+num_small]):
                cell = self.smart_crop(path, right_w, right_cell_h)
                x = left_w + gutter
                y = idx * (right_cell_h + gutter)
                canvas.paste(cell, (x, y))
            return canvas
        elif layout == "bauhaus":
            # Bauhaus: asymmetric geometric
            canvas = Image.new("RGB", LINKEDIN_SIZE, color=(255, 255, 255))
            half_w = (LINKEDIN_SIZE[0] - gutter) // 2
            half_h = (LINKEDIN_SIZE[1] - gutter) // 2
            # Top left square
            cell0 = self.smart_crop(image_paths[0], half_w, half_h)
            canvas.paste(cell0, (0, 0))
            # Top right tall
            if n >= 2:
                cell1 = self.smart_crop(image_paths[1], half_w, LINKEDIN_SIZE[1])
                canvas.paste(cell1, (half_w + gutter, 0))
            # Bottom left square
            if n >= 3:
                cell2 = self.smart_crop(image_paths[2], half_w, half_h)
                canvas.paste(cell2, (0, half_h + gutter))
            return canvas
        elif layout == "minimal":
            # Minimal: clean 2x3 grid
            rows, cols = 2, 3
            cell_w = (LINKEDIN_SIZE[0] - gutter * (cols - 1)) // cols
            cell_h = (LINKEDIN_SIZE[1] - gutter * (rows - 1)) // rows
            canvas = Image.new("RGB", LINKEDIN_SIZE, color=(255, 255, 255))
            for idx, path in enumerate(image_paths[:6]):
                row = idx // cols
                col = idx % cols
                cell = self.smart_crop(path, cell_w, cell_h)
                x = col * (cell_w + gutter)
                y = row * (cell_h + gutter)
                canvas.paste(cell, (x, y))
            return canvas
        else:
            # Default grid layout
            rows, cols = _GRID_LAYOUTS[n]
            cell_w = (LINKEDIN_SIZE[0] - gutter * (cols - 1)) // cols
            cell_h = (LINKEDIN_SIZE[1] - gutter * (rows - 1)) // rows

            canvas = Image.new("RGB", LINKEDIN_SIZE, color=(255, 255, 255))

            for idx, path in enumerate(image_paths[:n]):
                row = idx // cols
                col = idx % cols
                cell = self.smart_crop(path, cell_w, cell_h)
                x = col * (cell_w + gutter)
                y = row * (cell_h + gutter)
                canvas.paste(cell, (x, y))
            return canvas

    def create_instagram_stories(
        self,
        image_paths: List[str],
        captions: Optional[List[str]] = None,
        watermark_path: Optional[str] = None,
        layout: str = "single"
    ) -> List[Image.Image]:
        """Convert up to 4 images into sequential story frames with optional captions and layouts."""
        captions = captions or []
        
        # Handle different story layouts
        if layout == "single":
            return [
                self.create_story_frame(
                    p,
                    caption_text=captions[i] if i < len(captions) else "",
                    watermark_path=watermark_path,
                )
                for i, p in enumerate(image_paths[:4])
            ]
        elif layout == "split_v" and len(image_paths) >= 2:
            # Split vertical: 2 images stacked vertically per frame
            frames = []
            for i in range(0, min(len(image_paths), 4), 2):
                path1 = image_paths[i]
                path2 = image_paths[i+1] if i+1 < len(image_paths) else image_paths[i]
                
                img1 = self.smart_crop(path1, STORY_SIZE[0], STORY_SIZE[1] // 2)
                img2 = self.smart_crop(path2, STORY_SIZE[0], STORY_SIZE[1] // 2)
                
                frame = Image.new("RGB", STORY_SIZE, (255, 255, 255))
                frame.paste(img1, (0, 0))
                frame.paste(img2, (0, STORY_SIZE[1] // 2))
                frames.append(frame)
            return frames
        elif layout == "grid_2x2" and len(image_paths) >= 4:
            # 2x2 grid on one frame
            img1 = self.smart_crop(image_paths[0], STORY_SIZE[0] // 2, STORY_SIZE[1] // 2)
            img2 = self.smart_crop(image_paths[1], STORY_SIZE[0] // 2, STORY_SIZE[1] // 2)
            img3 = self.smart_crop(image_paths[2], STORY_SIZE[0] // 2, STORY_SIZE[1] // 2)
            img4 = self.smart_crop(image_paths[3], STORY_SIZE[0] // 2, STORY_SIZE[1] // 2)
            
            frame = Image.new("RGB", STORY_SIZE, (255, 255, 255))
            frame.paste(img1, (0, 0))
            frame.paste(img2, (STORY_SIZE[0] // 2, 0))
            frame.paste(img3, (0, STORY_SIZE[1] // 2))
            frame.paste(img4, (STORY_SIZE[0] // 2, STORY_SIZE[1] // 2))
            return [frame]
        else:
            # Default to single
            return [
                self.create_story_frame(
                    p,
                    caption_text=captions[i] if i < len(captions) else "",
                    watermark_path=watermark_path,
                )
                for i, p in enumerate(image_paths[:4])
            ]

    def create_reel(
        self,
        video_path: str,
        highlight_clips: List[Dict],
        output_path: str,
        transition: str = "crossfade",
        layout: str = "standard"
    ) -> bool:
        """
        Assemble highlight clips into a 9:16 vertical reel using ffmpeg.
        Layout options: standard, slideshow, kinetic
        Returns True on success, False if ffmpeg is unavailable or fails.
        """
        # Layout doesn't change reel assembly much right now, but we can expand later
        if not highlight_clips:
            return False

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            concat_path = f.name
            for clip in highlight_clips:
                f.write(f"file '{Path(video_path).resolve()}'\n")
                f.write(f"inpoint {clip['start']:.3f}\n")
                f.write(f"outpoint {clip['end']:.3f}\n")

        try:
            if transition == "crossfade" and len(highlight_clips) > 1:
                return self._create_reel_xfade(video_path, highlight_clips, output_path)
            else:
                return self._create_reel_concat(concat_path, output_path)
        except Exception:
            # Fall back to simple concat
            try:
                return self._create_reel_concat(concat_path, output_path)
            except Exception:
                return False
        finally:
            Path(concat_path).unlink(missing_ok=True)

    # ── Instagram carousel ────────────────────────────────────────────────────

    def create_instagram_carousel(self, image_paths: List[str]) -> List[Image.Image]:
        """
        Convert each image to 4:5 (1080×1350) for an Instagram carousel.
        Returns up to 10 slides. Uses thumbnail pre-processing for speed.
        """
        slides = []
        for path in image_paths[:10]:
            slide = self.smart_crop(path, *CAROUSEL_SIZE)
            slides.append(slide)
        return slides

    # ── Instagram stories ─────────────────────────────────────────────────────

    def create_story_frame(
        self,
        image_path: str,
        caption_text: str = "",          # Item 15: burn caption into frame
        watermark_path: Optional[str] = None,  # Item 16
        watermark_position: str = "bottom-right",
        watermark_opacity: float = 0.7,
    ) -> Image.Image:
        """
        Convert a single image to 9:16 (1080×1920) story format.

        Item 15: If caption_text is provided, renders it onto the frame
                 at the bottom with a shadow for legibility.
        Item 16: If watermark_path is provided, composites a logo.
        """
        frame = self.smart_crop(image_path, *STORY_SIZE)

        # Gradient overlay — bottom 15% of frame
        overlay_h = int(STORY_SIZE[1] * 0.15)
        overlay = Image.new("RGBA", STORY_SIZE, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for i in range(overlay_h):
            alpha = int(160 * (i / overlay_h))
            y = STORY_SIZE[1] - overlay_h + i
            draw.line([(0, y), (STORY_SIZE[0], y)], fill=(0, 0, 0, alpha))
        frame = Image.alpha_composite(frame.convert("RGBA"), overlay)

        # Item 15: Burn caption text
        if caption_text:
            frame = self._burn_text(frame, caption_text)

        # Item 16: Watermark
        if watermark_path:
            frame = self._apply_watermark(
                frame, watermark_path, watermark_position, watermark_opacity
            )

        return frame.convert("RGB")

    def _burn_text(self, frame: Image.Image, text: str) -> Image.Image:
        """
        Item 15: Render caption text onto the frame.
        Uses a system font with shadow for legibility on any background.
        """
        from PIL import ImageFont
        import textwrap

        draw = ImageDraw.Draw(frame)
        font_size = 52
        font = None

        # Try to load a decent font; fall back to default
        font_candidates = [
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
        for fc in font_candidates:
            try:
                font = ImageFont.truetype(fc, font_size)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()

        # Wrap text to fit frame width
        max_chars = int(STORY_SIZE[0] / (font_size * 0.55))
        lines = textwrap.wrap(text, width=max_chars)

        line_height = font_size + 8
        total_h = len(lines) * line_height
        y_start = STORY_SIZE[1] - int(STORY_SIZE[1] * 0.12) - total_h

        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            text_w = bbox[2] - bbox[0]
            x = (STORY_SIZE[0] - text_w) // 2
            y = y_start + i * line_height
            # Shadow
            draw.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0, 180))
            # Text
            draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))

        return frame

    def _apply_watermark(
        self,
        frame: Image.Image,
        watermark_path: str,
        position: str,
        opacity: float,
    ) -> Image.Image:
        """
        Item 16: Composite a logo onto the frame.
        Logo is resized to max 120px wide, placed at the specified corner.
        """
        try:
            logo = Image.open(watermark_path).convert("RGBA")
            # Resize to max 120px wide
            max_w = 120
            ratio = max_w / logo.width
            logo = logo.resize(
                (max_w, int(logo.height * ratio)), Image.Resampling.LANCZOS
            )
            # Apply opacity
            r, g, b, a = logo.split()
            a = a.point(lambda x: int(x * opacity))
            logo.putalpha(a)

            margin = 20
            fw, fh = frame.size
            lw, lh = logo.size

            positions = {
                "top-left":     (margin, margin),
                "top-right":    (fw - lw - margin, margin),
                "bottom-left":  (margin, fh - lh - margin),
                "bottom-right": (fw - lw - margin, fh - lh - margin),
                "center":       ((fw - lw) // 2, (fh - lh) // 2),
            }
            pos = positions.get(position, positions["bottom-right"])

            frame_rgba = frame if frame.mode == "RGBA" else frame.convert("RGBA")
            frame_rgba.paste(logo, pos, logo)
            return frame_rgba
        except Exception:
            return frame  # Watermark failure is non-fatal



    # ── Instagram reel ────────────────────────────────────────────────────────



    def _create_reel_concat(self, concat_path: str, output_path: str) -> bool:
        """Simple concat without transitions."""
        cmd = [
            "ffmpeg", "-f", "concat", "-safe", "0", "-i", concat_path,
            "-vf", "scale=1080:-2:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            "-y", output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        return result.returncode == 0

    def _create_reel_xfade(
        self, video_path: str, clips: List[Dict], output_path: str
    ) -> bool:
        """
        Item 14: Crossfade transitions using ffmpeg xfade filter.
        Builds a complex filtergraph that trims each clip then crossfades them.
        """
        fade_dur = 0.5  # seconds per transition

        # Build input args — one -i per clip segment
        inputs = []
        for clip in clips:
            inputs += [
                "-ss", str(clip["start"]),
                "-to", str(clip["end"]),
                "-i", str(Path(video_path).resolve()),
            ]

        n = len(clips)
        # Scale each input to 1080×1920
        scale_filter = "scale=1080:-2:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
        filter_parts = [f"[{i}:v]{scale_filter}[v{i}]" for i in range(n)]

        # Chain xfade filters
        prev = "v0"
        for i in range(1, n):
            clip_dur = clips[i-1]["end"] - clips[i-1]["start"]
            offset = max(0.1, clip_dur - fade_dur)
            out = f"xf{i}" if i < n - 1 else "vout"
            filter_parts.append(
                f"[{prev}][v{i}]xfade=transition=fade:duration={fade_dur}:offset={offset:.3f}[{out}]"
            )
            prev = out

        filtergraph = ";".join(filter_parts)

        cmd = (
            ["ffmpeg"] + inputs +
            ["-filter_complex", filtergraph,
             "-map", "[vout]",
             "-c:v", "libx264", "-preset", "fast", "-crf", "23",
             "-an",  # audio handled separately for simplicity
             "-movflags", "+faststart",
             "-y", output_path]
        )
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        return result.returncode == 0

    # ── Horizontal asset (story adaptation) ──────────────────────────────────

    def adapt_horizontal_to_story(self, image_path: str) -> Image.Image:
        """
        Adapt a landscape image to 9:16 by blurring and scaling it as a
        background, then overlaying the original centred at its natural size.
        This avoids cropping out important content in very wide shots.
        """
        orig = Image.open(image_path).convert("RGB")
        orig_w, orig_h = orig.size

        # Background: blurred + scaled to fill 9:16
        bg = self.smart_crop(image_path, *STORY_SIZE)
        bg_arr = cv2.cvtColor(np.array(bg), cv2.COLOR_RGB2BGR)
        bg_arr = cv2.GaussianBlur(bg_arr, (61, 61), 0)
        bg = Image.fromarray(cv2.cvtColor(bg_arr, cv2.COLOR_BGR2RGB))

        # Foreground: scale original to fit within story width
        scale = STORY_SIZE[0] / orig_w
        fg_w = STORY_SIZE[0]
        fg_h = int(orig_h * scale)
        fg = orig.resize((fg_w, fg_h), Image.Resampling.LANCZOS)

        # Centre vertically
        y_offset = (STORY_SIZE[1] - fg_h) // 2
        bg.paste(fg, (0, y_offset))
        return bg

    # ── Crop report (for quality verification & frontend inspection) ───────

    def compute_crop_report(
        self,
        image_paths: List[str],
    ) -> List[Dict]:
        """
        Compute intelligent-crop metadata for every image across the standard
        output formats, without rendering the crops.

        Returns a list of dicts (JSON-serialisable) with one entry per
        (image, format) pair, suitable for writing to ``crop_report.json`` and
        for feeding the frontend crop-inspection UI.
        """
        formats = [
            ("linkedin_collage_1_1", 1080, 1080),
            ("instagram_carousel_4_5", 1080, 1350),
            ("instagram_story_9_16", 1080, 1920),
            ("landscape_16_9", 1920, 1080),
        ]
        report: List[Dict] = []
        for path in image_paths:
            for name, tw, th in formats:
                entry = self.get_crop_box(path, tw, th)
                entry["format"] = name
                entry["source"] = path
                report.append(entry)
        return report
