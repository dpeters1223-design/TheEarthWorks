# aggregate.py

import json
from pathlib import Path
from collections import Counter

INPUT_PATH = Path("outputs/tiles.json")
OUTPUT_PATH = Path("outputs/site_summary.json")


def reduce_assumptions(assumptions, top_n=12):
    buckets = {
        "no_contours": ["no contour", "no visible contour"],
        "interval_unknown": ["interval not", "not visible", "not shown"],
        "interval_5ft": ["5 ft", "5 feet", "5ft"],
        "interval_2ft": ["2 ft", "2 feet", "2ft"],
        "interval_1ft": ["1 ft", "1 feet", "1ft"],
        "cut_present": ["cut"],
        "fill_present": ["fill"],
        "legend_used": ["legend"],
        "scale_used": ["scale"],
        "limited_visibility": ["portion", "partial", "not visible"],
    }

    counts = {k: 0 for k in buckets}
    others = 0

    for a in assumptions:
        matched = False
        a_low = a.lower()
        for k, keys in buckets.items():
            if any(key in a_low for key in keys):
                counts[k] += 1
                matched = True
                break
        if not matched:
            others += 1

    ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    summary = [f"{k} ({v})" for k, v in ranked if v > 0][:top_n]

    if others:
        summary.append(f"other ({others})")

    return summary


def contour_interval_stats(tiles):
    """
    Returns:
      - mode_interval: most common non-null interval or None
      - distribution: dict of interval -> count, including "unknown"
      - conflict: True if more than one distinct non-null interval is present
    """
    vals = []
    unknown = 0

    for t in tiles:
        v = t.get("contour_interval")
        if v:
            vals.append(v)
        else:
            unknown += 1

    counts = Counter(vals)
    distribution = dict(counts)
    if unknown:
        distribution["unknown"] = unknown

    mode_interval = counts.most_common(1)[0][0] if counts else None
    conflict = len(counts.keys()) > 1

    return mode_interval, distribution, conflict


def aggregate_tiles(tiles):
    mode_interval, interval_distribution, interval_conflict = contour_interval_stats(tiles)

    cut_present = any(t.get("cut_present", False) for t in tiles)
    fill_present = any(t.get("fill_present", False) for t in tiles)

    def range_union(key):
        ranges = [t.get(key) for t in tiles if t.get(key)]
        if not ranges:
            return None
        mins = [r[0] for r in ranges]
        maxs = [r[1] for r in ranges]
        return [min(mins), max(maxs)]

    cut_depth = range_union("cut_depth_estimate_ft")
    fill_depth = range_union("fill_depth_estimate_ft")

    confidence = sum(t.get("confidence", 0.0) for t in tiles) / len(tiles) if tiles else 0.0

    raw_assumptions = [a for t in tiles for a in t.get("assumptions", [])]
    assumptions = reduce_assumptions(raw_assumptions)

    return {
        "contour_interval": mode_interval,
        "contour_interval_distribution": interval_distribution,
        "contour_interval_conflict": interval_conflict,
        "cut_present": cut_present,
        "fill_present": fill_present,
        "cut_depth_estimate_ft": cut_depth,
        "fill_depth_estimate_ft": fill_depth,
        "confidence": round(confidence, 3),
        "assumptions": assumptions,
        "tile_count": len(tiles),
    }


if __name__ == "__main__":
    tiles = json.loads(INPUT_PATH.read_text())
    summary = aggregate_tiles(tiles)

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(summary, indent=2))

    print("Wrote outputs/site_summary.json")

