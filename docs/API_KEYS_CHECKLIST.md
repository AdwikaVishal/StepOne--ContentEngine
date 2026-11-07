# API Keys Checklist — Content & Design Engine

**Project:** `/Users/admin/Downloads/contentfinal5 copy 2`  
**Hardware:** MacBook Air M2, 8GB RAM  
**Security:** No secret values are recorded here. Variable names and statuses only.

---

## Bottom Line Up Front

**You do not need to obtain any API keys for MVP local testing.**

The complete content-generation workflow runs on local models (MLX Qwen2.5-0.5B-4bit for captions; CLIP, Florence-2, YOLOv11n, BLIP for vision) with no external credentials. The only credential present in `.env` (`GROQ_API_KEY`) is for an integration that is **disabled in code**.

---

## Category A — Essential for Core Local Testing

| # | Provider | Env var | Status | Needed for MVP local testing? | Notes |
|---|----------|---------|--------|------------------------------|-------|
| — | — | — | — | **None required** | MLX local inference replaces all hosted LLM APIs |

No external API key is required to test the full content-generation pipeline locally.

---

## Category B — Essential Only for Specific Optional Features

Obtain these **only** if you need the corresponding feature. All degrade gracefully (return "not configured") without them.

### B1. LinkedIn Publishing

| Field | Value |
|-------|-------|
| Provider | LinkedIn |
| Official dashboard URL | https://www.linkedin.com/developers/ |
| Environment variables | `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_ORGANIZATION_ID` |
| Free tier | Yes — LinkedIn developer apps are free |
| Credit card required | No |
| Necessary for MVP local testing? | No |
| Code location | `content_engine/studio/publishing.py` (`LinkedInPublisher`), `api/studio_routes.py` (`/api/studio/publish/linkedin`) |
| How to obtain | 1. Create a LinkedIn developer app at the dashboard URL. 2. Complete OAuth 2.0 flow to get an access token with `w_member_social` scope. 3. Add the four env vars to `.env`. |

### B2. Instagram Publishing (Meta)

| Field | Value |
|-------|-------|
| Provider | Instagram (Meta for Developers) |
| Official dashboard URL | https://developers.facebook.com/ |
| Environment variables | `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_BUSINESS_ACCOUNT_ID`, `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET` |
| Free tier | Yes — Meta developer apps are free |
| Credit card required | No |
| Necessary for MVP local testing? | No |
| Code location | `content_engine/studio/publishing.py` (`InstagramPublisher`), `api/studio_routes.py` (`/api/studio/publish/instagram`) |
| How to obtain | 1. Create a Meta developer app. 2. Add Instagram Basic Display or Instagram Graph API product. 3. You need an Instagram Business/Creator account connected to a Facebook Page. 4. Generate a long-lived access token. 5. Add the four env vars to `.env`. |

### B3. Sentry Error Tracking (Optional)

| Field | Value |
|-------|-------|
| Provider | Sentry |
| Official dashboard URL | https://sentry.io/ |
| Environment variables | `SENTRY_DSN` |
| Free tier | Yes (free tier available) |
| Credit card required | No (not for free tier) |
| Necessary for MVP local testing? | No |
| Code location | `api/worker.py` (lines 80-90), `config.py` (line 79) |
| How to obtain | 1. Create a Sentry project. 2. Copy the DSN from project settings. 3. Add to `.env`. |

---

## Category C — Production-Only

