"""
Gemini vision provider — cloud image understanding for cloud_testing mode.

Uses the current official Google Gen AI SDK (google-genai).
Lazy-imported so local mode never imports it.

Image workflow:
  1. Upload local file via client.files.upload(file=local_path)
  2. Poll client.files.get(name=file.name) until File.State.ACTIVE
  3. Generate via client.models.generate_content(model=..., contents=[file, prompt])
  4. Delete file via client.files.delete(name=file.name) in finally block

Video understanding is DEFERRED: understand_video() raises UnsupportedFeatureError
until the google-genai SDK video workflow is verified against the installed SDK.
"""

import os
import time
from typing import Any, Dict, List, Optional

from content_engine.ai_mode import ConfigurationError, require_cloud_key
from content_engine.providers.base import UnsupportedFeatureError, ProviderTimeoutError
from config import settings


class GeminiVisionProvider:
    """Gemini multimodal vision provider."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or require_cloud_key("GEMINI_API_KEY")
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from google import genai
            except ImportError as exc:
                raise ConfigurationError(
                    "google-genai SDK is not installed. Install it with "
                    "'pip install google-genai' or switch AI_EXECUTION_MODE to 'local'."
                ) from exc
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    # ── Image understanding ──────────────────────────────────────────

    def understand_image(self, image_path: str) -> Dict[str, Any]:
        """Return scene understanding using Gemini multimodal.

        Schema:
          {
            "scene_concepts": List[str],
            "relevance_scores": Dict[str, float],
            "concept_match_score": float,
            "provider": "gemini",
            "semantic_description": str,
          }

        NOTE: Gemini returns free-text descriptions, not Florence-2 object
        detection labels. The schema is preserved but the semantics differ
        from local mode. Results are not numerically equivalent to CLIP.

        relevance_scores is left empty ({}) because Gemini cannot produce
        CLIP-equivalent cosine similarity scores. concept_match_score is 0.0
        when no concepts are detected. These are explicitly testing
        representations, not real model predictions.
        """
        client = self._get_client()
        try:
            # Upload the image file
            uploaded = client.files.upload(file=image_path)
            try:
                # Wait for processing
                _wait_for_file_active(client, uploaded.name)

                # Simple, direct prompt — mirrors caption_image() which works
                # reliably. Avoids structured JSON requests that cause the
                # model to hang or return 503 UNAVAILABLE.
                prompt = (
                    "Describe this image in one sentence. "
                    "List the main objects and scenes you observe."
                )
                response = client.models.generate_content(
                    model=settings.gemini_model,
                    contents=[uploaded, prompt],
                    generation_config={
                        "max_output_tokens": 100,
                        "temperature": 0.0,
                    },
                )
                text = response.text or ""

                # Parse comma-separated concepts from the description.
                # Safe parsing: empty/malformed responses yield empty lists.
                raw_concepts = [c.strip() for c in text.split(",") if c.strip()]
                concepts = raw_concepts[:20]

                # relevance_scores is empty because Gemini cannot produce
                # CLIP-equivalent cosine similarity scores. concept_match_score
                # is 0.0 when no concepts are detected. These are explicitly
                # testing representations, not real model predictions.
                relevance_scores: Dict[str, float] = {}
                concept_match_score = 0.0

                return {
                    "scene_concepts": concepts,
                    "relevance_scores": relevance_scores,
                    "concept_match_score": round(concept_match_score, 4),
                    "semantic_description": text,
                    "provider": "gemini",
                }
            finally:
                # Clean up uploaded file
                try:
                    client.files.delete(name=uploaded.name)
                except Exception:
                    pass
        except Exception as exc:
            msg = str(exc).lower()
            if "timeout" in msg:
                from content_engine.providers.base import ProviderTimeoutError

                raise ProviderTimeoutError(f"Gemini image request timed out: {exc}") from exc
            if "rate limit" in msg or "429" in msg:
                from content_engine.providers.base import ProviderRateLimitError

                raise ProviderRateLimitError(f"Gemini rate limit exceeded: {exc}") from exc
            if "401" in msg or "403" in msg or "authentication" in msg or "api key" in msg:
                from content_engine.providers.base import ProviderError

                raise ProviderError(
                    f"Gemini authentication failed: {exc}"
                ) from exc
            from content_engine.providers.base import ProviderError

            raise ProviderError(f"Gemini image understanding failed: {exc}") from exc

    # ── Image captioning ─────────────────────────────────────────────

    def caption_image(self, image_path: str) -> str:
        """Return an image caption using Gemini."""
        client = self._get_client()
        try:
            uploaded = client.files.upload(file=image_path)
            try:
                _wait_for_file_active(client, uploaded.name)
                response = client.models.generate_content(
                    model=settings.gemini_model,
                    contents=[uploaded, "Write a concise one-sentence caption for this image."],
                )
                return (response.text or "").strip()
            finally:
                try:
                    client.files.delete(name=uploaded.name)
                except Exception:
                    pass
        except Exception as exc:
            from content_engine.providers.base import ProviderError

            raise ProviderError(f"Gemini captioning failed: {exc}") from exc

    # ── Video understanding (explicit upload/process/wait/cleanup) ──
    # DEFERRED: Video support is not yet verified against the installed
    # google-genai SDK. Return an explicit unsupported error rather than
    # calling untested SDK interfaces.

    def understand_video(self, video_path: str) -> Dict[str, Any]:
        """Return video understanding using Gemini video processing.

        DEFERRED: Video support is not yet verified against the installed
        google-genai SDK. Returns an unsupported error rather than calling
        untested SDK interfaces. Local video analysis remains unchanged.
        """
        raise UnsupportedFeatureError(
            "Gemini video understanding is deferred. "
            "Verify the google-genai SDK video upload/poll/generate/cleanup "
            "workflow before enabling cloud_testing mode for video analysis. "
            "Local video processing remains available."
        )

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def requires_api_key(self) -> bool:
        return True

    def is_available(self) -> bool:
        """True if GEMINI_API_KEY is set and google-genai SDK is importable."""
        if not os.getenv("GEMINI_API_KEY"):
            return False
        try:
            from google import genai  # noqa: F401
            return True
        except ImportError:
            return False


# ── Helpers ──────────────────────────────────────────────────────────

def _wait_for_file_active(client, file_name: str, timeout: float = 120.0,
                          poll_interval: float = 5.0) -> None:
    """Poll until the uploaded file reaches ACTIVE state."""
    from google.genai.types import FileState  # type: ignore

    elapsed = 0.0
    while elapsed < timeout:
        file_obj = client.files.get(name=file_name)
        state = file_obj.state

        if state == FileState.ACTIVE:
            return
        if state == FileState.FAILED:
            raise ConfigurationError(
                f"Gemini file processing failed with state: {state}"
            )
        # Non-terminal states: STATE_UNSPECIFIED, PROCESSING, and any
        # unknown state — continue polling until timeout. Do not assume
        # success for unknown states.
        time.sleep(poll_interval)
        elapsed += poll_interval

    raise ProviderTimeoutError(
        f"Gemini file {file_name} did not become ACTIVE within {timeout}s"
    )


def _parse_video_clips(text: str) -> List[Dict[str, Any]]:
    """Parse highlight clips from Gemini's free-text video response.

    Attempts to extract start_time - end_time: description patterns.
    Returns empty list if parsing fails — callers should handle gracefully.
    """
    import re

    clips = []
    # Pattern: "0:30 - 0:45: description" or "30s - 45s: description"
    pattern = re.compile(
        r"(\d+):?(\d+)?\s*[-–]\s*(\d+):?(\d+)?\s*:\s*(.+)"
    )
    for match in pattern.finditer(text):
        try:
            start_min = int(match.group(1) or 0)
            start_sec = int(match.group(2) or 0)
            end_min = int(match.group(3) or 0)
            end_sec = int(match.group(4) or 0)
            desc = match.group(5).strip()
            start = start_min * 60 + start_sec
            end = end_min * 60 + end_sec
            clips.append({
                "start": float(start),
                "end": float(end),
                "score": 0.8,  # Mock-equivalent placeholder; not CLIP-derived
                "description": desc,
            })
        except (ValueError, IndexError):
            continue
    return clips
