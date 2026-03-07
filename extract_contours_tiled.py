"""extract_contours_tiled.py

Divides the page 2 (existing conditions) image into a grid of smaller tiles
and sends each tile to the Vision API independently.  At drawing scale 1"=400',
elevation labels are ~7 px tall in a 2048-px full-page render; tiling brings
them up to ~21-31 px where the model can read them.

Outputs: outputs/contours_tiled.json  (same schema as contours.json but one
entry per tile with an added tile_origin_px field for coordinate back-conversion)
"""

import base64
import io
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image

BASE_DIR = Path(__file__).parent
INPUT_IMAGE = BASE_DIR / "outputs" / "grading_pages.json"   # re-use to get path
PAGE_SCALE_FILE = BASE_DIR / "outputs" / "page_scale.json"
OUTPUT_FILE = BASE_DIR / "outputs" / "contours_tiled.json"

# ------ tunable parameters ------
TILE_COLS = 4           # columns across the drawing area
TILE_ROWS = 3           # rows
TITLE_BLOCK_FRAC = 0.83 # fraction of page width that is drawing (rest is title block)
OVERLAP_PX = 200        # overlap between adjacent tiles (px in original image space)
MAX_RENDER_PX = 2048
# --------------------------------

load_dotenv(BASE_DIR / ".env")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


PROMPT = """
You are analyzing a TILE cut from a civil engineering existing-conditions grading plan.
The tile shows topographic contour lines at roughly 10-foot intervals (likely 520, 530,
540, 550, 560 ft range).

Your task: extract every elevation label visible in this tile.

Rules:
1. Report the elevation value as a plain number (e.g. 540).
2. Report its pixel (x, y) position within THIS tile image.
3. Classify as "existing" (thin/dashed contour) or "proposed" (thick/bold contour) or "spot".
4. Set confidence 0.9 if clearly legible, 0.6 if uncertain, 0.3 if guessing.
5. IGNORE text in the title block, notes, or legend areas — only report labels on contour lines.
6. If no labels are visible, return an empty elevation_readings list.

Return ONLY valid JSON, no markdown:
{
  "contour_interval_ft": <number or null>,
  "elevation_readings": [
    {"elevation_ft": <number>, "x_px": <int>, "y_px": <int>, "type": "existing"|"proposed"|"spot", "confidence": <float>}
  ],
  "assumptions": [<string>, ...]
}
"""


def image_to_data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def resize_to_max(img: Image.Image, max_px: int) -> tuple[Image.Image, float]:
    w, h = img.size
    longest = max(w, h)
    if longest <= max_px:
        return img, 1.0
    factor = max_px / longest
    new_w = round(w * factor)
    new_h = round(h * factor)
    return img.resize((new_w, new_h), Image.LANCZOS), factor


def clean_json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            inner = parts[1]
            lines = inner.split("\n", 1)
            if len(lines) == 2 and not lines[0].strip().startswith("{"):
                inner = lines[1]
            text = inner
    return text.strip()


def query_tile(client: OpenAI, tile_img: Image.Image) -> dict:
    """Send one tile to the Vision API, return parsed JSON."""
    render_img, sf = resize_to_max(tile_img, MAX_RENDER_PX)
    resp = client.responses.create(
        model=MODEL,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": PROMPT},
                {"type": "input_image", "image_url": image_to_data_url(render_img)},
            ],
        }],
    )
    raw = ""
    for item in resp.output:
        if hasattr(item, "content"):
            for c in item.content:
                if getattr(c, "type", None) == "output_text":
                    raw += c.text
    raw = raw.strip()
    cleaned = clean_json_text(raw) if raw else ""
    if not cleaned:
        return {"contour_interval_ft": None, "elevation_readings": [], "assumptions": ["No response"],
                "render_scale": sf}
    try:
        data = json.loads(cleaned)
        data["render_scale"] = sf
        return data
    except json.JSONDecodeError as exc:
        return {"contour_interval_ft": None, "elevation_readings": [],
                "assumptions": [f"JSON parse error: {exc}"], "render_scale": sf}


