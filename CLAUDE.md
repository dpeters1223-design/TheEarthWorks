# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TheEarthWorks.ai is an AI-powered civil engineering site plan analysis platform. It processes PDF construction documents to extract, classify, and quantify grading features (cut and fill earthwork operations). The project has two main entry points: a CLI processing pipeline and a FastAPI backend for interactive use.

## Environment Setup

Requires a `.env` file in the project root:
```
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1-mini   # optional, this is the default
MAX_TILES=10                 # optional, throttle for dev/testing
```

Core dependencies are in `backend/requirements.txt`. Install with:
```bash
pip install -r backend/requirements.txt
```
Additional root-level scripts may also require `openai`, `pdf2image`, and `python-dotenv`.

## Running the API Server

```bash
cd backend
uvicorn app.main:app --reload
```
Serves on `http://localhost:8000`.

## CLI Pipeline

The pipeline scripts must be run in this order from the project root:

```bash
python pdf_to_png.py          # Convert PDF pages to PNG (outputs to pages/)
python classify_sheets.py     # Classify pages as grading vs. other sheet types
python tiling.py              # Tile pages into 1024x1024 chunks with 128px overlap (outputs to tiles/)
python main.py                # Analyze each tile via OpenAI Vision API
python extract_features.py    # Extract CUT/FILL feature polygons from tile results
python feature_grouping.py    # Merge adjacent features into unified polygons
python extract_scale.py       # Detect graphic scale bars via vision
python scale_resolver.py      # Map each feature to its nearest scale bar
python inject_depth.py        # Apply default depth rules from config/depth_rules.json
python compute_quantities.py  # Calculate volumes (cu yd) and areas (sq ft)
python aggregate.py           # Produce final site_summary.json
```

All intermediate and final outputs land in `outputs/` as JSON files.

## Architecture

### Data Flow
```
PDF → PNG pages → 1024×1024 tiles → Vision API analysis → feature polygons
    → spatial grouping → scale bar detection → depth injection → volume calculation → site summary
```

### Key Design Decisions

**Tile-based vision analysis**: PDFs are split into overlapping tiles to fit within vision API input limits. `tiling.py` uses 1024×1024 tiles with 128px overlap to avoid cutting features at edges.

**Pipeline as separate scripts**: Each processing stage is its own script writing JSON to `outputs/`. This allows reruns at any stage without reprocessing earlier steps, which matters because vision API calls are expensive.

**Scale bar detection**: Rather than assuming a fixed scale, `extract_scale.py` uses the vision API to find graphic scale bars in the image, then `scale_resolver.py` does nearest-neighbor assignment to map features to the correct scale bar (important for multi-sheet plans with different scales).

**Confidence-weighted aggregation**: `aggregate.py` uses the confidence scores from vision analysis to weight depth estimates, producing a site summary with reliable uncertainty bounds rather than a naive average.

**Depth rules fallback**: `config/depth_rules.json` provides default depth ranges (cut: 2–5 ft, fill: 1–3 ft) used when the vision model cannot extract depths from the drawing.

### FastAPI Backend (`backend/app/`)

The API is primarily for interactive single-document workflows:
- `POST /upload` — receives a PDF, assigns a `job_id`, stores it in `Storage/uploads/`
- `GET /render/{job_id}/{page_number}` — renders a specific PDF page to PNG on demand
- `POST /save_polygon/{job_id}/{page_number}` — stores a user-drawn polygon annotation
- `GET /compute_cut_fill_stub/{job_id}/{page_number}` — returns a volume estimate from the stored polygon

Storage layout: `Storage/uploads/`, `Storage/renders/`, `Storage/polygons/` — all runtime, not committed.

### Output JSON Schema

| File | Contents |
|------|----------|
| `tiles.json` | Per-tile classification (grading/legend/etc), cut/fill flags, confidence |
| `sheet_classification.json` | Per-page sheet type from `classify_sheets.py` |
| `features.json` | Raw feature polygons in pixel coordinates with type and confidence |
| `features_grouped.json` | Spatially merged features |
| `features_with_scale.json` | Features annotated with feet/pixel ratio |
| `features_with_depth.json` | Features with depth ranges applied |
| `quantities.json` | Volumes (cu yd) and areas (sq ft) per feature |
| `site_summary.json` | Aggregated site totals with weighted confidence |
