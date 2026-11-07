"""
Brand photo selection logic documentation.
"""

SELECTION_LOGIC = """
## Brand Photo Segregation — Selection Logic

### Step 1: Brand Reference Preparation
- Load all render images provided for each brand
- Compute CLIP (ViT-B/32) image embeddings for each render
- Average embeddings per brand → single "brand prototype" vector

### Step 2: Asset Classification
For each photo:
1. Compute CLIP image embedding
2. Calculate cosine similarity to each brand prototype (normalised 0–1)
3. Compute HSV color histogram correlation as secondary signal
4. Combined score = CLIP × 0.80 + Histogram × 0.20

### Step 3: Brand Assignment
- If max(combined_score) ≥ threshold (default 0.60) → assign to that brand
- If max(combined_score) < threshold → "unmatched" bucket

### Step 4: Quality Scoring (within each brand)
- Technical quality 30%: Laplacian blur + HSV brightness
- Aesthetic quality 20%: CLIP similarity to quality prompts
- Face presence 30%: YOLOv11 detection with size weighting
- Concept relevance 20%: Semantic matching to event concepts

### Confidence Thresholds
| Score | Interpretation |
|-------|----------------|
| ≥ 0.70 | High confidence — clear visual match |
| 0.60–0.70 | Medium confidence — likely match |
| < 0.60 | Unmatched — flagged for manual review |
"""
