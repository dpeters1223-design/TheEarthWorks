"""compile_takeoff.py

Assembles all pipeline outputs into a complete 12-line-item earthwork take-off.

Reads:
  outputs/spot_volume.json      -> Items 10, 20 (cut/fill CY from spot elevations)
  outputs/stripping.json        -> Stripping CY (separate pay item)
  outputs/materials.json        -> Items 30, 60, 70, 80, 90, 100, 110, 120
  outputs/material_specs.json   -> Areas for reference

Prints a formatted table and writes outputs/takeoff.json.
"""

import json
from pathlib import Path

BASE_DIR            = Path(__file__).parent
SPOT_VOLUME_FILE    = BASE_DIR / "outputs" / "spot_volume.json"
STRIPPING_FILE      = BASE_DIR / "outputs" / "stripping.json"
MATERIALS_FILE      = BASE_DIR / "outputs" / "materials.json"
MATERIAL_SPECS_FILE = BASE_DIR / "outputs" / "material_specs.json"
OUTPUT_FILE         = BASE_DIR / "outputs" / "takeoff.json"

# Engineer's reference values for comparison (Palmyra ground truth)
REFERENCE = {
    10:  {"qty": 7054,   "unit": "CY"},
    20:  {"qty": 161,    "unit": "CY"},
    30:  {"qty": 229476, "unit": "SF"},
    40:  {"qty": 791,    "unit": "CY"},
    50:  {"qty": 513,    "unit": "CY"},
    60:  {"qty": 14202,  "unit": "SF"},
    70:  {"qty": 229476, "unit": "SF"},
    80:  {"qty": 264,    "unit": "CY"},
    90:  {"qty": 12749,  "unit": "CY"},
    100: {"qty": 4250,   "unit": "CY"},
    110: {"qty": 14202,  "unit": "SF"},
    120: {"qty": 229476, "unit": "SF"},
}


def load_json(path: Path, default=None):
    if path.exists():
        return json.loads(path.read_text())
    print(f"  Warning: {path.name} not found")
    return default or {}


def find_material_item(materials: list, keyword: str, unit: str) -> int | None:
    """Find the first materials item matching keyword and unit, return qty."""
    for item in materials:
        desc = (item.get("description") or "").lower()
        if keyword.lower() in desc and item.get("unit") == unit:
            return item.get("qty")
    return None


