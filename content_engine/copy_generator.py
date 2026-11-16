"""
Copy Generator
Produces platform-specific captions from event context + asset metadata.

Production generation uses the cached local Qwen model only. Template helpers
remain available for explicitly requested previews, but generation failures are
surfaced to the caller instead of being converted into template copy.

Event type detection:
  award_ceremony  → "award", "handshake", "applause"
  keynote         → "keynote", "speech", "stage", "presentation"
  networking      → "networking", "handshake", "dinner"
  workshop        → "workshop", "exhibition"
  default         → generic professional event

A/B variants: generate_variants() returns {"primary": str, "variants": [str, ...]}

Brand voice integration:
  All captions follow StepOne's brand voice:
  - Clear over clever
  - Active over passive
  - Specific over vague
  - Confident over tentative
  - Human over corporate
"""

import json
import os
import re
import time
import warnings
from dataclasses import dataclass, field
from typing import List, Optional, Dict

from config import QWEN_MODEL_PATH

from content_engine.ai_mode import is_cloud_testing
from content_engine.data_types import AssetMetadata
from content_engine.brand_voice import stepone_brand_voice, BrandVoice
from content_engine.providers import get_llm_provider
from content_engine.providers.base import LLMProvider

try:
    from api.logger import get_logger
    _log = get_logger(__name__)
except Exception:
    import logging
    _log = logging.getLogger(__name__)


# ── Event type detection ──────────────────────────────────────────────────────

_EVENT_CLUSTERS: Dict[str, List[str]] = {
    "award_ceremony": ["award", "handshake", "applause"],
    "keynote":        ["keynote", "speech", "stage", "presentation"],
    "networking":     ["networking", "handshake", "dinner"],
    "workshop":       ["workshop", "exhibition"],
}


def _detect_event_type(assets: List[AssetMetadata]) -> str:
    scores: Dict[str, float] = {k: 0.0 for k in _EVENT_CLUSTERS}
    for asset in assets:
        for concept, score in asset.relevance_scores.items():
            for event_type, keywords in _EVENT_CLUSTERS.items():
                if concept in keywords:
                    scores[event_type] += score
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "default"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hashtag(text: str) -> str:
    return "#" + re.sub(r"[^a-zA-Z0-9]", "", text.title())


def _top_concepts(assets: List[AssetMetadata], n: int = 3) -> List[str]:
    freq: dict = {}
    for a in assets:
        for concept in a.scene_concepts[:3]:
            freq[concept] = freq.get(concept, 0) + 1
    return [c for c, _ in sorted(freq.items(), key=lambda x: x[1], reverse=True)[:n]]


def _compact_prompt_facts(serialized_record: str) -> str:
    """Send known facts only; keep null/missing fields out of model context."""
    try:
        record = json.loads(serialized_record)
    except (TypeError, json.JSONDecodeError):
        return serialized_record
    details = record.get("verified_details") or {}
    compact = {
        "event_name": record.get("event_name"),
        "verified_details": {key: value for key, value in details.items() if value not in (None, "", [])},
        "user_brief": record.get("user_brief"),
        "brand_profile": record.get("brand_profile"),
        "tone": record.get("tone"),
    }
    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


def _total_faces(assets: List[AssetMetadata]) -> int:
    return sum(a.face_count for a in assets)


# ── Rich event context for LLM prompting ─────────────────────────────────────

@dataclass
class _EventContext:
    event_name: str
    event_description: str
    event_type: str
    detected_concepts: List[str]
    scene_labels: List[str]
    total_faces: int
    video_highlight_count: int
    top_asset_scores: List[float]
    hashtag: str


def _build_context(
    event_name: str,
    assets: List[AssetMetadata],
    event_description: str = "",
) -> _EventContext:
    concepts = _top_concepts(assets, 8)
    all_labels: List[str] = []
    for a in assets[:10]:
        all_labels.extend(a.scene_concepts[:3])
    # deduplicate preserving order
    seen: set = set()
    unique_labels = [l for l in all_labels if not (l in seen or seen.add(l))]  # type: ignore[func-returns-value]

    video_clips = 0
    for a in assets:
        if a.asset_type == "video" and a.highlight_clips:
            video_clips = len(a.highlight_clips)
            break

    return _EventContext(
        event_name=event_name,
        event_description=event_description or event_name,
        event_type=_detect_event_type(assets),
        detected_concepts=concepts,
        scene_labels=unique_labels[:10],
        total_faces=_total_faces(assets),
        video_highlight_count=video_clips,
        top_asset_scores=[round(a.final_score, 2) for a in sorted(assets, key=lambda x: x.final_score, reverse=True)[:3]],
        hashtag=_hashtag(event_name),
    )


# ── Brand context ───────────────────────────────────────────────────────────────

@dataclass
class BrandContext:
    """Brand-specific guidance injected into every caption prompt."""
    brand_name: Optional[str] = None
    brand_description: Optional[str] = None
    brand_tone: Optional[str] = None
    preferred_vocabulary: Optional[List[str]] = None
    avoided_words: Optional[List[str]] = None
    campaign_objective: Optional[str] = None
    campaign_description: Optional[str] = None
    audience: Optional[str] = None

    def summary(self) -> str:
        """Return a compact, non-null brand context block for prompting."""
        parts: List[str] = []
        if self.brand_name:
            parts.append(f"Brand: {self.brand_name}")
        if self.brand_description:
            parts.append(f"Brand description: {self.brand_description}")
        if self.brand_tone:
            parts.append(f"Brand tone: {self.brand_tone}")
        if self.preferred_vocabulary:
            parts.append(f"Preferred vocabulary: {', '.join(self.preferred_vocabulary[:8])}")
        if self.avoided_words:
            parts.append(f"Avoid these words/phrases: {', '.join(self.avoided_words[:8])}")
        if self.campaign_objective:
            parts.append(f"Campaign objective: {self.campaign_objective}")
        if self.campaign_description:
            parts.append(f"Campaign description: {self.campaign_description}")
        if self.audience:
            parts.append(f"Target audience: {self.audience}")
        return "\n".join(f"- {p}" for p in parts) if parts else "No brand context available."


# ── Placeholder validation ──────────────────────────────────────────────────────

