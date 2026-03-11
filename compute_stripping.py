"""compute_stripping.py

Computes earthwork stripping (topsoil removal) volume from the total disturbed
area and strip depth in material_specs.json.

Formula: strip_cy = total_disturbed_area_sf * strip_depth_ft / 27

Output: outputs/stripping.json
"""

import json
from pathlib import Path

BASE_DIR           = Path(__file__).parent
MATERIAL_SPECS_FILE = BASE_DIR / "outputs" / "material_specs.json"
OUTPUT_FILE        = BASE_DIR / "outputs" / "stripping.json"

# Fallback values if material_specs.json doesn't exist yet
DEFAULT_STRIP_DEPTH_FT      = 0.5        # 6 inches
DEFAULT_TOTAL_DISTURBED_SF  = 243678     # cap_area + outside_cap (Palmyra reference)


def load_specs() -> dict:
    if MATERIAL_SPECS_FILE.exists():
        return json.loads(MATERIAL_SPECS_FILE.read_text())
    print(f"Warning: {MATERIAL_SPECS_FILE.name} not found — using defaults")
    return {}


def main():
    specs = load_specs()

    strip_depth_ft = specs.get("strip_depth_ft", DEFAULT_STRIP_DEPTH_FT)
    strip_source   = specs.get("strip_depth_source", "default")
    area_sf        = specs.get("total_disturbed_area_sf", DEFAULT_TOTAL_DISTURBED_SF)
    area_source    = (specs.get("area_sources") or {}).get("cap_area", "default")

    if not area_sf:
        area_sf = DEFAULT_TOTAL_DISTURBED_SF
        area_source = "default"

    strip_cy = area_sf * strip_depth_ft / 27.0

    print(f"Strip depth : {strip_depth_ft} ft = {strip_depth_ft * 12:.1f} in  (from {strip_source})")
    print(f"Total area  : {area_sf:,.0f} SF")
    print(f"Stripping   : {area_sf:,.0f} SF × {strip_depth_ft} ft / 27 = {strip_cy:,.1f} CY")

    output = {
        "strip_depth_ft":    strip_depth_ft,
        "strip_depth_in":    round(strip_depth_ft * 12, 2),
        "strip_depth_source": strip_source,
        "area_sf":           area_sf,
        "area_source":       area_source,
        "stripping_cy":      round(strip_cy, 1),
        "formula":           "total_disturbed_area_sf * strip_depth_ft / 27",
    }

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(output, indent=2))
    print(f"\nWrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
