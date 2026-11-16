"""
Brand Intelligence Phase 1 — Brand Reference Library tests.

Covers:
- Additive v3 schema fields (brand_category, known_text_aliases,
  reference_notes) preserve every existing field and behaviour.
- Asset manifest: record / list / update / remove / replace round trips,
  profile schema sync (logo_path / visual_references) and confinement.
- Duplicate copies the manifest; unknown fields still rejected.
- Reference quality report: counts, categories, diversity, warnings.
- API contract for the new /api/brand-intel router and the category-aware
  asset upload on the existing studio endpoint.
"""
import io
import json
from pathlib import Path

import pytest

from content_engine.studio import StudioStorage


# Fields added by Brand Intelligence Phase 1 (all optional and additive).
V3_FIELDS = {"brand_category", "known_text_aliases", "reference_notes"}

# 1x1 transparent PNG (valid raster image, tiny).
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_storage(tmpdir) -> StudioStorage:
    return StudioStorage(base_dir=Path(tmpdir))


def _png(seed: int = 0, size=(32, 32)) -> bytes:
    """Valid PNG in memory (deterministic per-pixel noise via seed) for tests.

    Real photographs carry high-frequency detail; solid-color rectangles all
    hash identically, so tests must use textured images to exercise the
    diversity/near-duplicate logic meaningfully.
    """
    from PIL import Image
    import random
    rnd = random.Random(seed)
    img = Image.new("RGB", size)
    img.putdata([
        (rnd.randint(0, 255), rnd.randint(0, 255), rnd.randint(0, 255))
        for _ in range(size[0] * size[1])
    ])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Schema ────────────────────────────────────────────────────────────────────

class TestV3SchemaAdditive:
    def test_v3_fields_have_defaults_and_preserve_v1_v2(self):
        defaults = StudioStorage.BRAND_PROFILE_DEFAULTS
        assert V3_FIELDS.issubset(defaults.keys())
        assert defaults["brand_category"] == ""
        assert defaults["known_text_aliases"] == []
        assert defaults["reference_notes"] == ""
        # v1 invariants unchanged.
        assert defaults["name"] == ""
        assert defaults["tone_of_voice"] == "professional"
        assert defaults["logo_path"] is None
        assert len(defaults) == 48

    def test_v3_fields_validate(self, tmp_path):
        storage = _make_storage(tmp_path)
        profile = storage.create_brand_profile({
            "name": "V3",
            "brand_category": "Beverages",
            "known_text_aliases": ["AcmeCo", " acmeco ", "AcmeCo"],
            "reference_notes": "Focus on packaging shots",
        })
        assert profile["brand_category"] == "Beverages"
        # dedup + strip, same list semantics as every other list field.
        assert profile["known_text_aliases"] == ["AcmeCo", "acmeco"]
        assert profile["reference_notes"] == "Focus on packaging shots"

        with pytest.raises(ValueError, match="brand_category must be a string"):
            storage.create_brand_profile({"name": "X", "brand_category": 7})
        with pytest.raises(ValueError, match="at most 200 characters"):
            storage.create_brand_profile({"name": "X", "brand_category": "a" * 201})
        with pytest.raises(ValueError, match="known_text_aliases must be a list"):
            storage.create_brand_profile({"name": "X", "known_text_aliases": "Acme"})
        with pytest.raises(ValueError, match="at most 1000 characters"):
            storage.create_brand_profile({"name": "X", "reference_notes": "a" * 1001})

    def test_legacy_profile_still_loads_with_v3_defaults(self, tmp_path):
        storage = _make_storage(tmp_path)
        created = storage.create_brand_profile({"name": "Old"})
        # Simulate a pre-v3 file on disk.
        path = storage.brand_profiles_dir / f"{created['id']}.json"
        raw = json.loads(path.read_text())
        for field in V3_FIELDS:
            raw.pop(field, None)
        path.write_text(json.dumps(raw))

        loaded = storage.get_brand_profile(created["id"])
        assert loaded["brand_category"] == ""
        assert loaded["known_text_aliases"] == []
        assert loaded["reference_notes"] == ""
        # Read must not rewrite the file.
        assert V3_FIELDS & set(json.loads(path.read_text()).keys()) == set()

    def test_unknown_fields_still_rejected(self, tmp_path):
        storage = _make_storage(tmp_path)
        with pytest.raises(ValueError, match="Unknown brand profile field"):
            storage.create_brand_profile({"name": "X", "some_new_thing": 1})


