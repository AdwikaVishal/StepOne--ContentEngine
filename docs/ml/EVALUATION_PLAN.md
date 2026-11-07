# Evaluation Plan - Caption Generation

**Date:** 2026-10-27  
**Purpose:** Compare caption generation approaches

## Baselines to Compare

1. **Existing Baseline (Templates)** - Current template-based generation
2. **Groq Baseline (Current)** - Current LLM generation via Groq
3. **Retrieval-Assisted Local** - Local model with historical examples
4. **LoRA Fine-Tuned Local** - Fine-tuned model (FUTURE - not in scope now)

## Evaluation Metrics

### Automated Metrics
| Metric | Purpose | Target |
|--------|---------|--------|
| **Perplexity** | Language model quality | Lower is better |
| **BLEU/ROUGE** | Similarity to high-performing historical posts | Higher is better |
| **Brand voice compliance** | Use brand_voice.validate_copy() | Score >= 80 |
| **Length appropriateness** | Platform-specific length | Within platform limits |
| **Hashtag count** | Appropriate hashtag usage | Platform-appropriate |
| **Readability** | Flesch reading ease / grade level | Audience-appropriate |

### Human Evaluation
| Metric | Scale | Notes |
|--------|-------|-------|
| **Engagement potential** | 1-10 | Likelihood to drive engagement |
| **Brand fit** | 1-10 | Matches StepOne brand voice |
| **Authenticity** | 1-10 | Sounds human, not AI-generated |
| **Platform appropriateness** | 1-10 | Fits platform culture |
| **Relevance** | 1-10 | Relevant to event/content |
| **Overall quality** | 1-10 | Overall preference |

## Test Set

- Hold out chronologically (last 10-20% of posts by date)
- Stratify by platform and brand
- Ensure no leakage from train to test
- Minimum 100 test examples per platform if possible

## Evaluation Protocol

### Phase 1: Baseline Measurement
1. Run template generation on test set
2. Run Groq generation on test set (if API available)
3. Measure automated metrics

### Phase 2: Retrieval-Assisted Evaluation
1. Build retrieval index from training set
2. Test different k values (1, 3, 5, 10)
3. Test with/without brand filtering
4. Measure impact on quality

### Phase 3: Local Model Evaluation
1. Test with available local models
2. Compare with/without retrieval
3. Measure latency and resource usage
4. Check offline capability

## Data Leakage Prevention

- **Temporal split**: Train on older posts, test on newer posts
- **Duplicate detection**: Remove exact caption duplicates across splits
- **Campaign leakage**: Keep all posts from a campaign in same split
- **Brand leakage**: Consider brand-stratified splits
- **Asset leakage**: If same assets used, ensure proper handling

## Success Criteria

- Local model + retrieval achieves >= 80% of Groq quality on automated metrics
- Brand voice compliance >= 85%
- Generation works offline (no network required for local mode)
- Latency acceptable for batch processing (< 30s per post or better)
- No silent fallback to Groq in local_only mode

## Reporting

Results should be documented in:
- Automated metrics table
- Human evaluation results
- Resource usage (time, memory, GPU)
- Failure cases
- Recommendations

**Note:** Training/LoRA fine-tuning is explicitly out of scope for this milestone. Only baseline and evaluation plan needed.
