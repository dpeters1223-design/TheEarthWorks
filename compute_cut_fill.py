"""compute_cut_fill.py

Reads outputs/surface_model.json and computes cut/fill volumes by differencing
existing and proposed terrain surfaces cell by cell.

    diff = existing_elevation - proposed_elevation
    cut  += cell_area_sqft * max(0,  diff) / 27   (cubic yards)
    fill += cell_area_sqft * max(0, -diff) / 27   (cubic yards)

Output: outputs/site_quantities.json
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).parent
SURFACE_MODEL_FILE = BASE_DIR / "outputs" / "surface_model.json"
OUTPUT_FILE = BASE_DIR / "outputs" / "site_quantities.json"

CUBIC_FEET_PER_CY = 27.0


def compute_quantities(page_entry: dict) -> dict:
    resolution_ft = page_entry["grid_resolution_ft"]
    cell_area_sqft = resolution_ft ** 2

    existing = page_entry["existing_surface"]
    proposed = page_entry["proposed_surface"]
    ny = page_entry["grid_ny"]
    nx = page_entry["grid_nx"]

    total_cut_cf = 0.0
    total_fill_cf = 0.0
    cells_computed = 0
    cells_undetermined = 0
    cells_skipped = 0

    for iy in range(ny):
        for ix in range(nx):
            e = existing[iy][ix]
            p = proposed[iy][ix]

            if e is None and p is None:
                cells_skipped += 1
                continue

            if e is None or p is None:
                cells_undetermined += 1
                continue

            diff = e - p
            if diff > 0:
                total_cut_cf += cell_area_sqft * diff
            elif diff < 0:
                total_fill_cf += cell_area_sqft * (-diff)

            cells_computed += 1

    total_cut_cy = round(total_cut_cf / CUBIC_FEET_PER_CY, 1)
    total_fill_cy = round(total_fill_cf / CUBIC_FEET_PER_CY, 1)
    net_cy = round(total_cut_cy - total_fill_cy, 1)
    net_type = "cut" if net_cy >= 0 else "fill"

    return {
        "page": page_entry["page"],
        "total_cut_cy": total_cut_cy,
        "total_fill_cy": total_fill_cy,
        "net_cy": abs(net_cy),
        "net_type": net_type,
        "cells_computed": cells_computed,
        "cells_undetermined": cells_undetermined,
        "cells_skipped": cells_skipped,
        "grid_resolution_ft": resolution_ft,
    }


def main():
    if not SURFACE_MODEL_FILE.exists():
        raise FileNotFoundError(f"Missing {SURFACE_MODEL_FILE}. Run reconstruct_surface.py first.")

    surface_data = json.loads(SURFACE_MODEL_FILE.read_text())

    results = []
    for entry in surface_data:
        page = entry.get("page", "unknown")
        print(f"Computing cut/fill for {page} ...")
        result = compute_quantities(entry)
        results.append(result)
        print(
            f"  cut={result['total_cut_cy']:,.1f} cy  "
            f"fill={result['total_fill_cy']:,.1f} cy  "
            f"net={result['net_cy']:,.1f} cy ({result['net_type']})  "
            f"cells computed={result['cells_computed']}  "
            f"undetermined={result['cells_undetermined']}"
        )

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
