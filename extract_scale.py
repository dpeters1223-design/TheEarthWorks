# extract_scale.py
# Phase 3 scale extraction
# Extract scale bars anywhere on each PDF page and return feet per pixel plus bar bounding box
# Output is a per page list of scale bar candidates so later takeoff features can select the nearest scale

import json
import base64
import io
import os
from pathlib import Path

from pdf2image import convert_from_path
from PIL import Image
from dotenv import load_dotenv
from openai import OpenAI

PDF_PATH = Path("input/site_plan.pdf")
OUT_DIR = Path("outputs")
OUT_JSON = OUT_DIR / "page_scale.json"

DPI = 200
POPPLER_PATH = "/opt/local/bin"
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

def image_to_data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64}"

def extract_text(resp) -> str:
    texts = []
    for item in resp.output:
        if hasattr(item, "content"):
            for c in item.content:
                if getattr(c, "type", None) == "output_text":
                    texts.append(c.text)
    return "\n".join(texts).strip()

def clean_json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
    return text.strip()

def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None

def compute_feet_per_pixel(bar_feet_length, bar_pixel_length):
    if bar_feet_length is None or bar_pixel_length is None:
        return None
    if bar_pixel_length <= 0:
        return None
    return bar_feet_length / bar_pixel_length

def analyze_page(client: OpenAI, img: Image.Image, page_num: int) -> dict:
    width, height = img.size

    prompt = (
        "You are analyzing a full page from a civil plan set.\n"
        "Detect graphic scale bars. A scale bar is typically a segmented horizontal bar with labels like 0, 120', 240' or 0, 20, 40.\n"
        "The scale bar can appear anywhere on the page near the bottom of a drawing viewport.\n\n"
        "Return ONLY valid JSON.\n"
        "Return this schema exactly:\n"
        "{\n"
        "  \"scale_bars\": [\n"
        "    {\n"
        "      \"bar_detected\": true,\n"
        "      \"bar_pixel_length\": <number>,\n"
        "      \"bar_feet_length\": <number>,\n"
        "      \"bar_bbox\": {\"x1\": <number>, \"y1\": <number>, \"x2\": <number>, \"y2\": <number>},\n"
        "      \"confidence\": <number>,\n"
        "      \"assumptions\": [<string>, ...]\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Notes:\n"
        "bar_bbox is the bounding box around the visible scale bar itself in pixel coordinates on the full page image.\n"
        "If no scale bars exist, return scale_bars as an empty list.\n"
        "If there are multiple scale bars, include them all.\n"
    )

    resp = client.responses.create(
        model=MODEL,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": image_to_data_url(img)},
            ],
        }],
    )

    raw = extract_text(resp)
    cleaned = clean_json_text(raw) if raw else ""

    base = {
        "page": f"page_{page_num:03d}.png",
        "page_width_px": width,
        "page_height_px": height,
        "scale_bars": [],
        "assumptions": []
    }

    if not cleaned:
        base["assumptions"] = ["Model returned no parsable text"]
        return base

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        base["assumptions"] = ["Model response was not valid JSON", cleaned[:200]]
        return base

    bars = data.get("scale_bars", [])
    if not isinstance(bars, list):
        base["assumptions"] = ["scale_bars was not a list"]
        return base

    normalized = []
    for b in bars:
        if not isinstance(b, dict):
            continue

        bar_detected = bool(b.get("bar_detected", False))
        bar_pixel_length = safe_float(b.get("bar_pixel_length"))
        bar_feet_length = safe_float(b.get("bar_feet_length"))

        bbox = b.get("bar_bbox", {}) or {}
        x1 = safe_float(bbox.get("x1"))
        y1 = safe_float(bbox.get("y1"))
        x2 = safe_float(bbox.get("x2"))
        y2 = safe_float(bbox.get("y2"))

        conf = safe_float(b.get("confidence"))
        if conf is None:
            conf = 0.0

        fpp = compute_feet_per_pixel(bar_feet_length, bar_pixel_length)

        normalized.append({
            "bar_detected": bar_detected,
            "bar_pixel_length": bar_pixel_length,
            "bar_feet_length": bar_feet_length,
            "feet_per_pixel": round(fpp, 6) if fpp else None,
            "bar_bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
            "confidence": conf,
            "assumptions": b.get("assumptions", [])
        })

    base["scale_bars"] = normalized
    return base

def main():
    load_dotenv()

    if not PDF_PATH.exists():
        raise FileNotFoundError("input/site_plan.pdf not found")

    OUT_DIR.mkdir(exist_ok=True)

    print("Rendering PDF pages for scale extraction...")
    pages = convert_from_path(PDF_PATH, dpi=DPI, poppler_path=POPPLER_PATH)

    client = OpenAI()
    results = []

    for i, page_img in enumerate(pages, start=1):
        print(f"Analyzing scale bars on page {i}")
        results.append(analyze_page(client, page_img, i))

    OUT_JSON.write_text(json.dumps(results, indent=2))
    print(f"Wrote {OUT_JSON}")

if __name__ == "__main__":
    main()