_PLACEHOLDER_RE = re.compile(r"[\[{]\s*[a-zA-Z_][a-zA-Z0-9_]*\s*[\]}]")


def detect_placeholders(text: str) -> List[str]:
    """Return unresolved template placeholders like [date], {brand_name}, [industry]."""
    return _PLACEHOLDER_RE.findall(text or "")


def strip_placeholders(text: str) -> str:
    """Remove unresolved placeholder tokens, collapsing surrounding whitespace."""
    cleaned = _PLACEHOLDER_RE.sub("", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def validate_no_placeholders(text: str) -> Dict[str, object]:
    """Validate that text contains no unresolved placeholders.

    Returns {"valid": bool, "placeholders": List[str], "cleaned": str}
    """
    found = detect_placeholders(text)
    return {
        "valid": len(found) == 0,
        "placeholders": found,
        "cleaned": strip_placeholders(text) if found else text,
    }


# ── Generation metadata ─────────────────────────────────────────────────────────

@dataclass
class GenerationMetadata:
    provider: str
    model: str
    model_path: str
    operation: str
    inference_occurred: bool
    fallback_reason: Optional[str] = None
    validation: Optional[Dict[str, object]] = None
    device: Optional[str] = None
    duration_s: Optional[float] = None


# ── Groq client ───────────────────────────────────────────────────────────────

class _GroqGenerator:
    """
    Wraps the Groq API for ultra-fast LLM caption generation.
    Loaded once, reused across all caption calls.
    """

    def __init__(self, api_key: str, model: str, service_tier: str, temperature: float):
        from groq import Groq
        self._client = Groq(api_key=api_key)
        self._model = model
        self._service_tier = service_tier
        self._temperature = temperature
        _log.info("groq_ready", model=model, tier=service_tier)

    def complete(self, prompt: str, max_tokens: int = 400) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self._temperature,
            max_tokens=max_tokens,
            service_tier=self._service_tier,
        )
        return response.choices[0].message.content.strip()

    # ── Platform prompts ──────────────────────────────────────────────────────

    def linkedin(self, ctx: _EventContext) -> str:
        concepts_str = ", ".join(ctx.detected_concepts[:5]) if ctx.detected_concepts else "networking and keynotes"
        scenes_str   = ", ".join(ctx.scene_labels[:4]) if ctx.scene_labels else "the main stage"
        faces_line   = (
            f"Around {ctx.total_faces} people were visibly engaged in key moments."
            if ctx.total_faces > 0 else ""
        )
        event_type_hint = {
            "award_ceremony": "This was an awards ceremony — focus on recognition, achievement, and the emotional weight of the room.",
            "keynote":        "This was a keynote-heavy event — focus on ideas, insights, and what the speaker said that stuck.",
            "networking":     "This was a networking event — focus on conversations, connections, and the energy between people.",
            "workshop":       "This was a workshop — focus on learning, hands-on moments, and practical takeaways.",
        }.get(ctx.event_type, "This was a professional event.")

        prompt = f"""You attended {ctx.event_name} and are writing a LinkedIn post about it.

EVENT CONTEXT:
- Description: {ctx.event_description}
- {event_type_hint}
- What the AI detected in photos: {scenes_str}
- Key themes observed: {concepts_str}
- {faces_line}

REQUIREMENTS:
- Write in FIRST PERSON as if you genuinely attended
- Be specific — reference actual observations from the context above
- Professional tone, NO emojis in the body text
- NO "thrilled to announce", NO "excited to share", NO corporate filler
- Structure: opening observation → 2-3 specific insights → closing question
- End with a genuine question that invites engagement
- Max 220 words
- Include {ctx.hashtag} and 2 relevant hashtags at the end

Write the LinkedIn post (no title, no preamble, just the post):"""

        return self.complete(prompt, max_tokens=380)

    def instagram(self, ctx: _EventContext) -> str:
        concepts_str = ", ".join(ctx.detected_concepts[:3]) if ctx.detected_concepts else "the event"
        prompt = f"""You attended {ctx.event_name} and are writing an Instagram carousel caption.

EVENT CONTEXT:
- Themes detected: {concepts_str}
- Crowd: {ctx.total_faces} faces in key shots
- Event type: {ctx.event_type}

REQUIREMENTS:
- Casual, lowercase, conversational — NOT corporate
- 3-5 short punchy lines
- 2-3 emojis used naturally (not forced)
- End with a CTA: "swipe →", "save this", or "tag someone"
- Include {ctx.hashtag} and 2-3 relevant hashtags
- Max 100 words

Write the Instagram caption:"""

        return self.complete(prompt, max_tokens=180)

    def reel(self, ctx: _EventContext) -> str:
        clips_line = f"{ctx.video_highlight_count} highlight clips extracted." if ctx.video_highlight_count else ""
        prompt = f"""Write a short Instagram Reel caption for {ctx.event_name}.

Context: {ctx.event_description}. {clips_line}

Requirements:
- Very short: 15-25 words max
- Energetic, punchy
- 1-2 emojis
- End with a question or "tag someone" CTA
- Include {ctx.hashtag}

Write only the caption:"""

        return self.complete(prompt, max_tokens=80)

    def stories(self, ctx: _EventContext, num_frames: int) -> List[str]:
        """Generate sequential story captions as a narrative arc."""
        prompt = f"""Write {num_frames} Instagram Story captions for {ctx.event_name}.

These are sequential frames telling a story arc: arrival → main event → highlight → sign-off.
Event context: {ctx.event_description}
Themes: {", ".join(ctx.detected_concepts[:3]) if ctx.detected_concepts else "the event"}

Requirements:
- Each caption: 5-10 words only
- Casual, emoji-friendly
- Tell a narrative arc across the {num_frames} frames
- Number each one: "1.", "2.", etc.

Write the {num_frames} captions:"""

        raw = self.complete(prompt, max_tokens=120)
        # Parse numbered lines
        lines = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Strip leading "1." "2." etc
            cleaned = re.sub(r"^\d+[\.\)]\s*", "", line).strip()
            if cleaned:
                lines.append(cleaned)
        # Pad or trim to exact count
        fallback = _story_captions_template(ctx.event_name, num_frames)
        result = lines[:num_frames]
        while len(result) < num_frames:
            result.append(fallback[len(result)])
        return result

    def generate_all_batch(self, ctx: _EventContext, num_story_frames: int = 4) -> dict:
        """
        Generate all platform captions in a single LLM call — 2-3x faster
        than 4 individual calls. Falls back to individual calls on JSON error.
        """
        prompt = f"""You are a content creator who just attended {ctx.event_name}.

EVENT CONTEXT:
- Description: {ctx.event_description}
- Event type: {ctx.event_type}
- Key themes detected from photos: {', '.join(ctx.detected_concepts[:5]) or 'networking and keynotes'}
- {ctx.total_faces} people visibly engaged
- Scene labels: {', '.join(ctx.scene_labels[:5])}

Generate captions for all platforms below. Return ONLY valid JSON.

{{
  "linkedin": "Professional LinkedIn post, first person, 150-220 words, no emojis, specific observations from event, end with question. Include {ctx.hashtag} and 2 hashtags.",

  "instagram": "Instagram carousel caption, casual lowercase, 3-5 lines, 2-3 emojis, end with CTA. Include {ctx.hashtag} and 2-3 hashtags.",

  "reel": "Instagram Reel caption, very short 15-25 words, energetic, 1-2 emojis, tag CTA. Include {ctx.hashtag}.",

  "stories": ["Story 1 caption (5-10 words)", "Story 2 caption (5-10 words)", "Story 3 caption (5-10 words)", "Story 4 caption (5-10 words)"]
}}

Follow this brand voice: Clear over clever. Active over passive. Specific over vague. Confident over tentative. Human over corporate.

Return ONLY valid JSON with no markdown formatting, no code blocks, no explanation:"""

        try:
            raw = self.complete(prompt, max_tokens=800)
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1]
                cleaned = cleaned.rsplit("```", 1)[0]
            result = json.loads(cleaned)
            if not isinstance(result.get("stories"), list):
                result["stories"] = _story_captions_template(ctx.event_name, num_story_frames)
            while len(result["stories"]) < num_story_frames:
                result["stories"].append(_story_captions_template(ctx.event_name, 1)[0])
            result["stories"] = result["stories"][:num_story_frames]
            return result
        except Exception:
            return None

    def variant_linkedin(self, ctx: _EventContext) -> List[str]:
        """Generate 2 alternative LinkedIn angles."""
        tag = ctx.hashtag
        v1_prompt = f"""Write a LinkedIn post about {ctx.event_name} structured as 3 honest questions the event left you with.
Start with "Three questions {ctx.event_name} left me with:"
Each question should be thought-provoking and specific to a professional event.
End with "Still processing." 
Include {tag} #EventInsights
Max 120 words. Write only the post:"""

        v2_prompt = f"""Write a LinkedIn post about {ctx.event_name} structured as "what I expected vs what I got".
Format: "What I expected: [something generic]. What I got: [something specific and insightful]."
End with a line about the ROI of showing up in person.
Include {tag} #Leadership
Max 100 words. Write only the post:"""

        v1 = self.complete(v1_prompt, max_tokens=200)
        v2 = self.complete(v2_prompt, max_tokens=180)
        return [v1, v2]

    def variant_instagram(self, ctx: _EventContext) -> List[str]:
        """Generate 2 alternative Instagram angles."""
        tag = ctx.hashtag
        v1_prompt = f"""Write an Instagram caption for {ctx.event_name} as a "things that happened that the official recap won't mention" thread.
Use → bullet points for 3 specific moments.
End with "save this if you're going next year 📌"
Include {tag} #EventLife
Max 80 words. Write only the caption:"""

        v2_prompt = f"""Write an Instagram caption for {ctx.event_name} as a "rate this event" post.
Rate: content, networking, coffee, and one unexpected thing — each out of 10.
Funny and relatable tone.
Include {tag} #ConferenceLife
Max 60 words. Write only the caption:"""

        v1 = self.complete(v1_prompt, max_tokens=150)
        v2 = self.complete(v2_prompt, max_tokens=120)
        return [v1, v2]


