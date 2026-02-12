# EarthWorksTest/tiling.py

from PIL import Image
from pathlib import Path

def tile_image(
    image_path: str,
    output_dir: str = "tiles",
    tile_size: int = 1024,
    overlap: int = 128
):
    """
    Split image into overlapping tiles for better vision analysis.
    """
    img = Image.open(image_path)
    width, height = img.size

    Path(output_dir).mkdir(exist_ok=True)

    tiles = []
    step = tile_size - overlap

    for y in range(0, height, step):
        for x in range(0, width, step):
            box = (x, y, x + tile_size, y + tile_size)
            tile = img.crop(box)

            tile_name = f"tile_{x}_{y}.png"
            tile_path = Path(output_dir) / tile_name
            tile.save(tile_path)

            tiles.append(tile_path)

    return tiles
