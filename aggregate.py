# aggregate.py

import json
from pathlib import Path
from collections import Counter

INPUT_PATH = Path("outputs/tiles.json")
OUTPUT_PATH = Path("outputs/site_summary.json")

CONFIDENCE_THRESHOLD = 0.6
TRIM_PERCENT = 0.10  # 10% trim on each side


def reduce_assumptions(assumptions, top_n=12):
    counter = Counter(assumptions)
    return [f"{k} ({v})" for k, v in counter.most_common(top_n)]


def trim(values, pct):
    if not values:
        return []
    values = sorted(values)
    n = len(values)
    k = int(n * pct)
    return values[k : n - k] if n - k > k else values


def weighted_depth_range(tiles, key):
    raw_ranges = [t[key] for t in tiles if t.get(key)]
    if not raw_ranges:
        return None

    mins = []
    maxs = []
    weights = []

    for t in tiles:
        if t.get(key) and t.get("confidence", 0) >= CONFIDENCE_THRESHOLD:
            lo, hi = t[key]
            mins.append(lo)
            maxs.append(hi)
            weights.append(t["confidence"])

    if not mins:
        return {
            "weighted_range": None,
            "raw_union": [min(r[0] for r in raw_ranges), max(r[1] for r in raw_ranges)],
            "tiles_used": 0,
            "tiles_excluded_low_conf": len(raw_ranges),
        }

    mins_t = trim(mins, TRIM_PERCENT)
    maxs_t = trim(maxs, TRIM_PERCENT)
    weights_t = weights[: len(mins_t)]

    weighted_min = sum(m * w for m, w in zip(mins_t, weights_t)) / sum(weights_t)
    weighted_max = sum(m * w for m, w in zip(maxs_t, weights_t)) / sum(weights_t)

    return {
        "weighted_range": [round(weighted_min, 2), round(weighted_max, 2)],
        "raw_union": [min(r[0] for r in raw_ranges), max(r[1] for r in raw_ranges)],
        "tiles_used": len(mins_t),
        "tiles_excluded_low_conf": len(raw_ranges) - len(mins_t),
    }


def aggregate_tiles(tiles):
    grading_tiles = [t for t in tiles if t.get("tile_class") == "grading"]

    contour_vals = [t["contour_interval"] for t in grading_tiles if t.get("contour_interval")]
    contour_interval = Counter(contour_vals).most_common(1)[0][0] if contour_vals else None

    cut_depth = weighted_depth_range(grading_tiles, "cut_depth_estimate_ft")
    fill_depth = weighted_depth_range(grading_tiles, "fill_depth_estimate_ft")

    conf_tiles = [t["confidence"] for t in grading_tiles if t["confidence"] >= CONFIDENCE_THRESHOLD]
    confidence = sum(conf_tiles) / len(conf_tiles) if conf_tiles else 0.0

    raw_assumptions = [a for t in grading_tiles for a in t.get("assumptions", [])]
    tile_class_counts = Counter(t.get("tile_class") for t in tiles)

    return {
        "contour_interval": contour_interval,
        "cut_present": any(t.get("cut_present") for t in grading_tiles),
        "fill_present": any(t.get("fill_present") for t in grading_tiles),
        "cut_depth_estimate_ft": cut_depth,
        "fill_depth_estimate_ft": fill_depth,
        "confidence": round(confidence, 3),
        "assumptions": reduce_assumptions(raw_assumptions),
        "tile_counts_by_class": dict(tile_class_counts),
        "grading_tile_count": len(grading_tiles),
        "total_tile_count": len(tiles),
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "trim_percent": TRIM_PERCENT,
    }


if __name__ == "__main__":
    tiles = json.loads(INPUT_PATH.read_text())
    summary = aggregate_tiles(tiles)

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(summary, indent=2))

    print("Wrote outputs/site_summary.json")
