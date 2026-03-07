# Where We Started — March 7, 2026

This document captures the state of the pipeline at the start of the `Sunday-3-7` session,
what we tried, and what we learned. It is meant to orient future sessions.

---

## The Project

**Town of Palmyra — Old Palmyra Landfill Closure Remediation**
PDF: `Landfill Closure_Plans_REBID_06.06.25+.pdf` (8 pages)

This is a landfill cap closure project. The engineer's goal was to close the landfill by:
1. Grading the existing waste surface to a base grade
2. Placing a cap system (infiltration layer + vegetative support layer) on top

The engineer's official quantity estimate (ground truth we are trying to match):

| # | Item | Qty | Unit |
|---|------|-----|------|
| 10 | Unclassified Excavation (Cut) to Reach Finish Grade | 7,054 | CY |
| 20 | Unclassified Embankment (Fill) to Reach Finish Grade | 161 | CY |
| 30 | Finegrade Intermediate Cover Area | 229,476 | SF |
| 40 | Cut to Reach Subgrade for Infiltration/Topsoil | 791 | CY |
| 50 | Fill to Reach Subgrade for Infiltration/Topsoil | 513 | CY |
| 60 | Finegrade Outside Cap (Topsoil/Seed Area) | 14,202 | SF |
| 70 | Finegrade Final Cap | 229,476 | SF |
| 80 | Topsoil Between Cap Area and Grading Limits @ 6" | 264 | CY |
| 90 | Infiltration Layer @ 18" depth | 12,749 | CY |
| 100 | Vegetative Support Layer @ 6" depth | 4,250 | CY |
| 110 | Seed/Fertilize/Mulch — Outside Cap | 14,202 | SF |
| 120 | Seed/Fertilize/Mulch — Final Cap Area | 229,476 | SF |

The key numbers we are trying to compute:
- **Cut: 7,054 CY** (earthwork — existing conditions → base grading)
- **Fill: 161 CY** (earthwork — existing conditions → base grading)
- **Cap area: 229,476 SF**

---

## Plan Sheet Inventory

| Page | Sheet Type | What's On It |
|------|-----------|--------------|
| 1 | TITLE_SHEET | Cover sheet, no terrain data |
| 2 | EXISTING_CONDITIONS_PLAN | Current landfill surface — **no vector-readable elevation labels** |
| 3 | BASE_GRADING_PLAN | Target earthwork grade (proposed subgrade) — labeled contours 530–560 ft |
| 4 | FINAL_GRADING_PLAN | Top of cap after material placement — labeled contours 520–560 ft |
| 5 | SEDIMENT_CONTROL_PLAN | No terrain data |
| 6 | EROSION_CONTROL_PLAN | No terrain data |
| 7–8 | DETAILS | No terrain data |

---

## What We Tried This Session

### Approach 1: Contour-Based Surface Reconstruction (vector pipeline)

The existing pipeline (`label_contours.py` → `reconstruct_surface.py` → `compute_cut_fill.py`)
extracts elevation labels from vector paths in the PDF and builds IDW-interpolated surfaces.

**Result: 260–520× off**

| | Our Result | Engineer | Ratio |
|---|---|---|---|
| Cut | 2,040,004 CY | 7,054 CY | 260× too large |
| Fill | 352,570 CY | 161 CY | 523× too large |

**Root causes (from PIPELINE_ANALYSIS.md, prior session):**
1. Wrong surface comparison: was comparing BASE_GRADING → FINAL_GRADING (only 2 ft difference —
   the cap thickness) instead of EXISTING_CONDITIONS → BASE_GRADING (the actual earthwork)
2. No elevation labels on the existing conditions page (page 2) in vector form
3. Edge artifacts from title-block label numbers being mis-identified as terrain elevations

**Fix applied this session:** Corrected surface type assignments in `label_contours.py`
(`EXISTING_SURFACE_TYPES = {"EXISTING_CONDITIONS_PLAN"}`, `PROPOSED_SURFACE_TYPES = {"BASE_GRADING_PLAN"}`)
and re-ran the pipeline.

**New result after fix: 0.0 CY (over-filtered)**

The existing surface was empty — page 2 has zero vector-readable elevation labels.

---

### Approach 2: Vision API Tile Extraction of Page 2 (Existing Conditions)

Ran `extract_contours_tiled.py` (4×3 grid, 2641×2400 px tiles) on page 2.
Found **22 elevation readings at 520–560 ft**, but only **5 inside the LOD boundary**.
All 5 were clustered in the left portion of the LOD (x ≈ 2776–3047 ft).

Ran `extract_contours_lod.py` (6×7 fine grid, 600 px tiles, LOD-focused) on page 2.
Found **52 readings**, **38 inside the LOD**, covering x=[2564, 4750] ft.

**Result after injection into reconstruct_surface.py: 3,869,185 CY fill**

Why it failed:
- The proposed surface (page 3) has 224 of 245 LOD-area points at exactly z=560 ft
  (the boundary contour dominates the IDW)
