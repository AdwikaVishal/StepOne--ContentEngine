"""
Studio storage for projects, assets, and drafts.
"""
import json
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import settings


class StudioStorage:
    # Flat top-level brand profile schema. The first 13 data fields are the
    # original schema and must never be renamed or removed (existing profiles
    # on disk depend on them). All further fields are additive and optional.
    BRAND_PROFILE_DEFAULTS = {
        # -- original schema (v1) --
        "name": "", "description": "", "target_audience": "",
        "campaign_objectives": "", "tone_of_voice": "professional",
        "preferred_vocabulary": [], "avoid_words_claims": [],
        "preferred_cta": "", "hashtag_guidance": "", "logo_path": None,
        "brand_colors": [], "fonts": [], "visual_references": [],
        # -- brand identity --
        "industry": "", "website": "", "tagline": "", "mission": "",
        "core_values": [],
        # -- brand voice --
        "tone_description": "", "personality_traits": [],
        "formality_level": "", "writing_style": "",
        "sentence_length": "", "person_preference": "",
        # -- target audience --
        "secondary_audience": "", "audience_demographics": "",
        "audience_interests": "", "audience_pain_points": "",
        "technical_level": "", "communication_expectations": "",
        # -- language guidelines --
        "industry_vocabulary": "", "emoji_preference": "",
        "capitalization_preferences": "",
        # -- content guidelines --
        "linkedin_style": "", "instagram_style": "", "story_style": "",
        "reel_style": "", "preferred_caption_length": "",
        "preferred_hook_style": "", "cta_style": "",
        "content_themes": [], "topics_to_avoid": [],
        # -- visual identity --
        "visual_style": "", "logo_usage_guidelines": "",
        "text_overlay_preferences": "",
        # -- brand intelligence (additive, Phase 1) --
        "brand_category": "", "known_text_aliases": [],
        "reference_notes": "",
    }
    BRAND_PROFILE_TEXT_LIMITS = {
        "name": 120, "description": 2000, "target_audience": 1000,
        "campaign_objectives": 1000, "tone_of_voice": 80,
        "preferred_cta": 500, "hashtag_guidance": 500,
        "industry": 200, "website": 500, "tagline": 300, "mission": 1000,
        "tone_description": 1000, "formality_level": 80,
        "writing_style": 500, "sentence_length": 80, "person_preference": 80,
        "secondary_audience": 1000, "audience_demographics": 1000,
        "audience_interests": 1000, "audience_pain_points": 1000,
        "technical_level": 200, "communication_expectations": 1000,
        "industry_vocabulary": 1000, "emoji_preference": 80,
        "capitalization_preferences": 500,
        "linkedin_style": 1000, "instagram_style": 1000,
        "story_style": 1000, "reel_style": 1000,
        "preferred_caption_length": 200, "preferred_hook_style": 500,
        "cta_style": 500,
        "visual_style": 500, "logo_usage_guidelines": 1000,
        "text_overlay_preferences": 1000,
        "brand_category": 200, "reference_notes": 1000,
    }
    # Fields validated as string lists (deduped/stripped, max 50 items x 200 chars).
    BRAND_PROFILE_LIST_FIELDS = {
        "preferred_vocabulary", "avoid_words_claims", "brand_colors",
        "fonts", "visual_references", "core_values", "personality_traits",
        "content_themes", "topics_to_avoid", "known_text_aliases",
    }

    # ── Brand asset manifest (Brand Intelligence, Phase 1) ──────────────────
    # Every uploaded reference photograph and logo gets an entry with metadata
    # the flat profile schema has no room for. Entries only store the file NAME
    # (never paths), so duplicating a profile (copytree) needs no manifest
    # rewrite. asset_id == the stored file stem (a server-generated UUID).
    BRAND_ASSET_KINDS = ("logo", "reference")
    BRAND_ASSET_CATEGORIES = (
        "logo", "product", "packaging", "signage", "storefront",
        "banner", "uniform", "label", "placement", "other",
    )
    BRAND_ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".pdf"}
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else Path(settings.output_dir) / "studio"
        self.projects_dir = self.base_dir / "projects"
        self.assets_dir = self.base_dir / "assets"
        self.drafts_dir = self.base_dir / "drafts"
        self.jobs_dir = self.base_dir / "jobs"
        self.brand_profiles_dir = self.base_dir / "brand_profiles"
        self.brand_assets_dir = self.base_dir / "brand_assets"
        for d in [self.projects_dir, self.assets_dir, self.drafts_dir, self.jobs_dir, self.brand_profiles_dir, self.brand_assets_dir]:
            d.mkdir(parents=True, exist_ok=True)
    
    def create_project(self, name: str = "", brief: str = "", platforms: Optional[List[str]] = None) -> Dict[str, Any]:
        project_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        project = {
            "id": project_id,
            "name": name or f"Project {project_id[:8]}",
            "brief": brief,
            "platforms": platforms or ["linkedin", "instagram"],
            "status": "created",
            "created_at": now,
            "updated_at": now,
            "assets": [],
            "selected_assets": [],
            "analysis": {},
            "content": {},
            "platform_variants": {},
            "publishing": {},
        }
        self._save_project(project)
        return project
    
    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        path = self.projects_dir / f"{project_id}.json"
        if not path.exists():
            return None
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return None
    
    def save_project(self, project: Dict[str, Any]) -> Dict[str, Any]:
        project["updated_at"] = datetime.utcnow().isoformat()
        self._save_project(project)
        return project
    
    def _save_project(self, project: Dict[str, Any]):
        path = self.projects_dir / f"{project['id']}.json"
        with open(path, "w") as f:
            json.dump(project, f, indent=2)
    
    def list_projects(self) -> List[Dict[str, Any]]:
        projects = []
        for path in self.projects_dir.glob("*.json"):
            try:
                with open(path) as f:
                    projects.append(json.load(f))
            except Exception:
                continue
        projects.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return projects
    
    def save_draft(self, project_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        draft_id = data.get("draft_id") or str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        draft = {
            "draft_id": draft_id,
            "project_id": project_id,
            "data": data,
            "created_at": data.get("created_at") or now,
            "updated_at": now,
        }
        path = self.drafts_dir / f"{draft_id}.json"
        with open(path, "w") as f:
            json.dump(draft, f, indent=2)
        return draft
    
    def get_draft(self, draft_id: str) -> Optional[Dict[str, Any]]:
        path = self.drafts_dir / f"{draft_id}.json"
        if not path.exists():
            return None
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return None
    
    def list_drafts(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        drafts = []
        for path in self.drafts_dir.glob("*.json"):
            try:
                with open(path) as f:
                    d = json.load(f)
                    if project_id and d.get("project_id") != project_id:
                        continue
                    drafts.append(d)
            except Exception:
                continue
        drafts.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return drafts
    
    def create_job(self, job_type: str, project_id: str, meta: Optional[Dict[str, Any]] = None) -> str:
        job_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        job = {
            "job_id": job_id,
            "project_id": project_id,
            "type": job_type,
            "status": "pending",
            "progress": {"step": "queued", "pct": 0},
            "meta": meta or {},
            "result": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        path = self.jobs_dir / f"{job_id}.json"
        with open(path, "w") as f:
            json.dump(job, f, indent=2)
        return job_id
    
    def update_job(self, job_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        path = self.jobs_dir / f"{job_id}.json"
        if not path.exists():
            return None
        try:
            with open(path) as f:
                job = json.load(f)
            job.update(kwargs)
            job["updated_at"] = datetime.utcnow().isoformat()
            with open(path, "w") as f:
                json.dump(job, f, indent=2)
            return job
        except Exception:
            return None
    
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        path = self.jobs_dir / f"{job_id}.json"
        if not path.exists():
            return None
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return None


    # Brand Profiles
    @classmethod
    def validate_brand_profile(cls, data: Dict[str, Any], *, partial: bool = False) -> Dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("Brand profile must be an object")
        clean = {} if partial else {key: (value.copy() if isinstance(value, list) else value)
                                    for key, value in cls.BRAND_PROFILE_DEFAULTS.items()}
        list_fields = cls.BRAND_PROFILE_LIST_FIELDS
        for key, value in data.items():
            if key in {"id", "created_at", "updated_at"}:
                continue
            if key not in cls.BRAND_PROFILE_DEFAULTS:
                raise ValueError(f"Unknown brand profile field: {key}")
            if key in cls.BRAND_PROFILE_TEXT_LIMITS:
                if not isinstance(value, str):
                    raise ValueError(f"{key} must be a string")
                value = value.strip()
                if len(value) > cls.BRAND_PROFILE_TEXT_LIMITS[key]:
                    raise ValueError(f"{key} must be at most {cls.BRAND_PROFILE_TEXT_LIMITS[key]} characters")
            elif key in list_fields:
                if not isinstance(value, list) or len(value) > 50:
                    raise ValueError(f"{key} must be a list with at most 50 items")
                if not all(isinstance(item, str) and len(item.strip()) <= 200 for item in value):
                    raise ValueError(f"{key} items must be strings of at most 200 characters")
                value = list(dict.fromkeys(item.strip() for item in value if item.strip()))
                if key == "brand_colors" and any(not re.fullmatch(r"#[0-9a-fA-F]{6}", item) for item in value):
                    raise ValueError("brand_colors must contain six-digit hex colors")
            elif key == "logo_path":
                if value is not None and (not isinstance(value, str) or len(value) > 1000):
                    raise ValueError("logo_path must be a stored asset path or null")
            clean[key] = value
        if not partial and not clean["name"]:
            raise ValueError("Brand name is required")
        return clean

    @classmethod
    def _with_brand_profile_defaults(cls, profile: Dict[str, Any]) -> Dict[str, Any]:
        """Merge schema defaults into a stored profile at read time.

        Older profile JSON files lack fields added after they were written;
        readers always see the full schema. This never writes to disk, so
        loading an old profile does not modify it (no migration side effects).
        """
        merged = {key: (value.copy() if isinstance(value, list) else value)
                  for key, value in cls.BRAND_PROFILE_DEFAULTS.items()}
        merged.update(profile)
        return merged

    def create_brand_profile(self, data: Dict[str, Any]) -> Dict[str, Any]:
        profile_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        profile = {**self.validate_brand_profile(data), "id": profile_id, "created_at": now, "updated_at": now}
        self._save_brand_profile(profile)
        return profile
    
    def get_brand_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        try:
            profile_id = str(uuid.UUID(profile_id))
        except (ValueError, TypeError, AttributeError):
            return None
        path = self.brand_profiles_dir / f"{profile_id}.json"
        if not path.exists():
            return None
        try:
            with open(path) as f:
                return self._with_brand_profile_defaults(json.load(f))
        except Exception:
            return None
    
    def save_brand_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(profile.get("id"), str) or not profile["id"]:
            raise ValueError("Brand profile ID is required")
        try:
            profile["id"] = str(uuid.UUID(profile["id"]))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Invalid brand profile ID")
        clean = self.validate_brand_profile(profile)
        asset_root = (self.brand_assets_dir / profile["id"]).resolve()
        for asset_path in [clean.get("logo_path"), *(clean.get("visual_references") or [])]:
            if asset_path is None:
                continue
            try:
                Path(asset_path).resolve().relative_to(asset_root)
            except (ValueError, OSError, TypeError):
                raise ValueError("Brand assets must be stored inside their profile asset directory")
        profile = {**clean, "id": profile["id"], "created_at": profile.get("created_at") or datetime.utcnow().isoformat()}
        profile["updated_at"] = datetime.utcnow().isoformat()
        self._save_brand_profile(profile)
        return profile
    
    def _save_brand_profile(self, profile: Dict[str, Any]):
        path = self.brand_profiles_dir / f"{profile['id']}.json"
        with open(path, "w") as f:
            json.dump(profile, f, indent=2)
    
    def list_brand_profiles(self) -> List[Dict[str, Any]]:
        profiles = []
        for path in self.brand_profiles_dir.glob("*.json"):
            try:
                with open(path) as f:
                    profiles.append(self._with_brand_profile_defaults(json.load(f)))
            except Exception:
                continue
        profiles.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return profiles
    
    def delete_brand_profile(self, profile_id: str) -> bool:
        try:
            profile_id = str(uuid.UUID(profile_id))
        except (ValueError, TypeError, AttributeError):
            return False
        path = self.brand_profiles_dir / f"{profile_id}.json"
        if path.exists():
            try:
                path.unlink()
                shutil.rmtree(self.brand_assets_dir / profile_id, ignore_errors=True)
                return True
            except Exception:
                return False
        return False
    
    def duplicate_brand_profile(self, profile_id: str, new_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        original = self.get_brand_profile(profile_id)
        if not original:
            return None
        new_id = str(uuid.uuid4())
        new_profile = json.loads(json.dumps(original))
        new_profile["id"] = new_id
        new_profile["name"] = new_name or f"{original['name']} (Copy)"
        now = datetime.utcnow().isoformat()
        new_profile["created_at"] = now
        new_profile["updated_at"] = now
        new_profile = {**self.validate_brand_profile(new_profile), "id": new_id, "created_at": now, "updated_at": now}
        source_dir = self.brand_assets_dir / profile_id
        target_dir = self.brand_assets_dir / new_id
        if source_dir.exists():
            shutil.copytree(source_dir, target_dir)
            for field in ("logo_path",):
                if new_profile.get(field):
                    new_profile[field] = new_profile[field].replace(str(source_dir), str(target_dir))
            refs = new_profile.get("visual_references") or []
            new_profile["visual_references"] = [ref.replace(str(source_dir), str(target_dir)) if isinstance(ref, str) else ref for ref in refs]
        self._save_brand_profile(new_profile)
        return new_profile
    
    def save_brand_asset(self, profile_id: str, filename: str, content: bytes) -> str:
        try:
            profile_id = str(uuid.UUID(profile_id))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Invalid brand profile ID")
        if not self.get_brand_profile(profile_id):
            raise ValueError("Brand profile not found")
        ext = Path(filename).suffix.lower()
        if ext not in self.BRAND_ASSET_EXTENSIONS:
            raise ValueError("Unsupported brand asset type")
        profile_dir = self.brand_assets_dir / profile_id
        profile_dir.mkdir(parents=True, exist_ok=True)
        asset_id = str(uuid.uuid4())
        safe_name = f"{asset_id}{ext}"
        path = profile_dir / safe_name
        with open(path, 'wb') as f:
            f.write(content)
        return str(path)

    # ── Brand asset manifest (Brand Intelligence, Phase 1) ──────────────────

    def _brand_asset_dir(self, profile_id: str) -> Path:
        try:
            profile_id = str(uuid.UUID(profile_id))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Invalid brand profile ID")
        return self.brand_assets_dir / profile_id

    @staticmethod
    def _sha256_bytes(content: bytes) -> str:
        import hashlib
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def _image_dimensions(path: Path) -> tuple:
        """(width, height, format) for raster images; (None, None, fmt) otherwise."""
        fmt = path.suffix.lower().lstrip(".").upper() or None
        if fmt == "JPG":
            fmt = "JPEG"
        try:
            from PIL import Image
            with Image.open(path) as img:
                return img.width, img.height, (img.format or fmt)
        except Exception:
            return None, None, fmt

    def _manifest_entry_from_path(
        self,
        path: Path,
        *,
        kind: str,
        category: str = "",
        original_name: str = "",
        notes: str = "",
        uploaded_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        stat = path.stat()
        width, height, fmt = self._image_dimensions(path)
        with open(path, "rb") as f:
            sha = self._sha256_bytes(f.read())
        if uploaded_at is None:
            uploaded_at = datetime.utcfromtimestamp(stat.st_mtime).isoformat()
        return {
            "asset_id": path.stem,
            "kind": kind,
            "category": category or ("logo" if kind == "logo" else "other"),
            "stored_name": path.name,
            "original_name": original_name or path.name,
            "sha256": sha,
            "bytes": stat.st_size,
            "width": width,
            "height": height,
            "format": fmt,
            "uploaded_at": uploaded_at,
            "notes": notes,
        }

    def _load_manifest_raw(self, profile_id: str) -> List[Dict[str, Any]]:
        path = self._brand_asset_dir(profile_id) / "manifest.json"
        if not path.exists():
            return []
        try:
            with open(path) as f:
                data = json.load(f)
            assets = data.get("assets")
            return assets if isinstance(assets, list) else []
        except Exception:
            return []

    def _save_manifest_raw(self, profile_id: str, assets: List[Dict[str, Any]]) -> None:
        asset_dir = self._brand_asset_dir(profile_id)
        asset_dir.mkdir(parents=True, exist_ok=True)
        path = asset_dir / "manifest.json"
        with open(path, "w") as f:
            json.dump({"assets": assets, "updated_at": datetime.utcnow().isoformat()}, f, indent=2)

    def list_brand_assets(self, profile_id: str) -> List[Dict[str, Any]]:
        """Merged manifest view: persisted entries + any profile-referenced asset
        paths not yet recorded (e.g. assets uploaded before the manifest existed).

        Read-only: never writes to disk (no migration side effects on load).
        The schema (profile JSON) always wins for path membership.
        """
        profile = self.get_brand_profile(profile_id)
        if profile is None:
            raise ValueError("Brand profile not found")
        asset_dir = self._brand_asset_dir(profile_id)

        merged: List[Dict[str, Any]] = []
        seen_stored = set()
        for entry in self._load_manifest_raw(profile_id):
            if not isinstance(entry, dict) or not entry.get("stored_name"):
                continue
            if entry["stored_name"] in seen_stored:
                continue
            if not (asset_dir / entry["stored_name"]).exists():
                continue  # stale entry: file removed outside the API
            seen_stored.add(entry["stored_name"])
            merged.append(entry)

        # Schema-referenced paths missing from the manifest → rebuild entries.
        schema_paths = []
        if profile.get("logo_path"):
            schema_paths.append(("logo", profile["logo_path"]))
        for ref in profile.get("visual_references") or []:
            if isinstance(ref, str):
                schema_paths.append(("reference", ref))
        for kind, ref_path in schema_paths:
            name = Path(ref_path).name
            if name in seen_stored:
                continue
            file_path = Path(ref_path)
            if not file_path.exists():
                continue
            try:
                file_path.resolve().relative_to(asset_dir.resolve())
            except (ValueError, OSError, TypeError):
                continue  # never surface a path outside the asset directory
            merged.append(self._manifest_entry_from_path(
                file_path,
                kind=kind,
                original_name=name,
                category="logo" if kind == "logo" else "other",
            ))
            seen_stored.add(name)
        return merged

    def get_brand_asset_entry(self, profile_id: str, asset_id: str) -> Optional[Dict[str, Any]]:
        try:
            for entry in self.list_brand_assets(profile_id):
                if entry.get("asset_id") == asset_id:
                    return entry
        except ValueError:
            return None
        return None

    def _sync_profile_assets_from_manifest(self, profile_id: str) -> Dict[str, Any]:
        """Recompute the v1 view fields (logo_path / visual_references) from the
        manifest so schema and manifest can never drift after an asset mutation."""
        profile = self.get_brand_profile(profile_id)
        if profile is None:
            raise ValueError("Brand profile not found")
        entries = self.list_brand_assets(profile_id)
        asset_dir = self._brand_asset_dir(profile_id)

        logo_entries = [e for e in entries if e.get("kind") == "logo"]
        logo_paths = [str(asset_dir / e["stored_name"]) for e in logo_entries]
        current = profile.get("logo_path")
        if current and current in logo_paths:
            profile["logo_path"] = current          # keep explicit selection
        elif logo_paths:
            profile["logo_path"] = logo_paths[-1]   # newest uploaded logo wins
        else:
            profile["logo_path"] = None
        profile["visual_references"] = [
            str(asset_dir / e["stored_name"])
            for e in entries if e.get("kind") == "reference"
        ]
        return self.save_brand_profile(profile)

    def record_brand_asset(
        self,
        profile_id: str,
        path: str,
        *,
        kind: str,
        category: str = "",
        original_name: str = "",
        notes: str = "",
    ) -> Dict[str, Any]:
        if kind not in self.BRAND_ASSET_KINDS:
            raise ValueError("asset kind must be logo or reference")
        if category and category not in self.BRAND_ASSET_CATEGORIES:
            raise ValueError(f"Unknown brand asset category: {category}")
        asset_dir = self._brand_asset_dir(profile_id)
        file_path = Path(path)
        if not file_path.exists():
            raise ValueError("Brand asset file not found")
        try:
            file_path.resolve().relative_to(asset_dir.resolve())
        except (ValueError, OSError, TypeError):
            raise ValueError("Brand assets must be stored inside their profile asset directory")
        entry = self._manifest_entry_from_path(
            file_path,
            kind=kind,
            category=category,
            original_name=original_name or file_path.name,
            notes=notes,
            uploaded_at=datetime.utcnow().isoformat(),
        )
        assets = [e for e in self.list_brand_assets(profile_id)
                  if e.get("asset_id") != entry["asset_id"]]
        assets.append(entry)
        self._save_manifest_raw(profile_id, assets)
        return entry

    def update_brand_asset_entry(
        self,
        profile_id: str,
        asset_id: str,
        *,
        category: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        if category is not None and category not in self.BRAND_ASSET_CATEGORIES:
            raise ValueError(f"Unknown brand asset category: {category}")
        assets = self.list_brand_assets(profile_id)
        entry = next((e for e in assets if e.get("asset_id") == asset_id), None)
        if entry is None:
            raise ValueError("Brand asset not found")
        if category is not None:
            entry["category"] = category
        if notes is not None:
            if len(notes) > 1000:
                raise ValueError("notes must be at most 1000 characters")
            entry["notes"] = notes.strip()
        self._save_manifest_raw(profile_id, assets)
        return entry

    def remove_brand_asset(self, profile_id: str, asset_id: str) -> Dict[str, Any]:
        asset_dir = self._brand_asset_dir(profile_id)
        assets = self.list_brand_assets(profile_id)
        entry = next((e for e in assets if e.get("asset_id") == asset_id), None)
        if entry is None:
            raise ValueError("Brand asset not found")
        file_path = (asset_dir / entry["stored_name"]).resolve()
        try:
            file_path.relative_to(asset_dir.resolve())
        except (ValueError, OSError, TypeError):
            raise ValueError("Brand assets must be stored inside their profile asset directory")
        if file_path.exists():
            file_path.unlink()
        remaining = [e for e in assets if e.get("asset_id") != asset_id]
        self._save_manifest_raw(profile_id, remaining)
        self._sync_profile_assets_from_manifest(profile_id)
        return entry

    def replace_brand_asset(
        self,
        profile_id: str,
        asset_id: str,
        filename: str,
        content: bytes,
    ) -> Dict[str, Any]:
        """Swap the file behind an existing asset, keeping its identity
        (asset_id, kind, category, notes). Extension may change; profile paths
        are re-synced so the v1 schema view never points at a dead file."""
        asset_dir = self._brand_asset_dir(profile_id)
        assets = self.list_brand_assets(profile_id)
        entry = next((e for e in assets if e.get("asset_id") == asset_id), None)
        if entry is None:
            raise ValueError("Brand asset not found")
        ext = Path(filename).suffix.lower()
        if ext not in self.BRAND_ASSET_EXTENSIONS:
            raise ValueError("Unsupported brand asset type")
        if not content:
            raise ValueError("Replacement file is empty")

        old_path = (asset_dir / entry["stored_name"]).resolve()
        new_name = f"{asset_id}{ext}"
        new_path = asset_dir / new_name
        try:
            old_path.relative_to(asset_dir.resolve())
        except (ValueError, OSError, TypeError):
            raise ValueError("Brand assets must be stored inside their profile asset directory")
        with open(new_path, "wb") as f:
            f.write(content)
        if old_path.exists() and old_path != new_path.resolve():
            old_path.unlink()

        width, height, fmt = self._image_dimensions(new_path)
        entry.update({
            "stored_name": new_name,
            "original_name": Path(filename).name or entry.get("original_name", new_name),
            "sha256": self._sha256_bytes(content),
            "bytes": len(content),
            "width": width,
            "height": height,
            "format": fmt,
            "uploaded_at": datetime.utcnow().isoformat(),
        })
        self._save_manifest_raw(profile_id, assets)
        self._sync_profile_assets_from_manifest(profile_id)
        return entry
