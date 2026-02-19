"""label_contours.py

Classifies vector paths from extract_vectors.py into contour types, matches
elevation labels to paths, and outputs georeferenced point clouds ready for
surface reconstruction.

Steps:
  1. Classify paths by line width:
       - Proposed contours  (PROPOSED_WIDTH_MIN–MAX)
       - Existing contours  (EXISTING_WIDTH_MIN–MAX)
       - LOD boundary       (LOD_WIDTH_MIN–MAX, short dashed segments)
  2. Match each elevation label to the nearest contour path (proposed or existing).
  3. Collect all sample points from labeled paths → two point clouds.
  4. Chain the LOD boundary segments into a closed polygon.
  5. Convert all coordinates from PDF points to real-world feet using page_scale.json.

Output: outputs/labeled_contours.json
"""

import json
import math
from pathlib import Path

BASE_DIR = Path(__file__).parent
VECTORS_FILE   = BASE_DIR / "outputs" / "vectors.json"
SCALE_FILE     = BASE_DIR / "outputs" / "page_scale.json"
OUTPUT_FILE    = BASE_DIR / "outputs" / "labeled_contours.json"

# ------------------------------------------------------------------
# Width thresholds (PDF points).  Inspect vector_overlay.png and the
# width histogram printed by extract_vectors.py to tune for your drawing.
# ------------------------------------------------------------------
PROPOSED_WIDTH_MIN = 3.0
PROPOSED_WIDTH_MAX = 4.0

EXISTING_WIDTH_MIN = 0.75
EXISTING_WIDTH_MAX = 0.92

LOD_WIDTH_MIN = 5.0
LOD_WIDTH_MAX = 7.0

# A label is matched to the NEAREST contour path.
# Labels whose closest path is farther than this (pts) are flagged unmatched.
MAX_LABEL_DIST_PTS = 150.0

# When chaining LOD boundary segments into a polygon, endpoints are considered
# connected if they are within this many pts of each other.
LOD_CHAIN_GAP_PTS = 40.0

# When propagating elevation labels through connected contour segments,
# two paths are considered connected if any endpoint pair is within this
# many pts (median gap is ~7 pts; max observed ~18 pts).
CHAIN_GAP_PTS = 25.0


# ------------------------------------------------------------------
# Geometry helpers
# ------------------------------------------------------------------

def dist(p1, p2) -> float:
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def pt_to_path_dist(lx: float, ly: float, path_points: list) -> float:
    """Min distance from point (lx, ly) to any sampled point on a path."""
    best = float("inf")
    for x, y in path_points:
        d = math.hypot(x - lx, y - ly)
        if d < best:
            best = d
    return best


# ------------------------------------------------------------------
# Scale: PDF points → real-world feet
# ------------------------------------------------------------------

def compute_feet_per_pt(page_width_pts: float, scale_entries: list) -> float | None:
    """
    feet_per_pt = feet_per_pixel × (page_width_px / page_width_pts)

    page_scale.json records feet_per_pixel relative to the PNG render width.
    We convert to PDF-point scale using the ratio of px to pts widths.
    """
    for entry in scale_entries:
        pw_px = entry.get("page_width_px")
        for bar in entry.get("scale_bars", []):
            fpp = bar.get("feet_per_pixel")
            if fpp and pw_px:
                return fpp * (pw_px / page_width_pts)
    return None


def pts_to_ft(pts_coords: list, fpp: float) -> list:
    """Convert [[x_pts, y_pts], ...] → [[x_ft, y_ft], ...] (y-down preserved)."""
    return [[round(x * fpp, 3), round(y * fpp, 3)] for x, y in pts_coords]


# ------------------------------------------------------------------
# Connected-component label propagation
# ------------------------------------------------------------------

def propagate_labels(paths: list, path_elev: dict, gap_pts: float) -> dict:
    """
    Build connected components from path endpoint proximity, then propagate
    elevation labels from labeled paths to all unlabeled paths in the same
    component.

    paths      — list of path dicts (already filtered to one type: existing or proposed)
    path_elev  — {id(path): elevation_ft} for directly labeled paths
    gap_pts    — endpoint-to-endpoint distance threshold for connectivity

    Returns updated {id(path): elevation_ft} covering more paths.
    """
    n = len(paths)

    # Pre-extract endpoints
    endpoints = []
    for p in paths:
        pts = p["points"]
        endpoints.append((pts[0], pts[-1]))

    # Union-Find
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Connect paths whose endpoints are within gap_pts
    for i in range(n):
        s1, e1 = endpoints[i]
        for j in range(i + 1, n):
            s2, e2 = endpoints[j]
            if (dist(s1, s2) < gap_pts or dist(s1, e2) < gap_pts or
                    dist(e1, s2) < gap_pts or dist(e1, e2) < gap_pts):
                union(i, j)

    # Group paths by component root
    from collections import defaultdict
    components: dict[int, list] = defaultdict(list)
    for i in range(n):
        components[find(i)].append(i)

    # For each component, collect all labeled elevations → majority vote
    result = dict(path_elev)   # start with direct labels
    propagated = 0

    for root, members in components.items():
        labeled = [(path_elev[id(paths[i])], i)
                   for i in members if id(paths[i]) in path_elev]
        if not labeled:
            continue

        from collections import Counter
        elev = Counter(e for e, _ in labeled).most_common(1)[0][0]

        for i in members:
            pid = id(paths[i])
            if pid not in result:
                result[pid] = elev
                propagated += 1

    print(f"  Label propagation: +{propagated} paths labeled via connectivity")
    return result


