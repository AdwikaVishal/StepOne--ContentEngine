"""
Groq Vision provider — cloud image understanding for cloud_testing mode.

Uses the groq SDK (groq>=1.0.0) with vision-capable models (e.g.
qwen/qwen3.8-27b). Lazy-imported so local mode never imports it.

Image workflow:
  1. Read local image file and base64-encode it
  2. Send via client.chat.completions.create with image_url content
  3. Parse free-text response into scene_concepts list
  4. relevance_scores is left empty ({}) because Groq cannot produce
     CLIP-equivalent cosine similarity scores — explicitly testing data,
     not real predictions.
"""

import base64
import os
from typing import Any, Dict, List, Optional

from content_engine.ai_mode import ConfigurationError, require_cloud_key
from content_engine.providers.base import (
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    UnsupportedFeatureError,
)
from config import settings


class GroqVisionProvider:
    """Groq multimodal vision provider for cloud_testing mode.

    Uses vision-capable Groq models (e.g. qwen/qwen3.8-27b) for image
    captioning and image understanding. Video understanding is NOT
    supported — understand_video() raises UnsupportedFeatureError.

    All numeric scores are empty/zero because Groq cannot produce
    CLIP-equivalent embeddings. scene_concepts contains free-text labels
    parsed from the model's response.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or require_cloud_key("GROQ_API_KEY")
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from groq import Groq
            except ImportError as exc:
                raise ConfigurationError(
                    "groq SDK is not installed. Install it with "
                    "'pip install groq>=1.0.0' or switch "
                    "AI_EXECUTION_MODE to 'local'."
                ) from exc
            self._client = Groq(api_key=self.api_key)
        return self._client

    # ── Image understanding ──────────────────────────────────────────

    def understand_image(self, image_path: str) -> Dict[str, Any]:
        """Return scene understanding using Groq multimodal.

        Schema:
          {
            "scene_concepts": List[str],
            "relevance_scores": Dict[str, float],   # always {}
            "concept_match_score": Optional[float], # always None — not a real
                                                    # CLIP measurement
            "semantic_description": str,
            "provider": "groq",
          }

        relevance_scores is left empty because Groq cannot produce CLIP-equivalent
        cosine similarity scores. concept_match_score is None to explicitly
        indicate that no genuine similarity measurement was made — these are
        testing representations, not real model predictions.
        """
        client = self._get_client()
        try:
            image_b64 = self._encode_image(image_path)
            prompt = (
                "Describe this image in one sentence. "
                "List the main objects and scenes you observe."
            )
            response = client.chat.completions.create(
                model=settings.groq_vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_b64}"
                                },
                            },
                        ],
                    }
                ],
                max_tokens=100,
                temperature=0.0,
            )
            text = response.choices[0].message.content or ""

            # Parse comma-separated concepts from the description.
            # Safe parsing: empty/malformed responses yield empty lists.
            raw_concepts = [c.strip() for c in text.split(",") if c.strip()]
            concepts = raw_concepts[:20]

            # relevance_scores is empty because Groq cannot produce CLIP-equivalent
            # cosine similarity scores. concept_match_score is None to explicitly
            # indicate no genuine similarity measurement was made.
            relevance_scores: Dict[str, float] = {}
            concept_match_score: Optional[float] = None

            return {
                "scene_concepts": concepts,
                "relevance_scores": relevance_scores,
                "concept_match_score": concept_match_score,
                "semantic_description": text,
                "provider": "groq",
            }
        except Exception as exc:
            msg = str(exc).lower()
            if "timeout" in msg or "timed out" in msg:
                raise ProviderTimeoutError(
                    f"Groq image request timed out: {exc}"
                ) from exc
            if "rate limit" in msg or "429" in msg:
                raise ProviderRateLimitError(
                    f"Groq rate limit exceeded: {exc}"
                ) from exc
            if "401" in msg or "403" in msg or "authentication" in msg or "api key" in msg:
                raise ProviderError(f"Groq authentication failed: {exc}") from exc
            if "model" in msg and ("not found" in msg or "does not exist" in msg):
                raise ProviderError(f"Groq vision model unavailable: {exc}") from exc
            raise ProviderError(f"Groq image understanding failed: {exc}") from exc

    # ── Image captioning ─────────────────────────────────────────────

    def caption_image(self, image_path: str) -> str:
        """Return an image caption using Groq vision."""
        client = self._get_client()
        try:
            image_b64 = self._encode_image(image_path)
            response = client.chat.completions.create(
                model=settings.groq_vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Write a concise one-sentence caption for this image.",
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_b64}"
                                },
                            },
                        ],
                    }
                ],
                max_tokens=60,
                temperature=0.0,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            msg = str(exc).lower()
            if "timeout" in msg or "timed out" in msg:
                raise ProviderTimeoutError(
                    f"Groq caption request timed out: {exc}"
                ) from exc
            if "rate limit" in msg or "429" in msg:
                raise ProviderRateLimitError(
                    f"Groq rate limit exceeded: {exc}"
                ) from exc
            if "401" in msg or "403" in msg or "authentication" in msg or "api key" in msg:
                raise ProviderError(f"Groq authentication failed: {exc}") from exc
            if "model" in msg and ("not found" in msg or "does not exist" in msg):
                raise ProviderError(f"Groq vision model unavailable: {exc}") from exc
            raise ProviderError(f"Groq captioning failed: {exc}") from exc

    # ── Video understanding (not supported) ──────────────────────────

    def understand_video(self, video_path: str) -> Dict[str, Any]:
        """Return video understanding using Groq.

        DEFERRED: Groq vision models support image understanding but not
        video understanding. Returns an unsupported error rather than
        claiming video capability. Local video processing remains available.
        """
        raise UnsupportedFeatureError(
            "Groq video understanding is deferred. "
            "Groq vision models support image understanding but not video. "
            "Local video processing remains available."
        )

    # ── Helpers ──────────────────────────────────────────────────────

    def _encode_image(self, image_path: str) -> str:
        """Read and base64-encode an image file."""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    @property
    def name(self) -> str:
        return "groq"

    @property
    def requires_api_key(self) -> bool:
        return True

    def is_available(self) -> bool:
        """True if GROQ_API_KEY is set and groq SDK is importable."""
        if not os.getenv("GROQ_API_KEY"):
            return False
        try:
            import groq  # noqa: F401
            return True
        except ImportError:
            return False
