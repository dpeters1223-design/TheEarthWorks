"""compute_materials.py

Computes all placed material layer volumes (CY) and finegrading/seeding areas (SF)
from material_specs.json.

Formula for each layer: volume_cy = zone_area_sf * depth_ft / 27

Output: outputs/materials.json
"""

import json
from pathlib import Path

BASE_DIR            = Path(__file__).parent
MATERIAL_SPECS_FILE = BASE_DIR / "outputs" / "material_specs.json"
OUTPUT_FILE         = BASE_DIR / "outputs" / "materials.json"

# Fallback specs if material_specs.json is missing
DEFAULT_SPECS = {
    "cap_area_sf":           229476,
    "outside_cap_area_sf":   14202,
    "total_disturbed_area_sf": 243678,
    "layers": [
        {"name": "infiltration",       "zone": "cap_area",   "depth_ft": 1.5},
        {"name": "vegetative_support", "zone": "cap_area",   "depth_ft": 0.5},
        {"name": "topsoil",            "zone": "outside_cap","depth_ft": 0.5},
    ],
}

# Human-readable labels for each layer key
LAYER_LABELS = {
    "infiltration":       "Infiltration Layer",
    "vegetative_support": "Vegetative Support Layer",
    "topsoil":            "Topsoil",
    "intermediate_cover": "Intermediate Cover",
    "drainage":           "Drainage Layer",
    "gas_collection":     "Gas Collection Layer",
    "geomembrane":        "Geomembrane Liner",
}

ZONE_LABELS = {
    "cap_area":   "cap area",
    "outside_cap":"outside cap",
}


def load_specs() -> dict:
    if MATERIAL_SPECS_FILE.exists():
        return json.loads(MATERIAL_SPECS_FILE.read_text())
    print(f"Warning: {MATERIAL_SPECS_FILE.name} not found — using defaults")
    return DEFAULT_SPECS


def zone_area(specs: dict, zone: str) -> int:
    if zone == "cap_area":
        return specs.get("cap_area_sf", DEFAULT_SPECS["cap_area_sf"])
    elif zone == "outside_cap":
        return specs.get("outside_cap_area_sf", DEFAULT_SPECS["outside_cap_area_sf"])
    else:
        return specs.get("total_disturbed_area_sf", DEFAULT_SPECS["total_disturbed_area_sf"])


def depth_label(depth_ft: float) -> str:
    inches = round(depth_ft * 12)
    return f'{inches}"'


def main():
    specs = load_specs()

    cap_sf      = specs.get("cap_area_sf",          DEFAULT_SPECS["cap_area_sf"])
    outside_sf  = specs.get("outside_cap_area_sf",  DEFAULT_SPECS["outside_cap_area_sf"])
    total_sf    = specs.get("total_disturbed_area_sf", DEFAULT_SPECS["total_disturbed_area_sf"])

    print(f"Areas: cap={cap_sf:,} SF  outside_cap={outside_sf:,} SF  total={total_sf:,} SF\n")

    items = []

    # --- Material layer volumes ---
    for layer in specs.get("layers", DEFAULT_SPECS["layers"]):
        name     = layer.get("name", "unknown")
        zone     = layer.get("zone", "cap_area")
        depth_ft = layer.get("depth_ft", 0.0)
        area_sf  = zone_area(specs, zone)

        volume_cy = round(area_sf * depth_ft / 27.0)
        label     = LAYER_LABELS.get(name, name.replace("_", " ").title())
        dlabel    = depth_label(depth_ft)

        item = {
            "description": f'{label} @ {dlabel}',
            "qty":         volume_cy,
            "unit":        "CY",
            "zone":        zone,
            "area_sf":     area_sf,
            "depth_ft":    depth_ft,
            "formula":     f"{area_sf} SF × {depth_ft} ft / 27",
        }
        items.append(item)
        print(f"  {item['description']:<40} {volume_cy:>8,} CY  ({ZONE_LABELS.get(zone, zone)})")

    # --- Finegrading areas ---
    finegrade_items = [
        {"description": "Finegrade Final Cap / Intermediate Cover Area",
         "qty": cap_sf, "unit": "SF", "zone": "cap_area"},
        {"description": "Finegrade Outside Cap (Topsoil/Seed Area)",
         "qty": outside_sf, "unit": "SF", "zone": "outside_cap"},
    ]
    for item in finegrade_items:
        items.append(item)
        print(f"  {item['description']:<40} {item['qty']:>8,} SF")

    # --- Seeding/Mulch areas ---
    seed_items = [
        {"description": "Seed/Fertilize/Mulch — Final Cap Area",
         "qty": cap_sf, "unit": "SF", "zone": "cap_area"},
        {"description": "Seed/Fertilize/Mulch — Outside Cap (Seeding Area)",
         "qty": outside_sf, "unit": "SF", "zone": "outside_cap"},
    ]
    for item in seed_items:
        items.append(item)
        print(f"  {item['description']:<40} {item['qty']:>8,} SF")

    output = {
        "cap_area_sf":    cap_sf,
        "outside_cap_sf": outside_sf,
        "total_sf":       total_sf,
        "items":          items,
    }

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(output, indent=2))
    print(f"\nWrote {OUTPUT_FILE}")

    # Verification checks
    print("\n--- Verification ---")
    for item in items:
        if "infiltration" in item["description"].lower():
            print(f"  Item 90 (Infiltration @ 18\")  -> {item['qty']:,} CY  (expected 12,749)")
        if "vegetative" in item["description"].lower():
            print(f"  Item 100 (Vegetative @ 6\")    -> {item['qty']:,} CY  (expected 4,250)")


if __name__ == "__main__":
    main()