# ── Template fallbacks ────────────────────────────────────────────────────────

def _linkedin_template(event_name: str, assets: List[AssetMetadata]) -> str:
    concepts   = _top_concepts(assets)
    faces      = _total_faces(assets)
    tag        = _hashtag(event_name)
    event_type = _detect_event_type(assets)

    if event_type == "award_ceremony":
        opening = f"Proud to have been part of {event_name}."
        body    = "Watching people get recognised for work that genuinely moves the needle — that's the kind of room that reminds you why the work matters."
        cta     = "Who in your network deserves more recognition right now?"
    elif event_type == "keynote":
        concept_line = f"The session on {concepts[0]} reframed how I think about the problem." if concepts else "The keynote reframed how I think about the problem."
        opening = f"Back from {event_name}."
        body    = f"{concept_line} Not the polished slides — the unscripted Q&A after, where the real thinking happened."
        cta     = "What's the most useful thing a speaker has said to you recently?"
    elif event_type == "networking":
        opening = f"Just wrapped {event_name}."
        body    = (f"{'Over ' + str(faces) + ' people in the room' if faces > 10 else 'A focused room'}. "
                   "The best conversations happened between sessions, not during them.")
        cta     = "What's your go-to opener at industry events?"
    else:
        concept_line = (f"The conversations around {', '.join(concepts)} were the highlight." if concepts else "The conversations were the real highlight.")
        opening = f"Just wrapped {event_name} — here's what actually stood out."
        body    = f"{concept_line} Not the polished keynote slides, but the unscripted moments between sessions where the real thinking happens."
        cta     = "What's the most useful thing you've taken from an industry event recently?"

    return f"""{opening}

{body}

Three things I'm taking back to the team:
1. The gap between what people say on stage and what they discuss in the hallway is where the opportunity lives.
2. The best questions came from the audience, not the panellists.
3. Every event has one conversation that makes the whole trip worth it. Find it early.

{cta}

{tag} #ProfessionalDevelopment #EventInsights #Leadership"""


