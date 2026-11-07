"""Conservative deterministic checks for high-risk claims in generated captions.

These checks catch selected claim classes against supplied facts. They are not
semantic verification and cannot establish that every accepted sentence is true.
"""
from __future__ import annotations

import json
import re
from typing import Optional


_CLAIM_RULES = (
    ("audience eligibility", re.compile(
        r"\b(?:for all ages|all ages|open to everyone|open to all|everyone is welcome|"
        r"famil(?:y|ies)[ -]friendly|children welcome|kids welcome|adults only|"
        r"ages?\s*\d{1,2}\s*\+|\d{1,2}\s*\+\s*only)\b", re.I)),
    ("offer or price", re.compile(
        r"\b(?:free(?:\s+entry|\s+admission)?|discount(?:ed)?|\d+\s*%\s*off|"
        r"save\s+\d+%|early[ -]bird|buy\s+one|get\s+one|limited[ -]time offer)\b", re.I)),
    ("availability or attendance", re.compile(
        r"\b(?:sold[ -]out|fully booked|only\s+\d+\s+(?:spots|seats|tickets)|"
        r"\d+\s+(?:attendees|guests|participants|visitors))\b", re.I)),
    ("event recurrence", re.compile(r"\b(?:annual|yearly|monthly|weekly|inaugural)\b", re.I)),
    ("event or offer claim", re.compile(
        r"\b(?:today|tonight|tomorrow|this\s+(?:morning|afternoon|evening|weekend|week)|"
        r"next\s+(?:week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b", re.I)),
    ("outcome claim", re.compile(
        r"\b(?:transform\w*|guarantee\w*|ensure\w*|will\s+(?:learn|gain|meet|make|build|create|improve|"
        r"transform|discover|leave\s+with)|take\s+home|walk\s+away\s+with|make\s+a\s+difference|"
        r"create\s+memories|build\s+community|spark\s+\w+)\b", re.I)),
    ("venue or setting", re.compile(
        r"\b(?:in|at|inside)\s+(?:\w+\s+){0,6}"
        r"(?:space|setting|venue|location|environment)\b|\b(?:on[ -]site|in[ -]person)\b", re.I)),
    ("superlative or trend", re.compile(
        r"\b(?:latest|newest|leading|cutting[ -]edge|future\s+(?:of\s+)?[\w-]+|"
        r"\w+\s+trends?)\b", re.I)),
    ("event format", re.compile(
        r"\b(?:showcase|exhibit|feature|present|host|return|premiere)\w*\b", re.I)),
)


def unsupported_claim(caption: str, supplied_context: str) -> Optional[str]:
    """Return an issue when a detected high-risk phrase lacks explicit evidence."""
    try:
        record = json.loads(supplied_context)
    except (TypeError, json.JSONDecodeError):
        record = {}
    verified = record.get("verified_details") or {}
    # Evidence must be in user-supplied event facts, not merely the event's
    # name, brand copy, or model-facing instructions. Audience claims use the
    # audience field specifically to avoid treating unrelated brief wording as
    # proof of eligibility.
    audience_evidence = str(verified.get("audience") or "")
    fact_evidence = " ".join(
        str(value) for key, value in verified.items()
        if key not in {"audience"} and value not in (None, "", [])
    )
    fact_evidence += " " + str(record.get("user_brief") or "")
    evidence = " ".join((audience_evidence, fact_evidence)).casefold()
    for category, pattern in _CLAIM_RULES:
        for match in pattern.finditer(caption):
            phrase = match.group(0).casefold()
            relevant = audience_evidence.casefold() if category == "audience eligibility" else evidence
            equivalent = phrase.removeprefix("for ") if category == "audience eligibility" else phrase
            if phrase not in relevant and equivalent not in relevant:
                return category
    # Broad eligible-audience wording with no numeric age can take multiple
    # surface forms. Gate these too on the explicit audience field.
    broad_audience = re.search(
        r"\b(?:all ages|everyone|families|children|kids|adults)\b", caption, re.I
    )
    if broad_audience and broad_audience.group(0).casefold() not in audience_evidence.casefold():
        return "audience eligibility"
    return None
