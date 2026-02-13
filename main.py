#!/usr/bin/env python3
"""
main.py

Tile-level AI interpretation.

Input:
- tiles/*.png   (must already exist; created by tiling.py)

Output:
- outputs/tiles.json

Responsibilities:
- Read tiles
- Call OpenAI vision model
- Emit structured, auditable JSON
"""

import base64
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

# ---------- LOAD ENV ----------
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

# ---------- CONFIG ----------
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
TILES_DIR = Path("tiles")
OUT_DIR = Path("outputs")
OUT_JSON = OUT_DIR / "tiles.json"
MAX_TILES = os.getenv("MAX_TILES")  # optional dev throttle

# ---------- CLIENT ----------
client = OpenAI()

# ---------- HELPERS ----------
def encode_image_to_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"

def analyze_tile(tile_path: Path) -> dict:
    image_data_url = encode_image_to_data_url(tile_path)

    prompt = (
        "Analyze this tile from a civil site plan and respond ONLY with valid JSON.\n\n"
        "Schema:\n"
        "{\n"
        '  "tile_id": string,\n'
        '  "tile_class": one of ["grading","legend","title_block","empty","non_grading"],\n'
        '  "contour_interval": string or null,\n'
        '  "cut_present": boolean,\n'
        '  "fill_present": boolean,\n'
        '  "cut_depth_estimate_ft": [number, number] or null,\n'
        '  "fill_depth_estimate_ft": [number, number] or null,\n'
        '  "confidence": number between 0 and 1,\n'
        '  "assumptions": array of strings\n'
        "}\n\n"
        "Rules:\n"
        "- Use tile_class to describe what this tile primarily contains.\n"
        "- Only set cut/fill/interval/depth if tile_class is grading.\n"
        "- Use null where information is not visible.\n"
        "- No prose. No markdown. JSON only."
    )

    response = client.responses.create(
        model=MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": image_data_url},
                ],
            }
        ],
    )

    return json.loads(response.output_text)

# ---------- MAIN ----------
def main():
    if not TILES_DIR.exists():
        raise FileNotFoundError("tiles/ directory not found. Run tiling.py first.")

    tiles = sorted(TILES_DIR.glob("*.png"))
    if not tiles:
        raise FileNotFoundError("No tiles found in tiles/")

    if MAX_TILES:
        tiles = tiles[: int(MAX_TILES)]
        print(f"Limiting to first {len(tiles)} tiles (MAX_TILES)")

    OUT_DIR.mkdir(exist_ok=True)

    results = []

    for tile in tiles:
        print(f"Analyzing {tile.name}")
        try:
            result = analyze_tile(tile)
            # Force stable tile_id (filename stem)
            result["tile_id"] = tile.stem
            results.append(result)
        except Exception as e:
            # Safe failure: emit explicit error tile
            results.append({
                "tile_id": tile.stem,
                "tile_class": "error",
                "contour_interval": None,
                "cut_present": False,
                "fill_present": False,
                "cut_depth_estimate_ft": None,
                "fill_depth_estimate_ft": None,
                "confidence": 0.0,
                "assumptions": [f"Analysis failed: {type(e).__name__}: {e}"],
            })

    OUT_JSON.write_text(json.dumps(results, indent=2))
    print(f"Wrote {OUT_JSON} ({len(results)} tiles)")

if __name__ == "__main__":
    main()
