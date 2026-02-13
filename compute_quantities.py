# compute_quantities.py
import json
import math
import sys
from pathlib import Path

INFILE = Path("outputs/features_with_scale.json")
OUTFILE = Path("outputs/quantities.json")

def polyline_length(coords):
    return sum(
        math.hypot(x2 - x1, y2 - y1)
        for (x1, y1), (x2, y2) in zip(coords[:-1], coords[1:])
    )

def polygon_area(coords):
    area = 0
    for i in range(len(coords)):
        x1, y1 = coords[i]
        x2, y2 = coords[(i + 1) % len(coords)]
        area += (x1 * y2) - (x2 * y1)
    return abs(area) / 2

with open(INFILE) as f:
    features = json.load(f)

results = []

for ftr in features:
    if ftr.get("scale_status") != "resolved":
        sys.exit(f"BLOCKED: Feature {ftr.get('id')} missing resolved scale")

    scale = ftr["scale"]
    px_to_ft = scale["ratio"]

    geom = ftr["geometry"]
    ftype = ftr["feature_type"]

    record = {
        "feature_id": ftr["id"],
        "feature_type": ftype,
        "scale_id": scale["source_id"],
        "confidence": ftr.get("confidence", 0.5)
    }

    # LINEAR
    if ftype == "linear":
        px_len = polyline_length(geom)
        record["length_ft"] = px_len * px_to_ft

    # AREA
    elif ftype == "area":
        px_area = polygon_area(geom)
        record["area_sqft"] = px_area * (px_to_ft ** 2)

    # VOLUME
    elif ftype == "volume":
        if "min_depth_ft" not in ftr or "max_depth_ft" not in ftr:
            sys.exit(f"BLOCKED: Feature {ftr['id']} missing depth range")

        px_area = polygon_area(geom)
        area_sqft = px_area * (px_to_ft ** 2)

        record["min_volume_cy"] = (area_sqft * ftr["min_depth_ft"]) / 27
        record["max_volume_cy"] = (area_sqft * ftr["max_depth_ft"]) / 27

    else:
        sys.exit(f"BLOCKED: Unknown feature type {ftype}")

    results.append(record)

with open(OUTFILE, "w") as f:
    json.dump(results, f, indent=2)

print(f"Quantities computed safely → {OUTFILE}")
