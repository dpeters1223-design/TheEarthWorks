# inject_depth.py
import json
import sys
from pathlib import Path

INFILE = Path("outputs/features_with_scale.json")
CONFIG = Path("config/depth_rules.json")
OUTFILE = Path("outputs/features_with_depth.json")


with open(INFILE) as f:
    features = json.load(f)

with open(CONFIG) as f:
    depth_rules = json.load(f)

out = []

for ftr in features:
    ftr_out = ftr.copy()
    ftype = ftr["feature_type"]

    # feature-specific depth already exists
    if "depth" in ftr:
        out.append(ftr_out)
        continue

    # feature-type rule
    rule = depth_rules.get(ftype)

    if rule:
        ftr_out["depth"] = {
            "min_ft": rule["min_ft"],
            "max_ft": rule["max_ft"],
            "source": "type_default",
            "confidence": rule.get("confidence", 0.5),
        }
        out.append(ftr_out)
        continue

    # no depth available
    ftr_out["depth"] = None
    ftr_out["depth_status"] = "unresolved"
    out.append(ftr_out)

with open(OUTFILE, "w") as f:
    json.dump(out, f, indent=2)

print(f"Depth injection complete → {OUTFILE}")
