"""reconstruct_surface.py

Reads outputs/labeled_contours.json (produced by label_contours.py) and
reconstructs existing and proposed terrain surfaces on a regular grid using
IDW (Inverse Distance Weighting) interpolation.

Key differences from the old Vision-based version:
  - Input is the vector-extracted point cloud (~8 K points) not 15 AI guesses
  - Grid cells outside the LOD boundary are set to None (null)
  - numpy is used for vectorised distance computation (required for performance)

Output format is identical to the old surface_model.json so compute_cut_fill.py
works unchanged.

Output: outputs/surface_model.json
"""

import json
import math
import sys
from pathlib import Path

import numpy as np

BASE_DIR             = Path(__file__).parent
LABELED_CONTOURS     = BASE_DIR / "outputs" / "labeled_contours.json"
OUTPUT_FILE          = BASE_DIR / "outputs" / "surface_model.json"

GRID_RESOLUTION_FT   = 25    # ft — size of each grid cell
IDW_K                = 12    # nearest neighbours for IDW
IDW_POWER            = 2     # distance weighting exponent
CHUNK_SIZE           = 1000  # grid points processed per batch (memory control)


# ------------------------------------------------------------------
# IDW interpolation (numpy-vectorised)
# ------------------------------------------------------------------

def idw_batch(gx: np.ndarray, gy: np.ndarray,
              sx: np.ndarray, sy: np.ndarray, sz: np.ndarray,
              k: int, power: float) -> np.ndarray:
    """
    Interpolate elevations for a batch of grid points.

    gx, gy  — 1-D arrays of query point coordinates (length M)
    sx, sy, sz — 1-D arrays of sample point coordinates (length N)
    Returns 1-D array of interpolated elevations (length M).
    """
    M = len(gx)
    N = len(sx)

    # (M, N) distance-squared matrix
    dx   = gx[:, np.newaxis] - sx[np.newaxis, :]
    dy   = gy[:, np.newaxis] - sy[np.newaxis, :]
    d2   = dx * dx + dy * dy

    use_k = min(k, N)

    if N > use_k:
        part  = np.argpartition(d2, use_k, axis=1)[:, :use_k]
        rows  = np.arange(M)[:, np.newaxis]
        k_d2  = d2[rows, part]
        k_z   = sz[part]
    else:
        k_d2  = d2
        k_z   = np.broadcast_to(sz, (M, N)).copy()

    # Exact-hit guard: replace 0 with tiny value, remember position
    exact    = k_d2 < 1e-12
    safe_d2  = np.where(exact, 1e-12, k_d2)

    w        = 1.0 / (safe_d2 ** (power / 2.0))
    total_w  = w.sum(axis=1)
    interp   = (w * k_z).sum(axis=1) / total_w

    # Override with exact hit value where applicable
    hit_rows = np.where(exact.any(axis=1))[0]
    for r in hit_rows:
        col = np.argmax(exact[r])
        interp[r] = k_z[r, col]

    return interp


def interpolate_surface(sample_pts: np.ndarray,
                        inside_mask: np.ndarray,
                        gx_all: np.ndarray,
                        gy_all: np.ndarray) -> np.ndarray:
    """
    Interpolate for all grid points that are inside the LOD boundary.
    Returns 1-D array of float or NaN (same length as gx_all).
    """
    result = np.full(len(gx_all), np.nan)

    inside_idx = np.where(inside_mask)[0]
    if len(inside_idx) == 0 or len(sample_pts) == 0:
        return result

    gx_in = gx_all[inside_idx]
    gy_in = gy_all[inside_idx]
    sx    = sample_pts[:, 0]
    sy    = sample_pts[:, 1]
    sz    = sample_pts[:, 2]

    # Process in chunks to control peak memory
    vals = np.empty(len(inside_idx))
    for start in range(0, len(inside_idx), CHUNK_SIZE):
        end  = min(start + CHUNK_SIZE, len(inside_idx))
        vals[start:end] = idw_batch(
            gx_in[start:end], gy_in[start:end], sx, sy, sz,
            IDW_K, IDW_POWER
        )

    result[inside_idx] = vals
    return result


# ------------------------------------------------------------------
# Point-in-polygon (vectorised ray-casting)
# ------------------------------------------------------------------

