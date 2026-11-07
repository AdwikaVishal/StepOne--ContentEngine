"""
StepOne Brand Voice Configuration
Defines tone of voice, vocabulary, and language guidelines per the Brand Guidelines.
"""

from dataclasses import dataclass, field
from typing import Any, List, Dict


@dataclass
class BrandVoice:
    """
    StepOne brand voice guidelines.
    
    The voice sits at the intersection of strategic consultancy and creative studio.
    """

    # Core tone principles (must follow all)
    tone_principles: List[str] = field(default_factory=lambda: [
        "Clear over clever — we earn trust with precision, not wordplay",
        "Active over passive — we act, we deliver, we create",
        "Specific over vague — concrete examples and numbers beat abstract claims",
        "Confident over tentative — we say 'we do' and 'we deliver', not 'we try to'",
        "Human over corporate — contractions are fine; humanity is a feature",
    ])

    # Signature vocabulary (preferred terms)
    signature_vocabulary: Dict[str, List[str]] = field(default_factory=lambda: {
        "insight": [
            "audience truths", "signals", "behaviors", "barriers", "motivations",
            "behavioural drivers", "attention patterns", "engagement gaps"
        ],
        "ideas": [
            "concepts", "worlds", "moments", "choreography", "story",
            "visual narrative", "brand world", "experience architecture"
        ],
        "impact": [
            "outcomes", "recall", "engagement", "conversion", "loyalty", "community",
            "measurable ROI", "lasting impression", "behavioural shift"
        ],
    })

    # Language to use (preferred)
    language_to_use: List[str] = field(default_factory=lambda: [
        "insight-driven",
        "experience-led",
        "measurable impact",
        "experiential intelligence",
        "we design experiences that move people",
        "we create",
        "we deliver",
        "we build",
        "strategic",
        "creative",
        "precise",
    ])

    # Language to avoid
    language_to_avoid: List[str] = field(default_factory=lambda: [
        "creative agency",
        "event management",
        "event solutions",
        "we work hard to try to meet your needs",
        "best-in-class",
        "synergy",
        "leverage",
        "best practice",
        "cutting-edge",
        "world-class",
        "innovative solutions",
    ])

    # Tone by context
    tone_by_context: Dict[str, str] = field(default_factory=lambda: {
        "pitch": "bold, premium, visionary",
        "website": "bold, premium, visionary",
        "client_comms": "calm, proactive, reassuring",
        "thought_leadership": "provocative and evidence-led",
        "instagram": "visual-first, human, authentic, brand-aware",
        "linkedin": "professional, insightful, evidence-led",
    })

    # Instagram-specific guidelines
    instagram_guidelines: Dict[str, List[str]] = field(default_factory=lambda: {
        "do": [
            "Lead with a hook in the first line",
            "Use short sentences and punchy language",
            "Include relevant hashtags at the end",
            "Write as one human talking to another",
            "Match the visual energy of the content",
        ],
        "dont": [
            "Repost LinkedIn-style professional copy",
            "Use corporate jargon or buzzwords",
            "Write essays — captions should be scannable",
            "Use more than 5 hashtags",
            "Be vague — specificity is memorable",
        ],
    })

    # Instagram caption templates
    caption_templates: Dict[str, str] = field(default_factory=lambda: {
        "carousel": "{hook}\n\n{body}\n\n{cta}",
        "reel": "{hook} 👀\n\n{body}\n\n{cta}",
        "story": "{text}",
    })

    def get_context_guidance(self, context: str) -> str:
        """Get tone guidance for a specific context."""
        return self.tone_by_context.get(context, "")

    def apply_to_copy(self, copy: str, context: str = "instagram") -> str:
        """
        Apply brand voice to existing copy.
        This is a basic implementation — full LLM-based rewriting available via use_llm=True.
        """
        # Basic cleaning - replace avoided phrases
        cleaned = copy
        for phrase in self.language_to_avoid:
            cleaned = cleaned.replace(phrase, "[REDACTED]")

        return cleaned

    def validate_copy(self, copy: str) -> Dict[str, Any]:
        """
        Validate copy against brand voice guidelines.
        Returns validation report.
        """
        issues = []
        score = 100

        # Check for avoided phrases
        has_avoided_phrase = False
        for phrase in self.language_to_avoid:
            if phrase.lower() in copy.lower():
                issues.append(f"Avoided phrase detected: '{phrase}'")
                score -= 20
                has_avoided_phrase = True

        # Check for passive voice (basic check)
        passive_indicators = [" was ", " were ", " is being ", " are being "]
        for indicator in passive_indicators:
            if indicator in copy:
                issues.append(f"Passive voice detected: '{indicator.strip()}'")
                score -= 5

        # Check for tentative language
        tentative_phrases = ["we try to", "we hope to", "we aim to", "we will try", "hopefully"]
        for phrase in tentative_phrases:
            if phrase.lower() in copy.lower():
                issues.append(f"Tentative language detected: '{phrase}'")
                score -= 5

        # Check for specific vs vague
        if "something" in copy.lower() or "things" in copy.lower():
            issues.append("Avoid vague terms like 'something' or 'things'")
            score -= 3

        return {
            "valid": score >= 70 and not has_avoided_phrase,
            "score": max(0, score),
            "issues": issues,
        }


# Default brand voice instance
stepone_brand_voice = BrandVoice()
