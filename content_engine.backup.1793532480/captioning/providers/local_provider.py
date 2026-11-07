"""
Local LLM caption provider with Qwen2.5-1.5B-Instruct support.
Lazy loading, caching, local-files-only inference, no auto-download.
"""

import os
import time
from typing import List, Optional, Dict, Any

from .base import CaptionProvider, CaptionProviderError
from ..schema import CaptionGenerationContext, HistoricalPost


class LocalLLMProvider(CaptionProvider):
    """Local LLM-based caption generation using cached open-weight models."""
    
    DEFAULT_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
    
    def __init__(self, model_name: Optional[str] = None, model_path: Optional[str] = None):
        self.model_name = model_name or os.getenv("CAPTION_LOCAL_MODEL", "") or self.DEFAULT_MODEL
        self.model_path = model_path or os.getenv("CAPTION_LOCAL_MODEL_PATH", "") or None
        self._model = None
        self._tokenizer = None
        self._loaded = False
        self._load_error = None
        self._load_time = None
    
    def _get_model_id(self):
        return self.model_path if self.model_path else self.model_name
    
    def is_available(self) -> bool:
        """Check if local model weights are actually available without downloading."""
        model_id = self._get_model_id()
        if not model_id:
            return False
        # Must have actual model weights
        check_paths = []
        if self.model_path and os.path.isdir(self.model_path):
            check_paths.append(self.model_path)
        # Also check cache
        if not check_paths:
            try:
                from huggingface_hub import try_to_load_from_cache
            except Exception:
                pass
        # Check for model weights files
        for base in check_paths:
            for name in ['model.safetensors', 'pytorch_model.bin', 'model.safetensors.index.json']:
                if os.path.exists(os.path.join(base, name)):
                    return True
            # Check shards
            try:
                for f in os.listdir(base):
                    if f.startswith('model-') and (f.endswith('.safetensors') or f.endswith('.bin')):
                        return True
            except Exception:
                pass
        # If using HF cache, check blobs for model weights (not incomplete)
        try:
            if not self.model_path:
                cache_dir = os.path.expanduser(f'~/.cache/huggingface/hub/models--{self.model_name.replace("/", "--")}')
                if os.path.isdir(cache_dir):
                    blobs = os.path.join(cache_dir, 'blobs')
                    if os.path.isdir(blobs):
                        for f in os.listdir(blobs):
                            if not f.endswith('.incomplete') and os.path.getsize(os.path.join(blobs, f)) > 500*1024*1024:
                                return True
        except Exception:
            pass
        return False
    
    def get_name(self) -> str:
        return f"local:qwen2.5-1.5b-instruct" if "qwen" in self.model_name.lower() else f"local:{self.model_name}"
    
    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "local": True,
            "requires_api_key": False,
            "supports_retrieval": True,
            "platforms": ["linkedin", "instagram", "reel", "youtube"],
            "model_name": self.model_name,
            "model_path": self.model_path,
        }
    
    def load_model(self):
        """Load model explicitly - called lazily, cached."""
        if self._loaded:
            return self._model, self._tokenizer
        if self._load_error:
            raise self._load_error
        
        start = time.time()
        model_id = self._get_model_id()
        try:
            from transformers import AutoTokenizer, AutoModelForCausalLM
            import torch
            if self.model_path and os.path.isdir(self.model_path):
                self._tokenizer = AutoTokenizer.from_pretrained(self.model_path, local_files_only=True)
                self._model = AutoModelForCausalLM.from_pretrained(self.model_path, local_files_only=True, torch_dtype=torch.float32)
            else:
                self._tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=True)
                self._model = AutoModelForCausalLM.from_pretrained(model_id, local_files_only=True, torch_dtype=torch.float32)
            self._loaded = True
            self._load_time = time.time() - start
            return self._model, self._tokenizer
        except Exception as e:
            self._load_error = CaptionProviderError(f"Failed to load local model {model_id}: {e}. No auto-download attempted.")
            raise self._load_error
    
    def _build_prompt(self, ctx: CaptionGenerationContext, platform: str,
                      num_slides: int = 4,
                      examples: Optional[List[HistoricalPost]] = None) -> str:
        """Build structured prompt for Qwen."""
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
        
        try:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ]
            return self._tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        except Exception:
            return user
    
    def _generate(self, prompt: str, max_new_tokens: int = 200) -> str:
        model, tokenizer = self.load_model()
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=1024)
        import torch
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=0.7,
                do_sample=True,
                top_p=0.9,
                pad_token_id=tokenizer.eos_token_id,
            )
        response = tokenizer.decode(outputs[0][inputs['input_ids'].shape[1]:], skip_special_tokens=True)
        return response.strip()
    
    def generate_linkedin(self, ctx: CaptionGenerationContext, 
                         examples: Optional[List[HistoricalPost]] = None) -> str:
        if not self._loaded and not self.is_available():
            raise CaptionProviderError(f"Local model not available: {self._get_model_id()}. No cached weights found. Download required - see docs.")
        prompt = self._build_prompt(ctx, "linkedin", examples=examples)
        return self._generate(prompt, max_new_tokens=200)
    
    def generate_instagram(self, ctx: CaptionGenerationContext,
                          examples: Optional[List[HistoricalPost]] = None) -> str:
        if not self._loaded and not self.is_available():
            raise CaptionProviderError(f"Local model not available: {self._get_model_id()}. No cached weights found. Download required - see docs.")
        prompt = self._build_prompt(ctx, "instagram", examples=examples)
        return self._generate(prompt, max_new_tokens=150)
    
    def generate_reel(self, ctx: CaptionGenerationContext,
                     examples: Optional[List[HistoricalPost]] = None) -> str:
        if not self._loaded and not self.is_available():
            raise CaptionProviderError(f"Local model not available: {self._get_model_id()}. No cached weights found. Download required - see docs.")
        prompt = self._build_prompt(ctx, "reel", examples=examples)
        return self._generate(prompt, max_new_tokens=100)
    
    def generate_stories(self, ctx: CaptionGenerationContext,
                        num_slides: int = 4,
                        examples: Optional[List[HistoricalPost]] = None) -> List[str]:
        if not self._loaded and not self.is_available():
            raise CaptionProviderError(f"Local model not available: {self._get_model_id()}. No cached weights found. Download required - see docs.")
        prompt = self._build_prompt(ctx, "stories", num_slides=num_slides, examples=examples)
        result = self._generate(prompt, max_new_tokens=150)
        captions = [c.strip() for c in result.split("|")][:num_slides]
        while len(captions) < num_slides:
            captions.append("")
        return captions[:num_slides]
    
    def generate_youtube(self, ctx: CaptionGenerationContext,
                        examples: Optional[List[HistoricalPost]] = None) -> str:
        if not self._loaded and not self.is_available():
            raise CaptionProviderError(f"Local model not available: {self._get_model_id()}. No cached weights found. Download required - see docs.")
        prompt = self._build_prompt(ctx, "youtube", examples=examples)
        return self._generate(prompt, max_new_tokens=150)
