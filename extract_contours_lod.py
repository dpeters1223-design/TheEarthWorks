"""extract_contours_lod.py

Fine-grained Vision API tile pass targeting the LOD region of the
existing conditions page (page 2).  Uses 600x600 px tiles so elevation
labels are rendered at full resolution (no downscaling) instead of being
shrunk to ~4px tall by the whole-page 2048-px resize.

Reads:   Input/<page2>.png  (from grading_pages.json[0])
         outputs/lod_boundary.json  (for the crop region)
         outputs/page_scale.json    (for fpp)
Outputs: outputs/contours_lod.json  (same schema as contours_tiled.json)
"""

import base64, io, json, os
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image

BASE_DIR        = Path(__file__).parent
GRADING_PAGES   = BASE_DIR / "outputs" / "grading_pages.json"
PAGE_SCALE_FILE = BASE_DIR / "outputs" / "page_scale.json"
LOD_FILE        = BASE_DIR / "outputs" / "lod_boundary.json"
OUTPUT_FILE     = BASE_DIR / "outputs" / "contours_lod.json"

TILE_PX   = 600   # tile side in original image pixels (renders 1:1 — labels are full size)
OVERLAP   = 100   # overlap between tiles (px)
MARGIN    = 200   # extra pixels beyond LOD bbox to capture edge labels

load_dotenv(BASE_DIR / ".env")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

PROMPT = """You are analyzing a SMALL TILE from a civil engineering existing-conditions grading plan.
The tile shows topographic contour lines — look for any numeric elevation labels (likely 520, 530,
540, 550, or 560 ft range).

Rules:
1. Report every numeric label you can read, even if faint or partially clipped.
2. Report its pixel (x, y) within THIS tile image.
3. Type: "existing" (thin/dashed line) or "spot" (isolated marker).
4. Confidence: 0.9 clearly legible, 0.6 uncertain, 0.3 guessing.
5. IGNORE title block, notes, legend text — only labels ON contour lines in the drawing.
6. If none visible, return empty list.

Return ONLY valid JSON, no markdown:
{
  "contour_interval_ft": <number or null>,
  "elevation_readings": [
    {"elevation_ft": <number>, "x_px": <int>, "y_px": <int>, "type": "existing"|"spot", "confidence": <float>}
  ],
  "assumptions": [<string>]
}"""


def to_data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def query(client: OpenAI, tile: Image.Image) -> dict:
    resp = client.responses.create(
        model=MODEL,
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": PROMPT},
            {"type": "input_image", "image_url": to_data_url(tile)},
        ]}],
    )
    raw = "".join(
        c.text for item in resp.output if hasattr(item, "content")
        for c in item.content if getattr(c, "type", None) == "output_text"
    ).strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].split("\n", 1)[-1]
    try:
        return json.loads(raw.strip())
    except Exception as e:
        return {"contour_interval_ft": None, "elevation_readings": [], "assumptions": [f"parse error: {e}"]}


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
    grading_pages = json.loads(GRADING_PAGES.read_text())
    page = grading_pages[0]
    image_path = page["path"]

    scale_entries = json.loads(PAGE_SCALE_FILE.read_text()) if PAGE_SCALE_FILE.exists() else []
    fpp_ref, ref_w = best_fpp(scale_entries)

    img = Image.open(image_path)
    orig_w, orig_h = img.size
    fpp = fpp_ref * (ref_w / orig_w) if fpp_ref and ref_w and orig_w != ref_w else fpp_ref
    print(f"Image: {orig_w}x{orig_h} px, fpp={fpp:.6f} ft/px")

    # LOD bbox in pixel space
    lod_data = json.loads(LOD_FILE.read_text())
    verts_ft = lod_data.get("vertices_ft", [])
    if not verts_ft:
        # fall back to full drawing area
        rx0, ry0, rx1, ry1 = 0, 0, orig_w, orig_h
    else:
        xs = [v[0] for v in verts_ft]
        ys = [v[1] for v in verts_ft]
        rx0 = max(0, int(min(xs)/fpp) - MARGIN)
        ry0 = max(0, int(min(ys)/fpp) - MARGIN)
        rx1 = min(orig_w, int(max(xs)/fpp) + MARGIN)
        ry1 = min(orig_h, int(max(ys)/fpp) + MARGIN)

    print(f"Targeting region: px x=[{rx0},{rx1}], y=[{ry0},{ry1}] "
          f"({rx1-rx0}x{ry1-ry0} px = {(rx1-rx0)*fpp:.0f}x{(ry1-ry0)*fpp:.0f} ft)")

    step = TILE_PX - OVERLAP
    xs_starts = list(range(rx0, rx1, step))
    ys_starts = list(range(ry0, ry1, step))
    total = len(xs_starts) * len(ys_starts)
    print(f"Tiles: {len(xs_starts)} cols x {len(ys_starts)} rows = {total} tiles ({TILE_PX}px, overlap={OVERLAP}px)")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    results = []
    n = 0
    for y0 in ys_starts:
        for x0 in xs_starts:
            n += 1
            x1 = min(orig_w, x0 + TILE_PX)
            y1 = min(orig_h, y0 + TILE_PX)
            tile = img.crop((x0, y0, x1, y1))
            print(f"  [{n}/{total}] origin=({x0},{y0}) ...", end=" ", flush=True)

            data = query(client, tile)
            readings = data.get("elevation_readings", [])
            print(f"{len(readings)} readings")

            # Back-project to original image space and feet
            for r in readings:
                r["x_px_original"] = x0 + r["x_px"]
                r["y_px_original"] = y0 + r["y_px"]
                r["x_ft"] = (x0 + r["x_px"]) * fpp if fpp else None
                r["y_ft"] = (y0 + r["y_px"]) * fpp if fpp else None

            results.append({
                "tile": n, "tile_origin_px": [x0, y0], "tile_size_px": [x1-x0, y1-y0],
                "feet_per_pixel": fpp, **data,
            })

    all_readings = [r for tile in results for r in tile.get("elevation_readings", [])]
    print(f"\nTotal: {len(all_readings)} elevation readings")
    by_z: dict = {}
    for r in all_readings:
        z = r["elevation_ft"]
        by_z[z] = by_z.get(z, 0) + 1
    if by_z:
        print("Elevation counts:", dict(sorted(by_z.items())))

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(results, indent=2))
    print(f"Wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
