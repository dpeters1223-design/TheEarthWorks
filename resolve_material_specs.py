"""resolve_material_specs.py

Merges plan_notes.json + section_details.json into a single authoritative
material_specs.json.

Precedence for layer thicknesses:
  section_details (most explicit, from cross-section drawings) >
  plan_notes (from text notes) >
  hardcoded defaults

Area precedence:
  plan_notes (area callouts from drawings) >
  spot_volume.json (cap_area_sf from spot elevation pipeline) >
  lod_boundary.json (LOD polygon area, used as fallback total disturbed area)

Output: outputs/material_specs.json
"""

import json
from pathlib import Path

BASE_DIR            = Path(__file__).parent
PLAN_NOTES_FILE     = BASE_DIR / "outputs" / "plan_notes.json"
SECTION_DET_FILE    = BASE_DIR / "outputs" / "section_details.json"
SPOT_VOLUME_FILE    = BASE_DIR / "outputs" / "spot_volume.json"
LOD_BOUNDARY_FILE   = BASE_DIR / "outputs" / "lod_boundary.json"
OUTPUT_FILE         = BASE_DIR / "outputs" / "material_specs.json"

# --------------------------------------------------
# Hardcoded defaults (Palmyra project reference values)
# --------------------------------------------------

DEFAULTS = {
    "strip_depth_ft":    0.5,          # 6 inches
    "cap_area_sf":       229476,
    "outside_cap_sf":    14202,
    "layers": [
        {"name": "infiltration",       "zone": "cap_area",   "depth_ft": 1.5},   # 18"
        {"name": "vegetative_support", "zone": "cap_area",   "depth_ft": 0.5},   # 6"
        {"name": "topsoil",            "zone": "outside_cap","depth_ft": 0.5},   # 6"
    ],
}

# Canonical layer name aliases (lowercase fragments → canonical key)
LAYER_ALIASES = {
    "infiltration":          "infiltration",
    "infiltrat":             "infiltration",
    "vegetative support":    "vegetative_support",
    "vegetative":            "vegetative_support",
    "vegitative":            "vegetative_support",
    "topsoil":               "topsoil",
    "top soil":              "topsoil",
    "intermediate cover":    "intermediate_cover",
    "intermediate":          "intermediate_cover",
    "geomembrane":           "geomembrane",
    "drainage":              "drainage",
    "gas collection":        "gas_collection",
    "gas collect":           "gas_collection",
    "subgrade":              "subgrade",
    "liner":                 "geomembrane",
}


def normalize_layer_name(raw_name: str) -> str:
    if not raw_name:
        return "unknown"
    raw = raw_name.strip().lower()
    for fragment, canonical in LAYER_ALIASES.items():
        if fragment in raw:
            return canonical
    return raw.replace(" ", "_")


def inches_to_feet(inches) -> float | None:
    if inches is None:
        return None
    return round(float(inches) / 12.0, 6)


# --------------------------------------------------
# Load inputs
# --------------------------------------------------

def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text())
    print(f"  Warning: {path.name} not found — using default/empty")
    return default


def load_plan_notes() -> dict:
    return load_json(PLAN_NOTES_FILE, {})


def load_section_details() -> list:
    return load_json(SECTION_DET_FILE, [])


def load_spot_volume() -> dict:
    return load_json(SPOT_VOLUME_FILE, {})


def load_lod_boundary() -> dict:
    return load_json(LOD_BOUNDARY_FILE, {})


# --------------------------------------------------
# Layer resolution
# --------------------------------------------------

def build_layer_map_from_sections(section_details: list) -> dict:
    """Extract canonical_name -> depth_ft from section_details."""
    layer_map = {}
    for section in section_details:
        for layer in section.get("layers", []):
            key = normalize_layer_name(layer.get("name", ""))
            depth_ft = inches_to_feet(layer.get("thickness_in"))
            if key and depth_ft is not None:
                if key not in layer_map:
                    layer_map[key] = {"depth_ft": depth_ft,
                                      "source": f"section:{section.get('section_title','')}"}
    return layer_map


def build_layer_map_from_notes(plan_notes: dict) -> dict:
    """Extract canonical_name -> depth_ft from plan_notes."""
    layer_map = {}
    for layer in plan_notes.get("material_layers", []):
        key = normalize_layer_name(layer.get("name", ""))
        depth_ft = inches_to_feet(layer.get("depth_in"))
        if key and depth_ft is not None:
            if key not in layer_map:
                layer_map[key] = {"depth_ft": depth_ft,
                                  "source": f"plan_note:{layer.get('source_page','')}"}
    return layer_map


# --------------------------------------------------
# Area resolution
# --------------------------------------------------

