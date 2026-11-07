"""
Studio content orchestration - generate complete posts from selected images.
"""
import json
import re
from typing import Any, Dict, List, Optional

from content_engine.copy_generator import CopyGenerator
from content_engine.captioning.factory import get_caption_provider
from content_engine.captioning.schema import CaptionGenerationContext
from content_engine.studio.facts import build_fact_record
from content_engine.studio.grounding import unsupported_claim


class StudioGenerationError(RuntimeError):
    """Safe, actionable error for failed local-model copy generation."""


class StudioContentOrchestrator:
    def __init__(self):
        try:
            self.copy_gen = CopyGenerator()
        except Exception as e:
            raise RuntimeError(f"LLM provider initialization failed: {e}")
    
    def generate_post(
        self,
        event_name: str,
        selected_assets: List[Dict[str, Any]],
        brief: str = "",
        topic: str = "",
        tone: str = "professional",
        audience: str = "",
        key_points: str = "",
        call_to_action: str = "",
        platforms: Optional[List[str]] = None,
        brand_profile: Optional[Dict[str, Any]] = None,
        activity: Optional[str] = None,
        date: Optional[str] = None,
        time: Optional[str] = None,
        location: Optional[str] = None,
        organizer: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not hasattr(self, 'copy_gen') or self.copy_gen is None:
            raise RuntimeError("LLM provider not available")
        platforms = platforms or ["linkedin", "instagram"]
        
        # Build asset metadata for copy generator
        assets_meta = []
        try:
            from content_engine.data_types import AssetMetadata
            for asset in selected_assets:
                concepts = asset.get("subjects") or asset.get("scene_concepts") or []
                assets_meta.append(AssetMetadata(
                    path=asset.get("path") or asset.get("url") or "unknown",
                    asset_type=asset.get("asset_type") or "image",
                    quality_score=asset.get("quality", {}).get("quality_score", 0.8),
                    aesthetic_score=asset.get("quality", {}).get("aesthetic_score", 0.7),
                    face_count=0,
                    face_confidences=[],
                    relevance_scores={c: 0.8 for c in concepts},
                    scene_concepts=concepts,
                    final_score=asset.get("quality", {}).get("final_score", 0.75),
                ))
        except Exception:
            assets_meta = []
        
        # Studio image labels are observations, not event facts. Keep them out of
        # the generation brief; they remain available in image_descriptions below.
        for asset_meta in assets_meta:
            asset_meta.scene_concepts = []
        if brand_profile and brand_profile.get("preferred_cta") and not call_to_action:
            call_to_action = brand_profile["preferred_cta"]
        fact_record = build_fact_record(
            event_name=event_name,
            brief=brief or topic,
            activity=activity,
            audience=audience,
            date=date,
            time=time,
            location=location,
            organizer=organizer,
            call_to_action=call_to_action,
            key_points=key_points,
            brand_profile=brand_profile,
            tone=tone,
        )
        # JSON keeps missing fields explicitly null and prevents visual metadata
        # from being merged into the verified event facts.
        event_description = json.dumps(fact_record, ensure_ascii=False, separators=(",", ":"))
        
        result = {
            "event_name": event_name,
            "narrative": self._generate_narrative(event_name, selected_assets, brief, topic),
            "hook": "",
            "image_order": [a.get("asset_id") or a.get("id") for a in selected_assets],
            "image_descriptions": [],
            "platform_variants": {},
            "alternatives": [],
            "provider": "qwen2.5-1.5b-instruct",
            "ai_generated": True,
        }
        
        # Generate for each platform
        for platform in platforms:
            if platform == "linkedin":
                try:
                    caption = self._generate_validated_caption(
                        self.copy_gen.generate_linkedin_caption, event_name, assets_meta,
                        event_description, max_chars=3000, brand_profile=brand_profile,
                    )
                except Exception as e:
                    if isinstance(e, StudioGenerationError):
                        raise
                    raise StudioGenerationError(
                        "LLM provider could not generate the LinkedIn post. Check that the model is available, then try again."
                    ) from e
                result["platform_variants"]["linkedin"] = {
                    "caption": caption,
                    "media_order": result["image_order"],
                    "format_notes": "Professional tone, up to 3000 chars",
                    "cta": call_to_action or "",
                }
            elif platform == "instagram":
                try:
                    caption = self._generate_validated_caption(
                        self.copy_gen.generate_instagram_caption, event_name, assets_meta,
                        event_description, max_chars=2200, brand_profile=brand_profile,
                    )
                except Exception as e:
                    if isinstance(e, StudioGenerationError):
                        raise
                    raise StudioGenerationError(
                        "LLM provider could not generate the Instagram caption. Check that the model is available, then try again."
                    ) from e
                result["platform_variants"]["instagram"] = {
                    "caption": caption,
                    "media_order": result["image_order"],
                    "carousel": True,
                    "format_notes": "Visual-first, caption up to 2200 chars",
                    "cta": call_to_action or "swipe →",
                    "hashtags": self._extract_hashtags(caption),
                }
            elif platform == "stories":
                try:
                    stories = self.copy_gen.generate_story_captions(event_name, min(len(selected_assets), 4), assets_meta, event_description)
                except Exception as e:
                    raise RuntimeError(f"LLM provider failed to generate Stories captions: {e}")
                result["platform_variants"]["stories"] = {
                    "captions": stories,
                    "media_order": result["image_order"][:4],
                }
        
        # Generate alternatives
        result["alternatives"] = [
            {"type": "short_hook", "linkedin": f"{event_name}: A recap of key moments.", "instagram": f"highlights from {event_name} ✨"},
            {"type": "question_hook", "linkedin": f"What did {event_name} teach us about where we're headed?", "instagram": f"what was your favorite moment from {event_name}?"},
        ]
        
        # Image descriptions
        for asset in selected_assets:
            caption = asset.get("caption")
            desc = caption or asset.get("description") or ", ".join(asset.get("subjects") or [])
            result["image_descriptions"].append({
                "asset_id": asset.get("asset_id") or asset.get("id"),
                "description": desc or f"Photo from {event_name}",
                "is_uncertain_caption": bool(caption),
            })
        
        result["hook"] = result["alternatives"][0]["linkedin"]
        result["brand_compliance"] = self._check_brand_rules(result, brand_profile)
        return result

    def _generate_validated_caption(self, generator, event_name, assets, context, max_chars, brand_profile=None):
        retry_instruction = (
            "Rewrite once as only the finished caption. Use only information in the verified fact record."
        )
        try:
            caption = generator(event_name, assets, context)
            self._validate_generated_caption(caption, context, max_chars=max_chars, brand_profile=brand_profile)
            return caption
        except StudioGenerationError as first_error:
            reason = str(first_error).casefold()
            if "placeholder" in reason:
                retry_instruction = "Rewrite once without square-bracketed text. Use only the event name and nonempty supplied facts."
            elif "date or time" in reason or "event or offer claim" in reason:
                retry_instruction = "Rewrite once without unprovided schedule, timing, or offer details. Use only supplied facts."
            elif "venue" in reason or "location" in reason:
                retry_instruction = "Rewrite once without naming a venue unless a nonempty location field is supplied."
            elif "named entity" in reason:
                retry_instruction = "Rewrite once without any person, organization, or named entity absent from the fact record."
            elif "outcome claim" in reason or "brand restriction" in reason:
                retry_instruction = "Rewrite once without unsupported outcomes, promises, or restricted brand claims."
            elif "instruction" in reason or "debug" in reason:
                retry_instruction = "Rewrite once with only the finished caption; do not repeat instructions or diagnostic text."
        except Exception as first_error:
            chain = first_error
            error_text = []
            while chain is not None:
                error_text.append(str(chain).lower())
                chain = chain.__cause__
            if not any("token limit" in item or "empty output" in item for item in error_text):
                raise first_error
        try:
            caption = generator(
                event_name, assets, context,
                correction=f"{retry_instruction} Stay within {max_chars} characters.",
            )
            self._validate_generated_caption(caption, context, max_chars=max_chars, brand_profile=brand_profile)
            return caption
        except Exception as retry_error:
            raise StudioGenerationError(
                "Qwen could not produce a caption that passed the content checks. Edit the brief and retry."
            ) from retry_error

    @staticmethod
    def _validate_generated_caption(
        caption: str, supplied_context: str, max_chars: int = 3000,
        brand_profile: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Reject common unusable model artifacts without leaking them to users."""
        if not isinstance(caption, str) or not caption.strip():
            raise StudioGenerationError("The model returned empty copy. Please retry with a clearer brief.")
        if re.search(r"!\[[^\]]*\]\(https?://", caption, flags=re.IGNORECASE):
            raise StudioGenerationError(
                "The model returned an unsupported image link. Remove unverified links from the brief and retry."
            )
        # Markdown link labels are syntax, not fill-in placeholders. The URL is
        # checked separately below and must still be present in supplied facts.
        caption_without_markdown_links = re.sub(
            r"\[[^\]]{1,80}\]\(https?://[^)]+\)", " ", caption, flags=re.IGNORECASE
        )
        placeholders = re.findall(r"\[[^\]]{1,80}\]", caption_without_markdown_links)
        if any(item.casefold() not in supplied_context.casefold() for item in placeholders):
            raise StudioGenerationError(
                "The model returned an unfinished placeholder. Please retry with a more specific brief."
            )
        if re.search(
            r"\b(?:end each line(?: of text)?|return only the caption|write only the caption|requirements:|verified brief:|uncertain visual cues:|platform:)\b",
            caption,
            flags=re.IGNORECASE,
        ):
            raise StudioGenerationError(
                "The model repeated prompt instructions instead of writing a caption. Please retry."
            )
        source_urls = {
            match.rstrip(".,;:!?)]")
            for match in re.findall(r"https?://[^\s]+", supplied_context, flags=re.IGNORECASE)
        }
        generated_urls = {
            match.rstrip(".,;:!?)]")
            for match in re.findall(r"https?://[^\s]+", caption, flags=re.IGNORECASE)
        }
        if generated_urls - source_urls:
            raise StudioGenerationError(
                "The model returned a link that was not provided in the brief. Add the intended URL and retry."
            )
        supplied_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)?\b", supplied_context))
        generated_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)?\b", caption))
        if generated_numbers - supplied_numbers:
            raise StudioGenerationError("The model added a number not present in the brief. Please retry with verified details.")
        grounding_issue = unsupported_claim(caption, supplied_context)
        if grounding_issue:
            issue_label = grounding_issue if grounding_issue.endswith("claim") else f"{grounding_issue} claim"
            raise StudioGenerationError(
                f"The model added an unsupported {issue_label}. Please retry with verified details."
            )
        date_patterns = (
            r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
            r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:,?\s+\d{4})?\b",
            r"\b\d{1,2}:\d{2}\s?(?:am|pm)\b",
            r"\b\d{1,2}\s?(?:am|pm)\b",
        )
        for pattern in date_patterns:
            for date_or_time in re.findall(pattern, caption, flags=re.IGNORECASE):
                if date_or_time.casefold() not in supplied_context.casefold():
                    raise StudioGenerationError("The model added a date or time not present in the brief. Please retry.")
        caption_without_hashtags = re.sub(r"#\w+", " ", caption)
        named_phrases = re.findall(
            r"\b[A-Z][a-z]{2,}(?:(?:\s+(?:of|the|and|for)\s+|\s+)[A-Z][a-z]{2,})+\b",
            caption_without_hashtags,
        )
        for phrase in named_phrases:
            candidate = re.sub(
                r"^(?:join|visit|welcome|meet|explore|discover|celebrate|experience|browse|share|enjoy|make)\s+",
                "", phrase, flags=re.I,
            )
            if candidate.casefold() not in supplied_context.casefold():
                raise StudioGenerationError("The model added a named entity not present in the supplied facts. Please retry.")
        for role in ("artist", "expert", "speaker", "sponsor", "organizer", "host"):
            if re.search(rf"\b{role}s?\b", caption, re.I) and not re.search(rf"\b{role}s?\b", supplied_context, re.I):
                raise StudioGenerationError("The model added a participant or organization type not present in the supplied facts. Please retry.")
        try:
            fact_record = json.loads(supplied_context)
            explicit_location = (fact_record.get("verified_details") or {}).get("location")
        except (TypeError, json.JSONDecodeError):
            explicit_location = None
        for place_phrase in re.findall(r"\b(?:at|in|inside)\s+the\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", caption_without_hashtags):
            if not explicit_location or place_phrase.casefold() not in str(explicit_location).casefold():
                raise StudioGenerationError("The model implied a venue that was not explicitly supplied. Please retry.")
        unsupported_schedule = re.search(
            r"\b(?:next(?:\s+\w+)?|upcoming|virtual|online|inaugural|annual(?:ly)?|monthly|sold out|limited time|weekday|weekend|morning|afternoon|evening|tonight|tomorrow|today)\b",
            caption, re.I,
        )
        if unsupported_schedule and not re.search(re.escape(unsupported_schedule.group(0)), supplied_context, re.I):
                raise StudioGenerationError("The model added an event or offer claim not present in the brief. Please retry.")
        unsupported_promise = re.search(
            r"\b(?:transform\w*|make (?:our|the|your) (?:community|neighborhood) better|"
            r"make new friends|like-minded|\bfriends\b|make a difference|benefit everyone|guarantee\w*|unmatched|best ever|"
            r"enhance (?:our|the) community|improve (?:our|the) community|learn new skills|"
            r"create something beautiful|great (?:day|night)|make (?:our|the) neighborhood better|"
            r"enhanc\w*.{0,20}(?:community|neighborhood)|make (?:[A-Za-z][\w'-]*\s+){0,3}better|"
            r"make (?:our|the) community (?:vibrant|stronger)|build something new|build community|create memories|exclusive|"
            r"spark conversations|foster\w*|\bfree\b|open to all|innovative|innovation\w*)\b",
            caption, re.I,
        )
        if unsupported_promise and not re.search(re.escape(unsupported_promise.group(0)), supplied_context, re.I):
                raise StudioGenerationError("The model added an unsupported outcome claim. Please retry with verified details.")
        if len(caption) > max_chars:
            raise StudioGenerationError("The model output exceeded the platform length limit. Please shorten the brief and retry.")
        if re.search(r"\b(?:traceback|stack trace|model debug|internal error|exception:|api[_ -]?key)\b", caption, re.I):
            raise StudioGenerationError("The model returned internal or diagnostic text. Please retry with a shorter brief.")
        forbidden = (brand_profile or {}).get("avoid_words_claims") or []
        forbidden = [str(word).strip() for word in forbidden if str(word).strip()]
        if any(word.casefold() in caption.casefold() for word in forbidden):
            raise StudioGenerationError("The model output conflicts with a brand restriction. Please retry.")
    
    def _generate_narrative(self, event_name: str, selected_assets: List[Dict[str, Any]], brief: str, topic: str) -> str:
        subjects = []
        for a in selected_assets:
            subjects.extend(a.get("subjects") or [])
        unique = list(dict.fromkeys(subjects))[:8]
        narrative = f"A visual story from {event_name}. "
        if unique:
            narrative += f"Captured moments showcasing {', '.join(unique)}. "
        if brief:
            narrative += f"{brief} "
        narrative += f"Compiled from {len(selected_assets)} carefully selected images to tell a cohesive narrative."
        return narrative
    
    def _extract_hashtags(self, caption: str) -> List[str]:
        import re
        return re.findall(r'#\w+', caption)


    def _build_brand_prompt_section(self, brand_profile: Optional[Dict[str, Any]]) -> str:
        """Build brand rules section for prompt - checked in resulting content."""
        if not brand_profile:
            return ""
        parts = []
        if brand_profile.get('name'):
            parts.append(f"Brand: {brand_profile['name']}")
        if brand_profile.get('description'):
            parts.append(f"Brand description: {brand_profile['description']}")
        if brand_profile.get('campaign_objectives'):
            parts.append(f"Campaign objectives: {brand_profile['campaign_objectives']}")
        if brand_profile.get('tone_of_voice'):
            parts.append(f"Tone: {brand_profile['tone_of_voice']}")
        if brand_profile.get('target_audience'):
            parts.append(f"Target audience: {brand_profile['target_audience']}")
        if brand_profile.get('preferred_vocabulary'):
            vocab = brand_profile['preferred_vocabulary']
            if isinstance(vocab, list) and vocab:
                parts.append(f"Preferred vocabulary: {', '.join(vocab)}")
        if brand_profile.get('avoid_words_claims'):
            avoid = brand_profile['avoid_words_claims']
            if isinstance(avoid, list) and avoid:
                parts.append(f"AVOID: {', '.join(avoid)}")
        if brand_profile.get('preferred_cta'):
            parts.append(f"Preferred CTA style: {brand_profile['preferred_cta']}")
        if brand_profile.get('hashtag_guidance'):
            parts.append(f"Hashtag guidance: {brand_profile['hashtag_guidance']}")
        if brand_profile.get('brand_colors'):
            parts.append(f"Visual palette for any design direction: {', '.join(brand_profile['brand_colors'])}")
        if brand_profile.get('fonts'):
            parts.append(f"Brand fonts for any design direction: {', '.join(brand_profile['fonts'])}")
        parts.append("Follow every brand rule in the generated copy. Do not make unsupported factual or performance claims.")
        if not parts:
            return ""
        return "\nBRAND RULES:\n" + "\n".join(f"- {p}" for p in parts) + "\n"

    def _check_brand_rules(self, content: Dict[str, Any], brand_profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Return deterministic copy checks so generated variants can be reviewed."""
        if not brand_profile:
            return {"profile_id": None, "passed": True, "violations": []}
        violations = []
        avoid = brand_profile.get("avoid_words_claims") or []
        preferred = brand_profile.get("preferred_vocabulary") or []
        for platform, variant in content.get("platform_variants", {}).items():
            text = "\n".join(variant.get("captions", [])) if isinstance(variant.get("captions"), list) else variant.get("caption", "")
            lowered = text.casefold()
            for term in avoid:
                if term and term.casefold() in lowered:
                    violations.append({"platform": platform, "rule": "avoid_words_claims", "term": term})
            for term in preferred:
                if term and term.casefold() not in lowered:
                    violations.append({"platform": platform, "rule": "preferred_vocabulary_missing", "term": term})
            cta = brand_profile.get("preferred_cta", "").strip()
            if cta and cta.casefold() not in lowered:
                violations.append({"platform": platform, "rule": "preferred_cta_missing", "term": cta})
            guidance = (brand_profile.get("hashtag_guidance") or "").casefold()
            hashtags = self._extract_hashtags(text)
            if "hashtag" in guidance and ("no hashtag" in guidance or "avoid hashtag" in guidance) and hashtags:
                violations.append({"platform": platform, "rule": "hashtag_guidance", "detail": "Hashtags are present despite guidance to avoid them"})
            count_range = re.search(r"(\d+)\s*[-–]\s*(\d+)", guidance) if "hashtag" in guidance else None
            if count_range:
                minimum, maximum = map(int, count_range.groups())
                if not minimum <= len(hashtags) <= maximum:
                    violations.append({"platform": platform, "rule": "hashtag_count", "expected": f"{minimum}-{maximum}", "actual": len(hashtags)})
        return {"profile_id": brand_profile.get("id"), "passed": not violations, "violations": violations}
