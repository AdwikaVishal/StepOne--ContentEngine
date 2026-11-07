import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from content_engine.studio.content_orchestrator import (
    StudioContentOrchestrator,
    StudioGenerationError,
)
from content_engine.studio.facts import build_fact_record
from content_engine.copy_generator import _compact_prompt_facts


@pytest.mark.parametrize(
    ("platform", "method_name", "safe_fragment"),
    [
        ("linkedin", "generate_linkedin_caption", "LinkedIn post"),
        ("instagram", "generate_instagram_caption", "Instagram caption"),
    ],
)
def test_platform_generation_errors_are_not_replaced_with_fallback_copy(
    platform, method_name, safe_fragment
):
    generator = SimpleNamespace()
    setattr(generator, method_name, Mock(side_effect=RuntimeError("secret=/private/model/path")))
    orchestrator = StudioContentOrchestrator.__new__(StudioContentOrchestrator)
    orchestrator.copy_gen = generator

    with pytest.raises(StudioGenerationError) as caught:
        orchestrator.generate_post(
            event_name="Test Event",
            selected_assets=[],
            brief="A factual event brief",
            platforms=[platform],
        )

    assert safe_fragment in str(caught.value)
    assert "secret=" not in str(caught.value)
    assert caught.value.__cause__ is not None
    assert "secret=" in str(caught.value.__cause__)


def test_successful_qwen_captions_are_preserved():
    generator = SimpleNamespace(
        generate_linkedin_caption=Mock(return_value="A concise update about Test Event."),
        generate_instagram_caption=Mock(return_value="Join us at Test Event to share ideas."),
    )
    orchestrator = StudioContentOrchestrator.__new__(StudioContentOrchestrator)
    orchestrator.copy_gen = generator

    result = orchestrator.generate_post(
        event_name="Test Event",
        selected_assets=[],
        brief="A factual event brief",
        platforms=["linkedin", "instagram"],
    )

    assert result["platform_variants"]["linkedin"]["caption"] == "A concise update about Test Event."
    assert result["platform_variants"]["instagram"]["caption"] == "Join us at Test Event to share ideas."


def test_uncertain_image_captions_are_not_passed_as_verified_facts():
    generator = SimpleNamespace(
        generate_linkedin_caption=Mock(return_value="A grounded update about Fictional Summit."),
    )
    orchestrator = StudioContentOrchestrator.__new__(StudioContentOrchestrator)
    orchestrator.copy_gen = generator
    asset = {"asset_id": "photo-1", "caption": "a person standing near a stage"}

    result = orchestrator.generate_post(
        event_name="Fictional Summit",
        selected_assets=[asset],
        brief="A fictional community event",
        platforms=["linkedin"],
    )

    call = generator.generate_linkedin_caption.call_args
    assert "a person standing near a stage" not in call.args[2]
    assert result["image_descriptions"][0]["is_uncertain_caption"] is True
    record = json.loads(call.args[2])
    assert record["verified_details"]["date"] is None
    assert record["verified_details"]["location"] is None
    assert "a person standing near a stage" not in json.dumps(record)


def test_structured_fact_record_keeps_unknown_fields_null_and_extracts_labeled_details():
    record = build_fact_record(
        "Fictional Studio Day",
        "A fictional open studio.\nDate: June 12, 2027\nTime: 2:00 PM\nLocation: Harbor Hall",
        audience="students",
        brand_profile={"name": "Cedar Circle", "tone_of_voice": "warm", "avoid_words_claims": ["best"]},
    )
    assert record["verified_details"]["date"] == "June 12, 2027"
    assert record["verified_details"]["time"] == "2:00 PM"
    assert record["verified_details"]["location"] == "Harbor Hall"
    assert record["verified_details"]["audience"] == "students"
    assert record["verified_details"]["organizer"] is None
    assert record["brand_profile"]["avoid_words_claims"] == ["best"]


def test_prompt_only_receives_filled_fact_fields():
    record = build_fact_record(
        "Fictional Studio Day", "View student projects.",
        location="Harbor Hall",
    )
    compact = json.loads(_compact_prompt_facts(json.dumps(record)))
    assert compact["verified_details"] == {"location": "Harbor Hall"}
    assert "unknown_fields_are_null" not in compact