def _instagram_carousel_template(event_name: str, assets: List[AssetMetadata]) -> str:
    concepts    = _top_concepts(assets, 2)
    tag         = _hashtag(event_name)
    concept_str = f" ({' + '.join(concepts)})" if concepts else ""
    return f"""we went to {event_name}{concept_str} so you don't have to 😅

swipe for the moments that didn't make the official recap →

save this if you're going next year 📌

{tag} #EventLife #BehindTheScenes #NetworkingIRL"""


def _instagram_reel_template(event_name: str, assets: List[AssetMetadata]) -> str:
    tag = _hashtag(event_name)
    return f"""24 hours at {event_name} 🎬

the energy? unmatched.
the learnings? still processing.
the coffee? surprisingly good.

tag someone who needs to be in the room next year 👇

{tag} #EventReel #DayInTheLife #ContentCreator"""


def _story_captions_template(event_name: str, num_slides: int) -> List[str]:
    arc = [
        f"We're at {event_name} ✨",
        "The main stage 👀",
        "Best conversation of the day 🎯",
        "See you next year 👋",
        "The room before it filled up 📸",
        "This is why we show up 🙌",
    ]
    return arc[:num_slides]


# ── LLM Provider ───────────────────────────────────────────────────────


class CopyGenerator:
    """
    Generates platform-specific captions.

    Uses the mode-appropriate LLM provider (MLX in local mode, Groq in
    cloud_testing mode). No implicit template fallback — generation failures
    are surfaced to the caller.

    Args:
        use_llm: retained for call-site compatibility (always True).
        groq_key: retained for call-site compatibility (unused; Groq key is
                  read from GROQ_API_KEY env var via the provider factory).
        llm_provider: optional pre-constructed LLMProvider. If not provided,
                      the factory selects one based on AI_EXECUTION_MODE.
        brand_context: optional BrandContext with brand/campaign guidance injected
                       into every caption prompt.
    """

    def __init__(
        self,
        use_llm: bool = True,
        groq_key: Optional[str] = None,
        llm_provider: Optional[LLMProvider] = None,
        brand_context: Optional[BrandContext] = None,
    ):
        self._groq = None  # Groq handled through provider, not direct client
        self._provider = llm_provider or get_llm_provider()
        self._mlx_client = None
        self._mlx_errors = None
        self._brand_context = brand_context or BrandContext()
        self._last_metadata: Optional[GenerationMetadata] = None

    @property
    def last_metadata(self) -> Optional[GenerationMetadata]:
        """Metadata from the most recent generation call."""
        return self._last_metadata

    def _record_metadata(
        self,
        operation: str,
        inference_occurred: bool,
        fallback_reason: Optional[str] = None,
        validation: Optional[Dict[str, object]] = None,
        duration_s: Optional[float] = None,
    ) -> None:
        provider = self._provider
        self._last_metadata = GenerationMetadata(
            provider=provider.name,
            model=getattr(provider, "MODEL", "Qwen2.5-1.5B-Instruct"),
            model_path=getattr(provider, "MODEL_PATH", str(QWEN_MODEL_PATH)),
            operation=operation,
            inference_occurred=inference_occurred,
            fallback_reason=fallback_reason,
            validation=validation,
            device=getattr(provider, "device", "cpu"),
            duration_s=duration_s,
        )

    def _generate(
        self,
        prompt: str,
        max_new_tokens: int,
        correction: str = "",
        system_prompt: Optional[str] = None,
        operation: str = "caption",
        brand_context: Optional[BrandContext] = None,
        validate_placeholders: bool = True,
        max_correction_attempts: int = 2,
    ) -> str:
        """Generate text using the local Qwen provider.

        Routes exclusively through TorchLocalProvider (Qwen2.5-1.5B-Instruct,
        models/qwen/). No cloud fallback, no template substitution on failure.

        If validate_placeholders is true and unresolved placeholders are
        detected, a bounded correction/regeneration is attempted (up to
        max_correction_attempts) before returning the cleaned output.
        """
        ctx = brand_context or self._brand_context

        # Prepend brand context to the user prompt when available
        brand_block = ctx.summary()
        if brand_block and brand_block != "No brand context available.":
            prompt = f"{brand_block}\n\n{prompt}"

        if correction:
            prompt = f"{prompt}\n\nRetry constraint: {correction}"

        system = system_prompt or (
            "You write concise, accurate social media copy. Follow the user request exactly. "
            "Use only supplied facts. Never emit instructions, analysis, or placeholders. "
            "Never invent dates, statistics, or event facts not supplied in the context."
        )

        provider = self._provider
        t0 = time.perf_counter()
        inference_occurred = False
        output = ""
        try:
            output = provider.generate(
                system=system,
                user=prompt,
                max_tokens=max_new_tokens,
                temperature=0.0,  # Deterministic for factual copy
            )
            inference_occurred = True
            if not output:
                raise RuntimeError("Provider returned empty output")

            # Placeholder validation with bounded correction
            if validate_placeholders:
                for attempt in range(max_correction_attempts + 1):
                    validation = validate_no_placeholders(output)
                    if validation["valid"]:
                        break
                    if attempt < max_correction_attempts:
                        correction_msg = (
                            f"The previous output contained unresolved template placeholders: "
                            f"{', '.join(validation['placeholders'])}. "
                            f"Regenerate without any bracketed or brace-enclosed placeholders. "
                            f"If a detail is missing, rephrase naturally to omit it — never invent dates, "
                            f"numbers, or event facts. Do not use [ ] or {{ }} tokens."
                        )
                        output = provider.generate(
                            system=system,
                            user=f"{prompt}\n\nRetry constraint: {correction_msg}",
                            max_tokens=max_new_tokens,
                            temperature=0.0,
                        )
                        if not output:
                            break
                else:
                    # Final fallback: strip any remaining placeholders
                    output = strip_placeholders(output)

            duration = time.perf_counter() - t0
            self._record_metadata(
                operation=operation,
                inference_occurred=inference_occurred,
                validation=validate_no_placeholders(output) if validate_placeholders else None,
                duration_s=round(duration, 4),
            )
            _log.info(
                "llm_generation_ok",
                provider=provider.name,
                model="Qwen2.5-1.5B-Instruct",
                model_path=str(QWEN_MODEL_PATH),
                device=getattr(provider, "device", "cpu"),
                operation=operation,
                duration_s=round(duration, 4),
                max_tokens=max_new_tokens,
                success=True,
                inference_occurred=True,
            )
            return output
        except Exception as e:
            duration = time.perf_counter() - t0
            self._record_metadata(
                operation=operation,
                inference_occurred=inference_occurred,
                fallback_reason=str(e),
                duration_s=round(duration, 4),
            )
            _log.error(
                "llm_generation_failed",
                provider=provider.name,
                model="Qwen2.5-1.5B-Instruct",
                model_path=str(QWEN_MODEL_PATH),
                device=getattr(provider, "device", "cpu"),
                operation=operation,
                duration_s=round(duration, 4),
                success=False,
                error=str(e),
            )
            raise RuntimeError(f"LLM generation failed ({provider.name}): {e}") from e

    @property
    def backend(self) -> str:
        return self._provider.name

    # ── Batch generation (all platforms in one LLM call) ────────────────────

    def generate_all_captions_batch(
        self,
        event_name: str,
        selections: List[AssetMetadata],
        event_description: str = "",
        num_story_frames: int = 4,
        brand_context: Optional[BrandContext] = None,
    ) -> Optional[Dict[str, object]]:
        """
        Generate all platform captions in a single Qwen call (2-3x faster).
        Returns None if Qwen unavailable or JSON parsing fails.
        """
        try:
            ctx = _build_context(event_name, selections, event_description)
            brand_ctx = brand_context or self._brand_context
            brand_block = brand_ctx.summary()

            concepts_str = ", ".join(ctx.detected_concepts[:5]) or "networking and keynotes"
            scenes_str = ", ".join(ctx.scene_labels[:5])

            prompt = f"""You are a content creator who just attended {ctx.event_name}.

BRAND CONTEXT:
{brand_block}

EVENT CONTEXT:
- Event: {ctx.event_name}
- Description: {ctx.event_description}
- Event type: {ctx.event_type}
- Key themes detected from photos: {concepts_str}
- {ctx.total_faces} people visibly engaged
- Scene labels: {scenes_str}

Generate captions for all platforms below. Return ONLY valid JSON.

{{
  "linkedin": "Professional LinkedIn post, first person, 150-250 words, no emojis, specific observations from the event, end with a question. Include {ctx.hashtag} and 2 hashtags. No bracketed placeholders. Never invent dates or facts.",

  "instagram": "Instagram carousel caption, casual lowercase, 3-5 lines, 2-3 emojis, end with a CTA. Include {ctx.hashtag} and 2-3 hashtags. No bracketed placeholders.",

  "reel": "Instagram Reel caption, very short 15-25 words, energetic, 1-2 emojis, tag CTA. Include {ctx.hashtag}. No bracketed placeholders.",

  "stories": ["Story 1 caption (5-10 words)", "Story 2 caption (5-10 words)", "Story 3 caption (5-10 words)", "Story 4 caption (5-10 words)"]
}}

Follow this brand voice: Clear over clever. Active over passive. Specific over vague. Confident over tentative. Human over corporate.

Return ONLY valid JSON with no markdown formatting, no code blocks, no explanation:"""

            raw = self._generate(prompt, max_new_tokens=900, brand_context=brand_ctx, operation="batch")
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1]
                cleaned = cleaned.rsplit("```", 1)[0]
            result = json.loads(cleaned)
            stories = result.get("stories")
            if not isinstance(stories, list) or len(stories) < num_story_frames:
                # Never fabricate/pad with template captions — surface the
                # shortfall to the caller so it can decide how to respond.
                return None
            result["stories"] = [str(s) for s in stories[:num_story_frames]]
            # Validate placeholders in all outputs
            for key in ("linkedin", "instagram", "reel"):
                val = result.get(key)
                if isinstance(val, str):
                    v = validate_no_placeholders(val)
                    if not v["valid"]:
                        result[key] = v["cleaned"]
            _log.info("batch_captions_done", platforms=", ".join(result.keys()))
            return result
        except Exception as e:
            _log.warning("batch_captions_failed", error=str(e))
            return None

    # ── LinkedIn ──────────────────────────────────────────────────────────────

    def generate_linkedin_caption(
        self,
        event_name: str,
        assets: List[AssetMetadata],
        event_description: str = "",
        correction: str = "",
        brand_context: Optional[BrandContext] = None,
    ) -> str:
        """Generate a contextual LinkedIn post via Qwen.

        Includes brand voice, event details, detected visual concepts, audience,
        and platform requirements. Never emits bracketed placeholders.
        """
        ctx = _build_context(event_name, assets, event_description)
        brand_ctx = brand_context or self._brand_context
        brand_block = brand_ctx.summary()

        concepts_str = ", ".join(ctx.detected_concepts[:6]) if ctx.detected_concepts else "professional event moments"
        scenes_str = ", ".join(ctx.scene_labels[:5]) if ctx.scene_labels else "the event"
        faces_line = (
            f"About {ctx.total_faces} people were visibly engaged in key shots."
            if ctx.total_faces > 0 else ""
        )
        event_type_hint = {
            "award_ceremony": "This was an awards ceremony — focus on recognition, achievement, and the emotional weight of the room.",
            "keynote": "This was a keynote-heavy event — focus on ideas, insights, and what the speaker said that stuck.",
            "networking": "This was a networking event — focus on conversations, connections, and the energy between people.",
            "workshop": "This was a workshop — focus on learning, hands-on moments, and practical takeaways.",
        }.get(ctx.event_type, "This was a professional event.")

        prompt = f"""You attended {ctx.event_name} and are writing a LinkedIn post about it.

BRAND CONTEXT:
{brand_block}

EVENT CONTEXT:
- Event: {ctx.event_name}
- Description: {ctx.event_description}
- {event_type_hint}
- Visual themes detected in photos: {scenes_str}
- Key concepts: {concepts_str}
- {faces_line}

PLATFORM REQUIREMENTS (LinkedIn):
- Write in FIRST PERSON as if you genuinely attended
- Professional, insightful, evidence-led tone
- Be specific — reference actual observations from the context above
- NO "thrilled to announce", NO "excited to share", NO corporate filler
        - NO bracketed fill-ins like [date], [industry], {{brand_name}}, etc.
- Never invent dates, statistics, or event facts
- Structure: opening observation → 2-3 specific insights → closing question
- End with a genuine question that invites engagement
- 150-250 words
- Include {ctx.hashtag} and 2 relevant hashtags at the end
- No emojis in the body text

Write the LinkedIn post (no title, no preamble, just the post):"""

        try:
            return self._generate(
                prompt,
                max_new_tokens=450,
                correction=correction,
                brand_context=brand_ctx,
                operation="linkedin",
            )
        except Exception as e:
            raise RuntimeError(f"LLM inference failed: {e}")

    # ── Instagram carousel ────────────────────────────────────────────────────

    def generate_instagram_caption(
        self,
        event_name: str,
        assets: List[AssetMetadata],
        event_description: str = "",
        correction: str = "",
        brand_context: Optional[BrandContext] = None,
    ) -> str:
        """Generate a contextual Instagram carousel caption via Qwen."""
        ctx = _build_context(event_name, assets, event_description)
        brand_ctx = brand_context or self._brand_context
        brand_block = brand_ctx.summary()

        concepts_str = ", ".join(ctx.detected_concepts[:4]) if ctx.detected_concepts else "the event"
        scenes_str = ", ".join(ctx.scene_labels[:4]) if ctx.scene_labels else "the event"

        prompt = f"""You attended {ctx.event_name} and are writing an Instagram carousel caption.

BRAND CONTEXT:
{brand_block}

EVENT CONTEXT:
- Event: {ctx.event_name}
- Description: {ctx.event_description}
- Visual themes: {scenes_str}
- Key concepts: {concepts_str}
- Crowd: {ctx.total_faces} faces in key shots
- Event type: {ctx.event_type}

PLATFORM REQUIREMENTS (Instagram):
- Casual, lowercase, conversational — NOT corporate
- 3-5 short punchy lines
- 2-3 emojis used naturally (not forced)
- End with a CTA: "swipe →", "save this", or "tag someone"
        - NO bracketed fill-ins like [date], [industry], {{brand_name}}, etc.
- Never invent dates, statistics, or event facts
- Include {ctx.hashtag} and 2-3 relevant hashtags
- Max 100 words

Write the Instagram caption:"""

        try:
            return self._generate(
                prompt,
                max_new_tokens=200,
                correction=correction,
                brand_context=brand_ctx,
                operation="instagram",
            )
        except Exception as e:
            raise RuntimeError(f"LLM inference failed: {e}")

    # ── Instagram reel ────────────────────────────────────────────────────────

    def generate_reel_caption(
        self,
        event_name: str,
        assets: List[AssetMetadata],
        event_description: str = "",
        brand_context: Optional[BrandContext] = None,
    ) -> str:
        """Generate a contextual Instagram Reel caption via Qwen."""
        ctx = _build_context(event_name, assets, event_description)
        brand_ctx = brand_context or self._brand_context
        brand_block = brand_ctx.summary()

        concepts = _top_concepts(assets)
        concept_str = ", ".join(concepts) if concepts else "event highlights"
        clips_line = f"{ctx.video_highlight_count} highlight clips extracted." if ctx.video_highlight_count else ""

        prompt = f"""Write a short Instagram Reel caption for {ctx.event_name}.

BRAND CONTEXT:
{brand_block}

CONTEXT:
- Event: {ctx.event_name}
- Description: {ctx.event_description}
- Visual themes: {concept_str}
- {clips_line}

PLATFORM REQUIREMENTS (Instagram Reel):
- Very short: 15-25 words max
- Energetic, punchy
- 1-2 emojis
- End with a question or "tag someone" CTA
        - NO bracketed fill-ins like [date], [industry], {{brand_name}}, etc.
- Never invent dates or event facts
- Include {ctx.hashtag}

Write only the caption:"""

        try:
            return self._generate(
                prompt,
                max_new_tokens=100,
                brand_context=brand_ctx,
                operation="reel",
            )
        except Exception as e:
            raise RuntimeError(f"LLM inference failed: {e}")

    # ── Instagram stories ─────────────────────────────────────────────────────

    def generate_story_captions(
        self,
        event_name: str,
        num_slides: int = 4,
        assets: Optional[List[AssetMetadata]] = None,
        event_description: str = "",
        brand_context: Optional[BrandContext] = None,
    ) -> List[str]:
        """Generate sequential Instagram Story captions via Qwen."""
        ctx = _build_context(event_name, assets or [], event_description)
        brand_ctx = brand_context or self._brand_context
        brand_block = brand_ctx.summary()

        concepts_str = ", ".join(ctx.detected_concepts[:3]) if ctx.detected_concepts else "the event"

        prompt = f"""Write {num_slides} sequential Instagram Story captions for {ctx.event_name}.

BRAND CONTEXT:
{brand_block}

These are sequential frames telling a story arc: arrival → main event → highlight → sign-off.
Event context: {ctx.event_description}
Themes: {concepts_str}

PLATFORM REQUIREMENTS (Instagram Stories):
- Each caption: 5-10 words only
- Casual, emoji-friendly
- Tell a narrative arc across the {num_slides} frames
- Number each one: "1.", "2.", etc.
        - NO bracketed fill-ins like [date], [industry], {{brand_name}}, etc.
- Never invent dates or event facts

Write the {num_slides} captions:"""

        try:
            result = self._generate(
                prompt,
                max_new_tokens=max(64, num_slides * 32),
                brand_context=brand_ctx,
                operation="stories",
            )

            raw_parts = [part.strip() for part in result.split("|") if part.strip()]
            if len(raw_parts) < num_slides:
                lines = [ln.strip() for ln in result.splitlines() if ln.strip()]
                numbered = []
                for ln in lines:
                    cleaned = re.sub(r"^\d+[\.\)]\s*", "", ln).strip()
                    if cleaned:
                        numbered.append(cleaned)
                if len(numbered) >= len(raw_parts):
                    raw_parts = numbered

            captions = raw_parts[:num_slides]
            if len(captions) != num_slides:
                raise RuntimeError(
                    f"Qwen returned {len(captions)} Stories captions; expected {num_slides}"
                )
            return captions
        except Exception as e:
            raise RuntimeError(f"LLM Stories generation failed: {e}") from e

    # ── A/B variants ──────────────────────────────────────────────────────────

    def generate_variants(
        self,
        platform: str,
        event_name: str,
        assets: List[AssetMetadata],
        n: int = 3,
        event_description: str = "",
        brand_context: Optional[BrandContext] = None,
    ) -> Dict[str, object]:
        """
        Generate n caption variants for a platform.
        All variants are produced by Qwen — no hardcoded templates.
        Returns {"primary": str, "variants": [str, ...], "backend": str}
        """
        brand_ctx = brand_context or self._brand_context
        tag = _hashtag(event_name)
        concepts = _top_concepts(assets, 2)
        concept_str = f" ({', '.join(concepts)})" if concepts else ""

        if platform == "linkedin":
            primary = self.generate_linkedin_caption(event_name, assets, event_description, brand_context=brand_ctx)
            variants: List[str] = []
            v1_prompt = (
                f"Write a LinkedIn post about {event_name} structured as 3 honest questions "
                f"the event left you with. Start with 'Three questions {event_name} left me with:'. "
                f"Each question thought-provoking and specific to a professional event. "
                f"End with 'Still processing.' Include {tag} #EventInsights. Max 120 words. "
                f"No bracketed placeholders. Never invent dates or facts."
            )
            v2_prompt = (
                f"Write a LinkedIn post about {event_name} structured as 'what I expected vs what I got'. "
                f"Format: 'What I expected: [something specific]. What I got: [something specific and insightful].' "
                f"End with a line about the ROI of showing up in person. Include {tag} #Leadership. "
                f"Max 100 words. No bracketed placeholders. Never invent dates or facts."
            )
            try:
                variants.append(self._generate(v1_prompt, max_new_tokens=200, brand_context=brand_ctx, operation="linkedin-variant"))
            except Exception:
                pass
            try:
                variants.append(self._generate(v2_prompt, max_new_tokens=180, brand_context=brand_ctx, operation="linkedin-variant"))
            except Exception:
                pass
            return {"primary": primary, "variants": variants[:n - 1], "backend": self.backend}

        elif platform == "instagram":
            primary = self.generate_instagram_caption(event_name, assets, event_description, brand_context=brand_ctx)
            variants = []
            v1_prompt = (
                f"Write an Instagram caption for {event_name} as a 'things that happened that the official recap won't mention' thread. "
                f"Use → bullet points for 3 specific moments. End with 'save this if you're going next year 📌'. "
                f"Include {tag} #EventLife. Max 80 words. No bracketed placeholders."
            )
            v2_prompt = (
                f"Write an Instagram caption for {event_name} as a 'rate this event' post. "
                f"Rate: content, networking, coffee, and one unexpected thing — each out of 10. "
                f"Funny and relatable tone. Include {tag} #ConferenceLife. Max 60 words. No bracketed placeholders."
            )
            try:
                variants.append(self._generate(v1_prompt, max_new_tokens=150, brand_context=brand_ctx, operation="instagram-variant"))
            except Exception:
                pass
            try:
                variants.append(self._generate(v2_prompt, max_new_tokens=120, brand_context=brand_ctx, operation="instagram-variant"))
            except Exception:
                pass
            return {"primary": primary, "variants": variants[:n - 1], "backend": self.backend}

        else:  # reel
            primary = self.generate_reel_caption(event_name, assets, event_description, brand_context=brand_ctx)
            variants = []
            v1_prompt = (
                f"Write a short Instagram Reel caption for {event_name}. "
                f"Energetic, punchy, 15-25 words max. End with 'tag someone who needs to see this'. "
                f"Include {tag} #BehindTheScenes. No bracketed placeholders."
            )
            v2_prompt = (
                f"Write a short Instagram Reel caption for {event_name}. "
                f"Hook in the first line. 3-4 short lines max. End with a tag CTA. "
                f"Include {tag} #EventReel. No bracketed placeholders."
            )
            try:
                variants.append(self._generate(v1_prompt, max_new_tokens=80, brand_context=brand_ctx, operation="reel-variant"))
            except Exception:
                pass
            try:
                variants.append(self._generate(v2_prompt, max_new_tokens=80, brand_context=brand_ctx, operation="reel-variant"))
            except Exception:
                pass
            return {"primary": primary, "variants": variants[:n - 1], "backend": self.backend}

    # ── Brand-aware captions (GFF 2025 challenge) ──────────────────────────────

    def generate_brand_carousel_caption(
        self,
        brand_name: str,
        event_name: str,
        assets: List[AssetMetadata],
        event_description: str = "",
        brand_context: Optional[BrandContext] = None,
    ) -> str:
        """
        Generate Instagram carousel caption with brand awareness.
        Follows StepOne brand voice: clear, active, specific, confident, human.
        """
        brand_ctx = brand_context or BrandContext(brand_name=brand_name)
        concepts = _top_concepts(assets, 3)
        concept_str = ", ".join(concepts) if concepts else "highlights"

        try:
            ctx = _build_context(event_name, assets, event_description)
            brand_block = brand_ctx.summary()

            prompt = f"""You are writing an Instagram carousel caption for {brand_name}.

BRAND CONTEXT:
{brand_block}

BRAND VOICE REQUIREMENTS:
- Clear over clever — earn trust with precision
- Active over passive — we act, we deliver
- Specific over vague — concrete examples beat abstract claims
- Confident over tentative — say "we do", not "we try to"
- Human over corporate — lowercase is fine, emoji used naturally

EVENT CONTEXT:
- Brand: {brand_name}
- Event: {event_name}
- Key moments captured: {concept_str}
- Crowd energy: {ctx.total_faces} people in key shots

REQUIREMENTS:
- 4-6 short punchy lines (not an essay)
- Casual, lowercase, conversational
- 2-3 emojis used naturally
- End with clear CTA: "swipe →" or "save this"
- Include {ctx.hashtag} + 2-3 relevant hashtags
- Max 100 words
- NOT a LinkedIn repost — Instagram native tone
- No bracketed placeholders like [date], {brand_name}, etc.
- Never invent dates or event facts

Write the caption:"""

            result = self._generate(prompt, max_new_tokens=180, brand_context=brand_ctx, operation="brand-carousel")
            _log.info("brand_carousel_caption_done", brand=brand_name, chars=len(result))

            # Validate against brand voice
            validation = stepone_brand_voice.validate_copy(result)
            if validation["issues"]:
                _log.warning("caption_brand_voice_issues", brand=brand_name, issues=validation["issues"])

            return result
        except Exception as e:
            raise RuntimeError(f"LLM brand carousel generation failed: {e}") from e

    def generate_brand_reel_caption(
        self,
        brand_name: str,
        event_name: str,
        assets: List[AssetMetadata],
        event_description: str = "",
        brand_context: Optional[BrandContext] = None,
    ) -> str:
        """
        Generate Instagram Reel caption with brand awareness.
        30-60 second reel, sequenced storytelling.
        """
        brand_ctx = brand_context or BrandContext(brand_name=brand_name)
        concepts = _top_concepts(assets, 2)

        try:
            ctx = _build_context(event_name, assets, event_description)
            brand_block = brand_ctx.summary()

            prompt = f"""Write an Instagram Reel caption for {brand_name} at {event_name}.

BRAND CONTEXT:
{brand_block}

BRAND VOICE:
- Clear over clever, active over passive, specific over vague
- Confident — we deliver, we create, we build
- Human — lowercase, contractions, authentic

CONTEXT:
- Brand: {brand_name}
- Event: {event_name}
- Key themes: {', '.join(concepts) if concepts else 'event highlights'}
- Duration: 30-60 seconds

REQUIREMENTS:
- Hook in first line (makes them stop scrolling)
- 3-4 short lines max
- Energetic, punchy
- Ends with tag CTA: "tag someone who needs to see this" or "share with your team"
- Include 2-3 hashtags
- Max 60 words
- Instagram native — NOT corporate or LinkedIn style
- No bracketed placeholders like [date], {brand_name}, etc.
- Never invent dates or event facts

Write the caption:"""

            result = self._generate(prompt, max_new_tokens=120, brand_context=brand_ctx, operation="brand-reel")
            _log.info("brand_reel_caption_done", brand=brand_name, chars=len(result))
            return result
        except Exception as e:
            raise RuntimeError(f"LLM brand Reel generation failed: {e}") from e

    def generate_brand_story_captions(
        self,
        brand_name: str,
        event_name: str,
        num_slides: int = 4,
        assets: Optional[List[AssetMetadata]] = None,
        event_description: str = "",
        brand_context: Optional[BrandContext] = None,
    ) -> List[str]:
        """
        Generate sequential story captions with brand awareness.
        3-4 vertical frames that lead into each other.
        """
        brand_ctx = brand_context or BrandContext(brand_name=brand_name)
        concepts = _top_concepts(assets, 3) if assets else []

        try:
            ctx = _build_context(event_name, assets or [], event_description)
            brand_block = brand_ctx.summary()

            prompt = f"""Write {num_slides} sequential Instagram Story captions for {brand_name} at {event_name}.

BRAND CONTEXT:
{brand_block}

BRAND VOICE:
- Clear over clever, active over passive, specific over vague
- Human over corporate — short, punchy, conversational

STORY STRUCTURE (sequential narrative):
- Frame 1: Hook — "this is what happened at {event_name}..."
- Frame 2-3: Build — key moments, energy, insights
- Frame 4: CTA — "save this", "tag someone", "share"

CONTEXT:
- Brand: {brand_name}
- Event: {event_name}
- Key themes: {', '.join(concepts) if concepts else 'event highlights'}

REQUIREMENTS:
- Each caption: 1-2 short lines max
- Sequential — each frame leads into the next
- Vertical format — text readable on mobile
- End with clear CTA in final frame
- No hashtags needed for stories (optional)
- Total: {num_slides} captions, one per line, separated by |
- No bracketed placeholders like [date], {brand_name}, etc.
- Never invent dates or event facts

Write the story captions (format: frame1 | frame2 | frame3 | frame4):"""

            result = self._generate(prompt, max_new_tokens=200, brand_context=brand_ctx, operation="brand-stories")

            # Split by | delimiter
            captions = [c.strip() for c in result.split("|")][:num_slides]
            if len(captions) < num_slides:
                raise RuntimeError(f"Qwen returned {len(captions)} Stories captions; expected {num_slides}")

            _log.info("brand_story_captions_done", brand=brand_name, frames=len(captions))
            return captions
        except Exception as e:
            raise RuntimeError(f"LLM brand Stories generation failed: {e}") from e