def resolve_areas(plan_notes: dict, spot_volume: dict, lod_boundary: dict) -> dict:
    """Return {cap_area_sf, outside_cap_sf, total_disturbed_sf, sources}."""
    sources = {}

    # 1. Start with defaults
    cap_area_sf   = DEFAULTS["cap_area_sf"]
    outside_cap_sf = DEFAULTS["outside_cap_sf"]
    sources["cap_area"] = "default"
    sources["outside_cap"] = "default"

    # 2. Override from spot_volume.json cap_area_sf
    sv_cap = spot_volume.get("cap_area_sf")
    if sv_cap:
        cap_area_sf = sv_cap
        sources["cap_area"] = "spot_volume.json"

    # 3. Override from plan_notes areas_mentioned_sf
    pn_areas = plan_notes.get("areas_mentioned_sf", {})
    if "cap_area" in pn_areas:
        cap_area_sf = pn_areas["cap_area"]
        sources["cap_area"] = "plan_notes"
    if "seeding_area" in pn_areas:
        outside_cap_sf = pn_areas["seeding_area"]
        sources["outside_cap"] = "plan_notes"

    total_disturbed_sf = cap_area_sf + outside_cap_sf

    return {
        "cap_area_sf":       round(cap_area_sf),
        "outside_cap_sf":    round(outside_cap_sf),
        "total_disturbed_sf": round(total_disturbed_sf),
        "sources":           sources,
    }


# --------------------------------------------------
# Strip depth resolution
# --------------------------------------------------

def resolve_strip_depth(plan_notes: dict) -> tuple[float, str]:
    """Return (strip_depth_ft, source_description)."""
    pn_depth = plan_notes.get("strip_depth_in")
    if pn_depth is not None:
        return round(float(pn_depth) / 12.0, 6), f"plan_notes ({plan_notes.get('strip_depth_source')})"
    return DEFAULTS["strip_depth_ft"], "default (6 inches)"


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():
    print("Loading inputs ...")
    plan_notes     = load_plan_notes()
    section_details = load_section_details()
    spot_volume    = load_spot_volume()
    lod_boundary   = load_lod_boundary()

    # --- Layer resolution ---
    section_map = build_layer_map_from_sections(section_details)
    notes_map   = build_layer_map_from_notes(plan_notes)

    print(f"\nLayer depths found:")
    print(f"  From section_details: {list(section_map.keys())}")
    print(f"  From plan_notes:      {list(notes_map.keys())}")

    # Merge: section_details > plan_notes > defaults
    resolved_layers = []
    for default_layer in DEFAULTS["layers"]:
        key = default_layer["name"]
        if key in section_map:
            depth_ft = section_map[key]["depth_ft"]
            source   = section_map[key]["source"]
        elif key in notes_map:
            depth_ft = notes_map[key]["depth_ft"]
            source   = notes_map[key]["source"]
        else:
            depth_ft = default_layer["depth_ft"]
            source   = "default"
        resolved_layers.append({
            "name":     key,
            "zone":     default_layer["zone"],
            "depth_ft": depth_ft,
            "source":   source,
        })
        print(f"  {key}: {depth_ft} ft ({source})")

    # Also add any extra layers found in sections/notes not in defaults
    default_names = {L["name"] for L in DEFAULTS["layers"]}
    for key, info in {**notes_map, **section_map}.items():
        if key not in default_names and key not in ("unknown", "subgrade", "geomembrane",
                                                      "intermediate_cover", "drainage",
                                                      "gas_collection"):
            resolved_layers.append({
                "name":     key,
                "zone":     "cap_area",  # assume cap area if not specified
                "depth_ft": info["depth_ft"],
                "source":   info["source"],
            })
            print(f"  {key} (extra): {info['depth_ft']} ft ({info['source']})")

    # --- Area resolution ---
    areas = resolve_areas(plan_notes, spot_volume, lod_boundary)
    print(f"\nAreas resolved:")
    print(f"  cap_area      = {areas['cap_area_sf']:,} SF ({areas['sources'].get('cap_area')})")
    print(f"  outside_cap   = {areas['outside_cap_sf']:,} SF ({areas['sources'].get('outside_cap')})")
    print(f"  total_disturbed = {areas['total_disturbed_sf']:,} SF")

    # --- Strip depth resolution ---
    strip_depth_ft, strip_source = resolve_strip_depth(plan_notes)
    print(f"\nStrip depth: {strip_depth_ft} ft ({strip_source})")

    # --- Write output ---
    output = {
        "strip_depth_ft":        strip_depth_ft,
        "strip_depth_source":    strip_source,
        "cap_area_sf":           areas["cap_area_sf"],
        "outside_cap_area_sf":   areas["outside_cap_sf"],
        "total_disturbed_area_sf": areas["total_disturbed_sf"],
        "area_sources":          areas["sources"],
        "layers":                resolved_layers,
        "assumptions": [
            "Precedence: section_details > plan_notes > defaults",
            f"cap_area from {areas['sources'].get('cap_area')}",
            f"outside_cap from {areas['sources'].get('outside_cap')}",
            f"strip_depth from {strip_source}",
        ],
    }

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(output, indent=2))
    print(f"\nWrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
