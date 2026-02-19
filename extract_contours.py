"""extract_contours.py

For each grading page in outputs/grading_pages.json, sends the full page image
to OpenAI Vision and extracts elevation readings (existing contours, proposed
contours, and spot elevations).

Scale association: positional match — grading page N (0-indexed) → page_scale.json entry N.

Output: outputs/contours.json
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
GRADING_PAGES_FILE = BASE_DIR / "outputs" / "grading_pages.json"
PAGE_SCALE_FILE = BASE_DIR / "outputs" / "page_scale.json"
OUTPUT_FILE = BASE_DIR / "outputs" / "contours.json"

MAX_RENDER_PX = 2048  # resize longest edge to this if image is larger

load_dotenv(BASE_DIR / ".env")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def image_to_data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def resize_to_max(img: Image.Image, max_px: int) -> tuple[Image.Image, float]:
    """Return (resized_image, scale_factor).  scale_factor = new / original."""
    w, h = img.size
    longest = max(w, h)
    if longest <= max_px:
        return img, 1.0
    factor = max_px / longest
    new_w = round(w * factor)
    new_h = round(h * factor)
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    return resized, factor


def clean_json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            inner = parts[1]
            # strip optional language tag on first line
            lines = inner.split("\n", 1)
            if len(lines) == 2 and not lines[0].strip().startswith("{"):
                inner = lines[1]
            text = inner
    return text.strip()


def pick_feet_per_pixel(scale_entries: list, page_index: int) -> tuple[float | None, int | None]:
    """Positional match: grading page N → page_scale.json entry N.

    Returns (feet_per_pixel, ref_width_px) where ref_width_px is the pixel width
    of the image on which the scale bar was measured.  The caller must apply a
    correction if the actual processing image has a different width:

        fpp_corrected = fpp_ref * (ref_width_px / actual_width_px)
    """
    if not scale_entries or page_index >= len(scale_entries):
        return None, None
    entry = scale_entries[page_index]
    ref_width = entry.get("page_width_px")
    bars = entry.get("scale_bars", [])
    best = None
    best_conf = -1.0
    for bar in bars:
        fpp = bar.get("feet_per_pixel")
        conf = bar.get("confidence", 0.0)
        if fpp and conf > best_conf:
            best = fpp
            best_conf = conf
    return best, ref_width


# --------------------------------------------------
# Vision call
# --------------------------------------------------

PROMPT = """
You are analyzing a civil engineering site grading plan. Your task is to extract elevation contour labels.

## Step 1 — Understand the drawing conventions
Civil grading plans show TWO sets of contours on the same sheet:
- EXISTING contours: the terrain BEFORE construction. Drawn with THIN or DASHED lines. Labels are often italic or smaller. May be prefixed "EX" or "(E)".
- PROPOSED contours: the terrain AFTER construction. Drawn with THICK/BOLD/HEAVY solid lines. Labels are often upright and larger. May be prefixed "PR", "P", or "(P)".
- SPOT ELEVATIONS: a single elevation point marked with a small "x", "+", triangle, or circle. Often shown as "1342.5" with a marker.

CRITICAL: Both sets of contours cover the SAME site and therefore MUST have elevations in the same general range (within ~10–20 ft of each other). If your existing readings cluster around 1340–1360 ft, your proposed readings should also be in roughly the same range, NOT 40+ ft different. A difference that large means you have misidentified the contour type.

## Step 2 — Extract every visible elevation label
For each numeric label you can read:
1. Record the elevation value in feet (just the number, e.g. 1344)
2. Record its pixel (x, y) location in THIS image
3. Classify it as "existing", "proposed", or "spot" based on the LINE STYLE of the contour it labels:
   - Thin / dashed line → "existing"
   - Thick / bold / heavy solid line → "proposed"
   - Isolated point marker (x, +, triangle) → "spot"
   - If you CANNOT confidently tell from line style, classify as "existing" (safer default)
4. Set confidence: 0.9 if line style is clearly distinguishable, 0.6 if uncertain, 0.3 if guessing

## Step 3 — Sanity check before returning
- Do your existing and proposed elevation ranges overlap or nearly overlap (within ~20 ft)?
- If NOT, you have likely misclassified some labels. Re-examine and correct the type field.
- Add a note to "assumptions" explaining how you distinguished the two types visually.