@pytest.mark.parametrize(
    ("model_output", "message"),
    [
        ("![photo](https://example.invalid/photo.jpg)", "unsupported image link"),
        ("Join us at [insert topic here]", "unfinished placeholder"),
        ("More details: https://example.invalid", "not provided in the brief"),
        ("End each line of text in an appropriate way.", "repeated prompt instructions"),
        ("End each line with a hashtag.", "repeated prompt instructions"),
        ("Join 500 attendees next year at the annual summit", "number not present"),
        ("Join us for a fun evening of ideas", "event or offer claim"),
        ("Transform our neighborhood into something special", "unsupported outcome claim"),
        ("Join John Smith at our meetup", "named entity not present"),
        ("Join us for our next virtual meetup", "event or offer claim"),
        ("Join us for Willows of Creativity", "named entity not present"),
        ("Join us on [Cedar Circle]", "unfinished placeholder"),
        ("Join us this afternoon for the meetup", "event or offer claim"),
        ("Join us this weekend for the meetup", "event or offer claim"),
        ("Join us for the upcoming meetup", "event or offer claim"),
        ("Join the meetup with like-minded friends", "unsupported outcome claim"),
        ("Share handmade projects and create memories", "unsupported outcome claim"),
        ("Join for an exclusive meetup", "unsupported outcome claim"),
        ("Meet the artists at the meetup", "participant or organization type"),
        ("Let's make our community vibrant", "unsupported outcome claim"),
        ("Share ideas and build something new together", "unsupported outcome claim"),
        ("Traceback: model debug output", "internal or diagnostic"),
    ],
)
def test_studio_rejects_unverified_links_and_placeholders(model_output, message):
    orchestrator = StudioContentOrchestrator.__new__(StudioContentOrchestrator)
    orchestrator.copy_gen = SimpleNamespace(
        generate_instagram_caption=Mock(return_value=model_output),
    )

    with pytest.raises(StudioGenerationError, match="passed the content checks"):
        orchestrator.generate_post(
            event_name="Fictional Meetup", selected_assets=[],
            brief="A fictional neighborhood get-together.", platforms=["instagram"],
        )
    with pytest.raises(StudioGenerationError, match=message):
        StudioContentOrchestrator._validate_generated_caption(
            model_output, "A fictional neighborhood get-together."
        )


def test_invalid_first_caption_retries_once_and_preserves_valid_retry():
    generator = SimpleNamespace(
        generate_instagram_caption=Mock(side_effect=["Join us at [insert topic]", "Join our fictional meetup to share ideas."]),
    )
    orchestrator = StudioContentOrchestrator.__new__(StudioContentOrchestrator)
    orchestrator.copy_gen = generator

    result = orchestrator.generate_post(
        event_name="Fictional Meetup", selected_assets=[],
        brief="A fictional meetup to share ideas.", platforms=["instagram"],
    )

    assert result["platform_variants"]["instagram"]["caption"] == "Join our fictional meetup to share ideas."
    assert generator.generate_instagram_caption.call_count == 2
    assert "Rewrite once" in generator.generate_instagram_caption.call_args.kwargs["correction"]


def test_invalid_retry_exhaustion_raises_sanitized_error():
    generator = SimpleNamespace(
        generate_instagram_caption=Mock(return_value="[insert topic here]"),
    )
    orchestrator = StudioContentOrchestrator.__new__(StudioContentOrchestrator)
    orchestrator.copy_gen = generator

    with pytest.raises(StudioGenerationError, match="passed the content checks") as caught:
        orchestrator.generate_post(
            event_name="Fictional Meetup", selected_assets=[],
            brief="A fictional meetup.", platforms=["instagram"],
        )
    assert generator.generate_instagram_caption.call_count == 2
    assert "insert topic" not in str(caught.value)


def test_caption_cannot_turn_event_name_into_unprovided_venue():
    context = json.dumps(build_fact_record("Fictional Meetup", "A community get-together."))
    with pytest.raises(StudioGenerationError, match="implied a venue"):
        StudioContentOrchestrator._validate_generated_caption(
            "Join us in the Fictional Meetup", context,
        )


def test_explicitly_literal_user_placeholder_is_not_removed_or_rejected():
    context = json.dumps(build_fact_record("Fictional Meetup", "Keep [Date] as literal display text."))
    caption = "Fictional Meetup: [Date]"
    StudioContentOrchestrator._validate_generated_caption(caption, context)


def test_markdown_link_label_is_not_misclassified_as_placeholder():
    context = json.dumps(build_fact_record(
        "Harbor Hall Open Studio", "View student design projects.",
        location="Harbor Hall",
    ))
    with pytest.raises(StudioGenerationError, match="link that was not provided"):
        StudioContentOrchestrator._validate_generated_caption(
            "Visit [Harbor Hall](https://example.invalid/harbor) for details.", context,
        )


