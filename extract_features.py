#!/usr/bin/env python3
"""
extract_features.py

Phase 3.1 – Feature extraction (POC)

Input:
- outputs/tiles.json
- tiles/*.png (for tile position via filename)

Output:
- outputs/features.json

This version:
- Extracts CUT and FILL features only
- Groups adjacent grading tiles on the same page
- Produces bounding boxes + centroids in pixel space
- No scale, no quantities, no unit conversion
"""

import json
import re
from pathlib import Path
from collections import defaultdict

TILES_JSON = Path("outputs/tiles.json")
TILES_DIR = Path("tiles")
OUT_PATH = Path("outputs/features.json")

TILE_SIZE = 1024  # must match tiling.py
OVERLAP = 128

# -------------------------------------------------
# Helpers
# -------------------------------------------------

def parse_tile_coords(tile_id: str):
    """
    Expected tile_id format:
    page_003__tile_2048_1024
    """
    m = re.search(r"tile_(\d+)_(\d+)", tile_id)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))

def tile_bbox_px(tile_id: str):
    coords = parse_tile_coords(tile_id)
    if not coords:
        return None
    x, y = coords
    return {
        "x1": x,
        "y1": y,
        "x2": x + TILE_SIZE,
        "y2": y + TILE_SIZE,
    }

def merge_bboxes(bboxes):
    return {
        "x1": min(b["x1"] for b in bboxes),
        "y1": min(b["y1"] for b in bboxes),
        "x2": max(b["x2"] for b in bboxes),
        "y2": max(b["y2"] for b in bboxes),
    }

def centroid_from_bbox(bbox):
    return [
        int((bbox["x1"] + bbox["x2"]) / 2),
        int((bbox["y1"] + bbox["y2"]) / 2),
    ]

def tiles_adjacent(a, b):
    """
    Simple adjacency test using bbox overlap / proximity.
    """
    return not (
        a["x2"] < b["x1"] or
        a["x1"] > b["x2"] or
        a["y2"] < b["y1"] or
        a["y1"] > b["y2"]
    )

# -------------------------------------------------
# Feature grouping
# -------------------------------------------------

def group_tiles(tile_records):
    """
    Naive spatial clustering:
    - Same page
    - Same feature type
    - Adjacent bounding boxes
    """
    groups = []
    for tile in tile_records:
        placed = False
        bbox = tile_bbox_px(tile["tile_id"])
        if not bbox:
            continue

        for group in groups:
            if group["page"] != tile["page"]:
                continue
            if group["feature_type"] != tile["feature_type"]:
                continue

            if any(tiles_adjacent(bbox, gb) for gb in group["bboxes"]):
                group["tiles"].append(tile)
                group["bboxes"].append(bbox)
                placed = True
                break

        if not placed:
            groups.append({
                "page": tile["page"],
                "feature_type": tile["feature_type"],
                "tiles": [tile],
                "bboxes": [bbox],
            })

    return groups

# -------------------------------------------------
# Main
# -------------------------------------------------

def main():
    if not TILES_JSON.exists():
        raise FileNotFoundError("outputs/tiles.json not found")

    tiles = json.loads(TILES_JSON.read_text())

    # Filter grading tiles only
    grading = []
    for t in tiles:
        if t.get("tile_class") != "grading":
            continue

        feature_type = None
        if t.get("cut_present"):
            feature_type = "cut"
        elif t.get("fill_present"):
            feature_type = "fill"

        if not feature_type:
            continue

        grading.append({
            "tile_id": t["tile_id"],
            "page": t["tile_id"].split("__")[0] + ".png",
            "feature_type": feature_type,
            "confidence": t.get("confidence", 0.0),
            "assumptions": t.get("assumptions", []),
        })

    groups = group_tiles(grading)

    features = []
    for i, g in enumerate(groups, start=1):
        merged_bbox = merge_bboxes(g["bboxes"])
        centroid = centroid_from_bbox(merged_bbox)

        features.append({
            "feature_id": f"{g['feature_type']}_{i:03d}",
            "feature_type": g["feature_type"],
            "geometry_type": "polygon",
            "geometry": {
                "points_px": [
                    [merged_bbox["x1"], merged_bbox["y1"]],
                    [merged_bbox["x2"], merged_bbox["y1"]],
                    [merged_bbox["x2"], merged_bbox["y2"]],
                    [merged_bbox["x1"], merged_bbox["y2"]],
                ],
                "bbox_px": merged_bbox,
                "centroid_px": centroid,
            },
            "page": g["page"],
            "source_tiles": [t["tile_id"] for t in g["tiles"]],
            "confidence": round(
                sum(t["confidence"] for t in g["tiles"]) / len(g["tiles"]),
                3,
            ),
            "assumptions": list({
                a for t in g["tiles"] for a in t.get("assumptions", [])
            }),
        })

    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(features, indent=2))

    print(f"Wrote {OUT_PATH} ({len(features)} features)")

if __name__ == "__main__":
    main()
