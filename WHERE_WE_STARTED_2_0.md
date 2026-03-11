# Earthworks 2.0 — Pipeline Scaffold + What Comes Next

**Branch:** `earthworks-2.0`
**Date:** 2026-03-10

---

## What This Branch Does

Expands the take-off from 2 line items (cut CY, fill CY) to a full 12-item earthwork estimate.
Previous pipeline only computed items 10 and 20. This branch adds the scaffold for all 13.

### New scripts

| Script | What it does |
|--------|-------------|
| `classify_sheets.py` | Updated — adds GENERAL_NOTES and GEOTECH_SUMMARY sheet types |
| `extract_plan_notes.py` | Vision API: scans plan pages for strip depth, layer specs, area callouts |
| `extract_section_details.py` | Vision API: reads cross-section layer stacks from DETAILS pages |
| `resolve_material_specs.py` | Merges AI extraction with defaults → `material_specs.json` |
| `compute_stripping.py` | Math: `total_area × strip_depth / 27` → stripping CY |
| `compute_materials.py` | Math: layer volumes (CY) and finegrade/seed areas (SF) |
| `compile_takeoff.py` | Assembles full take-off table, compares against reference |

### Run order

```bash
python extract_plan_notes.py       # Vision API
python extract_section_details.py  # Vision API
python resolve_material_specs.py   # merge + defaults
python compute_stripping.py
python compute_materials.py
python compile_takeoff.py          # prints full table
```

---

## Where Things Stand — Honestly

The pipeline architecture is right. The math is right. Items 90 and 100 (infiltration and
vegetative support layers) will be exact once the areas and depths are confirmed, because the
formula is trivial: `area_sf × depth_ft / 27`.

What's missing is AI that actually reads the drawings well enough to replace the defaults.
Right now `material_specs.json` shows:

- `strip_depth_source: "default (6 inches)"` — AI hasn't read the notes yet
- `outside_cap: "default"` — AI hasn't found the 14,202 SF seeding area on the plan
- All layer depths: `"source": "default"` — AI hasn't read the cross-section dimensions

The Vision API scripts (`extract_plan_notes.py`, `extract_section_details.py`) are built
and ready to run. They haven't been validated against the Palmyra drawings yet.

Items 40 and 50 (cut/fill to reach subgrade) are not computed — they need a new pipeline
step that diffs BASE_GRADING_PLAN spot elevations against FINAL_GRADING_PLAN spot elevations.

---

## What's Next — Smarter AI Analysis

The goal for the next branch is to make the AI do real analytical work, not just OCR.
Specifically:

1. **Validate `extract_plan_notes.py` and `extract_section_details.py`** against the actual
   Palmyra drawings — confirm the AI finds strip depth (6") and seeding area (14,202 SF)
   without the defaults.

2. **Items 40/50: subgrade volume pipeline** — Vision API reads spot elevation pairs that
   appear on both BASE and FINAL sheets, diffs them, separates cut from fill within the
   cap footprint.

3. **Replace hardcoded zone areas with AI-detected zone polygons** — the cap area and
   seeding area should be traced from the plan, not pulled from a previous script's
   intermediate output.

4. **AI self-check**: run `extract_quantity_table.py` results through `compile_takeoff.py`
   as a validation column — if the plan has a printed quantity table, flag any computed
   value that disagrees with it by more than 5%.

5. **Reasoning layer over the full take-off** — once all line items are computed, a final
   AI step reviews the complete table for internal consistency (e.g., stripping CY should
   be proportional to total area; infiltration layer CY / cap area should equal depth / 27).
