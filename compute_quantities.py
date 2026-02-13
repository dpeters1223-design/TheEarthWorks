# compute_quantities.py
import json
import math
import sys
from pathlib import Path

INFILE = Path("outputs/features_with_depth.json")
OUTFILE = Path("outputs/quantities.json")

FEATURE_TYPE_MAP = {
    "cut": "volume",
    "fill": "volume",
    "silt_fence": "linear",
    "erosion_sock": "linear",
    "fabric": "area",
    "matting": "area",
    "stone": "area",
}


def polyline_length(points):
    return sum(
        math.hypot(x2 - x1, y2 - y1)
        for (x1, y1), (x2, y2) in zip(points[:-1], points[1:])
    )


def polygon_area(points):
    area = 0
    for i in range(len(points)):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % len(points)]
        area += (x1 * y2) - (x2 * y1)
    return abs(area) / 2


with open(INFILE) as f:
    features = json.load(f)

results = []

for ftr in features:
    # ---- Hard gates ----
    if ftr.get("scale_status") != "resolved":
        sys.exit(f"BLOCKED: Feature {ftr['feature_id']} missing resolved scale")

    if ftr.get("depth") is None and ftr["feature_type"] in ("cut", "fill"):
        sys.exit(f"BLOCKED: Feature {ftr['feature_id']} missing depth")

    # ---- Resolve feature class ----
    fclass = FEATURE_TYPE_MAP.get(ftr["feature_type"])
    if fclass is None:
        sys.exit(f"BLOCKED: Unsupported feature type {ftr['feature_type']}")

    scale = ftr["scale"]
    px_to_ft = scale["ratio"]

    geom = ftr["geometry"]
    points = geom["points_px"]

    record = {
        "feature_id": ftr["feature_id"],
        "feature_type": ftr["feature_type"],
        "feature_class": fclass,
        "scale_source": scale["source_id"],
        "confidence": ftr.get("confidence", 0.5),
    }

    # ---- Linear ----
    if fclass == "linear":
        length_px = polyline_length(points)
        record["length_ft"] = length_px * px_to_ft

    # ---- Area ----
    elif fclass == "area":
        area_px = polygon_area(points)
        record["area_sqft"] = area_px * (px_to_ft ** 2)

    # ---- Volume ----
    elif fclass == "volume":
        depth = ftr["depth"]
        area_px = polygon_area(points)
        area_sqft = area_px * (px_to_ft ** 2)

        record["min_volume_cy"] = (area_sqft * depth["min_ft"]) / 27
        record["max_volume_cy"] = (area_sqft * depth["max_ft"]) / 27
        record["depth_source"] = depth["source"]
        record["depth_confidence"] = depth["confidence"]

    results.append(record)

with open(OUTFILE, "w") as f:
    json.dump(results, f, indent=2)

print(f"Quantity computation complete → {OUTFILE}")
