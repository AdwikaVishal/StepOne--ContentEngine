# Smoke Test Commands

## 1. Test existing caption generation (must still work)
```bash
cd "/Users/admin/Downloads/contentfinal5 copy 2"
PYTHONPATH=/Users/admin/Downloads/contentfinal5\ copy\ 2 /opt/homebrew/bin/python3 -c "
from content_engine.copy_generator import CopyGenerator
from content_engine.data_types import AssetMetadata
gen = CopyGenerator(use_llm=False)
assets = [AssetMetadata(path='t.jpg', asset_type='image', quality_score=0.7, aesthetic_score=0.6, face_count=2, face_confidences=[0.9,0.9], relevance_scores={'keynote':1.0}, scene_concepts=['keynote'], final_score=0.6)]
print(gen.generate_linkedin_caption('Test Event', assets))
"
```

## 2. Test template provider
```bash
cd "/Users/admin/Downloads/contentfinal5 copy 2"
PYTHONPATH=/Users/admin/Downloads/contentfinal5\ copy\ 2 /opt/homebrew/bin/python3 -c "
from content_engine.captioning import get_caption_provider
from content_engine.captioning.schema import CaptionGenerationContext
p = get_caption_provider(mode='template_only')
ctx = CaptionGenerationContext(event_name='Summit', platform='linkedin')
print(p.generate_linkedin(ctx))
"
```

## 3. Test local_only mode fails without local model (must NOT fall back to Groq)
```bash
cd "/Users/admin/Downloads/contentfinal5 copy 2"
CAPTION_PROVIDER_MODE=local_only PYTHONPATH=/Users/admin/Downloads/contentfinal5\ copy\ 2 /opt/homebrew/bin/python3 -c "
from content_engine.captioning import get_caption_provider
try:
    p = get_caption_provider(mode='local_only')
    print('BAD')
except Exception as e:
    print(type(e).__name__)
    print('NO_GROQ_FALLBACK' if 'groq' not in str(e).lower() or 'not falling' in str(e).lower() else str(e))
"
```

## 4. Test ingestion
```bash
cd "/Users/admin/Downloads/contentfinal5 copy 2"
PYTHONPATH=/Users/admin/Downloads/contentfinal5\ copy\ 2 /opt/homebrew/bin/python3 scripts/ingest_historical.py tests/fixtures/synthetic_posts.json
```

## 5. Run tests
```bash
cd "/Users/admin/Downloads/contentfinal5 copy 2"
PYTHONPATH=/Users/admin/Downloads/contentfinal5\ copy\ 2 /opt/homebrew/bin/python3 -m pytest tests/test_copy_generator.py tests/test_captioning_provider.py tests/test_ingestion.py -v
```
