# FEATURE MATRIX

## Core Content Pipeline

| Feature | Status | Entry Point | Evidence | Dependencies | Notes |
|---------|--------|-------------|----------|--------------|-------|
| **Asset Discovery** | IMPLEMENTED AND VERIFIED | `ContentOrchestrator.run()` / `api.main` | `content_engine/orchestrator.py:186-209`, `api/main.py` file upload handling | Filesystem | Recursive discovery of images/videos by extension |
| **Quality Assessment** | IMPLEMENTED | `QualityAssessor` | `content_engine/models/quality.py` | PyTorch, CLIP (ViT-B/32), torchvision | Laplacian blur + brightness + CLIP aesthetic; adaptive thresholds from first 20 images |
| **Face Detection** | IMPLEMENTED | `FaceDetector` | `content_engine/models/face_detection.py` | ultralytics YOLOv11 | Face size weighting, confidence threshold |
| **Content Understanding** | IMPLEMENTED | `ContentUnderstander` | `content_engine/models/content_understanding.py` | Florence-2, CLIP | Scene concepts, relevance scoring, event-type concept weights |
| **Video Processing** | IMPLEMENTED | `VideoProcessor` | `content_engine/models/video_processing.py` | PySceneDetect, librosa, CLIP | Scene detection, audio energy, highlight extraction |
| **ML Asset Selection** | IMPLEMENTED | `ContentEngine.select_assets()` | `content_engine/pipeline.py`, `content_engine/orchestrator.py:247-270` | All 4 models | Weighted scoring (30% quality + 20% aesthetic + 30% faces + 20% concepts), low-confidence flagging |
| **LinkedIn Collage Generation** | IMPLEMENTED | `LayoutAssembler.create_linkedin_collage()` | `content_engine/layout_assembler.py:200-400+` | PIL, face-aware smart crop | 7 layouts (hero_right, hero_left, hero_center, magazine, panoramic, bauhaus, minimal), face-aware cropping |
| **Instagram Carousel** | IMPLEMENTED | `LayoutAssembler.create_carousel()` | `content_engine/layout_assembler.py` (search for method) | PIL | 1080x1350 (4:5), up to 10 slides |
| **Instagram Stories** | IMPLEMENTED | `LayoutAssembler.create_stories()` | `content_engine/layout_assembler.py` | PIL | 1080x1920 (9:16), horizontal adaptation for landscape |
| **Instagram Reel** | IMPLEMENTED | `LayoutAssembler.create_reel()` | `content_engine/layout_assembler.py:~500-600` | ffmpeg, PySceneDetect | 1080x1920, crossfade transitions (xfade filter), highlight clips from videos |
| **Caption Generation** | IMPLEMENTED | `CopyGenerator` | `content_engine/copy_generator.py` (38KB) | Groq API (optional), templates | Event-type aware, platform-specific, A/B variants |
| **Caption Regeneration (LLM)** | IMPLEMENTED | `/api/captions/regenerate` | `api/main.py:1856+` | Groq API | Groq llama-3.3-70b with fallback to templates |
| **Case Study Generation** | IMPLEMENTED | `generate_case_study()` | `content_engine/case_study_generator.py` | Templates | Markdown with selection logic, scores, QA flags |
| **Content Orchestrator (Full Pipeline)** | IMPLEMENTED | `ContentOrchestrator.run()` | `content_engine/orchestrator.py:211-400+` | All above | Wires everything together |

## Brand Segregation (GFF 2025)

| Feature | Status | Entry Point | Evidence | Dependencies | Notes |
|---------|--------|-------------|----------|--------------|-------|
| **BrandSegregator** | IMPLEMENTED AND VERIFIED | `content_engine/brand_segregator.py` | Tests pass structure, implementation present | CLIP (sentence-transformers or transformers) | CLIP similarity to brand render images, threshold-based assignment |
| **BrandOrchestrator** | IMPLEMENTED | `content_engine/brand_orchestrator.py` | 23KB file | BrandSegregator, ContentEngine, LayoutAssembler, CopyGenerator | Per-brand processing |
| **GFFOrchestrator** | IMPLEMENTED | `content_engine/gff/orchestrator_gff.py` | 15KB file | BrandOrchestrator | GFF-specific flow |
| **GFF API Routes** | IMPLEMENTED | `/api/gff/*` | `api/gff_routes.py` (315 lines), mounted in main.py:1812 | All above | `/process`, `/process-upload`, `/content/{brand_id}`, `/selection-logic` |
| **GFF CLI** | IMPLEMENTED | `generate_gff.py` | 7439 bytes | GFFOrchestrator | CLI interface |
| **Brand Clusters API** | IMPLEMENTED BUT NOT VERIFIED IN ROUTES | `/api/gff/brand-clusters` | Referenced in `ml_test_ui/src/api.ts:217-220` | Unknown | **NOT FOUND** in gff_routes.py grep - may be in main.py or missing |
| **Brand Threshold API** | IMPLEMENTED | `/api/brand/threshold/{job_id}` | `api/main.py:1820-1842` | Unknown implementation | GET/POST for thresholds |

## API Endpoints

