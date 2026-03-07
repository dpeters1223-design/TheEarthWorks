"""extract_spot_elevations.py

Tiles the base grading plan page and asks the Vision API to find spot
elevation pairs (existing grade / proposed grade) at the same point.
These are sub-contour-interval accuracy markers that can be used to
compute cut/fill earthwork even when the depth is smaller than the
contour interval.

Reads:   Input/<page3>.png  (BASE_GRADING_PLAN from sheet_classification.json)
         outputs/lod_boundary.json  (for crop region)
         outputs/page_scale.json    (for fpp)
Outputs: outputs/spot_elevations.json
         outputs/spot_cut_fill.json  (cut/fill computed from pairs)
"""

import base64, io, json, math, os
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image

BASE_DIR         = Path(__file__).parent
SHEET_CLASS_FILE = BASE_DIR / "outputs" / "sheet_classification.json"
PAGE_SCALE_FILE  = BASE_DIR / "outputs" / "page_scale.json"
LOD_FILE         = BASE_DIR / "outputs" / "lod_boundary.json"
OUTPUT_SPOTS     = BASE_DIR / "outputs" / "spot_elevations.json"
OUTPUT_CUTFILL   = BASE_DIR / "outputs" / "spot_cut_fill.json"

TILE_PX       = 1200  # tile side in original image px — labels render at full size
OVERLAP       = 200   # overlap between tiles
TITLE_BLOCK   = 0.83  # fraction of page width that is drawing (rest is title block)
FULL_DRAWING  = True  # True = search full drawing area; False = LOD region + MARGIN only
MARGIN        = 300   # extra px around LOD bbox (only used when FULL_DRAWING=False)

TARGET_SHEET_TYPES = {"BASE_GRADING_PLAN", "FINAL_GRADING_PLAN", "SITE_GRADING_PLAN", "GRADING_PLAN"}

load_dotenv(BASE_DIR / ".env")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

PROMPT = """You are analyzing a TILE from a civil engineering grading plan.

Your goal: find SPOT ELEVATIONS — specific grade points marked on the drawing
with small symbols (cross "+", "x", circle "○", triangle "△", or dot "·").

Spot elevations appear in two ways on grading plans:
  A) PAIRED: existing grade stacked above proposed grade at the same marker:
        EX. 547.32          (existing, above)
        PR. 546.00          (proposed, below)
     Or shown as:  "547.32" on top  /  "546.00" on bottom

  B) SINGLE: just one value (existing OR proposed), near a marker symbol.
     Often the existing grade is in parentheses: (547.32) or dashed box.
     The proposed grade may have no decoration.

For each spot elevation you find:
1. Record pixel (x, y) of the marker symbol within THIS tile.
2. Record existing_elev_ft (the pre-construction grade, or null if not shown).
3. Record proposed_elev_ft (the post-construction grade, or null if not shown).
4. Set confidence: 0.9 if both values clearly legible, 0.6 if one is uncertain.
5. IGNORE contour line labels (numbers along a line) — only isolated grade points.
6. IGNORE title block text, notes, or legend numbers.

Expected elevation range for this project: 520–570 ft.

Return ONLY valid JSON, no markdown:
{
  "spot_elevations": [
    {
      "x_px": <int>,
      "y_px": <int>,
      "existing_elev_ft": <float or null>,
      "proposed_elev_ft": <float or null>,
      "confidence": <float>
    }
  ],
  "assumptions": [<string>]
}
"""


def to_data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def query(client: OpenAI, tile: Image.Image) -> dict:
    resp = client.responses.create(
        model=MODEL,
        input=[{"role": "user", "content": [
            {"type": "input_text",  "text": PROMPT},
            {"type": "input_image", "image_url": to_data_url(tile)},
        ]}],
    )
    raw = "".join(
        c.text for item in resp.output if hasattr(item, "content")
        for c in item.content if getattr(c, "type", None) == "output_text"
    ).strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        inner = parts[1] if len(parts) >= 2 else raw
        lines = inner.split("\n", 1)
        raw = lines[1] if len(lines) == 2 and not lines[0].strip().startswith("{") else inner
    try:
        return json.loads(raw.strip())
    except Exception as e:
        return {"spot_elevations": [], "assumptions": [f"parse error: {e}"]}


