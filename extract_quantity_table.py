"""extract_quantity_table.py

For each grading page in outputs/grading_pages.json, sends the full page image
to OpenAI Vision and extracts any printed earthwork quantity / schedule table,
returning cut CY and fill CY values.

Output: outputs/quantity_table.json
"""

import base64
import io
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image

BASE_DIR            = Path(__file__).parent
SHEET_CLASS_FILE    = BASE_DIR / "outputs" / "sheet_classification.json"
OUTPUT_FILE         = BASE_DIR / "outputs" / "quantity_table.json"
INPUT_DIR           = BASE_DIR / "Input"

# Sheet types likely to contain an earthwork quantity table
QUANTITY_SHEET_TYPES = {
    "BASE_GRADING_PLAN",
    "FINAL_GRADING_PLAN",
    "SITE_GRADING_PLAN",
    "GRADING_PLAN",
    "EXISTING_CONDITIONS_PLAN",
}

MAX_RENDER_PX = 2048  # resize longest edge to this before sending

load_dotenv(BASE_DIR / ".env")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


# --------------------------------------------------
# Helpers (shared with extract_contours.py pattern)
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
            lines = inner.split("\n", 1)
            if len(lines) == 2 and not lines[0].strip().startswith("{"):
                inner = lines[1]
            text = inner
    return text.strip()


# --------------------------------------------------
# Vision prompt
# --------------------------------------------------

PROMPT = """
You are analyzing a civil engineering grading plan sheet.

Your task: find any printed earthwork quantity table or "earthwork schedule" on this drawing.
These tables typically appear as a box or grid on the plan sheet (often in a corner or below
the title block) and contain rows like:

  "Unclassified Excavation (Cut)   7,054 CY"
  "Unclassified Embankment (Fill)    161 CY"
  "Net Cut" or "Net Fill"            xxx CY

Common column headers: ITEM / DESCRIPTION, QUANTITY, UNIT.
Common units: CY (cubic yards), BCY, LCY, CY Bank, CY Compacted.

Instructions:
1. Scan the ENTIRE image — the table may be small and located in a margin or title block area.
2. If you find a table, extract EVERY row and record the item description, quantity (number only,
   no commas), and unit.
3. Sum all cut-type rows into total_cut_cy and all fill-type rows into total_fill_cy.
   - "cut", "excavation", "removal", "export" → cut
   - "fill", "embankment", "import", "borrow" → fill
   - "net cut" / "net fill" rows → use as-is if individual rows are missing
4. If no quantity table is visible on this sheet, set table_found to false.

Return ONLY valid JSON — no markdown fences, no text outside the object:
{
  "table_found": true | false,
  "confidence": <0.0 to 1.0>,
  "quantities": [
    {"item": "<description>", "qty": <number>, "unit": "<unit>"},
    ...
  ],
  "total_cut_cy": <number or null>,
  "total_fill_cy": <number or null>,
  "assumptions": ["<note>", ...]
}
"""


# --------------------------------------------------
# Per-page extraction
# --------------------------------------------------

def extract_page_quantities(client: OpenAI, image_path: str) -> dict:
    img = Image.open(image_path)
    render_img, _ = resize_to_max(img, MAX_RENDER_PX)

    resp = client.responses.create(
        model=MODEL,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text",  "text": PROMPT},
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

    base = {
        "table_found": False,
        "confidence": 0.0,
        "quantities": [],
        "total_cut_cy": None,
        "total_fill_cy": None,
        "assumptions": [],
    }

    if not raw:
        base["assumptions"] = ["Model returned no text"]
        return base

    cleaned = clean_json_text(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        base["assumptions"] = [f"JSON parse error: {exc}", cleaned[:300]]
        return base

    base.update({
        "table_found":   data.get("table_found", False),
        "confidence":    data.get("confidence",  0.0),
        "quantities":    data.get("quantities",  []),
        "total_cut_cy":  data.get("total_cut_cy"),
        "total_fill_cy": data.get("total_fill_cy"),
        "assumptions":   data.get("assumptions", []),
    })
    return base


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():
    if not SHEET_CLASS_FILE.exists():
        raise FileNotFoundError(
            f"Missing {SHEET_CLASS_FILE}. Run classify_sheets.py first."
        )

    all_sheets = json.loads(SHEET_CLASS_FILE.read_text())
    grading_pages = [
        {"file": s["file"], "path": str(INPUT_DIR / s["file"])}
        for s in all_sheets
        if s.get("sheet_type") in QUANTITY_SHEET_TYPES
    ]
    if not grading_pages:
        print("No grading/terrain sheets found in sheet_classification.json.")
        return
    print(f"Scanning {len(grading_pages)} sheet(s) for quantity tables ...")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    results = []
    for idx, page in enumerate(grading_pages):
        image_path = page["path"]
        print(f"[{idx + 1}/{len(grading_pages)}] Scanning for quantity table: {page['file']} ...")

        try:
            result = extract_page_quantities(client, image_path)
            result["page"] = page["file"]
            if result["table_found"]:
                print(f"  Table found (confidence={result['confidence']:.2f}): "
                      f"cut={result['total_cut_cy']} CY, fill={result['total_fill_cy']} CY")
            else:
                print(f"  No table found on this page")
        except Exception as exc:
            print(f"  ERROR: {exc}")
            result = {
                "page":         page["file"],
                "table_found":  False,
                "confidence":   0.0,
                "quantities":   [],
                "total_cut_cy": None,
                "total_fill_cy": None,
                "assumptions":  [f"Processing error: {exc}"],
            }

        results.append(result)

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {OUTPUT_FILE}")

    # Print summary
    tables_found = [r for r in results if r.get("table_found")]
    if tables_found:
        total_cut  = sum(r["total_cut_cy"]  or 0 for r in tables_found)
        total_fill = sum(r["total_fill_cy"] or 0 for r in tables_found)
        print(f"\nSummary across {len(tables_found)} page(s) with tables:")
        print(f"  Total cut : {total_cut:,.0f} CY")
        print(f"  Total fill: {total_fill:,.0f} CY")
    else:
        print("\nNo quantity tables found on any grading page.")


if __name__ == "__main__":
    main()