def pip_mask(qx: np.ndarray, qy: np.ndarray,
             poly_x: np.ndarray, poly_y: np.ndarray) -> np.ndarray:
    """
    Returns boolean array: True where query point is inside the polygon.
    Uses ray-casting (even-odd rule).
    """
    inside = np.zeros(len(qx), dtype=bool)
    n = len(poly_x)
    j = n - 1
    for i in range(n):
        xi, yi = poly_x[i], poly_y[i]
        xj, yj = poly_x[j], poly_y[j]

        cross_y = (yi > qy) != (yj > qy)
        # x coordinate of edge at query y
        denom   = (yj - yi)
        safe_d  = np.where(np.abs(denom) < 1e-12, 1e-12, denom)
        edge_x  = (xj - xi) * (qy - yi) / safe_d + xi
        cross_x = qx < edge_x

        inside ^= (cross_y & cross_x)
        j = i

    return inside


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def build_surface_model(page_entry: dict) -> dict:
    page_name = page_entry["page"]

    existing_pts = np.array(page_entry["existing_points"], dtype=float)  # (N, 3)
    proposed_pts = np.array(page_entry["proposed_points"],  dtype=float)  # (M, 3)
    lod_raw      = page_entry.get("lod_boundary", [])

    if len(existing_pts) == 0 or len(proposed_pts) == 0:
        missing = []
        if len(existing_pts) == 0: missing.append("existing")
        if len(proposed_pts) == 0: missing.append("proposed")
        print(f"  ERROR: missing {' and '.join(missing)} contour points — cannot reconstruct.")
        sys.exit(1)

    print(f"  Existing: {len(existing_pts)} pts  "
          f"z=[{existing_pts[:,2].min():.0f}, {existing_pts[:,2].max():.0f}] ft")
    print(f"  Proposed: {len(proposed_pts)} pts  "
          f"z=[{proposed_pts[:,2].min():.0f}, {proposed_pts[:,2].max():.0f}] ft")

    # LOD boundary polygon
    if len(lod_raw) >= 3:
        lod = np.array(lod_raw, dtype=float)
        # Ensure closed
        if not np.allclose(lod[0], lod[-1], atol=1.0):
            lod = np.vstack([lod, lod[0]])
        poly_x, poly_y = lod[:, 0], lod[:, 1]
        use_lod = True
        print(f"  LOD boundary: {len(lod)} vertices")
    else:
        print("  Warning: no LOD boundary — using point cloud bounding box")
        use_lod = False

    # Grid bounding box from LOD boundary (or all points if no LOD)
    if use_lod:
        x0 = float(poly_x.min())
        y0 = float(poly_y.min())
        x1 = float(poly_x.max())
        y1 = float(poly_y.max())
    else:
        all_xy = np.vstack([existing_pts[:, :2], proposed_pts[:, :2]])
        x0, y0 = all_xy.min(axis=0)
        x1, y1 = all_xy.max(axis=0)

    res = GRID_RESOLUTION_FT
    nx  = max(1, math.ceil((x1 - x0) / res))
    ny  = max(1, math.ceil((y1 - y0) / res))
    print(f"  Grid: {nx} × {ny} = {nx*ny:,} cells at {res} ft resolution")

    # Grid cell centre coordinates (flat arrays)
    ix_arr = np.arange(nx)
    iy_arr = np.arange(ny)
    gx_row = x0 + (ix_arr + 0.5) * res   # (nx,)
    gy_col = y0 + (iy_arr + 0.5) * res   # (ny,)

    # Full flat arrays for all cells
    gy_all, gx_all = np.meshgrid(gy_col, gx_row, indexing="ij")  # (ny, nx)
    gx_flat = gx_all.ravel()
    gy_flat = gy_all.ravel()

    # LOD mask
    if use_lod:
        print("  Computing LOD mask ...")
        inside = pip_mask(gx_flat, gy_flat, poly_x, poly_y)
        n_inside = inside.sum()
        print(f"  {n_inside:,} of {nx*ny:,} cells inside LOD boundary")
    else:
        inside = np.ones(len(gx_flat), dtype=bool)

    # IDW interpolation
    print("  Interpolating existing surface ...")
    ex_flat = interpolate_surface(existing_pts, inside, gx_flat, gy_flat)

    print("  Interpolating proposed surface ...")
    pr_flat = interpolate_surface(proposed_pts, inside, gx_flat, gy_flat)

    # Reshape to (ny, nx) and convert to nested lists (None for NaN)
    ex_grid = ex_flat.reshape(ny, nx)
    pr_grid = pr_flat.reshape(ny, nx)

    def to_list(grid: np.ndarray) -> list:
        rows = []
        for row in grid:
            rows.append([
                round(float(v), 2) if not math.isnan(v) else None
                for v in row
            ])
        return rows

    return {
        "page":               page_name,
        "grid_resolution_ft": res,
        "origin_ft":          [round(x0, 3), round(y0, 3)],
        "grid_nx":            nx,
        "grid_ny":            ny,
        "existing_surface":   to_list(ex_grid),
        "proposed_surface":   to_list(pr_grid),
        "point_counts": {
            "existing": len(existing_pts),
            "proposed": len(proposed_pts),
        },
    }


def main():
    if not LABELED_CONTOURS.exists():
        raise FileNotFoundError(
            f"Missing {LABELED_CONTOURS}. Run label_contours.py first."
        )

    pages = json.loads(LABELED_CONTOURS.read_text())

    results = []
    for entry in pages:
        print(f"\nReconstructing surface for {entry['page']} ...")
        result = build_surface_model(entry)
        results.append(result)

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
