"""reconstruct_surface.py

Reads outputs/contours.json and reconstructs existing and proposed terrain surfaces
via IDW interpolation on a regular grid.

Pixel coordinates from the contours file are in render-space (potentially downscaled).
They are converted to real-world feet using:
    feet_per_pixel_render = feet_per_pixel_original / scale_factor

Grid resolution is controlled by GRID_RESOLUTION_FT.

Output: outputs/surface_model.json
"""

import json
import math
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
CONTOURS_FILE = BASE_DIR / "outputs" / "contours.json"
OUTPUT_FILE = BASE_DIR / "outputs" / "surface_model.json"

GRID_RESOLUTION_FT = 25  # configurable
IDW_POWER = 2
IDW_K = 10          # number of nearest neighbours for IDW
BBOX_PAD_FRACTION = 0.10  # 10% padding around point extent
MIN_CONFIDENCE = 0.5  # discard low-confidence readings


# --------------------------------------------------
# IDW interpolation (pure Python)
# --------------------------------------------------

def idw_interpolate(query_x: float, query_y: float, points: list[tuple], power: int, k: int) -> float | None:
    """
    points: list of (x_ft, y_ft, elevation_ft)
    Returns interpolated elevation or None if no points available.
    """
    if not points:
        return None

    # compute squared distances
    dists = []
    for px, py, pz in points:
        d2 = (query_x - px) ** 2 + (query_y - py) ** 2
        dists.append((d2, pz))

    # sort by distance, take k nearest
    dists.sort(key=lambda t: t[0])
    nearest = dists[:k]

    # exact hit
    if nearest[0][0] == 0.0:
        return nearest[0][1]

    weights = [1.0 / (d2 ** (power / 2)) for d2, _ in nearest]
    total_w = sum(weights)
    if total_w == 0:
        return None
    return sum(w * z for w, (_, z) in zip(weights, nearest)) / total_w


# --------------------------------------------------
# Grid builder
# --------------------------------------------------

def build_grid(points: list[tuple], resolution_ft: float, bbox: tuple) -> list[list]:
    """
    Build a 2-D grid of interpolated elevations.
    bbox = (min_x, min_y, max_x, max_y) in feet.
    Returns a list of rows (outer = Y, inner = X), value or None.
    """
    min_x, min_y, max_x, max_y = bbox
    nx = max(1, math.ceil((max_x - min_x) / resolution_ft))
    ny = max(1, math.ceil((max_y - min_y) / resolution_ft))

    grid = []
    for iy in range(ny):
        row = []
        qy = min_y + (iy + 0.5) * resolution_ft
        for ix in range(nx):
            qx = min_x + (ix + 0.5) * resolution_ft
            val = idw_interpolate(qx, qy, points, IDW_POWER, IDW_K)
            row.append(round(val, 3) if val is not None else None)
        grid.append(row)

    return grid, nx, ny


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():
    if not CONTOURS_FILE.exists():
        raise FileNotFoundError(f"Missing {CONTOURS_FILE}. Run extract_contours.py first.")

    contours_data = json.loads(CONTOURS_FILE.read_text())

    results = []

    for page_entry in contours_data:
        page = page_entry.get("page", "unknown")
        scale_factor = page_entry.get("scale_factor")
        fpp_original = page_entry.get("feet_per_pixel_original")

        if scale_factor is None or fpp_original is None:
            print(f"[{page}] Skipping: missing scale_factor or feet_per_pixel_original")
            continue

        fpp_render = fpp_original / scale_factor

        readings = page_entry.get("elevation_readings", [])

        # Filter by confidence and build typed point lists
        existing_pts: list[tuple] = []
        proposed_pts: list[tuple] = []

        for r in readings:
            conf = r.get("confidence", 0.0)
            if conf < MIN_CONFIDENCE:
                continue
            elev = r.get("elevation_ft")
            x_px = r.get("x_px")
            y_px = r.get("y_px")
            rtype = r.get("type", "existing")

            if elev is None or x_px is None or y_px is None:
                continue

            x_ft = x_px * fpp_render
            y_ft = y_px * fpp_render

            if rtype == "proposed":
                proposed_pts.append((x_ft, y_ft, float(elev)))
            else:
                # "existing" and "spot" both contribute to existing surface
                existing_pts.append((x_ft, y_ft, float(elev)))

        # Validate we have both surface types
        has_existing = len(existing_pts) >= 1
        has_proposed = len(proposed_pts) >= 1

        if not has_existing or not has_proposed:
            missing = []
            if not has_existing:
                missing.append("existing")
            if not has_proposed:
                missing.append("proposed")
            print(
                f"\nERROR [{page}]: Cannot reconstruct surfaces — no '{' and '.join(missing)}' contour data found.\n"
                f"Please provide a grading plan that includes both existing and proposed contours.\n"
            )
            sys.exit(1)

        print(f"[{page}] existing={len(existing_pts)} pts, proposed={len(proposed_pts)} pts")

        # Build combined bounding box with padding
        all_pts = existing_pts + proposed_pts
        min_x = min(p[0] for p in all_pts)
        min_y = min(p[1] for p in all_pts)
        max_x = max(p[0] for p in all_pts)
        max_y = max(p[1] for p in all_pts)

        pad_x = (max_x - min_x) * BBOX_PAD_FRACTION
        pad_y = (max_y - min_y) * BBOX_PAD_FRACTION
        bbox = (
            min_x - pad_x,
            min_y - pad_y,
            max_x + pad_x,
            max_y + pad_y,
        )

        print(f"  Bounding box (ft): x=[{bbox[0]:.1f}, {bbox[2]:.1f}]  y=[{bbox[1]:.1f}, {bbox[3]:.1f}]")
        print(f"  Interpolating at {GRID_RESOLUTION_FT} ft grid resolution ...")

        existing_grid, nx, ny = build_grid(existing_pts, GRID_RESOLUTION_FT, bbox)
        proposed_grid, _, _ = build_grid(proposed_pts, GRID_RESOLUTION_FT, bbox)

        print(f"  Grid size: {nx} x {ny} = {nx * ny} cells")

        results.append({
            "page": page,
            "grid_resolution_ft": GRID_RESOLUTION_FT,
            "origin_ft": [round(bbox[0], 3), round(bbox[1], 3)],
            "grid_nx": nx,
            "grid_ny": ny,
            "existing_surface": existing_grid,
            "proposed_surface": proposed_grid,
            "point_counts": {
                "existing": len(existing_pts),
                "proposed": len(proposed_pts),
            },
        })

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