def test_unsupported_markdown_link_uses_link_correction_on_retry():
    generator = SimpleNamespace(generate_linkedin_caption=Mock(side_effect=[
        "Visit [Harbor Hall](https://example.invalid/harbor) for details.",
        "View student design projects at Harbor Hall.",
    ]))
    orchestrator = StudioContentOrchestrator.__new__(StudioContentOrchestrator)
    orchestrator.copy_gen = generator
    result = orchestrator.generate_post(
        event_name="Harbor Hall Open Studio", selected_assets=[],
        brief="View student design projects.", location="Harbor Hall",
        platforms=["linkedin"],
    )
    assert result["platform_variants"]["linkedin"]["caption"] == "View student design projects at Harbor Hall."
    correction = generator.generate_linkedin_caption.call_args.kwargs["correction"]
    assert "square-bracketed" not in correction
    assert "Use only information in the verified fact record" in correction


def test_brand_name_is_not_used_in_an_unsupported_outcome_claim():
    context = json.dumps(build_fact_record("Cedar Circle Meetup", "Share one idea."))
    with pytest.raises(StudioGenerationError, match="unsupported outcome claim"):
        StudioContentOrchestrator._validate_generated_caption("Make Cedar Circle better", context)


@pytest.mark.parametrize("caption", [
    "Join Willow Library's vibrant Art Day! It's a creative celebration for all ages!",
    "Families are welcome at Willow Library Art Day.",
    "Get 20% off at Willow Library Art Day.",
    "Only 25 seats remain for Willow Library Art Day.",
    "Our annual Willow Library Art Day returns.",
])
def test_grounding_rejects_high_risk_claims_without_matching_facts(caption):
    context = json.dumps(build_fact_record(
        "Willow Library Art Day", "Browse community art and leave feedback."
    ))
    with pytest.raises(StudioGenerationError):
        StudioContentOrchestrator._validate_generated_caption(caption, context)


def test_grounding_allows_explicit_audience_and_offer_facts():
    context = json.dumps(build_fact_record(
        "Willow Library Art Day",
        "A family-friendly event with free entry.",
        audience="all ages",
    ))
    StudioContentOrchestrator._validate_generated_caption(
        "Willow Library Art Day is a creative celebration for all ages, with free entry.",
        context,
    )


def test_retry_that_introduces_unsupported_eligibility_claim_is_rejected():
    generator = SimpleNamespace(generate_instagram_caption=Mock(side_effect=[
        "Join Willow Library Art Day to browse community art and leave feedback this weekend.",
        "Join Willow Library Art Day for a creative celebration for all ages.",
    ]))
    orchestrator = StudioContentOrchestrator.__new__(StudioContentOrchestrator)
    orchestrator.copy_gen = generator
    with pytest.raises(StudioGenerationError, match="passed the content checks"):
        orchestrator.generate_post(
            event_name="Willow Library Art Day", selected_assets=[],
            brief="Browse community art and leave feedback.", platforms=["instagram"],
        )
    assert generator.generate_instagram_caption.call_count == 2


def test_grounding_uses_audience_field_not_uncertain_image_caption():
    from content_engine.studio.grounding import unsupported_claim
    record = build_fact_record("Fictional Event", "A community gathering.")
    context = json.dumps(record)
    issue = unsupported_claim("A family-friendly event for all ages.", context)
    assert issue == "audience eligibility"


@pytest.mark.parametrize("platform", ["linkedin", "instagram"])
@pytest.mark.parametrize("caption", [
    "Join us tonight at Harbor Hall!",
    "Meet us today at Willow Library.",
    "Transform your community at our meetup.",
    "You will leave with new skills.",
    "Only 25 seats remain; get 20% off at example.invalid.",
])
def test_high_risk_claims_rejected_on_both_platforms(platform, caption):
    context = json.dumps(build_fact_record(
        "Willow Library Art Day", "Browse community art and leave feedback."
    ))
    with pytest.raises(StudioGenerationError):
        StudioContentOrchestrator._validate_generated_caption(
            caption, context, max_chars=2200 if platform == "instagram" else 3000
        )


@pytest.mark.parametrize("platform", ["linkedin", "instagram"])
def test_neutral_copy_using_only_supplied_facts_is_accepted(platform):
    context = json.dumps(build_fact_record(
        "Willow Library Art Day", "Browse community art and leave feedback.",
        activity="Browse community art and leave feedback",
    ))
    StudioContentOrchestrator._validate_generated_caption(
        "Willow Library Art Day: browse community art and leave feedback.",
        context,
        max_chars=2200 if platform == "instagram" else 3000,
    )


