# Pipeline Analysis: Town of Palmyra Landfill Closure

## Original Q&A — Session Context

> **User:** So how close are these results to this estimate?
>
> | Item # | Item Description | Qty | Unit |
> |--------|-----------------|-----|------|
> | 10 | Unclassified Excavation (Cut) Required To Reach Finish Grade Elevations | 7,054.00 | CY |
> | 20 | Unclassified Embankment Required (Fill) To Reach Finish Grade Elevations | 161.00 | CY |
> | 30 | Finegrade Intermediate Cover Area | 229,476.00 | SF |
> | 40 | Unclassified Excavation (Cut) Required To Reach Subgrade Elevations - For Infiltration And Topsoil = FG - 24" Depth | 791.00 | CY |
> | 50 | Unclassified Embankment Required (Fill) To Reach Subgrade Elevations - For Infiltration And Topsoil = FG - 24" Depth | 513.00 | CY |
> | 60 | Finegrade Areas Outside Of Cap To Receive Topsoil And Seed | 14,202.00 | SF |
> | 70 | Finegrade Final Cap | 229,476.00 | SF |
> | 80 | Place Topsoil Between Cap Area And Grading Limits @ 6" Depth | 264.00 | CY |
> | 90 | Place Infiltration Layer @ 18" Depth | 12,749.00 | CY |
> | 100 | Place Vegetative Support Layer @ 6" Depth | 4,250.00 | CY |
> | 110 | Seed, Fertilize And Mulch - Between Cap Area And Grading Limits | 14,202.00 | SF |
> | 120 | Seed, Fertilize And Mulch - Final Cap Area | 229,476.00 | SF |
>
> **Claude:** The honest answer is: very far off — by a factor of roughly 260–520×.
>
> | Quantity | Our Result | Engineer's Estimate | Ratio |
> |---|---|---|---|
> | Cut | 2,040,004 CY | 7,054 + 791 = 7,845 CY | **260× too large** |
> | Fill | 352,570 CY | 161 + 513 = 674 CY | **523× too large** |
>
> Three compounding errors:
>
> **Root Cause 1 — Wrong Surface Comparison:** Treating BASE_GRADING as "existing" and
> FINAL_GRADING as "proposed" was a conceptual mistake. These two plans differ by ≈2 ft (the
> cap system thickness: 18" infiltration + 6" vegetative). Cross-check: `12,749 CY × 27 ÷ 1.5 ft = 229,482 SF`
> and `4,250 CY × 27 ÷ 0.5 ft = 229,500 SF` — both match the cap footprint of 229,476 SF
> exactly. The actual earthwork (items 10–20) comes from EXISTING CONDITIONS → BASE GRADING.
> The base and final plans show the same topography ±2 ft, below the 10 ft contour interval —
> 71.8% of our cells correctly showed diff ≈ 0.
>
> **Root Cause 2 — Edge Artifacts:** The 18 surviving existing-conditions label points
> (z = 558–568 ft) are in the title block area (x ≈ 11,158 ft), not inside the drawing.
> The IDW extrapolates those high z-values outward, and where the proposed surface does reach,
> artificial diffs of 30–40 ft appear → millions of CY of spurious cut.
>
> **Root Cause 3 — Existing Conditions Plan Has No Readable Elevation Labels:** Only 7
> elevation text elements total: 2 scale-bar noise (z=100), 4 in the title block (z=558–568),
> 1 year (z=2024). Zero labeled contour elevations in the drawing area. Without labels on the
> existing terrain contours, we cannot reconstruct the existing surface.
>
> **What the Correct Pipeline Needs:**
> 1. Extract existing surface elevation labels — try `extract_contours.py` (Vision API) which
>    was designed exactly for this case (vector extraction failing)
> 2. Use the LOD boundary (229,476 SF cap footprint) as a clip mask
> 3. Compare EXISTING CONDITIONS → BASE GRADING (not base → final)

---


## Project
Town of Palmyra — Old Palmyra Landfill Closure Remediation
Plans: `Landfill Closure_Plans_REBID_06.06.25+.pdf` (8 pages)

## Engineer's Official Quantity Estimate (Ground Truth)

