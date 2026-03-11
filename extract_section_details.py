"""extract_section_details.py

Reads DETAILS sheet(s) — tiles the page and asks Vision to read cross-section
layer stacks (cap system cross sections, typical sections, etc.).

Extracts each layer name and thickness from dimension annotations on the drawings.

Output: outputs/section_details.json
"""

import base64
import io
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image

BASE_DIR         = Path(__file__).parent
SHEET_CLASS_FILE = BASE_DIR / "outputs" / "sheet_classification.json"
OUTPUT_FILE      = BASE_DIR / "outputs" / "section_details.json"
INPUT_DIR        = BASE_DIR / "Input"

DETAILS_TYPES = {"DETAILS"}

# Tile the detail sheets at this resolution for closer reads
MAX_RENDER_PX = 2048
TILE_SIZE     = 1024
TILE_OVERLAP  = 128

load_dotenv(BASE_DIR / ".env")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
MODEL = os.getenv("OLLAMA_MODEL", "gemma3:27b")


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def image_to_data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def resize_to_max(img: Image.Image, max_px: int) -> Image.Image:
    w, h = img.size
    longest = max(w, h)
    if longest <= max_px:
        return img
    factor = max_px / longest
    return img.resize((round(w * factor), round(h * factor)), Image.LANCZOS)


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


def make_tiles(img: Image.Image, tile_size: int, overlap: int) -> list:
    """Return list of (tile_img, col, row, x_off, y_off)."""
    w, h = img.size
    tiles = []
    y = 0
    row = 0
    while y < h:
        x = 0
        col = 0
        while x < w:
            x1 = x
            y1 = y
            x2 = min(x + tile_size, w)
            y2 = min(y + tile_size, h)
            tile = img.crop((x1, y1, x2, y2))
            tiles.append((tile, col, row, x1, y1))
            col += 1
            x += tile_size - overlap
            if x >= w:
                break
        row += 1
        y += tile_size - overlap
        if y >= h:
            break
    return tiles


# --------------------------------------------------
# Vision prompt
# --------------------------------------------------

PROMPT = """
You are analyzing a civil engineering construction detail or cross-section drawing.

Your task: find any CROSS SECTION or TYPICAL SECTION diagram that shows stacked material layers
(e.g. a cap system cross section, closure section, or soil layering diagram).

For each cross section found:
1. Note the section title (e.g. "CAP CROSS SECTION", "TYPICAL CLOSURE SECTION", "CAP SYSTEM DETAIL")
2. List every material layer shown, reading from TOP to BOTTOM:
   - Layer name (e.g. "Vegetative Support Layer", "Infiltration Layer", "Intermediate Cover",
     "Geomembrane Liner", "Gas Collection Layer", "Drainage Layer", "Subgrade")
   - Thickness annotation if shown (look for dimension arrows with labels like "6\"", "18 IN",
     "1.5 FT", "450mm", etc.)
3. Note any area or quantity callouts (e.g. "229,476 SF", "14,202 SF") if present near the section.

Scan the ENTIRE image — sections may be in any corner or orientation.

Return ONLY valid JSON — no markdown fences, no text outside the object:
{
  "sections_found": [
    {
      "section_title": "<title or 'Unnamed Section'>",
      "layers": [
        {
          "name": "<layer name>",
          "thickness_in": <number in inches, or null if not dimensioned>,
          "thickness_note": "<exact dimension text seen, or null>"
        }
      ],
      "area_callout_sf": <number or null>,
      "area_callout_note": "<exact text or null>"
    }
  ],
  "assumptions": ["<note>", ...]
}

If no cross-section is visible, return sections_found as an empty array.
"""


# --------------------------------------------------
# Per-tile extraction
# --------------------------------------------------

def extract_tile_sections(client: OpenAI, tile: Image.Image,
                          page_name: str, tile_label: str) -> list:
    """Return list of section dicts found in this tile."""
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": image_to_data_url(tile)}},
            ],
        }],
    )

    raw = (resp.choices[0].message.content or "").strip()

    if not raw:
        return []

    cleaned = clean_json_text(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return []

    sections = data.get("sections_found", [])
    for s in sections:
        s["source_page"] = page_name
        s["source_tile"] = tile_label
    return sections


# --------------------------------------------------
# Per-page extraction
# --------------------------------------------------

def extract_page_sections(client: OpenAI, image_path: str, page_name: str) -> list:
    img = Image.open(image_path)

    # Try full-page first (downscaled)
    render_img = resize_to_max(img, MAX_RENDER_PX)
    print(f"  Full-page scan ({render_img.size[0]}x{render_img.size[1]}) ...")
    sections = extract_tile_sections(client, render_img, page_name, "full_page")
    print(f"  -> {len(sections)} section(s) found")

    # Also tile for closer reads (cross sections may have small annotations)
    tiles = make_tiles(render_img, TILE_SIZE, TILE_OVERLAP)
    print(f"  Tiling into {len(tiles)} tiles ...")
    for tile_img, col, row, x_off, y_off in tiles:
        label = f"tile_{row}_{col}"
        tile_sections = extract_tile_sections(client, tile_img, page_name, label)
        if tile_sections:
            print(f"    {label}: {len(tile_sections)} section(s)")
            sections.extend(tile_sections)

    return sections


# --------------------------------------------------
# Deduplicate sections
# --------------------------------------------------

def deduplicate_sections(all_sections: list) -> list:
    """Keep unique sections by title; prefer those with more layers dimensioned."""
    by_title = {}
    for s in all_sections:
        title = (s.get("section_title") or "Unnamed Section").strip().upper()
        layers = s.get("layers", [])
        dimensioned = sum(1 for L in layers if L.get("thickness_in") is not None)

        if title not in by_title:
            by_title[title] = s
        else:
            existing_dim = sum(
                1 for L in by_title[title].get("layers", [])
                if L.get("thickness_in") is not None
            )
            if dimensioned > existing_dim:
                by_title[title] = s

    return list(by_title.values())


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():
    if not SHEET_CLASS_FILE.exists():
        raise FileNotFoundError(
            f"Missing {SHEET_CLASS_FILE}. Run classify_sheets.py first."
        )

    all_sheets = json.loads(SHEET_CLASS_FILE.read_text())
    detail_pages = [
        {"file": s["file"], "path": str(INPUT_DIR / s["file"])}
        for s in all_sheets
        if s.get("sheet_type") in DETAILS_TYPES
    ]

    if not detail_pages:
        print("No DETAILS sheets found in sheet_classification.json.")
        OUTPUT_FILE.parent.mkdir(exist_ok=True)
        OUTPUT_FILE.write_text(json.dumps([], indent=2))
        return

    print(f"Scanning {len(detail_pages)} DETAILS page(s) for cross-section layer stacks ...\n")

    client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")

    all_sections = []
    for idx, page in enumerate(detail_pages):
        print(f"[{idx + 1}/{len(detail_pages)}] {page['file']}")
        try:
            sections = extract_page_sections(client, page["path"], page["file"])
            all_sections.extend(sections)
        except Exception as exc:
            print(f"  ERROR: {exc}")

    unique_sections = deduplicate_sections(all_sections)

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(unique_sections, indent=2))
    print(f"\nWrote {OUTPUT_FILE}")

    print(f"\n--- Summary: {len(unique_sections)} unique section(s) ---")
    for s in unique_sections:
        print(f"  {s.get('section_title')} ({s.get('source_page')})")
        for L in s.get("layers", []):
            depth = f"{L.get('thickness_in')} in" if L.get("thickness_in") else "not dimensioned"
            print(f"    {L.get('name')}: {depth}")


if __name__ == "__main__":
    main()
