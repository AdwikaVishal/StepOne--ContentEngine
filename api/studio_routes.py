"""
Studio API routes for multi-image social post creation and publishing.
"""
import json
import os
import shutil
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, UploadFile, HTTPException, Form, Request
from fastapi.responses import JSONResponse

from api.logger import get_logger
from api.utils import safe_jsonify
from config import settings
from content_engine.studio import (
    StudioStorage,
    StudioIngestion,
    StudioIntelligence,
    StudioContentOrchestrator,
    StudioGenerationError,
    LinkedInPublisher,
    InstagramPublisher,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/studio", tags=["studio"])

storage = StudioStorage()
ingestion = StudioIngestion()
intelligence = StudioIntelligence()
content_orch = StudioContentOrchestrator()
linkedin_pub = LinkedInPublisher()
instagram_pub = InstagramPublisher()


@router.post("/projects")
async def create_project(name: str = Form(""), brief: str = Form(""), platforms: str = Form('["linkedin","instagram"]')):
    try:
        plats = json.loads(platforms) if platforms else ["linkedin", "instagram"]
        project = storage.create_project(name=name, brief=brief, platforms=plats)
        return safe_jsonify(project)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects")
async def list_projects():
    projects = storage.list_projects()
    return safe_jsonify({"projects": projects})


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return safe_jsonify(project)


@router.post("/projects/{project_id}/upload")
async def upload_images(project_id: str, files: List[UploadFile] = File(...)):
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    uploaded = []
    errors = []
    for f in files:
        try:
            ok, msg = ingestion.validate_file(f.filename or "")
            if not ok:
                errors.append({"filename": f.filename, "error": msg})
                continue
            content = await f.read()
            if len(content) > settings.max_file_size_bytes:
                errors.append({"filename": f.filename, "error": "File too large"})
                continue
            asset = ingestion.save_upload(content, f.filename or "upload")
            uploaded.append(asset)
        except Exception as e:
            errors.append({"filename": f.filename, "error": str(e)})
    
    project["assets"].extend(uploaded)
    project["status"] = "uploaded"
    storage.save_project(project)
    return safe_jsonify({"project_id": project_id, "uploaded": uploaded, "errors": errors, "total_assets": len(project["assets"])})


@router.post("/projects/{project_id}/analyze")
async def analyze_project(project_id: str, brief: str = Form("")):
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project.get("assets"):
        raise HTTPException(status_code=400, detail="No assets to analyze")
    
    job_id = storage.create_job("analyze", project_id, {"brief": brief})
    try:
        analysis = intelligence.analyze_assets(project["assets"], brief=brief)
        selection = intelligence.select_best_images(analysis["analyzed"], max_count=12)
        project["analysis"] = analysis
        project["selected_assets"] = selection["selected"]
        project["status"] = "analyzed"
        storage.save_project(project)
        storage.update_job(job_id, status="completed", progress={"step": "done", "pct": 100}, result={"analysis": analysis, "selection": selection})
        return safe_jsonify({"project_id": project_id, "job_id": job_id, "analysis": analysis, "selection": selection})
    except Exception as e:
        storage.update_job(job_id, status="failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{project_id}/select")
async def update_selection(project_id: str, request: Request):
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    body = await request.json()
    selected_ids = body.get("selected_asset_ids") or []
    all_analyzed = project.get("analysis", {}).get("analyzed", [])
    selected = [a for a in all_analyzed if a.get("asset_id") in selected_ids]
    # Also include full asset data
    asset_map = {a["id"]: a for a in project.get("assets", [])}
    for s in selected:
        if s.get("asset_id") in asset_map:
            s["path"] = asset_map[s["asset_id"]].get("path")
            s["url"] = asset_map[s["asset_id"]].get("url")
            s["original_filename"] = asset_map[s["asset_id"]].get("original_filename")
    project["selected_assets"] = selected
    project["status"] = "selected"
    storage.save_project(project)
    return safe_jsonify({"project_id": project_id, "selected_assets": selected})


@router.post("/projects/{project_id}/generate")
async def generate_post(project_id: str, request: Request):
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    body = await request.json()
    
    event_name = body.get("event_name") or project.get("name") or "Event"
    brief = body.get("brief") or project.get("brief") or ""
    platforms = body.get("platforms") or project.get("platforms") or ["linkedin", "instagram"]
    
    job_id = storage.create_job("generate", project_id, body)
    try:
        selected = project.get("selected_assets") or []
        # Enrich with asset paths
        asset_map = {a["id"]: a for a in project.get("assets", [])}
        for s in selected:
            aid = s.get("asset_id") or s.get("id")
            if aid in asset_map:
                s["path"] = asset_map[aid].get("path")
                s["url"] = asset_map[aid].get("url")
        
        # Load brand profile if attached
        brand_profile = None
        bp_id = project.get("brand_profile_id") or body.get("brand_profile_id")
        if bp_id:
            brand_profile = storage.get_brand_profile(bp_id)
            if not brand_profile:
                project.pop("brand_profile_id", None)
                storage.save_project(project)
                raise HTTPException(status_code=404, detail="Selected brand profile no longer exists; choose another profile")
        
        content = content_orch.generate_post(
            event_name=event_name,
            selected_assets=selected,
            brief=brief,
            topic=body.get("topic", ""),
            tone=body.get("tone", "professional"),
            audience=body.get("audience", ""),
            key_points=body.get("key_points", ""),
            call_to_action=body.get("call_to_action", ""),
            platforms=platforms,
            brand_profile=brand_profile,
            activity=body.get("activity"),
            date=body.get("date"),
            time=body.get("time"),
            location=body.get("location"),
            organizer=body.get("organizer"),
        )
        if brand_profile:
            content["brand_profile"] = {"id": brand_profile["id"], "name": brand_profile["name"]}
        project["content"] = content
        project["platform_variants"] = content.get("platform_variants", {})
        project["status"] = "generated"
        storage.save_project(project)
        storage.update_job(job_id, status="completed", progress={"step": "done", "pct": 100}, result=content)
        return safe_jsonify({"project_id": project_id, "job_id": job_id, "content": content})
    except HTTPException as e:
        storage.update_job(job_id, status="failed", error=str(e.detail))
        raise
    except StudioGenerationError as e:
        logger.exception("studio_copy_generation_failed", error=str(e.__cause__ or e))
        storage.update_job(job_id, status="failed", error=str(e))
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception("studio_generation_failed", error=str(e))
        message = "Content generation failed. Check that the local Qwen model is available, then try again."
        storage.update_job(job_id, status="failed", error=message)
        raise HTTPException(status_code=503, detail=message) from e


@router.put("/projects/{project_id}/content")
async def update_content(project_id: str, request: Request):
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    body = await request.json()
    if "platform_variants" in body:
        project["platform_variants"].update(body["platform_variants"])
    if "content" in body:
        project["content"] = body["content"]
    storage.save_project(project)
    return safe_jsonify({"project_id": project_id, "status": "updated"})


@router.post("/projects/{project_id}/draft")
async def save_draft(project_id: str, request: Request):
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    body = await request.json()
    draft = storage.save_draft(project_id, {"project": project, **body})
    project["status"] = "draft"
    storage.save_project(project)
    return safe_jsonify({"draft_id": draft["draft_id"], "project_id": project_id})


@router.get("/drafts")
async def list_drafts(project_id: Optional[str] = None):
    drafts = storage.list_drafts(project_id)
    return safe_jsonify({"drafts": drafts})


@router.get("/drafts/{draft_id}")
async def get_draft(draft_id: str):
    draft = storage.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return safe_jsonify(draft)


@router.get("/jobs/{job_id}")
async def get_studio_job(job_id: str):
    job = storage.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return safe_jsonify(job)


@router.get("/publishing/status")
async def publishing_status():
    return safe_jsonify({
        "linkedin": {
            "configured": linkedin_pub.is_configured(),
            "auth_url": linkedin_pub.get_auth_url().get("auth_url"),
            "scopes": ["openid", "profile", "w_member_social"],
        },
        "instagram": {
            "configured": instagram_pub.is_configured(),
            "auth_url": instagram_pub.get_auth_url().get("auth_url"),
            "account_type_required": "Instagram Business/Creator",
        },
    })


@router.post("/publish/{platform}")
async def publish(platform: str, request: Request):
    project_id = (await request.json()).get("project_id")
    project = storage.get_project(project_id) if project_id else None
    if not project and project_id:
        raise HTTPException(status_code=404, detail="Project not found")
    
    variants = project.get("platform_variants", {}) if project else {}
    variant = variants.get(platform, {})
    caption = variant.get("caption") or variant.get("captions", [""])[0] if isinstance(variant.get("captions"), list) else ""
    media_urls = [s.get("url") for s in (project.get("selected_assets") or []) if s.get("url")]
    
    if platform == "linkedin":
        result = linkedin_pub.publish_post(caption, media_urls)
    elif platform == "instagram":
        result = instagram_pub.publish_carousel(caption, media_urls)
    else:
        raise HTTPException(status_code=400, detail="Unsupported platform")
    
    if project:
        if "publishing" not in project:
            project["publishing"] = {}
        project["publishing"][platform] = result
        storage.save_project(project)
    
    return safe_jsonify(result)


# Brand Profiles
@router.post("/brand-profiles")
async def create_brand_profile(request: Request):
    try:
        body = await request.json()
        profile = storage.create_brand_profile(body)
        return safe_jsonify(profile)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/brand-profiles")
async def list_brand_profiles():
    profiles = storage.list_brand_profiles()
    return safe_jsonify({"profiles": profiles})


@router.get("/brand-profiles/{profile_id}")
async def get_brand_profile(profile_id: str):
    profile = storage.get_brand_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Brand profile not found")
    return safe_jsonify(profile)


@router.put("/brand-profiles/{profile_id}")
async def update_brand_profile(profile_id: str, request: Request):
    profile = storage.get_brand_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Brand profile not found")
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="Brand profile must be an object")
        profile.update(body)
        profile["id"] = profile_id
        profile = storage.save_brand_profile(profile)
        return safe_jsonify(profile)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/brand-profiles/{profile_id}")