# ------------------------------------------------------------------
# LOD boundary reconstruction
# ------------------------------------------------------------------

def chain_lod_segments(lod_paths: list) -> list:
    """
    Chain short LOD boundary segments (the dashes) into one ordered polygon.

    Each path contributes its first and last point as endpoints.  We greedily
    pick the next unused segment whose start or end is nearest to the current
    chain tip, reversing if needed.  Returns [[x, y], ...] in pts.
    """
    # represent each segment as (start_pt, end_pt, all_points)
    segs = []
    for p in lod_paths:
        pts = p["points"]
        if len(pts) < 2:
            continue
        segs.append((pts[0], pts[-1], pts))

    if not segs:
        return []

    chain = list(segs[0][2])
    used  = {0}
    tip   = chain[-1]

    while len(used) < len(segs):
        best_i, best_d, best_rev = None, float("inf"), False
        for i, (start, end, _) in enumerate(segs):
            if i in used:
                continue
            ds = dist(tip, start)
            de = dist(tip, end)
            if ds < best_d:
                best_d, best_i, best_rev = ds, i, False
            if de < best_d:
                best_d, best_i, best_rev = de, i, True

        if best_d > LOD_CHAIN_GAP_PTS:
            print(f"  LOD chain gap {best_d:.1f} pts > threshold — stopping early "
                  f"({len(used)}/{len(segs)} segments chained)")
            break

        pts = segs[best_i][2]
        if best_rev:
            pts = pts[::-1]
        chain.extend(pts[1:])   # skip duplicate endpoint
        tip = chain[-1]
        used.add(best_i)

    return chain


# ------------------------------------------------------------------
# Core processing
# ------------------------------------------------------------------

