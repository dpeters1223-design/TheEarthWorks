# validate_scale_lock.py
import json
import sys
from pathlib import Path

INFILE = Path("outputs/features_with_scale.json")

with open(INFILE) as f:
    features = json.load(f)

unresolved = [
    f for f in features
    if f.get("scale_status") != "resolved"
]

if unresolved:
    print("❌ SCALE LOCK FAILURE")
    print(f"{len(unresolved)} features missing scale. Quantity math is BLOCKED.")
    for f in unresolved[:5]:
        print(f"- Feature ID: {f.get('id')} | Page: {f.get('page')}")
    sys.exit(1)

print("✅ All features have resolved scales. Safe to proceed.")
sys.exit(0)