Return ONLY valid JSON — no markdown fences, no text outside the object:
{
  "contour_interval_ft": <number or null>,
  "elevation_readings": [
    {
      "elevation_ft": <number>,
      "x_px": <integer>,
      "y_px": <integer>,
      "type": "existing" | "proposed" | "spot",
      "confidence": <0.0 to 1.0>
    }
  ],
  "assumptions": [<string>, ...]
}

If no elevation data is visible, return elevation_readings as an empty list.
"""


def extract_page_contours(client: OpenAI, image_path: str, scale_factor: float) -> dict:
    img = Image.open(image_path)
    original_size = img.size

    render_img, sf = resize_to_max(img, MAX_RENDER_PX)
    render_size = render_img.size

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

    # extract text from response
    raw = ""
    for item in resp.output:
        if hasattr(item, "content"):
            for c in item.content:
                if getattr(c, "type", None) == "output_text":
                    raw += c.text
    raw = raw.strip()

    cleaned = clean_json_text(raw) if raw else ""

    base = {
        "original_size_px": list(original_size),
        "render_size_px": list(render_size),
        "scale_factor": round(sf, 6),
        "feet_per_pixel_original": scale_factor,
        "contour_interval_ft": None,
        "elevation_readings": [],
        "assumptions": [],
    }

    if not cleaned:
        base["assumptions"] = ["Model returned no parsable text"]
        return base

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        base["assumptions"] = [f"JSON parse error: {exc}", cleaned[:300]]
        return base

    base["contour_interval_ft"] = data.get("contour_interval_ft")
    base["elevation_readings"] = data.get("elevation_readings", [])
    base["assumptions"] = data.get("assumptions", [])
    return base


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():
    if not GRADING_PAGES_FILE.exists():
        raise FileNotFoundError(f"Missing {GRADING_PAGES_FILE}. Run grading_sheet_router.py first.")

    grading_pages = json.loads(GRADING_PAGES_FILE.read_text())
    if not grading_pages:
        print("No grading pages found. Nothing to process.")
        return

    scale_entries = []
    if PAGE_SCALE_FILE.exists():
        scale_entries = json.loads(PAGE_SCALE_FILE.read_text())
    else:
        print(f"Warning: {PAGE_SCALE_FILE} not found — feet_per_pixel will be null")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    results = []
    for idx, page in enumerate(grading_pages):
        image_path = page["path"]
        print(f"[{idx + 1}/{len(grading_pages)}] Extracting contours from {page['file']} ...")

        fpp_ref, ref_width_px = pick_feet_per_pixel(scale_entries, idx)

        # Correct feet_per_pixel for DPI differences between the scale-calibration
        # image (e.g. 200 DPI → 6800 px wide) and the actual processing image
        # (e.g. 300 DPI → 10200 px wide).  fpp scales linearly with image size:
        #   fpp_correct = fpp_ref * (ref_width_px / actual_width_px)
        fpp = fpp_ref
        if fpp_ref is not None and ref_width_px:
            from PIL import Image as _Image
            with _Image.open(image_path) as _img:
                actual_width_px = _img.width
            if actual_width_px != ref_width_px:
                correction = ref_width_px / actual_width_px
                fpp = fpp_ref * correction
                print(f"  DPI correction: ref={ref_width_px}px, actual={actual_width_px}px "
                      f"fpp {fpp_ref:.6f} -> {fpp:.6f} ft/px")

        if fpp is None:
            print(f"  Warning: no feet_per_pixel for page index {idx}, scale will be null")

        try:
            result = extract_page_contours(client, image_path, fpp)
            result["page"] = page["file"]
            n = len(result.get("elevation_readings", []))
            print(f"  Found {n} elevation reading(s), contour_interval={result.get('contour_interval_ft')} ft")
        except Exception as exc:
            print(f"  ERROR: {exc}")
            result = {
                "page": page["file"],
                "original_size_px": None,
                "render_size_px": None,
                "scale_factor": None,
                "feet_per_pixel_original": fpp,
                "contour_interval_ft": None,
                "elevation_readings": [],
                "assumptions": [f"Processing error: {exc}"],
            }

        results.append(result)

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