def process_page(page_data: dict, scale_entries: list) -> dict:
    page_name    = page_data["page"]
    pw_pts       = page_data["page_width_pts"]
    ph_pts       = page_data["page_height_pts"]
    paths        = page_data["paths"]
    text_elems   = page_data["text_elements"]

    # Scale factor
    fpp = compute_feet_per_pt(pw_pts, scale_entries)
    if fpp is None:
        print(f"  Warning: no scale found for {page_name} — coordinates in pts")
        fpp = 1.0

    print(f"  Scale: {fpp:.4f} ft/pt  (page {pw_pts:.0f}×{ph_pts:.0f} pts)")

    # Classify paths
    proposed_paths = []
    existing_paths = []
    lod_paths      = []

    for p in paths:
        w = p["width"]
        if PROPOSED_WIDTH_MIN <= w <= PROPOSED_WIDTH_MAX:
            proposed_paths.append(p)
        elif EXISTING_WIDTH_MIN <= w <= EXISTING_WIDTH_MAX:
            existing_paths.append(p)
        elif LOD_WIDTH_MIN <= w <= LOD_WIDTH_MAX:
            lod_paths.append(p)

    print(f"  Classified: {len(proposed_paths)} proposed paths, "
          f"{len(existing_paths)} existing paths, "
          f"{len(lod_paths)} LOD segments")

    # Elevation labels
    elev_labels = [t for t in text_elems if t["is_elevation"]]
    print(f"  Elevation labels: {len(elev_labels)}")

    # All contour paths combined for matching (tag with type)
    candidates = (
        [(p, "proposed") for p in proposed_paths] +
        [(p, "existing") for p in existing_paths]
    )

    # For each path, pre-cache its point list (avoid repeated dict lookup)
    path_pts_cache = {id(p): p["points"] for p, _ in candidates}

    # Match labels → nearest path
    path_elevations: dict[int, list] = {}   # path id → list of matched elevations
    matched   = 0
    unmatched = 0

    for lbl in elev_labels:
        lx, ly = lbl["x"], lbl["y"]
        elev   = lbl["elevation_ft"]

        best_pid, best_d, best_type = None, float("inf"), None
        for p, ptype in candidates:
            d = pt_to_path_dist(lx, ly, path_pts_cache[id(p)])
            if d < best_d:
                best_d, best_pid, best_type = d, id(p), ptype

        if best_d <= MAX_LABEL_DIST_PTS:
            path_elevations.setdefault(best_pid, []).append((elev, best_d))
            matched += 1
        else:
            print(f"  Unmatched label: {elev} ft at ({lx:.0f},{ly:.0f}) "
                  f"— nearest path {best_d:.0f} pts away")
            unmatched += 1

    # Resolve conflicts: if a path got multiple elevations, use the one
    # from the closest label.
    path_elev_direct: dict[int, float] = {}
    for pid, matches in path_elevations.items():
        best_elev = min(matches, key=lambda m: m[1])[0]
        path_elev_direct[pid] = best_elev

    # Propagate labels through connected contour segments
    proposed_elev = {pid: e for pid, e in path_elev_direct.items()
                     if any(id(p) == pid for p, t in candidates if t == "proposed")}
    existing_elev = {pid: e for pid, e in path_elev_direct.items()
                     if any(id(p) == pid for p, t in candidates if t == "existing")}

    proposed_elev = propagate_labels(proposed_paths, proposed_elev, CHAIN_GAP_PTS)
    existing_elev = propagate_labels(existing_paths, existing_elev, CHAIN_GAP_PTS)

    path_elev_final = {**proposed_elev, **existing_elev}

    # Build point clouds from labeled paths
    existing_points  = []   # [x_ft, y_ft, elev_ft]
    proposed_points  = []
    existing_labeled = 0
    proposed_labeled = 0
    existing_skipped = 0
    proposed_skipped = 0

    for p, ptype in candidates:
        pid  = id(p)
        elev = path_elev_final.get(pid)
        pts_ft = pts_to_ft(path_pts_cache[pid], fpp)

        if elev is None:
            if ptype == "proposed":
                proposed_skipped += 1
            else:
                existing_skipped += 1
            continue

        for pt in pts_ft:
            pt.append(round(elev, 1))   # [x_ft, y_ft, elev_ft]

        if ptype == "proposed":
            proposed_points.extend(pts_ft)
            proposed_labeled += 1
        else:
            existing_points.extend(pts_ft)
            existing_labeled += 1

    print(f"  Existing : {existing_labeled} labeled paths "
          f"({existing_skipped} unlabeled), {len(existing_points)} points")
    print(f"  Proposed : {proposed_labeled} labeled paths "
          f"({proposed_skipped} unlabeled), {len(proposed_points)} points")

    # LOD boundary
    lod_chain_pts = chain_lod_segments(lod_paths)
    lod_boundary  = pts_to_ft(lod_chain_pts, fpp)
    print(f"  LOD boundary: {len(lod_boundary)} vertices from {len(lod_paths)} segments")

    # Contour interval (most common step between sorted unique elevations)
    unique_elevs = sorted({p[2] for p in existing_points + proposed_points})
    contour_interval = None
    if len(unique_elevs) >= 2:
        steps = [round(unique_elevs[i+1] - unique_elevs[i], 2)
                 for i in range(len(unique_elevs) - 1)]
        from collections import Counter
        contour_interval = Counter(steps).most_common(1)[0][0]

    return {
        "page": page_name,
        "page_width_pts":  pw_pts,
        "page_height_pts": ph_pts,
        "feet_per_pt":     round(fpp, 6),
        "contour_interval_ft": contour_interval,
        "elevation_range_ft": {
            "min": min(unique_elevs) if unique_elevs else None,
            "max": max(unique_elevs) if unique_elevs else None,
        },
        "existing_points": existing_points,
        "proposed_points": proposed_points,
        "lod_boundary":    lod_boundary,
        "diagnostics": {
            "labels_matched":   matched,
            "labels_unmatched": unmatched,
            "existing_paths_labeled":  existing_labeled,
            "existing_paths_skipped":  existing_skipped,
            "proposed_paths_labeled":  proposed_labeled,
            "proposed_paths_skipped":  proposed_skipped,
            "lod_segments":            len(lod_paths),
            "lod_boundary_vertices":   len(lod_boundary),
        },
    }


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    if not VECTORS_FILE.exists():
        raise FileNotFoundError(
            f"Missing {VECTORS_FILE}. Run extract_vectors.py first."
        )

    pages = json.loads(VECTORS_FILE.read_text())

    scale_entries = []
    if SCALE_FILE.exists():
        scale_entries = json.loads(SCALE_FILE.read_text())
    else:
        print(f"Warning: {SCALE_FILE} not found — coordinates will be in PDF points")

    results = []
    for page_data in pages:
        print(f"\nProcessing {page_data['page']} ...")
        result = process_page(page_data, scale_entries)
        results.append(result)

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {OUTPUT_FILE}")

    for r in results:
        d = r["diagnostics"]
        print(f"  {r['page']}: "
              f"{len(r['existing_points'])} existing pts, "
              f"{len(r['proposed_points'])} proposed pts, "
              f"contour interval={r['contour_interval_ft']} ft, "
              f"LOD {d['lod_boundary_vertices']} vertices")


if __name__ == "__main__":
    main()