| # | Item | Qty | Unit |
|---|------|-----|------|
| **Base Grading Earthwork** | | | |
| 10 | Unclassified Excavation (Cut) to Reach Finish Grade | 7,054 | CY |
| 20 | Unclassified Embankment (Fill) to Reach Finish Grade | 161 | CY |
| 30 | Finegrade Intermediate Cover Area | 229,476 | SF |
| **Final Cap Earthwork** | | | |
| 40 | Excavation (Cut) to Reach Subgrade for Infiltration/Topsoil | 791 | CY |
| 50 | Embankment (Fill) to Reach Subgrade for Infiltration/Topsoil | 513 | CY |
| 60 | Finegrade Outside Cap to Receive Topsoil/Seed | 14,202 | SF |
| 70 | Finegrade Final Cap | 229,476 | SF |
| 80 | Topsoil Between Cap Area and Grading Limits @ 6" | 264 | CY |
| **Final Cap Materials** | | | |
| 90 | Infiltration Layer @ 18" depth | 12,749 | CY |
| 100 | Vegetative Support Layer @ 6" depth | 4,250 | CY |
| **Seeding** | | | |
| 110 | Seed/Fertilize/Mulch — Between Cap and Grading Limits | 14,202 | SF |
| 120 | Seed/Fertilize/Mulch — Final Cap Area | 229,476 | SF |

**Key facts derived from the estimate:**
- Cap footprint: **229,476 SF = 5.27 acres** (verified from items 90 and 100)
- Cap system thickness: 18" infiltration + 6" vegetative = **24" = 2 ft total**
- Cross-check: `12,749 CY × 27 / 1.5 ft = 229,482 SF` ✓ and `4,250 CY × 27 / 0.5 ft = 229,500 SF` ✓
- Total base grading earthwork: **7,845 CY** (7,054 cut + 161 fill — very shallow, ≈0.83 ft avg cut)

---

## Our Pipeline Results vs Ground Truth

| | Our Result | Engineer's Estimate | Error Factor |
|---|---|---|---|
| Total Cut | 2,040,004 CY | 7,845 CY | **260× too large** |
| Total Fill | 352,570 CY | 674 CY | **523× too large** |

**These numbers are completely wrong.** Three compounding root causes:

---

## Root Cause 1: Wrong Surface Comparison (Conceptual Error)

We compared **BASE_GRADING_PLAN → FINAL_GRADING_PLAN**, but this is the wrong pair.

- The actual earthwork (items 10–20) comes from: **EXISTING CONDITIONS → BASE GRADING**
- The BASE and FINAL grading plans differ by only **2 ft** (the cap system thickness)
- At a 10 ft contour interval, both plans show the **same contour lines at the same elevations** (530, 540, 550, 560 ft)
- 71.8% of our computed cells correctly showed diff ≈ 0 — because the two surfaces ARE nearly identical

The correct pipeline requires:
```
EXISTING CONDITIONS PLAN  →  compare  →  BASE GRADING PLAN
                                           = Items 10/20 earthwork
```
Not:
```
BASE GRADING PLAN  →  compare  →  FINAL GRADING PLAN
                                   = ~0 (just cap thickness, items 90/100)
```

---

## Root Cause 2: Title-Block Label Points Creating Edge Artifacts

The existing conditions plan (page 2) has almost no labeled contour elevations in the
**drawing area**. The 7 total elevation text elements found were:

| z value | Location in page | Source |
|---------|-----------------|--------|
| 100.0 (×2) | x≈514, 719 pts | Scale bar "0 100 200 300" |
| 558.38, 567.44, 567.7, 567.85 | x≈2022 pts (right edge) | **Title block** / schedule table |
| 2024.0 | x≈2375 pts | Year in title block |

After the cross-surface elevation filter (removes z < 470 ft), 18 points at z = 558–568 ft
survived. But these are **at x ≈ 11,158 ft** in real-world coordinates — right at the
title block border, not over the landfill. The IDW for the existing surface extrapolates
these z = 560 ft values outward, and where the proposed surface IS defined nearby,
artificial diffs of 30–40 ft appear → millions of spurious CY of cut.

---

## Root Cause 3: Existing Conditions Plan Has No Readable Elevation Labels

The existing conditions plan shows 457 vector paths (contour lines) but essentially
zero labeled contour elevations in the drawing area. This is the fundamental blocker.
Without elevation labels on the existing terrain contours, we cannot reconstruct the
existing surface and cannot compute the base grading earthwork.

Possible reasons the labels are missing:
- Labels are very small text at 1"≈400' drawing scale and fell below PyMuPDF's text
  extraction threshold at 200 DPI rendering
- Labels may be embedded as annotation objects rather than text spans
- The plan may use implied elevations (only label every Nth contour, others implied
  by interval) and the labeled contours happen to be in areas the extractor missed

---

## What Needs to Change to Get Correct Results

### Fix 1: Re-run `extract_scale.py` + `extract_vectors.py` at higher DPI
Increase the DPI rendering from 200 to 300 (or 400) in `extract_scale.py` (change
`DPI = 200` to `DPI = 300`) and add a similar option to `extract_vectors.py`/PyMuPDF
page rendering. This may surface small elevation labels currently below the text
extraction threshold.