def test_generated_setting_superlative_and_trend_claims_are_rejected():
    context = json.dumps(build_fact_record(
        "Juniper Studio Open House", "A fictional open house to view student projects.",
        date="September 18, 2027", location="Juniper Studio",
    ))
    with pytest.raises(StudioGenerationError):
        StudioContentOrchestrator._validate_generated_caption(
            "Join us on September 18, 2027, for the Juniper Studio Open House where students "
            "showcase their latest projects in a professional setting. Visit our location at "
            "Juniper Studio for an insightful look into future design trends.", context
        )


def test_unverified_physical_space_is_not_inferred_from_brand_tone():
    context = json.dumps(build_fact_record(
        "Gentle Hands Craft Table",
        "A fictional craft session where neighbors can share small handmade projects.",
        brand_profile={"tone_of_voice": "calm and welcoming"},
    ))
    with pytest.raises(StudioGenerationError):
        StudioContentOrchestrator._validate_generated_caption(
            "Join Gentle Hands' crafting community! Share your small handmade projects "
            "with neighbors in this calm and welcoming space.", context
        )


def test_studio_api_returns_safe_generation_error_and_marks_job_failed(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import content_engine.studio as studio_package

    monkeypatch.setattr(studio_package, "StudioContentOrchestrator", lambda: None)
    from api import studio_routes

    storage = studio_routes.StudioStorage(base_dir=Path(tmp_path))
    project = storage.create_project(name="Test Event", platforms=["linkedin"])

    class FailingOrchestrator:
        def generate_post(self, **kwargs):
            raise StudioGenerationError(
                "Qwen could not generate the LinkedIn post. Check the local model, then retry."
            ) from RuntimeError("secret=/private/model/path")

    monkeypatch.setattr(studio_routes, "storage", storage)
    monkeypatch.setattr(studio_routes, "content_orch", FailingOrchestrator())
    app = FastAPI()
    app.include_router(studio_routes.router)

    response = TestClient(app).post(
        f"/api/studio/projects/{project['id']}/generate",
        json={"platforms": ["linkedin"]},
    )

    assert response.status_code == 503
    assert "Qwen could not generate the LinkedIn post" in response.json()["detail"]
    assert "secret=" not in response.text
    jobs = [json.loads(path.read_text()) for path in storage.jobs_dir.glob("*.json")]
    assert len(jobs) == 1
    assert jobs[0]["status"] == "failed"
    assert "Qwen could not generate the LinkedIn post" in jobs[0]["error"]
    assert "secret=" not in jobs[0]["error"]
    saved_project = storage.get_project(project["id"])
    assert not ((saved_project or {}).get("platform_variants") or {}).get("linkedin", {}).get("caption")


def test_studio_api_forwards_structured_facts_and_persists_mocked_success(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api import studio_routes

    storage = studio_routes.StudioStorage(base_dir=Path(tmp_path))
    project = storage.create_project(name="Fictional Open Studio", platforms=["instagram"])
    observed = {}
    caption = "Visit Harbor Hall on June 12, 2027 for the open studio."

    from content_engine.studio.content_orchestrator import StudioContentOrchestrator

    orchestrator = StudioContentOrchestrator.__new__(StudioContentOrchestrator)
    orchestrator.copy_gen = SimpleNamespace(
        generate_instagram_caption=Mock(return_value=caption),
    )
    original_generate_post = orchestrator.generate_post

    def capture_grounded_generation(**kwargs):
        observed.update(kwargs)
        return original_generate_post(**kwargs)

    monkeypatch.setattr(studio_routes, "storage", storage)
    monkeypatch.setattr(studio_routes, "content_orch", SimpleNamespace(generate_post=capture_grounded_generation))
    app = FastAPI()
    app.include_router(studio_routes.router)
    response = TestClient(app).post(
        f"/api/studio/projects/{project['id']}/generate",
        json={
            "event_name": "Fictional Open Studio", "brief": "Visitors can view student designs.",
            "platforms": ["instagram"], "date": "June 12, 2027", "time": "2:00 PM",
            "location": "Harbor Hall", "activity": "View student designs",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["content"]["platform_variants"]["instagram"]["caption"] == caption
    assert observed["date"] == "June 12, 2027"
    assert observed["time"] == "2:00 PM"
    assert observed["location"] == "Harbor Hall"
    assert storage.get_job(payload["job_id"])["status"] == "completed"
    saved = storage.get_project(project["id"])
    assert saved["platform_variants"]["instagram"]["caption"] == payload["content"]["platform_variants"]["instagram"]["caption"]
