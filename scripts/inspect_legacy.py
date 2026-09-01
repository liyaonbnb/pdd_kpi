import json, glob
from pathlib import Path
import pandas as pd
base = Path("/opt/pdd_bi_v2_test/legacy_full")
print("STORES")
stores = json.loads((base / "stores.json").read_text(encoding="utf-8"))
print(json.dumps({k: {"platform": v.get("platform", "pdd"), "name": v.get("name")} for k, v in list(stores.items())[:5]}, ensure_ascii=False))
print("total stores", len(stores))
print("\nCOSTS keys")
costs = json.loads((base / "costs.json").read_text(encoding="utf-8"))
print(list(costs.keys()))
print("global_merchant_costs samples", list(costs.get("global_merchant_costs", {}).items())[:3])
print("product_merchant_maps samples", list(costs.get("product_merchant_maps", {}).items())[:3])
print("\nPARQUET columns")
for prefix in ["orders", "promo", "product", "style"]:
    fs = sorted(glob.glob(str(base / f"processed/{prefix}_*.parquet")))
    if fs:
        df = pd.read_parquet(fs[0])
        print(prefix, len(fs), "files", list(df.columns))
        print(df.head(1).to_json(orient="records", force_ascii=False, date_format="iso"))
        print()
