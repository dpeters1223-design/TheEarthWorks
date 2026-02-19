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
MAX_INTERP_DIST_FT   = 300   # cells farther than this from any sample point → null
                              # prevents wild extrapolation into data-sparse zones


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


def nearest_dist(gx: np.ndarray, gy: np.ndarray,
                 sx: np.ndarray, sy: np.ndarray) -> np.ndarray:
    """Return distance (ft) from each grid point to its nearest sample point."""
    result = np.empty(len(gx))
    for start in range(0, len(gx), CHUNK_SIZE):
        end = min(start + CHUNK_SIZE, len(gx))
        dx  = gx[start:end, np.newaxis] - sx[np.newaxis, :]
        dy  = gy[start:end, np.newaxis] - sy[np.newaxis, :]
        result[start:end] = np.sqrt((dx*dx + dy*dy).min(axis=1))
    return result


def interpolate_surface(sample_pts: np.ndarray,
                        inside_mask: np.ndarray,
                        gx_all: np.ndarray,
                        gy_all: np.ndarray) -> np.ndarray:
    """
    Interpolate for grid points inside the LOD boundary AND within
    MAX_INTERP_DIST_FT of a sample point.
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

    # Mask out cells that are too far from any sample point
    near_dist = nearest_dist(gx_in, gy_in, sx, sy)
    in_range  = near_dist <= MAX_INTERP_DIST_FT
    n_dropped = int((~in_range).sum())
    if n_dropped:
        print(f"    {n_dropped:,} cells beyond {MAX_INTERP_DIST_FT} ft — set to null")
    inside_idx = inside_idx[in_range]
    gx_in = gx_in[in_range]
    gy_in = gy_in[in_range]

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


def filter_by_range(pts: np.ndarray, z_min: float, z_max: float, label: str) -> np.ndarray:
    """Remove points whose elevation falls outside [z_min, z_max]."""
    keep = (pts[:, 2] >= z_min) & (pts[:, 2] <= z_max)
    n_removed = int((~keep).sum())
    if n_removed > 0:
        print(f"  Range filter ({label}): removed {n_removed} points "
              f"outside z=[{z_min:.1f}, {z_max:.1f}] ft")
    return pts[keep]


def lod_covers_site(lod: list, all_pts: np.ndarray, min_fraction: float = 0.25) -> bool:
    """
    Return True only if the LOD boundary bounding box covers at least
    min_fraction of the point-cloud bounding box in both x and y.

    This guards against picking up small annotation elements (title block
    borders, callout boxes) as the LOD boundary.
    """
    if len(lod) < 3 or len(all_pts) == 0:
        return False
    lod_arr = np.array(lod, dtype=float)
    pts_dx  = float(all_pts[:, 0].max() - all_pts[:, 0].min())
    pts_dy  = float(all_pts[:, 1].max() - all_pts[:, 1].min())
    lod_dx  = float(lod_arr[:, 0].max() - lod_arr[:, 0].min())
    lod_dy  = float(lod_arr[:, 1].max() - lod_arr[:, 1].min())
    if pts_dx < 1 or pts_dy < 1:
        return True  # degenerate point cloud — accept whatever we have
    return (lod_dx / pts_dx) >= min_fraction and (lod_dy / pts_dy) >= min_fraction


def main():
    if not LABELED_CONTOURS.exists():
        raise FileNotFoundError(
            f"Missing {LABELED_CONTOURS}. Run label_contours.py first."
        )

    pages = json.loads(LABELED_CONTOURS.read_text())

    # Aggregate existing and proposed points across all pages.
    # Each page sheet type determines whether its contours are existing or proposed.
    # A page may contribute to only one surface (e.g. EXISTING_CONDITIONS_PLAN),
    # so we merge across pages to get both surfaces for the full site.
    all_existing: list = []
    all_proposed: list = []
    lod_candidates: list[list] = []   # collect all non-empty LOD polygons for validation
    page_names: list[str] = []

    for page in pages:
        page_names.append(page["page"])
        ex = page.get("existing_points", [])
        pr = page.get("proposed_points", [])
        if ex:
            all_existing.extend(ex)
        if pr:
            all_proposed.extend(pr)
        lod = page.get("lod_boundary", [])
        if len(lod) >= 3:
            lod_candidates.append(lod)

    print(f"Aggregated from {len(pages)} page(s):")
    print(f"  Raw existing points : {len(all_existing)}")
    print(f"  Raw proposed points : {len(all_proposed)}")

    # --- Cross-surface elevation filtering -----------------------------------
    # Remove existing points that fall far outside the proposed elevation range.
    # This eliminates scale-bar numbers and other annotation text that were
    # mis-identified as elevation labels on the existing conditions sheet.
    CROSS_SURFACE_TOLERANCE_FT = 50.0

    if all_existing and all_proposed:
        pr_arr = np.array(all_proposed, dtype=float)
        pr_z_min = float(pr_arr[:, 2].min())
        pr_z_max = float(pr_arr[:, 2].max())
        ex_arr = np.array(all_existing, dtype=float)
        ex_arr = filter_by_range(
            ex_arr,
            pr_z_min - CROSS_SURFACE_TOLERANCE_FT,
            pr_z_max + CROSS_SURFACE_TOLERANCE_FT,
            "existing (cross-surface)"
        )
        all_existing = ex_arr.tolist()

    print(f"  Filtered existing   : {len(all_existing)}")

    # --- LOD boundary validation ---------------------------------------------
    # Use the first LOD polygon whose bounding box covers at least 25 % of the
    # combined point-cloud extent.  Tiny polygons (e.g. title block borders)
    # that were mis-classified as LOD are discarded.
    lod_boundary: list = []
    all_pts_arr = np.array(all_existing + all_proposed, dtype=float) if (all_existing or all_proposed) else np.empty((0, 3))

    for lod in lod_candidates:
        if lod_covers_site(lod, all_pts_arr):
            lod_boundary = lod
            print(f"  LOD boundary: accepted polygon with {len(lod)} vertices")
            break
        else:
            lod_arr = np.array(lod, dtype=float)
            print(f"  LOD boundary: rejected polygon with {len(lod)} vertices "
                  f"(extent {lod_arr[:,0].max()-lod_arr[:,0].min():.0f}x"
                  f"{lod_arr[:,1].max()-lod_arr[:,1].min():.0f} ft — too small)")

    if not lod_boundary:
        print("  LOD boundary: none valid — will use point cloud bounding box")

    combined_name = page_names[0] if len(page_names) == 1 else "combined"
    combined = {
        "page":            combined_name,
        "existing_points": all_existing,
        "proposed_points": all_proposed,
        "lod_boundary":    lod_boundary,
    }

    print(f"\nReconstructing surface ...")
    result = build_surface_model(combined)

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    # Wrap in a list for compatibility with compute_cut_fill.py which iterates pages
    OUTPUT_FILE.write_text(json.dumps([result], indent=2))
    print(f"\nWrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