# ── Manifest ──────────────────────────────────────────────────────────────────

class TestAssetManifest:
    def test_record_and_list_assets(self, tmp_path):
        storage = _make_storage(tmp_path)
        profile = storage.create_brand_profile({"name": "Mf"})
        logo_path = storage.save_brand_asset(profile["id"], "logo.png", PNG_BYTES)
        ref_path = storage.save_brand_asset(profile["id"], "shelf.jpg", PNG_BYTES)
        profile["logo_path"] = logo_path
        profile["visual_references"] = [ref_path]
        storage.save_brand_profile(profile)

        logo_entry = storage.record_brand_asset(
            profile["id"], logo_path, kind="logo",
            original_name="coca-cola-logo.png")
        ref_entry = storage.record_brand_asset(
            profile["id"], ref_path, kind="reference",
            category="packaging", original_name="shelf.png")

        assets = storage.list_brand_assets(profile["id"])
        assert len(assets) == 2
        assert logo_entry["kind"] == "logo"
        assert logo_entry["category"] == "logo"
        assert ref_entry["category"] == "packaging"
        assert ref_entry["original_name"] == "shelf.png"
        assert ref_entry["sha256"] and len(ref_entry["sha256"]) == 64
        assert ref_entry["width"] == 1 and ref_entry["height"] == 1
        # asset_id == stored file stem, manifest stores names not paths.
        assert ref_entry["stored_name"] == f"{ref_entry['asset_id']}.jpg"
        assert "path" not in ref_entry

    def test_rebuild_from_profile_when_manifest_missing(self, tmp_path):
        """Assets uploaded before the manifest existed appear after a merge."""
        storage = _make_storage(tmp_path)
        profile = storage.create_brand_profile({"name": "Pre"})
        logo_path = storage.save_brand_asset(profile["id"], "logo.png", PNG_BYTES)
        ref_path = storage.save_brand_asset(profile["id"], "ref.png", PNG_BYTES)
        profile["logo_path"] = logo_path
        profile["visual_references"] = [ref_path]
        storage.save_brand_profile(profile)
        assert not (storage.brand_assets_dir / profile["id"] / "manifest.json").exists()

        assets = storage.list_brand_assets(profile["id"])
        assert len(assets) == 2
        kinds = sorted(a["kind"] for a in assets)
        assert kinds == ["logo", "reference"]
        # Read-only: no manifest was written by loading.
        assert not (storage.brand_assets_dir / profile["id"] / "manifest.json").exists()

    def test_update_category_and_notes(self, tmp_path):
        storage = _make_storage(tmp_path)
        profile = storage.create_brand_profile({"name": "Upd"})
        path = storage.save_brand_asset(profile["id"], "ref.png", PNG_BYTES)
        entry = storage.record_brand_asset(profile["id"], path, kind="reference")

        updated = storage.update_brand_asset_entry(
            profile["id"], entry["asset_id"],
            category="signage", notes="Storefront banner, main entrance")
        assert updated["category"] == "signage"
        assert updated["notes"] == "Storefront banner, main entrance"
        reloaded = storage.get_brand_asset_entry(profile["id"], entry["asset_id"])
        assert reloaded["category"] == "signage"

        with pytest.raises(ValueError, match="Unknown brand asset category"):
            storage.update_brand_asset_entry(
                profile["id"], entry["asset_id"], category="not-a-category")
        with pytest.raises(ValueError, match="Brand asset not found"):
            storage.update_brand_asset_entry(profile["id"], "nope", category="logo")

    def test_remove_syncs_profile_and_deletes_file(self, tmp_path):
        storage = _make_storage(tmp_path)
        profile = storage.create_brand_profile({"name": "Rm"})
        logo_path = storage.save_brand_asset(profile["id"], "logo.png", PNG_BYTES)
        ref1 = storage.save_brand_asset(profile["id"], "a.png", PNG_BYTES)
        ref2 = storage.save_brand_asset(profile["id"], "b.png", PNG_BYTES)
        profile["logo_path"] = logo_path
        profile["visual_references"] = [ref1, ref2]
        storage.save_brand_profile(profile)

        ref1_entry = next(a for a in storage.list_brand_assets(profile["id"])
                          if a["stored_name"] == Path(ref1).name)
        storage.remove_brand_asset(profile["id"], ref1_entry["asset_id"])

        assert not Path(ref1).exists()          # file gone
        assert Path(ref2).exists()              # sibling untouched
        loaded = storage.get_brand_profile(profile["id"])
        assert loaded["visual_references"] == [ref2]   # schema synced
        assert loaded["logo_path"] == logo_path        # logo preserved
        assert len(storage.list_brand_assets(profile["id"])) == 2

        # Removing the last logo clears logo_path.
        logo_entry = next(a for a in storage.list_brand_assets(profile["id"])
                          if a["kind"] == "logo")
        storage.remove_brand_asset(profile["id"], logo_entry["asset_id"])
        loaded = storage.get_brand_profile(profile["id"])
        assert loaded["logo_path"] is None

        with pytest.raises(ValueError, match="Brand asset not found"):
            storage.remove_brand_asset(profile["id"], ref1_entry["asset_id"])

    def test_replace_keeps_identity_and_updates_bytes(self, tmp_path):
        storage = _make_storage(tmp_path)
        profile = storage.create_brand_profile({"name": "Rep"})
        path = storage.save_brand_asset(profile["id"], "ref.png", PNG_BYTES)
        profile["visual_references"] = [path]
        storage.save_brand_profile(profile)
        entry = storage.record_brand_asset(profile["id"], path, kind="reference",
                                           category="product")
        original_sha = entry["sha256"]

        new_bytes = _png(seed=99, size=(16, 16))
        replaced = storage.replace_brand_asset(
            profile["id"], entry["asset_id"], "better.png", new_bytes)
        assert replaced["asset_id"] == entry["asset_id"]        # identity kept
        assert replaced["category"] == "product"                # metadata kept
        assert replaced["sha256"] != original_sha
        assert replaced["bytes"] == len(new_bytes)
        assert (storage.brand_assets_dir / profile["id"] / replaced["stored_name"]).exists()
        # Old file removed, profile path re-synced (extension may change).
        loaded = storage.get_brand_profile(profile["id"])
        assert loaded["visual_references"] == [
            str(storage.brand_assets_dir / profile["id"] / replaced["stored_name"])]

        with pytest.raises(ValueError, match="Unsupported brand asset type"):
            storage.replace_brand_asset(profile["id"], entry["asset_id"],
                                        "evil.exe", b"x")
        with pytest.raises(ValueError, match="Brand asset not found"):
            storage.replace_brand_asset(profile["id"], "ghost", "a.png", PNG_BYTES)

    def test_duplicate_copies_manifest_with_original(self, tmp_path):
        storage = _make_storage(tmp_path)
        profile = storage.create_brand_profile({"name": "Src"})
        logo_path = storage.save_brand_asset(profile["id"], "logo.png", PNG_BYTES)
        ref_path = storage.save_brand_asset(profile["id"], "ref.png", PNG_BYTES)
        profile["logo_path"] = logo_path
        profile["visual_references"] = [ref_path]
        storage.save_brand_profile(profile)
        storage.record_brand_asset(profile["id"], logo_path, kind="logo")
        storage.record_brand_asset(profile["id"], ref_path, kind="reference",
                                   category="product")

        dup = storage.duplicate_brand_profile(profile["id"])
        dup_assets = storage.list_brand_assets(dup["id"])
        assert len(dup_assets) == 2
        assert sorted(a["kind"] for a in dup_assets) == ["logo", "reference"]
        # Every duplicated asset file exists in the new directory.
        for entry in dup_assets:
            assert (storage.brand_assets_dir / dup["id"] / entry["stored_name"]).exists()
        # Original untouched.
        assert len(storage.list_brand_assets(profile["id"])) == 2

    def test_confinement_still_enforced(self, tmp_path):
        storage = _make_storage(tmp_path)
        profile = storage.create_brand_profile({"name": "Conf"})
        # A path outside the profile asset directory must be rejected on save.
        outside = tmp_path / "outside.png"
        outside.write_bytes(PNG_BYTES)
        profile["visual_references"] = [str(outside)]
        with pytest.raises(ValueError, match="inside their profile asset directory"):
            storage.save_brand_profile(profile)
        # And never surfaced by the manifest listing either — the raw profile
        # save fails first, so the listing has nothing to leak.