| # | Provider | Env var(s) | Reason production-only |
|---|----------|-----------|----------------------|
| 1 | LinkedIn | `LINKEDIN_ACCESS_TOKEN` + 3 others | Only needed when publishing to live LinkedIn |
| 2 | Instagram | `INSTAGRAM_ACCESS_TOKEN` + 3 others | Only needed when publishing to live Instagram |
| 3 | Sentry | `SENTRY_DSN` | Only needed for production error reporting |
| 4 | Redis (persistent) | `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | Only needed for distributed async jobs; APScheduler in-memory suffices for local/dev |

---

## Category D — Not Required (Local Alternative Exists)

| Instead of (paid/external) | Local alternative | Code location |
|---------------------------|-------------------|---------------|
| Groq LLM API | MLX Qwen2.5-0.5B-Instruct-4bit | `content_engine/llm/mlx_client.py`, `copy_generator.py` |
| Paid image captioning | BLIP (Salesforce/blip-image-captioning-base) | `content_engine/photo_intelligence/blip_captioner.py` |
| Paid object detection | Florence-2-base (microsoft) | `content_engine/models/content_understanding.py` |
| Paid face detection | YOLOv11n-face (AdamCodd) | `content_engine/models/face_detection.py` |
| Paid aesthetic/CLIP embeddings | CLIP ViT-B/32 (sentence-transformers) | `content_engine/models/quality.py`, `content_understanding.py`, `video_processing.py` |
| Paid brand matching | CLIP cosine similarity | `content_engine/brand/brand_matcher.py`, `brand_segregator.py` |
| Cloud object storage | Local filesystem (`uploads/`, `output/`) | `config.py`, `studio/storage.py` |
| Paid image/video generation | Not used by this application | N/A |

---

## Existing Credentials in `.env` (Names and Status Only)

Values are never printed. "Configured" means the variable has a non-empty value in `.env`.

| Env var | Configured? | Referenced in code? | Integration active? | Notes |
|---------|------------|---------------------|---------------------|-------|
| `GROQ_API_KEY` | Yes | config.py:82, copy_generator.py, groq_provider.py | **No — disabled** | Key present but Groq integration is disabled in `captioning/factory.py` and `CopyGenerator._groq` is always `None` |
| `GROQ_MODEL` | Yes | config.py:83 | No | Unused (Groq disabled) |
| `GROQ_SERVICE_TIER` | Yes | config.py:84 | No | Unused |
| `GROQ_TEMPERATURE` | Yes | config.py:85 | No | Unused |
| `MLX_MODEL_ID` | Yes | mlx_config.py:42 | Yes | Active MLX model repo id |
| `MLX_MAX_TOKENS` | Yes | mlx_config.py:45 | Yes | — |
| `MLX_MAX_CONTEXT` | Yes | mlx_config.py:46 | Yes | — |
| `MLX_TIMEOUT_SECONDS` | Yes | mlx_config.py:48 | Yes | — |
| `MODEL_PATH` | Yes | Not referenced in active code | No | Dead config (local Qwen PyTorch path, unused by MLX path) |
| All other vars (`REDIS_URL`, `API_HOST`, etc.) | Yes | config.py | N/A | Infrastructure settings, not credentials |

## Missing Credentials (In `.env.example` but Not in `.env`)

| Env var | Category | Needed for MVP? | Notes |
|---------|----------|-----------------|-------|
| `LINKEDIN_CLIENT_ID` | B | No | Optional publishing |
| `LINKEDIN_CLIENT_SECRET` | B | No | Optional publishing |
| `LINKEDIN_ACCESS_TOKEN` | B | No | Optional publishing |
| `LINKEDIN_ORGANIZATION_ID` | B | No | Optional publishing |
| `INSTAGRAM_ACCESS_TOKEN` | B | No | Optional publishing |
| `INSTAGRAM_BUSINESS_ACCOUNT_ID` | B | No | Optional publishing |
| `INSTAGRAM_APP_ID` | B | No | Optional publishing |
| `INSTAGRAM_APP_SECRET` | B | No | Optional publishing |
| `SENTRY_DSN` | B/C | No | Optional error tracking |
| `FLOWER_USER`, `FLOWER_PASSWORD` | C | No | Flower dashboard auth (commented out) |

## Security Findings

1. **`.env.example` contains a literal `GROQ_API_KEY` value (line 67).** This is a security issue — template files should never contain real secrets. The value should be replaced with a placeholder like `gsk_your_key_here`. (Outside audit scope to modify `.env` or `.env.example`.)

2. No AWS, Stripe, SendGrid, Twilio, Google Maps, Cloudinary, or other cloud credentials are referenced anywhere in the active codebase.

3. No OAuth token exchange is implemented — `studio/publishing.py` only constructs authorization URLs (prepared boundary, not functional).

## Acquisition Steps Summary (Only If You Need Optional Features)

| Feature | Step 1 | Step 2 | Step 3 |
|---------|--------|--------|--------|
| LinkedIn publishing | Go to https://www.linkedin.com/developers/ and create an app | Complete OAuth flow → get `LINKEDIN_ACCESS_TOKEN` | Add 4 LinkedIn env vars to `.env` |
| Instagram publishing | Go to https://developers.facebook.com/ and create a Meta app | Connect Instagram Business/Creator account to Facebook Page → generate token | Add 4 Instagram env vars to `.env` |
| Sentry | Go to https://sentry.io/ and create a project | Copy DSN from project settings | Add `SENTRY_DSN` to `.env` |

## Files Created by This Audit

- `docs/API_INTEGRATION_AUDIT.md`
- `docs/LOCAL_TESTING_READINESS.md`
- `docs/API_KEYS_CHECKLIST.md` (this file)