async def delete_brand_profile(profile_id: str):
    ok = storage.delete_brand_profile(profile_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Brand profile not found")
    for project in storage.list_projects():
        if project.get("brand_profile_id") == profile_id:
            project.pop("brand_profile_id", None)
            storage.save_project(project)
    return safe_jsonify({"status": "deleted"})


@router.post("/brand-profiles/{profile_id}/assets")
async def upload_brand_asset(profile_id: str, file: UploadFile = File(...), asset_kind: str = Form("reference")):
    profile = storage.get_brand_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Brand profile not found")
    if asset_kind not in {"logo", "reference"}:
        raise HTTPException(status_code=422, detail="asset_kind must be logo or reference")
    content = await file.read()
    if not content or len(content) > settings.max_file_size_bytes:
        raise HTTPException(status_code=422, detail="Brand asset is empty or exceeds the upload limit")
    try:
        path = storage.save_brand_asset(profile_id, file.filename or "brand-asset.png", content)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if asset_kind == "logo":
        profile["logo_path"] = path
    else:
        profile.setdefault("visual_references", []).append(path)
    storage.save_brand_profile(profile)
    return safe_jsonify({"profile": profile, "asset_path": path})


@router.post("/brand-profiles/{profile_id}/duplicate")
async def duplicate_brand_profile(profile_id: str, request: Request):
    try:
        body = await request.json()
        new_name = body.get("name")
        profile = storage.duplicate_brand_profile(profile_id, new_name)
        if not profile:
            raise HTTPException(status_code=404, detail="Brand profile not found")
        return safe_jsonify(profile)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{project_id}/brand-profile")
async def set_project_brand_profile(project_id: str, request: Request):
    project = storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        body = await request.json()
        profile_id = body.get("brand_profile_id")
        if profile_id:
            profile = storage.get_brand_profile(profile_id)
            if not profile:
                raise HTTPException(status_code=404, detail="Brand profile not found")
        elif profile_id is not None:
            raise HTTPException(status_code=422, detail="brand_profile_id must be a profile ID or null")
        project["brand_profile_id"] = profile_id
        storage.save_project(project)
        return safe_jsonify({"project_id": project_id, "brand_profile_id": profile_id})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