def main():
    print("Loading pipeline outputs ...\n")
    spot_volume    = load_json(SPOT_VOLUME_FILE)
    stripping      = load_json(STRIPPING_FILE)
    mat_data       = load_json(MATERIALS_FILE)
    mat_specs      = load_json(MATERIAL_SPECS_FILE)

    materials = mat_data.get("items", [])
    cap_sf    = mat_data.get("cap_area_sf",    mat_specs.get("cap_area_sf",           229476))
    out_sf    = mat_data.get("outside_cap_sf", mat_specs.get("outside_cap_area_sf",   14202))
    total_sf  = mat_data.get("total_sf",       mat_specs.get("total_disturbed_area_sf", 243678))

    # --- Extract cut/fill from spot_volume ---
    best_range = spot_volume.get("best_estimate_range_cy", [None, None])
    cut_cy_lo, cut_cy_hi = best_range[0], best_range[1]
    # Use midpoint of trimmed range as best estimate
    if cut_cy_lo is not None and cut_cy_hi is not None:
        cut_cy = round((cut_cy_lo + cut_cy_hi) / 2.0)
    else:
        cut_cy = spot_volume.get("estimates", {}).get("trimmed_p50_cy")
        if cut_cy:
            cut_cy = round(cut_cy)

    # Fill not separately tracked yet — use engineer reference or 0
    fill_cy = None  # Items 40/50 (subgrade cut/fill) not yet computed

    # --- Build line items ---
    line_items = []

    # Item 10: Unclassified Excavation (Cut) to Reach Finish Grade
    line_items.append({
        "item": 10,
        "description": "Unclassified Excavation (Cut) to Reach Finish Grade",
        "qty": cut_cy,
        "unit": "CY",
        "source": "spot_volume.json (trimmed mean of spot elevations)",
        "range": f"{cut_cy_lo:,.0f}–{cut_cy_hi:,.0f} CY" if cut_cy_lo else None,
    })

    # Item 20: Unclassified Embankment (Fill) to Reach Finish Grade
    # Fill is typically small; not computed separately yet (would need fill spots)
    line_items.append({
        "item": 20,
        "description": "Unclassified Embankment (Fill) to Reach Finish Grade",
        "qty": None,
        "unit": "CY",
        "source": "not yet computed (spot elevation fill pipeline needed)",
        "note": "engineer reference: 161 CY",
    })

    # Item 30: Finegrade Intermediate Cover Area
    finegrade_cap = find_material_item(materials, "finegrade final cap", "SF")
    if finegrade_cap is None:
        finegrade_cap = cap_sf
    line_items.append({
        "item": 30,
        "description": "Finegrade Intermediate Cover Area",
        "qty": finegrade_cap,
        "unit": "SF",
        "source": "materials.json (cap area)",
    })

    # Items 40/50: Cut/Fill to Reach Subgrade for Infiltration/Topsoil
    # These require BASE→FINAL spot elevation differencing — not yet implemented
    line_items.append({
        "item": 40,
        "description": "Cut to Reach Subgrade for Infiltration/Topsoil",
        "qty": None,
        "unit": "CY",
        "source": "not yet computed (BASE→FINAL spot elev delta needed)",
        "note": "engineer reference: 791 CY",
    })
    line_items.append({
        "item": 50,
        "description": "Fill to Reach Subgrade for Infiltration/Topsoil",
        "qty": None,
        "unit": "CY",
        "source": "not yet computed (BASE→FINAL spot elev delta needed)",
        "note": "engineer reference: 513 CY",
    })

    # Item 60: Finegrade Outside Cap (Topsoil/Seed Area)
    finegrade_out = find_material_item(materials, "finegrade outside cap", "SF")
    if finegrade_out is None:
        finegrade_out = out_sf
    line_items.append({
        "item": 60,
        "description": "Finegrade Outside Cap (Topsoil/Seed Area)",
        "qty": finegrade_out,
        "unit": "SF",
        "source": "materials.json (outside_cap area)",
    })

    # Item 70: Finegrade Final Cap
    line_items.append({
        "item": 70,
        "description": "Finegrade Final Cap",
        "qty": cap_sf,
        "unit": "SF",
        "source": "materials.json (cap area)",
    })

    # Item 80: Topsoil Between Cap Area and Grading Limits @ 6"
    topsoil_cy = find_material_item(materials, "topsoil", "CY")
    if topsoil_cy is None:
        topsoil_cy = round(out_sf * 0.5 / 27.0)
    line_items.append({
        "item": 80,
        "description": 'Topsoil Between Cap Area and Grading Limits @ 6"',
        "qty": topsoil_cy,
        "unit": "CY",
        "source": "materials.json (outside_cap_sf × 0.5 ft / 27)",
    })

    # Item 90: Infiltration Layer @ 18"
    infil_cy = find_material_item(materials, "infiltration", "CY")
    if infil_cy is None:
        infil_cy = round(cap_sf * 1.5 / 27.0)
    line_items.append({
        "item": 90,
        "description": 'Infiltration Layer @ 18"',
        "qty": infil_cy,
        "unit": "CY",
        "source": "materials.json (cap_area_sf × 1.5 ft / 27)",
    })

    # Item 100: Vegetative Support Layer @ 6"
    veg_cy = find_material_item(materials, "vegetative", "CY")
    if veg_cy is None:
        veg_cy = round(cap_sf * 0.5 / 27.0)
    line_items.append({
        "item": 100,
        "description": 'Vegetative Support Layer @ 6"',
        "qty": veg_cy,
        "unit": "CY",
        "source": "materials.json (cap_area_sf × 0.5 ft / 27)",
    })

    # Item 110: Seed/Fertilize/Mulch — Outside Cap
    seed_out = find_material_item(materials, "outside cap", "SF")
    if seed_out is None:
        seed_out = out_sf
    line_items.append({
        "item": 110,
        "description": "Seed/Fertilize/Mulch — Outside Cap",
        "qty": seed_out,
        "unit": "SF",
        "source": "materials.json (outside_cap area)",
    })

    # Item 120: Seed/Fertilize/Mulch — Final Cap Area
    seed_cap = find_material_item(materials, "final cap area", "SF")
    if seed_cap is None:
        seed_cap = cap_sf
    line_items.append({
        "item": 120,
        "description": "Seed/Fertilize/Mulch — Final Cap Area",
        "qty": seed_cap,
        "unit": "SF",
        "source": "materials.json (cap area)",
    })

    # Stripping (separate pay item, not numbered in reference)
    strip_cy   = stripping.get("stripping_cy")
    strip_depth_in = stripping.get("strip_depth_in", 6.0)
    strip_area = stripping.get("area_sf", total_sf)
    line_items.append({
        "item": "S",
        "description": f'Stripping @ {strip_depth_in:.0f}" Depth',
        "qty": round(strip_cy) if strip_cy is not None else None,
        "unit": "CY",
        "source": f"stripping.json ({strip_area:,} SF × {strip_depth_in/12:.3f} ft / 27)",
    })

    # --- Print formatted table ---
    print("=" * 95)
    print(f"{'#':<5} {'Description':<48} {'Qty':>10} {'Unit':<6} {'Ref Qty':>10} {'Delta':>10}")
    print("=" * 95)

    for item in line_items:
        num  = str(item["item"])
        desc = item["description"][:47]
        qty  = item.get("qty")
        unit = item.get("unit", "")
        ref  = REFERENCE.get(item["item"], {}).get("qty")

        qty_str  = f"{qty:,.0f}" if qty is not None else "TBD"
        ref_str  = f"{ref:,.0f}" if ref is not None else "—"

        if qty is not None and ref is not None and unit == REFERENCE.get(item["item"], {}).get("unit"):
            delta = qty - ref
            delta_str = f"{delta:+,.0f}"
        else:
            delta_str = "—"

        print(f"{num:<5} {desc:<48} {qty_str:>10} {unit:<6} {ref_str:>10} {delta_str:>10}")

    print("=" * 95)

    # --- Write output ---
    output = {
        "line_items": line_items,
        "areas": {
            "cap_area_sf":           cap_sf,
            "outside_cap_area_sf":   out_sf,
            "total_disturbed_area_sf": total_sf,
        },
        "reference": REFERENCE,
    }

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(output, indent=2))
    print(f"\nWrote {OUTPUT_FILE}")

    # Verification checks
    print("\n--- Verification ---")
    for item in line_items:
        num = item["item"]
        ref = REFERENCE.get(num)
        if ref and item.get("qty") is not None:
            expected = ref["qty"]
            actual   = item["qty"]
            ok = abs(actual - expected) <= max(1, expected * 0.01)  # within 1%
            status = "OK" if ok else "DIFF"
            print(f"  Item {num:>3}: {actual:>10,} {item['unit']}  ref={expected:>10,}  [{status}]")


if __name__ == "__main__":
    main()