| Feature | Status | Entry Point | Evidence | Dependencies | Notes |
|---------|--------|-------------|----------|--------------|-------|
| **Health Check** | IMPLEMENTED | `GET /health` | `api/main.py:550` | - | |
| **Model Status** | IMPLEMENTED | `GET /api/model-status` | `api/main.py:569` | - | |
| **Individual ML Endpoints** | IMPLEMENTED | `/api/quality, /api/faces, /api/content, /api/highlights` | `api/main.py:589-671` | Models | For testing individual components |
| **Pipeline Sync/Async** | IMPLEMENTED | `/api/pipeline`, `/api/pipeline/async` | `api/main.py:674-709` | ContentEngine | |
| **Generate Async/Fast** | IMPLEMENTED | `/api/generate/async`, `/api/generate/fast` | `api/main.py:711-903` | Orchestrator | |
| **Job Status/Result/Cancel** | IMPLEMENTED | `/api/jobs/{id}/status`, `/api/jobs/{id}/result`, `/api/jobs/{id}/cancel` | `api/main.py:904-977` | Job backend | |
| **ML Status** | IMPLEMENTED | `GET /api/ml/status` | `api/main.py:1039` | - | |
| **Enhanced Assets** | IMPLEMENTED | `GET /api/assets/enhanced/{job_id}` | `api/main.py:1101` | - | Frontend has smart categorization fallback |
| **Categorized Assets** | IMPLEMENTED | `GET /api/assets/categorized/{job_id}` | `api/main.py:1279` | - | |
| **Generate From Selected** | IMPLEMENTED | `POST /api/generate/from-selected` | `api/main.py:1376` | - | Asset selection flow |
| **Generate Custom** | IMPLEMENTED | `POST /api/generate/custom` | `api/main.py:1479` | - | With layout choices |
| **Layout Preview** | IMPLEMENTED | `POST /api/layout/preview` | `api/main.py:1569` | LayoutAssembler | |
| **Enriched Case Study** | IMPLEMENTED | `GET /api/jobs/{job_id}/case-study/enriched` | `api/main.py:1656` | - | |
| **Captions Regenerate** | IMPLEMENTED | `POST /api/captions/regenerate` | `api/main.py:1856` | Groq | |
| **Generate (legacy?)** | IMPLEMENTED | `POST /api/generate` | `api/main.py:1844` | Unknown | |
| **Static File Serving** | IMPLEMENTED | `/uploads`, `/output` | `api/main.py:~450-480` | StaticFiles | |

## Frontend UI

| Feature | Status | Entry Point | Evidence | Dependencies | Notes |
|---------|--------|-------------|----------|--------------|-------|
| **Studio Page** | IMPLEMENTED | `ml_test_ui/src/pages/StudioPage.tsx` | 400+ lines | All components, api.ts | Upload, brand mode, event wizard, job progress |
| **Results Page** | IMPLEMENTED | `ml_test_ui/src/pages/ResultsPage.tsx` | Imported in App.tsx | - | Results gallery |
| **Asset Selection Page** | IMPLEMENTED | `ml_test_ui/src/pages/AssetSelectionPage.tsx` | Imported in App.tsx | - | Flow after generation |
| **Analytics Page** | IMPLEMENTED | `ml_test_ui/src/pages/AnalyticsPage.tsx` | Imported in App.tsx | - | |
| **Brand Segregation Panel** | IMPLEMENTED | `ml_test_ui/src/components/BrandSegregationPanel.tsx` | Used in StudioPage | - | For brand mode |
| **Event Wizard** | IMPLEMENTED | `ml_test_ui/src/components/wizard/EventWizard.tsx` | Used in StudioPage | - | Configuration |
| **Job Polling** | IMPLEMENTED | `ml_test_ui/src/hooks/useJobPolling.ts` | Used in StudioPage | - | |
| **Theme Context** | IMPLEMENTED | `ml_test_ui/src/contexts/ThemeContext.tsx` | Used in App | - | |
| **Job/Analytics Context** | IMPLEMENTED | Contexts present | App.tsx | - | State management |

## "Design Engine" Assessment

The project is called "Content and Design Engine" but I need to assess if there's a true design engine vs just layout assembly.

| Capability | Status | Evidence | Notes |
|------------|--------|----------|-------|
| **Layout/Composition System** | IMPLEMENTED | LayoutAssembler with multiple layouts | This is more "automated layout generation" than design editor |
| **Canvas/Artboard** | NOT FOUND | - | No canvas element, no Fabric.js/Konva, no drawing tools |
| **Layer Management** | NOT FOUND | - | No layers panel, no z-index manipulation UI |
| **Element Selection/Drag-Drop** | NOT FOUND | - | Layouts are auto-generated, not manually editable in canvas |
| **Design Tokens/Themes** | PARTIAL | CSS variables in frontend, concept_weights.json | Some theming but not a full design token system |
| **Design Templates** | PARTIAL | Layout presets (hero_right, etc.) | Hardcoded layouts, not user-creatable templates |
| **Image Editing** | NOT FOUND | - | No crop/rotate/filters in UI beyond smart crop |
| **Brand Kits** | PARTIAL | Brand segregation, brand voice | Brand assets support but not a full brand kit manager |
| **Undo/Redo** | NOT FOUND | - | No undo/redo system visible |
| **Export Formats** | PARTIAL | JPEG, PNG implied, MP4 for video | Limited export options visible |
| **Content-to-Design Transformation** | IMPLEMENTED | Orchestrator passes content to layouts based on intended_use | This IS the connection between content and design |

**Conclusion:** The "Design Engine" is primarily the **Layout Assembler + Orchestrator composition system**, not a traditional design editor/canvas. The name might be aspirational or refer to automated design generation. The connection between content generation and visual design exists and is functional in the pipeline.
