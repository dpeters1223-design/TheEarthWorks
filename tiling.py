# EarthWorksTest/tiling.py

from PIL import Image
from pathlib import Path

TILE_SIZE = 1024
OVERLAP = 128

PAGES_DIR = Path("pages")
OUT_DIR = Path("tiles")

def tile_image(
    image_path: Path,
    output_dir: Path,
    tile_size: int,
    overlap: int,
    prefix: str,
):
    img = Image.open(image_path).convert("RGB")
    width, height = img.size

    output_dir.mkdir(exist_ok=True)

    tiles = []
    step = tile_size - overlap

    for y in range(0, height, step):
        for x in range(0, width, step):
            box = (x, y, x + tile_size, y + tile_size)
            tile = img.crop(box)

            tile_name = f"{prefix}tile_{x}_{y}.png"
            tile_path = output_dir / tile_name
            tile.save(tile_path)

            tiles.append(tile_path)

    return tiles

def main():
    page_files = sorted(PAGES_DIR.glob("page_*.png"))
    if not page_files:
        raise FileNotFoundError("No page_*.png files found in pages/")

    total = 0
    for page in page_files:
        prefix = page.stem + "__"
        tiles = tile_image(
            image_path=page,
            output_dir=OUT_DIR,
            tile_size=TILE_SIZE,
            overlap=OVERLAP,
            prefix=prefix,
        )
        total += len(tiles)

    print(f"Tiled {len(page_files)} pages into {total} tiles")

if __name__ == "__main__":
    main()
