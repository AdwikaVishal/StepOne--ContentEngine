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
    BRAND_PROFILE_DEFAULTS = {
        "name": "", "description": "", "target_audience": "",
        "campaign_objectives": "", "tone_of_voice": "professional",
        "preferred_vocabulary": [], "avoid_words_claims": [],
        "preferred_cta": "", "hashtag_guidance": "", "logo_path": None,
        "brand_colors": [], "fonts": [], "visual_references": [],
    }
    BRAND_PROFILE_TEXT_LIMITS = {
        "name": 120, "description": 2000, "target_audience": 1000,
        "campaign_objectives": 1000, "tone_of_voice": 80,
        "preferred_cta": 500, "hashtag_guidance": 500,
    }
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
        list_fields = {"preferred_vocabulary", "avoid_words_claims", "brand_colors", "fonts", "visual_references"}
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
                return json.load(f)
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
                    profiles.append(json.load(f))
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
        if ext not in {".png", ".jpg", ".jpeg", ".webp", ".svg", ".pdf"}:
            raise ValueError("Unsupported brand asset type")
        profile_dir = self.brand_assets_dir / profile_id
        profile_dir.mkdir(parents=True, exist_ok=True)
        asset_id = str(uuid.uuid4())
        safe_name = f"{asset_id}{ext}"
        path = profile_dir / safe_name
        with open(path, 'wb') as f:
            f.write(content)
        return str(path)
