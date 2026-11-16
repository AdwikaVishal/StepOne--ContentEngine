"""
Local caption provider — PyTorch/transformers backend (Windows/Linux/CPU)
with optional MLX fallback (macOS). Lazy initialization, serialized requests,
no auto-download.
"""

import os
from typing import List, Optional, Dict, Any

from .base import CaptionProvider, CaptionProviderError
from ..schema import CaptionGenerationContext, HistoricalPost
from config import QWEN_MODEL_PATH


class LocalLLMProvider(CaptionProvider):
    """Local caption generation using the shared local backend (torch preferred)."""

    DEFAULT_MODEL = QWEN_MODEL_PATH

    def __init__(self, model_name: Optional[str] = None, model_path: Optional[str] = None):
        self.model_name = model_name or os.getenv("TORCH_LLM_MODEL", "") or self.DEFAULT_MODEL
        self.model_path = model_path or os.getenv("QWEN_MODEL_PATH", "") or None
        self._mlx_client = None
        self._mlx_errors = None
        self._initialized = False
        self._init_error = None
        self._backend = "torch"

    def _get_model_id(self) -> str:
        return self.model_path if self.model_path else self.model_name

    @staticmethod
    def _mlx_configured() -> bool:
        from content_engine.llm.mlx_config import get_config

        try:
            issues = get_config().validate()
        except Exception:
            return False
        return not any("not found" in issue for issue in issues)

    def _ensure_client(self):
        """Lazy initialize the selected local backend."""
        if self._initialized:
            if self._init_error:
                raise self._init_error
            return

        requested = os.getenv("LOCAL_LLM_BACKEND", "auto").strip().lower()
        use_mlx = requested == "mlx" or (
            requested != "torch" and self._mlx_configured()
        )

        try:
            if use_mlx:
                from content_engine.llm.mlx_client import (
                    get_mlx_client,
                    MLXClientError,
                    MLXWorkerUnavailable,
                    MLXModelError,
                )
                self._mlx_client = get_mlx_client()
                self._mlx_errors = (MLXClientError, MLXWorkerUnavailable, MLXModelError)
                self._backend = "mlx"
            else:
                from content_engine.llm.torch_backend import is_torch_backend_available
                if not is_torch_backend_available():
                    raise CaptionProviderError(
                        "No local caption backend available: MLX worker is not "
                        "configured and torch/transformers is not installed."
                    )
                self._backend = "torch"
        except CaptionProviderError as e:
            self._init_error = e
            raise
        except Exception as e:
            self._init_error = CaptionProviderError(f"Failed to initialize local caption backend: {e}")
            raise self._init_error
        finally:
            self._initialized = True

    def is_available(self) -> bool:
        """True when the selected local backend can run (no model load)."""
        try:
            self._ensure_client()
            return True
        except Exception:
            return False

    def get_name(self) -> str:
        if self._backend == "torch":
            model = os.getenv("TORCH_LLM_MODEL", "torch-local")
            return f"local:torch:{model.split('/')[-1]}"
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
            "backend": self._backend,
        }

    def _build_prompt(self, ctx: CaptionGenerationContext, platform: str,
                      num_slides: int = 4,
                      examples: Optional[List[HistoricalPost]] = None) -> str:
        """Build structured prompt for the local model."""
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

        if self._backend == "torch":
            from content_engine.llm.torch_backend import get_torch_generator

            try:
                output = get_torch_generator().generate(
                    system="You are a social media copywriter. Write ONLY the caption text. Do not invent facts, statistics, awards, or quotes. Use only information provided.",
                    user=prompt,
                    max_tokens=max_new_tokens,
                    temperature=0.0,
                )
                if not output:
                    raise CaptionProviderError("Torch backend returned empty output")
                return output
            except CaptionProviderError:
                raise
            except Exception as e:
                raise CaptionProviderError(f"Torch generation failed: {e}") from e

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