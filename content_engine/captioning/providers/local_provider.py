"""
Local MLX caption provider - MLX inference via dedicated worker.
Lazy initialization, serialized requests, no auto-download.
"""

import os
from typing import List, Optional, Dict, Any

from .base import CaptionProvider, CaptionProviderError
from ..schema import CaptionGenerationContext, HistoricalPost


class LocalLLMProvider(CaptionProvider):
    """Local MLX-based caption generation using shared MLX worker."""

    DEFAULT_MODEL = "mlx-community/Qwen2.5-0.5B-Instruct-4bit"

    def __init__(self, model_name: Optional[str] = None, model_path: Optional[str] = None):
        self.model_name = model_name or os.getenv("MLX_MODEL_ID", "") or self.DEFAULT_MODEL
        self.model_path = model_path or os.getenv("MLX_MODEL_PATH", "") or None
        self._mlx_client = None
        self._mlx_errors = None
        self._initialized = False
        self._init_error = None

    def _get_model_id(self) -> str:
        return self.model_path if self.model_path else self.model_name

    def _ensure_client(self):
        """Lazy initialize MLX client."""
        if self._initialized:
            if self._init_error:
                raise self._init_error
            return

        try:
            from content_engine.llm.mlx_client import get_mlx_client, MLXClientError, MLXWorkerUnavailable, MLXModelError
            self._mlx_client = get_mlx_client()
            self._mlx_errors = (MLXClientError, MLXWorkerUnavailable, MLXModelError)
        except Exception as e:
            self._init_error = CaptionProviderError(f"Failed to initialize MLX client: {e}")
            raise self._init_error
        finally:
            self._initialized = True

    def is_available(self) -> bool:
        """Check if MLX worker can be reached (doesn't load model)."""
        try:
            self._ensure_client()
            # Quick health check without waiting for model load
            return True
        except Exception:
            return False

    def get_name(self) -> str:
        if "qwen" in self.model_name.lower():
            return "local:qwen2.5-mlx"
        return f"local:mlx:{self.model_name.split('/')[-1]}"

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "local": True,
            "requires_api_key": False,
            "supports_retrieval": True,
            "platforms": ["linkedin", "instagram", "reel", "youtube", "stories"],
            "model_name": self.model_name,
            "model_path": self.model_path,
            "backend": "mlx",
        }

    def _build_prompt(self, ctx: CaptionGenerationContext, platform: str,
                      num_slides: int = 4,
                      examples: Optional[List[HistoricalPost]] = None) -> str:
        """Build structured prompt for MLX model."""
        platform_rules = {
            "linkedin": "Professional B2B tone. First-person authentic. End with a question to drive engagement. 100-150 words max. No emojis. Include relevant hashtags at the end.",
            "instagram": "Casual, authentic Instagram tone. Conversational. 50-100 words. 2-4 hashtags at the end. Emojis sparingly if natural.",
            "reel": "Punchy for video caption. Hook in first line. 25-60 words. 2-3 hashtags.",
            "youtube": "YouTube description style. Clear hook. Include relevant keywords. 50-100 words. 3-5 hashtags at the end.",
            "stories": f"Write {num_slides} sequential Story captions separated by ' | '. Each 5-15 words. Build narrative across slides, CTA on last slide."
        }

        system = "You are a social media copywriter. Write ONLY the caption text. Do not invent facts, statistics, awards, or quotes. Use only information provided."

        user = f"{system}\n\nBrand: {ctx.brand or 'Brand'}\nEvent/Campaign: {ctx.event_name}\n"
        if ctx.event_description:
            user += f"Details: {ctx.event_description}\n"
        user += f"Platform: {platform}\n{platform_rules.get(platform, '')}\n"
        user += "Brand voice: Clear over clever, active over passive, specific over vague, confident not tentative, human not corporate.\n"

        if ctx.detected_concepts:
            user += f"Topics: {', '.join(ctx.detected_concepts[:5])}\n"

        if examples and ctx.use_retrieval and len(examples) > 0:
            user += "\nStyle examples (match tone only, do NOT copy):\n"
            for ex in examples[:ctx.retrieval_k]:
                user += f"- {ex.caption[:120]}\n"

        user += "\nWrite the caption now:"
        return user

    def _generate(self, prompt: str, max_new_tokens: int = 200) -> str:
        self._ensure_client()
        MLXClientError, MLXWorkerUnavailable, MLXModelError = self._mlx_errors

        try:
            response = self._mlx_client.generate(
                system="You are a social media copywriter. Write ONLY the caption text. Do not invent facts, statistics, awards, or quotes. Use only information provided.",
                user=prompt,
                max_tokens=max_new_tokens,
                temperature=0.0,  # Deterministic for factual copy
            )
            output = response.text.strip()
            if not output:
                raise CaptionProviderError("MLX returned empty output")
            return output
        except MLXWorkerUnavailable as e:
            raise CaptionProviderError(f"MLX worker unavailable: {e}") from e
        except MLXModelError as e:
            raise CaptionProviderError(f"MLX generation failed: {e}") from e
        except MLXClientError as e:
            raise CaptionProviderError(f"MLX client error: {e}") from e

    def generate_linkedin(self, ctx: CaptionGenerationContext,
                          examples: Optional[List[HistoricalPost]] = None) -> str:
        self._ensure_client()
        prompt = self._build_prompt(ctx, "linkedin", examples=examples)
        return self._generate(prompt, max_new_tokens=200)

    def generate_instagram(self, ctx: CaptionGenerationContext,
                          examples: Optional[List[HistoricalPost]] = None) -> str:
        self._ensure_client()
        prompt = self._build_prompt(ctx, "instagram", examples=examples)
        return self._generate(prompt, max_new_tokens=150)

    def generate_reel(self, ctx: CaptionGenerationContext,
                      examples: Optional[List[HistoricalPost]] = None) -> str:
        self._ensure_client()
        prompt = self._build_prompt(ctx, "reel", examples=examples)
        return self._generate(prompt, max_new_tokens=100)

    def generate_stories(self, ctx: CaptionGenerationContext,
                         num_slides: int = 4,
                         examples: Optional[List[HistoricalPost]] = None) -> List[str]:
        self._ensure_client()
        prompt = self._build_prompt(ctx, "stories", num_slides=num_slides, examples=examples)
        result = self._generate(prompt, max_new_tokens=150)
        captions = [c.strip() for c in result.split("|")][:num_slides]
        while len(captions) < num_slides:
            captions.append("")
        return captions[:num_slides]

    def generate_youtube(self, ctx: CaptionGenerationContext,
                         examples: Optional[List[HistoricalPost]] = None) -> str:
        self._ensure_client()
        prompt = self._build_prompt(ctx, "youtube", examples=examples)
        return self._generate(prompt, max_new_tokens=150)