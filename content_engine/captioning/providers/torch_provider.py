"""
PyTorch/transformers caption provider (Windows/Linux/CPU).

Uses the same shared local model as the LLM provider so only one set of weights
is ever resident, regardless of which subsystem calls it first.
"""

import os
from typing import Any, Dict, List, Optional

from .base import CaptionProvider, CaptionProviderError
from ..schema import CaptionGenerationContext, HistoricalPost
from content_engine.llm.torch_backend import get_torch_generator, is_torch_backend_available

SYSTEM_PROMPT = (
    "You are a social media copywriter. Write ONLY the caption text. "
    "Do not invent facts, statistics, awards, or quotes. Use only information provided."
)


class TorchCaptionProvider(CaptionProvider):
    """Local caption generation backed by transformers."""

    def __init__(self, model_name: Optional[str] = None) -> None:
        self.model_name = model_name or os.getenv("TORCH_LLM_MODEL", "")

    def is_available(self) -> bool:
        return is_torch_backend_available()

    def get_name(self) -> str:
        model = self.model_name or os.getenv("TORCH_LLM_MODEL", "torch-local")
        return f"local:torch:{model.split('/')[-1]}"

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "local": True,
            "requires_api_key": False,
            "supports_retrieval": True,
            "platforms": ["linkedin", "instagram", "reel", "youtube", "stories"],
            "model_name": self.model_name,
            "backend": "torch",
        }

    def _build_prompt(
        self,
        ctx: CaptionGenerationContext,
        platform: str,
        num_slides: int = 4,
        examples: Optional[List[HistoricalPost]] = None,
    ) -> str:
        platform_rules = {
            "linkedin": "Professional B2B tone. First-person authentic. End with a question to drive engagement. 100-150 words max. No emojis. Include relevant hashtags at the end.",
            "instagram": "Casual, authentic Instagram tone. Conversational. 50-100 words. 2-4 hashtags at the end. Emojis sparingly if natural.",
            "reel": "Punchy for video caption. Hook in first line. 25-60 words. 2-3 hashtags.",
            "youtube": "YouTube description style. Clear hook. Include relevant keywords. 50-100 words. 3-5 hashtags at the end.",
            "stories": f"Write {num_slides} sequential Story captions separated by ' | '. Each 5-15 words. Build narrative across slides, CTA on last slide.",
        }

        user = f"Brand: {ctx.brand or 'Brand'}\nEvent/Campaign: {ctx.event_name}\n"
        if ctx.event_description:
            user += f"Details: {ctx.event_description}\n"
        user += f"Platform: {platform}\n{platform_rules.get(platform, '')}\n"
        user += "Brand voice: Clear over clever, active over passive, specific over vague, confident not tentative, human not corporate.\n"

        if ctx.detected_concepts:
            user += f"Topics: {', '.join(ctx.detected_concepts[:5])}\n"

        if examples and ctx.use_retrieval and len(examples) > 0:
            user += "\nStyle examples (match tone only, do NOT copy):\n"
            for example in examples[: ctx.retrieval_k]:
                user += f"- {example.caption[:120]}\n"

        user += "\nWrite the caption now:"
        return user

    def _generate(self, prompt: str, max_new_tokens: int = 200) -> str:
        try:
            output = get_torch_generator().generate(
                system=SYSTEM_PROMPT,
                user=prompt,
                max_tokens=max_new_tokens,
                temperature=0.0,
            )
        except Exception as exc:
            raise CaptionProviderError(f"Torch generation failed: {exc}") from exc
        if not output:
            raise CaptionProviderError("Torch backend returned empty output")
        return output

    def generate_linkedin(
        self, ctx: CaptionGenerationContext, examples: Optional[List[HistoricalPost]] = None
    ) -> str:
        return self._generate(self._build_prompt(ctx, "linkedin", examples=examples), 200)

    def generate_instagram(
        self, ctx: CaptionGenerationContext, examples: Optional[List[HistoricalPost]] = None
    ) -> str:
        return self._generate(self._build_prompt(ctx, "instagram", examples=examples), 150)

    def generate_reel(
        self, ctx: CaptionGenerationContext, examples: Optional[List[HistoricalPost]] = None
    ) -> str:
        return self._generate(self._build_prompt(ctx, "reel", examples=examples), 100)

    def generate_stories(
        self,
        ctx: CaptionGenerationContext,
        num_slides: int = 4,
        examples: Optional[List[HistoricalPost]] = None,
    ) -> List[str]:
        prompt = self._build_prompt(ctx, "stories", num_slides=num_slides, examples=examples)
        result = self._generate(prompt, 150)
        captions = [caption.strip() for caption in result.split("|")][:num_slides]
        while len(captions) < num_slides:
            captions.append("")
        return captions[:num_slides]

    def generate_youtube(
        self, ctx: CaptionGenerationContext, examples: Optional[List[HistoricalPost]] = None
    ) -> str:
        return self._generate(self._build_prompt(ctx, "youtube", examples=examples), 150)