# ── Reference quality ─────────────────────────────────────────────────────────

class TestReferenceQuality:
    def _quality(self, storage, profile_id):
        from content_engine.brand_intel.reference_quality import get_reference_quality
        return get_reference_quality(storage, profile_id)

    def test_no_references_warns(self, tmp_path):
        storage = _make_storage(tmp_path)
        profile = storage.create_brand_profile({"name": "Empty"})
        report = self._quality(storage, profile["id"])
        assert report["counts"] == {"logos": 0, "references": 0, "total": 0}
        codes = {w["code"] for w in report["warnings"]}
        assert "no_references" in codes
        assert "no_logo" in codes
        assert report["readiness"] < 100

    def test_diversity_and_near_duplicates(self, tmp_path):
        storage = _make_storage(tmp_path)
        profile = storage.create_brand_profile({"name": "Diverse"})

        # Two identical photos + one very different photo → near-dup flagged.
        same = _png(seed=1, size=(64, 64))
        paths = []
        for i, content in enumerate([same, same, _png(seed=7, size=(64, 64))]):
            p = storage.save_brand_asset(profile["id"], f"r{i}.png", content)
            profile.setdefault("visual_references", []).append(p)
            storage.record_brand_asset(profile["id"], p, kind="reference",
                                       category="product" if i < 2 else "signage")
        storage.save_brand_profile(profile)

        report = self._quality(storage, profile["id"])
        assert report["counts"]["references"] == 3
        assert report["categories"] == {"product": 2, "signage": 1}
        assert report["diversity"] is not None
        assert report["diversity"]["near_duplicate_pairs"], "identical pair not flagged"
        codes = {w["code"] for w in report["warnings"]}
        assert "many_near_duplicates" in codes
        assert "no_references" not in codes
        assert 0 <= report["readiness"] <= 100

    def test_healthy_library_has_fewer_warnings(self, tmp_path):
        storage = _make_storage(tmp_path)
        profile = storage.create_brand_profile({"name": "Healthy"})
        logo = storage.save_brand_asset(profile["id"], "logo.png", PNG_BYTES)
        profile["logo_path"] = logo
        storage.record_brand_asset(profile["id"], logo, kind="logo")
        for i in range(3):
            p = storage.save_brand_asset(profile["id"], f"r{i}.png",
                                         _png(seed=10 + i, size=(300, 300)))
            profile.setdefault("visual_references", []).append(p)
            storage.record_brand_asset(profile["id"], p, kind="reference",
                                       category=["product", "signage", "storefront"][i])
        storage.save_brand_profile(profile)

        report = self._quality(storage, profile["id"])
        codes = {w["code"] for w in report["warnings"]}
        assert "no_references" not in codes
        assert "few_references" not in codes
        assert "no_logo" not in codes
        assert "low_diversity" not in codes
        assert report["readiness"] >= 90

    def test_missing_profile_returns_none(self, tmp_path):
        storage = _make_storage(tmp_path)
        assert self._quality(storage, "11111111-1111-1111-1111-111111111111") is None


