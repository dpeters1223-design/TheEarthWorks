"""
feature_grouping.py

Feature-to-feature grouping using spatial adjacency.
Pure spatial logic. No AI. No scale.
Uses bbox_px already embedded in geometry.
"""

import json
from pathlib import Path

INFILE = Path("outputs/features.json")
OUTFILE = Path("outputs/features_grouped.json")


def bboxes_adjacent(a, b, padding=0):
    return not (
        a["x2"] + padding < b["x1"] or
        a["x1"] - padding > b["x2"] or
        a["y2"] + padding < b["y1"] or
        a["y1"] - padding > b["y2"]
    )


def group_features(features):
    groups = []

    for feature in features:
        bbox = feature["geometry"]["bbox_px"]
        placed = False

        for group in groups:
            if feature["page"] != group["page"]:
                continue
            if feature["feature_type"] != group["feature_type"]:
                continue

            if any(bboxes_adjacent(bbox, gb) for gb in group["bboxes"]):
                group["features"].append(feature)
                group["bboxes"].append(bbox)
                placed = True
                break

        if not placed:
            groups.append({
                "page": feature["page"],
                "feature_type": feature["feature_type"],
                "features": [feature],
                "bboxes": [bbox],
            })

    return groups


if __name__ == "__main__":
    with open(INFILE) as f:
        features = json.load(f)

    grouped = group_features(features)

    with open(OUTFILE, "w") as f:
        json.dump(grouped, f, indent=2)

    print(f"Grouped features written to {OUTFILE}")
