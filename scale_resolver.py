# scale_resolver.py
# Select the correct scale bar for a feature based on spatial proximity

import math

def bbox_center(bbox):
    x = (bbox["x1"] + bbox["x2"]) / 2
    y = (bbox["y1"] + bbox["y2"]) / 2
    return x, y

def distance(p1, p2):
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

def resolve_scale_for_feature(feature_bbox, page_scale_entry, min_confidence=0.85):
    """
    feature_bbox: {"x1":..., "y1":..., "x2":..., "y2":...}
    page_scale_entry: one page object from page_scale.json

    returns feet_per_pixel or None
    """

    scale_bars = page_scale_entry.get("scale_bars", [])
    if not scale_bars:
        return None

    feature_center = bbox_center(feature_bbox)

    best = None
    best_dist = None

    for bar in scale_bars:
        if bar.get("confidence", 0) < min_confidence:
            continue
        if bar.get("feet_per_pixel") is None:
            continue

        bar_center = bbox_center(bar["bar_bbox"])
        d = distance(feature_center, bar_center)

        if best is None or d < best_dist:
            best = bar
            best_dist = d

    if best is None:
        return None

    return best["feet_per_pixel"]