def best_fpp(scale_entries):
    best, best_conf, ref_w = None, -1.0, None
    for entry in scale_entries:
        for bar in entry.get("scale_bars", []):
            if bar.get("feet_per_pixel", 0) and bar.get("confidence", 0) > best_conf:
                best = bar["feet_per_pixel"]
                best_conf = bar["confidence"]
                ref_w = entry.get("page_width_px")
    return best, ref_w


def main():
    sheets = json.loads(SHEET_CLASS_FILE.read_text())
    target = next(
        (s for s in sheets if s.get("sheet_type") in TARGET_SHEET_TYPES),
        None
    )
    if not target:
        print(f"No sheet with type in {TARGET_SHEET_TYPES} found.")
        return

    image_path = BASE_DIR / "Input" / target["file"]
    print(f"Target page: {target['file']} ({target['sheet_type']})")

    scale_entries = json.loads(PAGE_SCALE_FILE.read_text()) if PAGE_SCALE_FILE.exists() else []
    fpp_ref, ref_w = best_fpp(scale_entries)

    img = Image.open(image_path)
    orig_w, orig_h = img.size
    fpp = fpp_ref * (ref_w / orig_w) if fpp_ref and ref_w and orig_w != ref_w else fpp_ref
    print(f"Image: {orig_w}x{orig_h} px, fpp={fpp:.6f} ft/px")

    # Search region in pixel space
    lod_data = json.loads(LOD_FILE.read_text()) if LOD_FILE.exists() else {}
    verts_ft = lod_data.get("vertices_ft", [])
    if FULL_DRAWING or not verts_ft or not fpp:
        # Full drawing area excluding title block
        rx0, ry0 = 0, 0
        rx1 = round(orig_w * TITLE_BLOCK)
        ry1 = orig_h
    else:
        xs = [v[0] for v in verts_ft]
        ys = [v[1] for v in verts_ft]
        rx0 = max(0, int(min(xs) / fpp) - MARGIN)
        ry0 = max(0, int(min(ys) / fpp) - MARGIN)
        rx1 = min(orig_w, int(max(xs) / fpp) + MARGIN)
        ry1 = min(orig_h, int(max(ys) / fpp) + MARGIN)

    print(f"Search region: px x=[{rx0},{rx1}], y=[{ry0},{ry1}] "
          f"({(rx1-rx0)*fpp:.0f}x{(ry1-ry0)*fpp:.0f} ft)")

    step = TILE_PX - OVERLAP
    xs_starts = list(range(rx0, rx1, step))
    ys_starts = list(range(ry0, ry1, step))
    total = len(xs_starts) * len(ys_starts)
    print(f"Tiles: {len(xs_starts)} cols x {len(ys_starts)} rows = {total} "
          f"({TILE_PX}px, overlap={OVERLAP}px)")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    tile_results = []
    n = 0

    for y0 in ys_starts:
        for x0 in xs_starts:
            n += 1
            x1 = min(orig_w, x0 + TILE_PX)
            y1 = min(orig_h, y0 + TILE_PX)
            tile = img.crop((x0, y0, x1, y1))
            print(f"  [{n}/{total}] origin=({x0},{y0}) ...", end=" ", flush=True)

            data = query(client, tile)
            spots = data.get("spot_elevations", [])
            paired = [s for s in spots if s.get("existing_elev_ft") and s.get("proposed_elev_ft")]
            print(f"{len(spots)} spots ({len(paired)} paired)")

            # Back-project to original image space and feet
            for s in spots:
                s["x_px_original"] = x0 + s["x_px"]
                s["y_px_original"] = y0 + s["y_px"]
                s["x_ft"] = (x0 + s["x_px"]) * fpp if fpp else None
                s["y_ft"] = (y0 + s["y_px"]) * fpp if fpp else None

            tile_results.append({
                "tile": n, "tile_origin_px": [x0, y0], "tile_size_px": [x1-x0, y1-y0], **data
            })

    # Flatten all spots
    all_spots = [s for tile in tile_results for s in tile.get("spot_elevations", [])]
    paired_spots = [s for s in all_spots
                    if s.get("existing_elev_ft") is not None and s.get("proposed_elev_ft") is not None]

    print(f"\nTotal: {len(all_spots)} spots, {len(paired_spots)} paired (both ex + pr)")

    # Deduplicate by proximity (within 50 ft → same physical point)
    deduped = []
    DEDUP_DIST_FT = 50.0
    for s in paired_spots:
        sx, sy = s.get("x_ft") or 0, s.get("y_ft") or 0
        is_dup = any(
            math.hypot(sx - d["x_ft"], sy - d["y_ft"]) < DEDUP_DIST_FT
            for d in deduped
            if d.get("x_ft") and d.get("y_ft")
        )
        if not is_dup:
            deduped.append(s)

    print(f"After dedup (within {DEDUP_DIST_FT} ft): {len(deduped)} unique paired spots")

    # Compute cut/fill from pairs
    cuts, fills = [], []
    for s in deduped:
        ex = s["existing_elev_ft"]
        pr = s["proposed_elev_ft"]
        diff = ex - pr   # positive → cut (remove material), negative → fill (add material)
        if diff > 0:
            cuts.append(diff)
        elif diff < 0:
            fills.append(-diff)

    avg_cut_depth  = sum(cuts)  / len(cuts)  if cuts  else 0.0
    avg_fill_depth = sum(fills) / len(fills) if fills else 0.0

    # LOD area from lod_boundary.json
    lod_area_sf = lod_data.get("area_sq_ft") or 0.0
    if not lod_area_sf and verts_ft:
        # Approximate from bounding box if exact area not stored
        xs = [v[0] for v in verts_ft]
        ys = [v[1] for v in verts_ft]
        lod_area_sf = (max(xs) - min(xs)) * (max(ys) - min(ys))  # bbox approx

    # Use known cap area from the project (229,476 SF from engineer's estimate)
    # as the computation footprint, since the LOD (159 acres) is the full waste boundary
    CAP_AREA_SF = 229476.0

    est_cut_cy  = avg_cut_depth  * CAP_AREA_SF / 27.0
    est_fill_cy = avg_fill_depth * CAP_AREA_SF / 27.0

    print(f"\nSpot elevation summary:")
    print(f"  Cut  depth samples: {len(cuts)} (avg {avg_cut_depth:.2f} ft)")
    print(f"  Fill depth samples: {len(fills)} (avg {avg_fill_depth:.2f} ft)")
    print(f"  Using cap area: {CAP_AREA_SF:,.0f} SF")
    print(f"  Est cut : {est_cut_cy:,.0f} CY")
    print(f"  Est fill: {est_fill_cy:,.0f} CY")
    print(f"  Engineer: cut=7,054 CY, fill=161 CY")

    cutfill = {
        "method": "spot_elevation_avg_depth",
        "source_page": target["file"],
        "total_paired_spots": len(deduped),
        "cut_depth_samples": len(cuts),
        "fill_depth_samples": len(fills),
        "avg_cut_depth_ft": round(avg_cut_depth, 3),
        "avg_fill_depth_ft": round(avg_fill_depth, 3),
        "cap_area_sf": CAP_AREA_SF,
        "estimated_cut_cy": round(est_cut_cy, 1),
        "estimated_fill_cy": round(est_fill_cy, 1),
        "engineer_cut_cy": 7054,
        "engineer_fill_cy": 161,
        "spots": deduped,
    }

    OUTPUT_SPOTS.parent.mkdir(exist_ok=True)
    OUTPUT_SPOTS.write_text(json.dumps(tile_results, indent=2))
    OUTPUT_CUTFILL.write_text(json.dumps(cutfill, indent=2))
    print(f"\nWrote {OUTPUT_SPOTS}")
    print(f"Wrote {OUTPUT_CUTFILL}")


if __name__ == "__main__":
    main()
