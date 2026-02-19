# extract_scale.py
# Detects graphic scale bars on every grading page via OpenAI Vision.
# Uses PyMuPDF to render pages (no poppler dependency).
# Page naming matches the new pipeline: {stem}_page_N.png
#
# Reads:  outputs/sheet_classification.json  (to limit to grading pages)
# Output: outputs/page_scale.json

import base64
import io
import json
import os
import re
from pathlib import Path

import fitz
from dotenv import load_dotenv
from openai import OpenAI

BASE_DIR   = Path(__file__).parent
INPUT_DIR  = BASE_DIR / "Input"
SHEET_FILE = BASE_DIR / "outputs" / "sheet_classification.json"
OUT_FILE   = BASE_DIR / "outputs" / "page_scale.json"

DPI   = 200
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

GRADING_TYPES = {
    "SITE_GRADING_PLAN", "GRADING_PLAN",
    "EXISTING_CONDITIONS_PLAN",
    "BASE_GRADING_PLAN",
    "FINAL_GRADING_PLAN",
}

load_dotenv(BASE_DIR / ".env")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def image_to_data_url(pix: fitz.Pixmap) -> str:
    buf = io.BytesIO(pix.tobytes("png"))
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


def parse_page_number(filename: str):
    m = re.search(r"_page_(\d+)\.png$", filename, re.IGNORECASE)
    if m:
        return filename[:m.start()], int(m.group(1))
    return Path(filename).stem, 1


def find_pdf(stem: str) -> Path:
    for ext in (".pdf", ".PDF"):
        p = INPUT_DIR / (stem + ext)
        if p.exists():
            return p
    raise FileNotFoundError(f"Cannot find {stem}.pdf in {INPUT_DIR}/")


def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None


def clean_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            lines = text.split("\n", 1)
            if len(lines) == 2 and not lines[0].strip().startswith("{"):
                text = lines[1]
    return text.strip()


PROMPT = """You are analyzing a civil engineering plan sheet.
Find all graphic scale bars. A scale bar is a segmented horizontal bar with
numeric labels like "0  120  240" or "0  50  100" — usually near the bottom
of a drawing viewport.

Return ONLY valid JSON, no markdown fences:
{
  "scale_bars": [
    {
      "bar_detected": true,
      "bar_pixel_length": <number>,
      "bar_feet_length": <number>,
      "bar_bbox": {"x1": <n>, "y1": <n>, "x2": <n>, "y2": <n>},
      "confidence": <0.0–1.0>,
      "assumptions": ["..."]
    }
  ]
}

If no scale bar is visible, return scale_bars as an empty list.
If there are multiple scale bars, include them all.
Pixel coordinates are in the full page image you received."""


def analyze_page(client: OpenAI, pix: fitz.Pixmap, file_name: str) -> dict:
    base = {
        "page": file_name,
        "page_width_px":  pix.width,
        "page_height_px": pix.height,
        "scale_bars": [],
        "assumptions": [],
    }

    resp = client.responses.create(
        model=MODEL,
        input=[{"role": "user", "content": [
            {"type": "input_text",  "text": PROMPT},
            {"type": "input_image", "image_url": image_to_data_url(pix)},
        ]}],
    )

    raw = ""
    for item in resp.output:
        if hasattr(item, "content"):
            for c in item.content:
                if getattr(c, "type", None) == "output_text":
                    raw += c.text
    raw = clean_json(raw.strip())
    if not raw:
        base["assumptions"] = ["Model returned no parsable text"]
        return base

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        base["assumptions"] = [f"JSON parse error: {exc}", raw[:200]]
        return base

    bars = []
    for b in (data.get("scale_bars") or []):
        bpl  = safe_float(b.get("bar_pixel_length"))
        bfl  = safe_float(b.get("bar_feet_length"))
        fpp  = (bfl / bpl) if (bpl and bfl and bpl > 0) else None
        bbox = b.get("bar_bbox") or {}
        bars.append({
            "bar_detected":    bool(b.get("bar_detected", False)),
            "bar_pixel_length": bpl,
            "bar_feet_length":  bfl,
            "feet_per_pixel":   round(fpp, 6) if fpp else None,
            "bar_bbox": {
                "x1": safe_float(bbox.get("x1")),
                "y1": safe_float(bbox.get("y1")),
                "x2": safe_float(bbox.get("x2")),
                "y2": safe_float(bbox.get("y2")),
            },
            "confidence": safe_float(b.get("confidence")) or 0.0,
            "assumptions": b.get("assumptions", []),
        })

    base["scale_bars"] = bars
    return base


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    if not SHEET_FILE.exists():
        raise FileNotFoundError(f"Missing {SHEET_FILE}. Run classify_sheets.py first.")

    classifications = json.loads(SHEET_FILE.read_text())
    grading_entries = [
        e for e in classifications
        if e.get("sheet_type") in GRADING_TYPES and e.get("confidence", 0) >= 0.5
    ]

    if not grading_entries:
        print("No grading pages found — running scale extraction on all pages.")
        grading_entries = classifications   # fallback: process everything

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # Group by PDF stem so each PDF is opened once
    by_pdf: dict[str, list] = {}
    for entry in grading_entries:
        stem, page_num = parse_page_number(entry["file"])
        by_pdf.setdefault(stem, []).append((page_num, entry["file"]))

    mat = fitz.Matrix(DPI / 72, DPI / 72)
    results = []

    for stem, pages in by_pdf.items():
        pdf_path = find_pdf(stem)
        print(f"Opening {pdf_path.name} ...")
        doc = fitz.open(str(pdf_path))

        for page_num, file_name in sorted(pages):
            idx = page_num - 1
            if idx < 0 or idx >= doc.page_count:
                print(f"  Page {page_num} out of range — skipping")
                continue
            print(f"  [page {page_num}] {file_name} — detecting scale bar ...")
            pix    = doc[idx].get_pixmap(matrix=mat)
            result = analyze_page(client, pix, file_name)
            n_bars = len([b for b in result["scale_bars"] if b.get("bar_detected")])
            best   = next((b["feet_per_pixel"] for b in result["scale_bars"]
                           if b.get("feet_per_pixel")), None)
            print(f"    {n_bars} scale bar(s) found"
                  + (f", best fpp={best:.6f}" if best else ""))
            results.append(result)

        doc.close()

    OUT_FILE.parent.mkdir(exist_ok=True)
    OUT_FILE.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {OUT_FILE}")


if __name__ == "__main__":
    main()