# ── API contract ──────────────────────────────────────────────────────────────

class TestBrandIntelApi:
    @pytest.fixture()
    def env(self, monkeypatch, tmp_path):
        import content_engine.studio as studio
        monkeypatch.setattr(studio, "StudioContentOrchestrator", lambda: None)
        from api import studio_routes, brand_intel_routes
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(studio_routes.router)
        app.include_router(brand_intel_routes.router)
        storage = StudioStorage(base_dir=Path(tmp_path) / "studio")
        monkeypatch.setattr(studio_routes, "storage", storage)
        monkeypatch.setattr(brand_intel_routes, "storage", storage)
        client = TestClient(app)
        created = client.post("/api/studio/brand-profiles", json={"name": "Api Brand"})
        assert created.status_code == 200
        return client, storage, created.json()["id"]

    def test_upload_with_category_records_manifest(self, env):
        client, storage, profile_id = env
        resp = client.post(
            f"/api/studio/brand-profiles/{profile_id}/assets",
            files={"file": ("shelf.png", PNG_BYTES, "image/png")},
            data={"asset_kind": "reference", "category": "packaging"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["asset"]["category"] == "packaging"
        assert body["asset"]["original_name"] == "shelf.png"
        assert body["asset_path"] in body["profile"]["visual_references"]

        # Default category for references is "other".
        resp = client.post(
            f"/api/studio/brand-profiles/{profile_id}/assets",
            files={"file": ("plain.png", PNG_BYTES, "image/png")},
            data={"asset_kind": "reference"},
        )
        assert resp.status_code == 200
        assert resp.json()["asset"]["category"] == "other"

        # Logo upload forces category "logo".
        resp = client.post(
            f"/api/studio/brand-profiles/{profile_id}/assets",
            files={"file": ("logo.png", PNG_BYTES, "image/png")},
            data={"asset_kind": "logo", "category": "product"},
        )
        assert resp.status_code == 200
        assert resp.json()["asset"]["kind"] == "logo"
        assert resp.json()["asset"]["category"] == "logo"
        assert resp.json()["profile"]["logo_path"] is not None

        # Unknown category rejected.
        resp = client.post(
            f"/api/studio/brand-profiles/{profile_id}/assets",
            files={"file": ("x.png", PNG_BYTES, "image/png")},
            data={"asset_kind": "reference", "category": "nope"},
        )
        assert resp.status_code == 422

    def test_list_patch_replace_delete_roundtrip(self, env):
        client, storage, profile_id = env
        upload = client.post(
            f"/api/studio/brand-profiles/{profile_id}/assets",
            files={"file": ("ref.png", PNG_BYTES, "image/png")},
            data={"asset_kind": "reference", "category": "product"},
        ).json()
        asset_id = upload["asset"]["asset_id"]

        listed = client.get(f"/api/brand-intel/brands/{profile_id}/assets").json()
        assert len(listed["assets"]) == 1
        assert listed["assets"][0]["asset_id"] == asset_id

        patched = client.patch(
            f"/api/brand-intel/brands/{profile_id}/assets/{asset_id}",
            json={"category": "signage", "notes": "front sign"},
        )
        assert patched.status_code == 200
        assert patched.json()["asset"]["category"] == "signage"
        assert patched.json()["asset"]["notes"] == "front sign"

        bad = client.patch(
            f"/api/brand-intel/brands/{profile_id}/assets/{asset_id}",
            json={"category": "invalid"},
        )
        assert bad.status_code == 422

        replaced = client.post(
            f"/api/brand-intel/brands/{profile_id}/assets/{asset_id}/replace",
            files={"file": ("new.png", _png(seed=5), "image/png")},
        )
        assert replaced.status_code == 200
        assert replaced.json()["asset"]["asset_id"] == asset_id
        assert replaced.json()["asset"]["category"] == "signage"
        # Same extension → the stored file is replaced in place and the schema
        # path stays valid; exactly one reference remains and it exists on disk.
        refs = replaced.json()["profile"]["visual_references"]
        assert len(refs) == 1
        assert Path(refs[0]).exists()
        assert refs[0].endswith(f"{asset_id}.png")

        deleted = client.delete(
            f"/api/brand-intel/brands/{profile_id}/assets/{asset_id}")
        assert deleted.status_code == 200
        assert deleted.json()["profile"]["visual_references"] == []
        assert client.get(
            f"/api/brand-intel/brands/{profile_id}/assets").json()["assets"] == []

        assert client.delete(
            f"/api/brand-intel/brands/{profile_id}/assets/ghost").status_code == 404
        assert client.patch(
            f"/api/brand-intel/brands/{profile_id}/assets/ghost",
            json={"notes": "x"}).status_code == 404

    def test_reference_quality_endpoint(self, env):
        client, storage, profile_id = env
        resp = client.get(f"/api/brand-intel/brands/{profile_id}/reference-quality")
        assert resp.status_code == 200
        body = resp.json()
        assert body["profile_id"] == profile_id
        assert body["brand_name"] == "Api Brand"
        assert body["counts"]["references"] == 0
        assert any(w["code"] == "no_references" for w in body["warnings"])
        assert 0 <= body["readiness"] <= 100

        resp = client.get(
            "/api/brand-intel/brands/11111111-1111-1111-1111-111111111111"
            "/reference-quality")
        assert resp.status_code == 404

    def test_unknown_profile_404s(self, env):
        client, _, _ = env
        ghost = "22222222-2222-2222-2222-222222222222"
        assert client.get(f"/api/brand-intel/brands/{ghost}/assets").status_code == 404
