"""
Brand Voice Preview — generate a sample paragraph from a brand profile.

Uses the existing local-only LLM provider (TorchLocalProvider →
Qwen2.5-1.5B-Instruct in models/qwen/). No external inference APIs, no
model downloads, no persistence: the preview never reads or writes
brand profile files — it only formats the (possibly unsaved) values it
is given into a prompt.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

from content_engine.providers.factory import get_llm_provider

# Small sample — one short paragraph, deterministic output.
MAX_SAMPLE_TOKENS = 240

_SYSTEM_PROMPT = (
    "You simulate a brand's writing voice. Given brand guidelines, write one "
    "short sample paragraph exactly as that brand would write it. "
    "Output ONLY the paragraph itself: no preamble, no labels, no analysis, "
    "no bullet points, no quotation marks around the paragraph. "
    "Use only the facts supplied — never invent products, services, "
    "partnerships, statistics or achievements, and never contradict the "
    "guidelines."
)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _line(label: str, value: Any) -> str:
    text = _clean(value)
    return f"- {label}: {text}" if text else ""


def build_voice_prompt(profile: Dict[str, Any]) -> Tuple[str, str]:
    """Format (possibly unsaved) profile values into (system, user) prompts.

    Only non-empty fields are included so the model is not flooded with
    defaults. Field names match the 45-field flat schema.
    """
    profile = profile or {}

    identity = "\n".join(filter(None, [
        _line("Brand name", profile.get("name")),
        _line("What the brand is about", profile.get("description")),
        _line("Industry", profile.get("industry")),
        _line("Tagline", profile.get("tagline")),
        _line("Mission", profile.get("mission")),
    ]))
    voice = "\n".join(filter(None, [
        _line("Tone", profile.get("tone_of_voice")),
        _line("Tone description", profile.get("tone_description")),
        _line("Personality traits", profile.get("personality_traits")),
        _line("Formality", profile.get("formality_level")),
        _line("Writing style", profile.get("writing_style")),
        _line("Sentence length", profile.get("sentence_length")),
        _line("Person preference (first/third person)", profile.get("person_preference")),
    ]))
    audience = "\n".join(filter(None, [
        _line("Primary audience", profile.get("target_audience")),
        _line("Secondary audience", profile.get("secondary_audience")),
        _line("Audience interests", profile.get("audience_interests")),
        _line("Audience pain points", profile.get("audience_pain_points")),
        _line("Technical knowledge level", profile.get("technical_level")),
        _line("Communication expectations", profile.get("communication_expectations")),
    ]))
    language = "\n".join(filter(None, [
        _line("Preferred words/phrases (use these)", profile.get("preferred_vocabulary")),
        _line("Words/phrases to avoid (must never appear)",
              profile.get("avoid_words_claims")),
        _line("Industry vocabulary", profile.get("industry_vocabulary")),
        _line("Emoji preference", profile.get("emoji_preference")),
        _line("Capitalization preference", profile.get("capitalization_preferences")),
        _line("Call to action", profile.get("preferred_cta")),
        _line("CTA style", profile.get("cta_style")),
        _line("Hashtag guidance", profile.get("hashtag_guidance")),
    ]))

    sections = [text for text in (identity, voice, audience, language) if text]
    if not sections:
        sections = [_line("Brand name", profile.get("name")) or "- Brand name: (not set)"]

    user = (
        "Write a short sample paragraph (60-90 words) demonstrating how this "
        "brand writes a social media post for its audience.\n\n"
        "BRAND GUIDELINES\n" + "\n".join(sections) + "\n\n"
        "Rules:\n"
        "- Match the tone, style and personality described above.\n"
        "- Respect the emoji preference exactly.\n"
        "- If words/phrases to avoid are listed, they must not appear.\n"
        "- Prefer the listed vocabulary where natural.\n"
        "- Do not invent facts, claims, products or achievements.\n"
        "- Output only the paragraph."
    )
    return _SYSTEM_PROMPT, user


def generate_voice_preview(
    profile: Dict[str, Any],
    *,
    provider: Optional[Any] = None,
) -> Dict[str, Any]:
    """Generate a voice sample via the local LLM provider.

    Raises RuntimeError when the local model is unavailable or returns
    nothing — callers surface the failure instead of substituting a
    hardcoded sample.
    """
    system, user = build_voice_prompt(profile)
    llm = provider or get_llm_provider()
    t0 = time.perf_counter()
    sample = llm.generate(
        system=system,
        user=user,
        max_tokens=MAX_SAMPLE_TOKENS,
        temperature=0.0,
    )
    duration = round(time.perf_counter() - t0, 3)
    if not sample or not str(sample).strip():
        raise RuntimeError("Local Qwen returned an empty voice sample")
    return {
        "sample": str(sample).strip(),
        "model": "Qwen2.5-1.5B-Instruct",
        "provider": getattr(llm, "name", "torch_local"),
        "local_only": True,
        "duration_s": duration,
    }
