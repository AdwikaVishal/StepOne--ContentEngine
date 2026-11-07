"""Conservative fact record for Studio generation prompts."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional


_FACT_FIELDS = ("activity", "audience", "date", "time", "location", "organizer", "call_to_action")
_BRIEF_LABELS = {
    "activity": "activity",
    "audience": "audience",
    "date": "date",
    "time": "time",
    "location": "location|venue",
    "organizer": "organizer|host",
    "call_to_action": "call to action|cta",
}


def build_fact_record(
    event_name: str,
    brief: str = "",
    *,
    activity: Optional[str] = None,
    audience: Optional[str] = None,
    date: Optional[str] = None,
    time: Optional[str] = None,
    location: Optional[str] = None,
    organizer: Optional[str] = None,
    call_to_action: Optional[str] = None,
    key_points: Optional[str] = None,
    brand_profile: Optional[Dict[str, Any]] = None,
    tone: Optional[str] = None,
) -> Dict[str, Any]:
    """Keep only explicit values; labeled brief fields are extracted verbatim."""
    values = {
        "activity": activity,
        "audience": audience,
        "date": date,
        "time": time,
        "location": location,
        "organizer": organizer,
        "call_to_action": call_to_action,
    }
    source = brief or ""
    for field in _FACT_FIELDS:
        if values[field] and str(values[field]).strip():
            values[field] = str(values[field]).strip()
            continue
        labels = _BRIEF_LABELS[field]
        match = re.search(rf"(?:^|[\n;])\s*(?:{labels})\s*[:=]\s*([^\n;]+)", source, re.I)
        values[field] = match.group(1).strip().rstrip(".") if match else None
    if key_points and str(key_points).strip():
        values["key_points"] = str(key_points).strip()
    else:
        values["key_points"] = None

    brand = None
    if brand_profile:
        brand_keys = (
            "name", "description", "tone_of_voice", "target_audience",
            "preferred_vocabulary", "avoid_words_claims", "preferred_cta", "hashtag_guidance",
        )
        brand = {key: brand_profile[key] for key in brand_keys if brand_profile.get(key) not in (None, "", [])}
    effective_tone = (brand_profile or {}).get("tone_of_voice") or tone
    return {
        "event_name": event_name or None,
        "verified_details": values,
        "user_brief": source.strip() or None,
        "brand_profile": brand,
        "tone": effective_tone or None,
        "unknown_fields_are_null": True,
    }
