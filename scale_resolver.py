# scale_resolver.py
import json
import math
from pathlib import Path

FEATURES_IN = Path("outputs/features_grouped.json")
SCALES_IN = Path("outputs/page_scale.json")
OUT = Path("outputs/features_with_scale.json")


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def centroid_from_bbox(b):
    return [
        (b["x1"] + b["x2"]) / 2,
        (b["y1"] + b["y2"]) / 2,
    ]

def centroid_from_scale_bar(bar):
    if "bar_bbox" in bar:
        b = bar["bar_bbox"]
    elif "bbox_px" in bar:
        b = bar["bbox_px"]
    elif "geometry" in bar and "bbox_px" in bar["geometry"]:
        b = bar["geometry"]["bbox_px"]
    else:
        raise KeyError(f"Scale bar missing bbox: {bar.keys()}")

    return [
        (b["x1"] + b["x2"]) / 2,
        (b["y1"] + b["y2"]) / 2
    ]


with open(FEATURES_IN) as f:
    groups = json.load(f)

with open(SCALES_IN) as f:
    page_scales = json.load(f)

# index scale bars by page
scale_bars_by_page = {}
for page in page_scales:
    bars = page.get("scale_bars", [])
    if bars:
        scale_bars_by_page.setdefault(page["page"], []).extend(bars)

resolved = []

for group in groups:
    page = group["page"]
    bars = scale_bars_by_page.get(page, [])

    for feature in group["features"]:
        f_out = feature.copy()

        if not bars:
            f_out["scale"] = None
            f_out["scale_status"] = "unresolved"
            resolved.append(f_out)
            continue

        f_centroid = feature["geometry"]["centroid_px"]

        nearest = min(
            bars,
            key=lambda b: dist(
                f_centroid,
                centroid_from_scale_bar(b)
            )
        )

        f_out["scale"] = {
            "ratio": nearest["feet_per_pixel"],
            "units": "ft",
            "source_id": nearest.get("id", "scale_bar")
        }
        f_out["scale_status"] = "resolved"

        resolved.append(f_out)

with open(OUT, "w") as f:
    json.dump(resolved, f, indent=2)

print(f"Scale resolution complete → {OUT}")