### Fix 2: Use `extract_contours.py` (Vision API) for the existing conditions page
`extract_contours.py` was specifically designed for cases where vector extraction fails.
It sends the full page image to the Vision API and asks it to read elevation labels
directly. This should work on the existing conditions plan even if PyMuPDF misses labels.

Run sequence:
```bash
python grading_sheet_router.py   # or manually create grading_pages.json for page_2 only
python extract_contours.py       # Vision API reads existing conditions page elevations
```
Then merge those Vision-extracted existing readings with the page_3 vector-extracted
base grading data to reconstruct the existing surface.

### Fix 3: Properly identify and use the LOD boundary as a clip mask
The 229,476 SF cap footprint is the LOD (Limit of Disturbance) boundary. Clipping
the computation to this boundary would:
- Eliminate computation over the 330+ acres outside the cap
- Focus the result on the actual earthwork zone
- Dramatically reduce spurious cut/fill from edge extrapolation

The LOD boundary is drawn on the plans but currently undetectable because its
line-width classification picks up small annotation boxes instead of the site boundary.
Debugging the width histogram from `extract_vectors.py` for pages 3 and 4 is needed
to identify the correct LOD line width.

### Fix 4: Compare EXISTING CONDITIONS → BASE GRADING (not base → final)
After fixes 1–3 provide an existing surface, update `reconstruct_surface.py` surface
type assignments:
```python
EXISTING_SURFACE_TYPES = {"EXISTING_CONDITIONS_PLAN"}
PROPOSED_SURFACE_TYPES = {"BASE_GRADING_PLAN"}   # the earthwork target
```
The FINAL_GRADING_PLAN comparison (base → final) would then give ≈16,999 CY fill
(the cap material volume, consistent with items 90–100 in the estimate).

---

## Current Pipeline State (as of this session)

**What works:**
- `pdf_to_png.py` → `classify_sheets.py` → `extract_scale.py` → `extract_vectors.py`
  → `label_contours.py` → `reconstruct_surface.py` → `compute_cut_fill.py` all run
  end-to-end without errors
- Scale bar correctly detected for pages 3 and 4: **1"≈400' scale** (fpp ≈ 1.987 ft/px at 200 DPI)
- Unified scale fix (`label_contours.py`) ensures all pages use a single consistent
  feet_per_pt value, preventing coordinate misalignment
- Cross-surface elevation filter in `reconstruct_surface.py` correctly removes z=100
  scale-bar noise from existing surface (366 of 384 page-2 points removed)
- LOD boundary size validation correctly rejects the tiny (44×23 ft) mis-classified
  LOD polygons

**What doesn't work:**
- Existing conditions plan surface is unrecoverable from vector extraction alone —
  no labeled elevation contours in the drawing area
- Base vs Final comparison gives meaningless results (surfaces differ by only cap
  thickness ≈2 ft, below the 10 ft contour interval)

---

## Plan Sheet Inventory for This Project

| Page | Sheet Type | Vector Paths | Elevation Labels (drawing area) | Useful for? |
|------|-----------|-------------|--------------------------------|-------------|
| 1 | TITLE_SHEET | — | — | Nothing |
| 2 | EXISTING_CONDITIONS_PLAN | 457 paths | **0** (only title-block labels) | Existing surface — currently unusable |
| 3 | BASE_GRADING_PLAN | 425 paths | 14 (530, 540, 550, 560 ft) | Proposed subgrade surface ✓ |
| 4 | FINAL_GRADING_PLAN | 315 paths | 33 (520–560 ft) | Proposed final surface ✓ |
| 5 | SEDIMENT_CONTROL_PLAN | — | — | Nothing |
| 6 | EROSION_CONTROL_PLAN | — | — | Nothing |
| 7–8 | DETAILS | — | — | Nothing |

---

## Next Session — Recommended Starting Points

1. **Quick win**: Run `extract_contours.py` (Vision API) against the existing conditions
   page (page 2) with `grading_pages.json` pointing only to that page. The Vision API
   can read labels that PyMuPDF's text extractor misses.

2. **Investigate LOD boundary**: Print the width histogram for page_3/page_4 paths to
   find the true LOD line width. A quick script reading `outputs/vectors.json` and
   printing `sorted(set(round(p['width'],2) for p in page['paths']))` will show all
   unique widths. Then adjust `LOD_WIDTH_MIN/MAX` in `label_contours.py`.

3. **Validate with cap volume**: After fixing the surface comparison, the FINAL-vs-BASE
   diff should yield ≈16,999 CY fill (cap material) — a good sanity check before
   comparing existing vs base for the earthwork quantities.