def best_fpp(scale_entries: list) -> tuple[float | None, int | None]:
    best = None
    best_conf = -1.0
    ref_width = None
    for entry in scale_entries:
        pw_px = entry.get("page_width_px")
        for bar in entry.get("scale_bars", []):
            fpp = bar.get("feet_per_pixel")
            conf = bar.get("confidence", 0.0)
            if fpp and conf > best_conf:
                best = fpp
                best_conf = conf
                ref_width = pw_px
    return best, ref_width


def main():
    grading_pages = json.loads(INPUT_IMAGE.read_text())
    if not grading_pages:
        print("No pages in grading_pages.json")
        return

    scale_entries = []
    if PAGE_SCALE_FILE.exists():
        scale_entries = json.loads(PAGE_SCALE_FILE.read_text())

    fpp_ref, ref_width_px = best_fpp(scale_entries)
    print(f"Best scale: fpp_ref={fpp_ref}, ref_width_px={ref_width_px}")

    page = grading_pages[0]
    image_path = page["path"]
    print(f"Loading {page['file']} ...")
    img = Image.open(image_path)
    orig_w, orig_h = img.size
    print(f"  Image size: {orig_w}×{orig_h} px")

    # Correct fpp for actual image width vs calibration image width
    fpp = fpp_ref
    if fpp_ref is not None and ref_width_px and orig_w != ref_width_px:
        fpp = fpp_ref * (ref_width_px / orig_w)
        print(f"  DPI correction: {fpp_ref:.6f} -> {fpp:.6f} ft/px")

    # Drawing area: exclude title block on the right
    draw_w = round(orig_w * TITLE_BLOCK_FRAC)
    draw_h = orig_h
    print(f"  Drawing area: {draw_w}×{draw_h} px (title block excluded)")

    # Tile dimensions
    tile_w_base = draw_w // TILE_COLS
    tile_h_base = draw_h // TILE_ROWS

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    results = []
    tile_num = 0

    for row in range(TILE_ROWS):
        for col in range(TILE_COLS):
            tile_num += 1
            x0 = max(0, col * tile_w_base - OVERLAP_PX)
            y0 = max(0, row * tile_h_base - OVERLAP_PX)
            x1 = min(draw_w, (col + 1) * tile_w_base + OVERLAP_PX)
            y1 = min(draw_h, (row + 1) * tile_h_base + OVERLAP_PX)

            tile_img = img.crop((x0, y0, x1, y1))
            tile_pixel_w, tile_pixel_h = tile_img.size

            print(f"  Tile {tile_num}/{TILE_COLS * TILE_ROWS} (row={row} col={col}) "
                  f"origin=({x0},{y0}) size={tile_pixel_w}×{tile_pixel_h} ...", end=" ", flush=True)

            data = query_tile(client, tile_img)
            n = len(data.get("elevation_readings", []))
            print(f"{n} reading(s)")

            # Back-convert tile pixel coords → original image pixel coords
            render_scale = data.pop("render_scale", 1.0)
            for reading in data.get("elevation_readings", []):
                # tile render-space → tile original-space → full image space
                tx_orig = reading["x_px"] / render_scale
                ty_orig = reading["y_px"] / render_scale
                reading["x_px_original"] = round(x0 + tx_orig)
                reading["y_px_original"] = round(y0 + ty_orig)
                # Convert to feet (origin = top-left of original image)
                reading["x_ft"] = (x0 + tx_orig) * fpp if fpp else None
                reading["y_ft"] = (y0 + ty_orig) * fpp if fpp else None

            results.append({
                "tile": tile_num,
                "row": row,
                "col": col,
                "tile_origin_px": [x0, y0],
                "tile_size_px": [tile_pixel_w, tile_pixel_h],
                "render_scale": render_scale,
                "feet_per_pixel_original": fpp,
                **data,
            })

    # Summary
    all_readings = [r for tile in results for r in tile.get("elevation_readings", [])]
    print(f"\nTotal: {len(all_readings)} elevation readings from {len(results)} tiles")
    by_elev: dict[float, int] = {}
    for r in all_readings:
        e = r["elevation_ft"]
        by_elev[e] = by_elev.get(e, 0) + 1
    if by_elev:
        print("  Elevation counts:", dict(sorted(by_elev.items())))

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
