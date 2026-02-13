# main.py

import base64
import os
from pathlib import Path
from openai import OpenAI
from PIL import Image
from dotenv import load_dotenv

# ---------- LOAD ENV ----------
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

# ---------- CONFIG ----------
OPENAI_MODEL = "gpt-4.1-mini"
IMAGE_PATH = "input/site_plan.png"
TILES_DIR = "tiles"
TILE_SIZE = 1024
OVERLAP = 128
MAX_TILES = os.getenv("MAX_TILES")  # optional, for low-power testing

# ---------- CLIENT ----------
client = OpenAI()

# ---------- IMAGE HELPERS ----------
def encode_image_to_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"

def tile_image(image_path: str, output_dir: str, tile_size: int, overlap: int):
    img = Image.open(image_path)
    width, height = img.size

    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    tiles = []
    step = tile_size - overlap

    for y in range(0, height, step):
        for x in range(0, width, step):
            tile = img.crop((x, y, x + tile_size, y + tile_size))
            tile_path = output_path / f"tile_{x}_{y}.png"
            tile.save(tile_path)
            tiles.append(tile_path)

    return tiles

# ---------- OPENAI ANALYSIS ----------
def analyze_tile(tile_path: Path) -> dict:
    import json

    image_data_url = encode_image_to_data_url(tile_path)

    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
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
                            "- Only set cut or fill info if tile_class is grading.\n"
                            "- Use null where information is not visible.\n"
                            "- No prose, no markdown, JSON only."
                        ),
                    },
                    {
                        "type": "input_image",
                        "image_url": image_data_url,
                    },
                ],
            }
        ],
    )

    return json.loads(response.output_text)

# ---------- MAIN ----------
if __name__ == "__main__":
    import json

    if not Path(IMAGE_PATH).exists():
        raise FileNotFoundError(f"Image not found: {IMAGE_PATH}")

    tiles = tile_image(IMAGE_PATH, TILES_DIR, TILE_SIZE, OVERLAP)

    if MAX_TILES:
        tiles = tiles[: int(MAX_TILES)]
        print(f"Limiting run to first {len(tiles)} tiles (MAX_TILES)")

    results = []

    for tile in tiles:
        print(f"Analyzing {tile.name}")
        tile_result = analyze_tile(tile)
        tile_result["tile_id"] = tile.stem
        results.append(tile_result)

    output_path = Path("outputs")
    output_path.mkdir(exist_ok=True)

    with open(output_path / "tiles.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Wrote outputs/tiles.json")