# ── Brand-aware templates ─────────────────────────────────────────────────────

def _brand_carousel_template(brand_name: str, event_name: str, assets: List[AssetMetadata]) -> str:
    """Template for brand carousel caption (fallback when LLM unavailable)."""
    concepts = _top_concepts(assets, 3)
    concept_str = ", ".join(concepts) if concepts else "highlights"

    return f"""{brand_name} was in the room.

 here's what we captured: {concept_str}

 the moments that mattered. the people who showed up. the energy you can't fake.

 swipe through for the full story →

 #{brand_name.replace(' ', '')} #GFF2025 #EventHighlights"""


def _brand_reel_template(brand_name: str, event_name: str, assets: List[AssetMetadata]) -> str:
    """Template for brand reel caption."""
    concepts = _top_concepts(assets, 2)
    concept_str = ", ".join(concepts) if concepts else "highlights"

    return f"""we documented {brand_name} at {event_name} 🎬

 {concept_str} — the moments that mattered

 watch till the end 👀

 #{brand_name.replace(' ', '')} #GFF2025 #BehindTheScenes"""


def _brand_story_template(brand_name: str, event_name: str, num_slides: int = 4) -> List[str]:
    """Template for brand story captions (sequential narrative)."""
    templates = [
        f"this is what {brand_name} looked like at {event_name}...",
        f"the energy was real. the moments were worth capturing.",
        f"we build experiences that move people.",
        f"save this for next time → #{brand_name.replace(' ', '')}",
    ]
    return templates[:num_slides]
