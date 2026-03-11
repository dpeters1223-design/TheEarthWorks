import os
import json
import base64
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv


# --------------------------------------------------
# PATH SETUP
# --------------------------------------------------

BASE_DIR = Path(__file__).parent
INPUT_DIR = BASE_DIR / "Input"
OUTPUT_FILE = BASE_DIR / "outputs" / "sheet_classification.json"


# --------------------------------------------------
# LOAD ENV
# --------------------------------------------------

load_dotenv(BASE_DIR / ".env")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# --------------------------------------------------
# CLASSIFY FUNCTION
# --------------------------------------------------

def classify_page(image_path):

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    data_url = f"data:image/png;base64,{image_b64}"

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text":
                        """
Classify this civil engineering plan sheet by reading the sheet title, title block, and drawing content.

Return ONLY JSON (no markdown fences):
{
  "sheet_type": "<TYPE>",
  "confidence": 0.0 to 1.0
}

Sheet types — choose the most specific match:
  EXISTING_CONDITIONS_PLAN  - shows existing / pre-construction topography or site conditions
  BASE_GRADING_PLAN         - shows subgrade or intermediate grading (before cap or final surface layers)
  FINAL_GRADING_PLAN        - shows the finished / proposed grade after all construction
  SITE_GRADING_PLAN         - generic grading plan where existing and proposed are both on one sheet
  EROSION_CONTROL_PLAN      - erosion and sediment control
  SEDIMENT_CONTROL_PLAN     - sediment or stormwater control
  DETAILS                   - construction details, sections, or typical sections
  TITLE_SHEET               - cover sheet, general notes, index, or legend
  GENERAL_NOTES             - sheet primarily containing general notes, specifications, or construction requirements (text-heavy, may include material layer specs, stripping depth, seeding notes)
  GEOTECH_SUMMARY           - geotechnical recommendations table or summary page (soil borings, bearing capacity, material classifications)
  OTHER                     - anything else
"""
                    },
                    {
                        "type": "input_image",
                        "image_url": data_url
                    }
                ]
            }
        ]
    )

    text = response.output_text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            inner = parts[1]
            lines = inner.split("\n", 1)
            text = lines[1] if len(lines) == 2 and not lines[0].strip().startswith("{") else inner
        text = text.strip()

    try:
        return json.loads(text)
    except Exception:
        raise Exception(f"Invalid JSON returned:\n{text}")


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():

    if not INPUT_DIR.exists():
        print("Input folder missing")
        return

    image_files = list(INPUT_DIR.glob("*.png"))

    print(f"Found {len(image_files)} images\n")

    results = []

    for image_path in image_files:

        try:

            result = classify_page(image_path)

            results.append({
                "file": image_path.name,
                "sheet_type": result["sheet_type"],
                "confidence": result["confidence"]
            })

            print(f"{image_path.name} -> {result}")

        except Exception as e:

            print(f"\nERROR processing {image_path.name}")
            print(e)

            results.append({
                "file": image_path.name,
                "sheet_type": "ERROR",
                "confidence": 0.0
            })

    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nSaved -> {OUTPUT_FILE}")


# --------------------------------------------------

if __name__ == "__main__":
    main()
