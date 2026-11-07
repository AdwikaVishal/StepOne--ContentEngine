# Captioning Architecture - Local Model Integration Design

**Date:** 2026-10-27  
**Purpose:** Design local caption generation adapter to replace Groq dependency

## Current Architecture

```
CopyGenerator
├── _GroqGenerator (if GROQ_API_KEY set) - LLM via Groq API
├── Local LLM (Phi-3.5-mini mentioned in comment) - "if use_llm=True and Groq unavailable" 
└── Template fallback - always works
```

**Issue:** The "Local LLM (Phi-3.5-mini)" is mentioned in comments but not implemented. Only Groq and templates exist.

## Proposed Architecture

### 1. Provider Interface
Create a unified interface for caption generation providers:

```python
class CaptionProvider(ABC):
    @abstractmethod
    def generate_linkedin(self, ctx: EventContext, examples: List[HistoricalPost]) -> str:
        pass
    
    @abstractmethod
    def generate_instagram(self, ctx: EventContext, examples: List[HistoricalPost]) -> str:
        pass
    
    @abstractmethod
    def generate_reel(self, ctx: EventContext, examples: List[HistoricalPost]) -> str:
        pass
    
    @abstractmethod
    def generate_stories(self, ctx: EventContext, examples: List[HistoricalPost]) -> str:
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        pass
```

### 2. Provider Implementations

| Provider | Priority | Status | Notes |
|----------|----------|--------|-------|
| `GroqProvider` | 1 (current) | TO CREATE (wrap existing) | Keep intact for now |
| `LocalLLMProvider` | 2 | TO CREATE | Use local open-weight model (llama-3.2, mistral, phi, etc.) |
| `TemplateProvider` | 3 (fallback) | EXISTS | Current template logic |

### 3. Provider Selection Logic

```python
class CaptionProviderFactory:
    def get_provider(self, mode: str = "auto", force_local: bool = False) -> CaptionProvider:
        if mode == "local_only":
            provider = LocalLLMProvider()
            if not provider.is_available():
                raise CaptionProviderError("Local provider required but not available")
            return provider
        elif mode == "groq_only":
            provider = GroqProvider()
            if not provider.is_available():
                raise CaptionProviderError("Groq provider required but not available")
            return provider
        else:  # auto
            # Try local first if available and preferred, else Groq, else template
            ...
```

**Critical:** Never silently fall back to Groq when local_only mode is selected.

### 4. Retrieval System
For retrieval-assisted generation using historical posts:

```python
class HistoricalPostRetriever:
    def retrieve(
        self,
        brand: str,
        platform: str,
        content_type: str,
        campaign_context: Optional[str] = None,
        k: int = 5
    ) -> List[HistoricalPost]:
        # Filter by brand, platform, content_type, campaign
        # Return top-k relevant examples
        pass
```

### 5. Canonical Post Schema
Define schema for historical posts:

```python
@dataclass
class HistoricalPost:
    # Identifiers
    post_id: str
    brand: str
    platform: str  # linkedin, instagram, youtube
    content_type: str  # carousel, reel, story, photo, video
    
    # Content
    caption: str
    hashtags: List[str]
    assets: List[Dict]  # asset metadata
    
    # Engagement (for learning)
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    saves: Optional[int] = None
    views: Optional[int] = None
    engagement_rate: Optional[float] = None
    
    # Context
    campaign_id: Optional[str] = None
    campaign_name: Optional[str] = None
    posted_at: Optional[datetime] = None
    language: str = "en"
    
    # Metadata
    source: Optional[str] = None
    raw_data: Optional[Dict] = None
```

### 6. Local Model Selection
**Do NOT download automatically.** Need to inspect:
- Available RAM
- GPU availability (CUDA/MPS)
- Disk space
- Existing model cache

Candidate models (small enough for local):
- Llama-3.2-3B/1B
- Mistral-7B-v0.3 (might be too large)
- Phi-3.5-mini (mentioned in comments)
- Gemma-2-2B
- Smollm2 series

Recommend checking `huggingface_hub`, `transformers` cache, and system resources.

## Integration Points with Existing Code

1. **CopyGenerator** - Add provider system, keep backward compatible
2. **config.py** - Add caption provider settings
3. **api/main.py** - Add provider selection to regenerate endpoint
4. **orchestrator** - Use CopyGenerator as-is (should be compatible)

## File Structure (Proposed)
```
content_engine/
├── captioning/
│   ├── __init__.py
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── groq_provider.py
│   │   ├── local_provider.py
│   │   └── template_provider.py
│   ├── retrieval/
│   │   ├── __init__.py
│   │   └── retriever.py
│   ├── schema.py
│   └── factory.py
data/
├── historical/  # For historical posts (gitignored)
└── processed/   # Processed datasets
scripts/
└── profile_dataset.py
```
