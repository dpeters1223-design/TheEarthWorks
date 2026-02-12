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
                            "Analyze this portion of a civil site grading plan and respond ONLY with "
                            "valid JSON matching this schema:\n\n"
                            "{\n"
                            '  "tile_id": string,\n'
                            '  "contour_interval": string or null,\n'
                            '  "cut_present": boolean,\n'
                            '  "fill_present": boolean,\n'
                            '  "cut_depth_estimate_ft": [number, number] or null,\n'
                            '  "fill_depth_estimate_ft": [number, number] or null,\n'
                            '  "confidence": number between 0 and 1,\n'
                            '  "assumptions": array of strings\n'
                            "}\n\n"
                            "Do not include explanations, markdown, or extra text. "
                            "Use null where information is not visible."
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
    if not Path(IMAGE_PATH).exists():
        raise FileNotFoundError(f"Image not found: {IMAGE_PATH}")

    tiles = tile_image(IMAGE_PATH, TILES_DIR, TILE_SIZE, OVERLAP)
    print(f"Generated {len(tiles)} tiles")

    test_tile = tiles[0]
    result = analyze_tile(test_tile)
    print(result)