- Existing surface in the proposed-data zone extrapolates to ~522–545 ft
- Result: proposed (560) >> existing (530) everywhere → massive spurious fill
- **Root cause: the earthwork depth (avg 0.83 ft) is far below the 10-ft contour interval**
  Contour-based methods cannot detect sub-interval differences.

---

### Approach 3: Spot Elevation Extraction (Vision API, page 3)

Created `extract_spot_elevations.py` — tiles page 3 (base grading plan) at 800 px resolution
and asks the Vision model to find paired existing/proposed grade points.

**Found: 19 paired spot elevations; 11 valid interior pairs after filtering**

Filter criteria applied:
- Excluded readings within 200 ft of the LOD north boundary (drainage/edge features)
- Excluded one impossible reading (proposed 19 ft above existing — clear misread)

| | Our Result | Engineer | Ratio |
|---|---|---|---|
| Cut | 25,575 CY | 7,054 CY | 3.6× too large |
| Fill | 1,785 CY | 161 CY | 11× (1 sample only) |

**Significant improvement from 260× → 3.6× off on cut.**

Valid interior spot elevation pairs:

| Ex ft | Pr ft | Diff ft | x_ft | y_ft |
|-------|-------|---------|------|------|
| 542.64 | 542.85 | −0.21 | 2207 | 3138 |
| 544.53 | 540.68 | +3.85 | 2277 | 5420 |
| 548.16 | 547.92 | +0.24 | 2301 | 2862 |
| 544.75 | 542.75 | +2.00 | 2552 | 2789 |
| 541.48 | 539.11 | +2.37 | 2567 | 2596 |
| 547.74 | 541.80 | +5.94 | 2727 | 5698 |
| 542.70 | 542.50 | +0.20 | 2795 | 2919 |
| 545.20 | 542.05 | +3.15 | 3203 | 5321 |
| 547.08 | 538.23 | +8.85 | 3388 | 5649 |
| 547.55 | 544.85 | +2.70 | 4180 | 2098 |
| 539.50 | 537.00 | +2.50 | 5003 | 5687 |
| 545.80 | 544.50 | +1.30 | 5527 | 6013 |

**Why 3.6× error remains:**
Spot elevations are placed by engineers at *control points* — grade breaks and transitions —
not at randomly distributed interior points. These locations have above-average depth changes.
Most of the 229,476 SF cap footprint has < 0.5 ft of cut with no spot elevation marked.
Simple average of control-point depths is biased high relative to the true area-weighted average.

---

## The Fundamental Limitation of This Project Type

**Average earthwork depth: 7,054 CY × 27 ft³/CY ÷ 229,476 SF = 0.83 ft**

The contour interval on these plans is **10 ft** — twelve times the average depth.
No contour-based surface reconstruction method can detect sub-interval differences.

This is not a data quality or pipeline bug. It is a physical limitation of the source data.

---

## Accuracy By Method (Summary)

| Method | Our Result (cut) | Error vs 7,054 CY |
|--------|-----------------|-------------------|
| Contour surface diff (BASE vs FINAL) | 2,040,004 CY | 260× |
| Contour surface diff (EXISTING vs BASE, no existing data) | 0 CY | ∞ |
| Spot elevation avg depth (all 19 pairs) | 34,331 CY | 4.9× |
| Spot elevation avg depth (11 interior pairs filtered) | 25,575 CY | 3.6× |
| Cap spec × area (items 90–100 only) | exact | 1× (but different items) |
| Quantity table on plans | N/A — no table found | — |

---

## What Would Actually Work

1. **More spot elevations with spatial weighting (TIN/triangulation)** — if we can find 50+
   distributed spot pairs and build a triangulated surface instead of averaging depths, the
   area-weighting would correct the selection bias. Current count: 11 interior pairs.

2. **Expand tile search** — we only searched the LOD region of page 3. The full drawing area
   may contain more spot elevations in the interior of the cap footprint that would pull the
   average depth down toward the true 0.83 ft.

3. **Quantity table extraction** — if plans included a printed earthwork schedule (they don't
   here), this would give exact numbers directly.

4. **Underlying CAD/survey data** — the engineer computed from a CAD surface model. Without
   access to those files, plans-based extraction is inherently approximate for this depth range.

---

## Next Steps (Recommended Priority)

1. **Expand spot elevation search to full page 3 drawing area** — currently limited to the
   LOD region (229,476 SF cap footprint). More interior pairs → less selection bias → better
   average depth estimate.

2. **Implement TIN-based volume from spot elevations** — instead of averaging depths, build
   a triangulated irregular network from the paired spot points and integrate over the cap area.
   This corrects for uneven spatial sampling.

3. **Try page 4 (FINAL_GRADING_PLAN) for items 40–50** — the cap subgrade adjustment
   cut/fill (791 CY cut, 513 CY fill) compares BASE_GRADING → FINAL_GRADING. Page 4 may
   have more spot elevation data with larger depth values (since the cap layers are 18"+6"=24").

4. **Validate cap material volumes** — items 90–100 can be computed exactly from
   `area × depth / 27`: infiltration 229,476 × 1.5 / 27 = 12,748 CY ✓, vegetative
   229,476 × 0.5 / 27 = 4,249 CY ✓. These are already correct from spec alone.
