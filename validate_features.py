#!/usr/bin/env python3
"""
validate_features.py

Phase 3.1 – Feature validation

Purpose:
- Ensure outputs/features.json is structurally sound
- Catch geometry and provenance errors early
- Fail before scale or takeoff math runs
"""

import json
import sys
from pathlib import Path

FEATURES_JSON = Path("outputs/features.json")
PAGES_DIR = Path("pages")
TILES_DIR = Path("tiles")

REQUIRED_TOP_KEYS = {
    "feature_id",
    "feature_type",
    "geometry_type",
    "geometry",
    "page",
    "source_tiles",
    "confidence",
    "assumptions",
}

REQUIRED_GEOM_KEYS = {
    "points_px",
    "bbox_px",
    "centroid_px",
}

def fail(msg):
    print(f"❌ VALIDATION ERROR: {msg}")
    sys.exit(1)

def validate_bbox(bbox):
    for k in ("x1", "y1", "x2", "y2"):
        if k not in bbox:
            return False
    return bbox["x1"] < bbox["x2"] and bbox["y1"] < bbox["y2"]

def validate_feature(feature):
    # Top-level keys
    missing = REQUIRED_TOP_KEYS - feature.keys()
    if missing:
        fail(f"{feature.get('feature_id')} missing keys: {missing}")

    geom = feature["geometry"]
    missing_geom = REQUIRED_GEOM_KEYS - geom.keys()
    if missing_geom:
        fail(f"{feature['feature_id']} geometry missing: {missing_geom}")

    # Geometry sanity
    if not geom["points_px"]:
        fail(f"{feature['feature_id']} has empty geometry")

    if not validate_bbox(geom["bbox_px"]):
        fail(f"{feature['feature_id']} has invalid bbox")

    cx, cy = geom["centroid_px"]
    b = geom["bbox_px"]
    if not (b["x1"] <= cx <= b["x2"] and b["y1"] <= cy <= b["y2"]):
        fail(f"{feature['feature_id']} centroid outside bbox")

    # Page existence
    page_path = PAGES_DIR / feature["page"]
    if not page_path.exists():
        fail(f"{feature['feature_id']} references missing page {feature['page']}")

    # Tile provenance
    if not feature["source_tiles"]:
        fail(f"{feature['feature_id']} has no source tiles")

    for tile_id in feature["source_tiles"]:
        matches = list(TILES_DIR.glob(f"*{tile_id}.png"))
        if not matches:
            fail(f"{feature['feature_id']} references missing tile {tile_id}")

    # Confidence bounds
    if not (0.0 <= feature["confidence"] <= 1.0):
        fail(f"{feature['feature_id']} confidence out of range")

def main():
    if not FEATURES_JSON.exists():
        fail("outputs/features.json not found")

    features = json.loads(FEATURES_JSON.read_text())
    if not isinstance(features, list):
        fail("features.json must be a list")

    for f in features:
        validate_feature(f)

    print(f"✅ Feature validation passed ({len(features)} features)")

if __name__ == "__main__":
    main()
