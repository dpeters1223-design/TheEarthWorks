# EarthWorksTest/main.py

import base64
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
def analyze_tile(tile_path: Path) -> str:
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
                            "Analyze this portion of a civil site grading plan. "
                            "Identify cut vs fill areas, contour spacing, "
                            "and estimate average depth differences if visible. "
                            "State assumptions clearly."
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

    return response.output_text

# ---------- MAIN ----------
if __name__ == "__main__":
    if not Path(IMAGE_PATH).exists():
        raise FileNotFoundError(f"Image not found: {IMAGE_PATH}")

    tiles = tile_image(IMAGE_PATH, TILES_DIR, TILE_SIZE, OVERLAP)
    print(f"\nGenerated {len(tiles)} tiles\n")

    for tile in tiles:
        print(f"\n--- ANALYZING {tile.name} ---\n")
        print(analyze_tile(tile))
