"""旧版数据迁移前的只读盘点工具。

它不会修改旧版 Parquet/JSON，也不会写入数据库。输出的报告用于决定商品、BOM、
链接映射和期初批次需要补录多少数据，避免迁移时把“未匹配”静默当作零成本或零库存。
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


DATE_FROM_FILENAME = re.compile(r"(\d{4}-\d{2}-\d{2})\.parquet$")


def _text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    rendered = str(value).strip()
    if rendered in {"", "\\t", "nan", "NaN", "None", "null", "NULL"}:
        return ""
    return rendered[:-2] if rendered.endswith(".0") else rendered


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _store_from_filename(path: Path) -> str:
    name = path.stem
    if not name.startswith("orders_"):
        return name
    prefix = name[len("orders_"):]
    return re.sub(r"_\d{4}-\d{2}-\d{2}$", "", prefix)


def _dates_from_files(files: Iterable[Path]) -> list[str]:
    dates = []
    for file in files:
        match = DATE_FROM_FILENAME.search(file.name)
        if match:
            dates.append(match.group(1))
    return sorted(set(dates))


@dataclass
class MigrationProfile:
    source: str
    date_from: str | None
    date_to: str | None
    order_files: int
    stores_in_files: int
    order_rows: int
    distinct_order_ids: int
    duplicate_order_lines: int
    missing_order_id_rows: int
    missing_payment_time_rows: int
    invalid_or_cancelled_rows: int
    inventory_candidate_rows: int
    missing_product_id_rows: int
    missing_style_id_rows: int
    missing_merchant_code_rows: int
    direct_cost_covered_rows: int
    style_mapping_covered_rows: int
    any_cost_covered_rows: int
    any_cost_coverage_rate: float
    legacy_cost_rows: int
    global_cost_records: int
    global_style_mapping_records: int
    stores_configured: int
    top_unmapped_skus: list[dict[str, Any]]
    by_store: list[dict[str, Any]]
    migration_warnings: list[str]


def profile_legacy_source(source: Path) -> MigrationProfile:
    processed = source / "processed"
    files = sorted(processed.glob("orders_*.parquet"))
    costs = _read_json(source / "costs.json")
    stores = _read_json(source / "stores.json")
    global_costs = costs.get("global_merchant_costs", {}) if isinstance(costs.get("global_merchant_costs"), dict) else {}
    style_map = costs.get("global_style_merchant_map", {}) if isinstance(costs.get("global_style_merchant_map"), dict) else {}
    store_costs = costs.get("merchant_costs", {}) if isinstance(costs.get("merchant_costs"), dict) else {}

    rows_total = duplicate_order_lines = missing_order_id = missing_pay_time = 0
    all_order_ids: set[str] = set()
    invalid_or_cancelled = inventory_candidates = missing_product_id = missing_style_id = missing_merchant_code = 0
    direct_cost_covered = style_mapping_covered = any_cost_covered = legacy_cost_rows = 0
    sku_counter: Counter[tuple[str, str, str, str]] = Counter()
    store_metrics: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "order_ids": set(),
        "rows": 0,
        "missing_order_id": 0,
        "duplicate_lines": 0,
        "missing_payment_time": 0,
        "inventory_candidates": 0,
        "invalid_or_cancelled": 0,
        "missing_product_id": 0,
        "missing_style_id": 0,
        "missing_merchant_code": 0,
        "cost_covered": 0,
        "cost_uncovered": 0,
    })

    for file in files:
        frame = pd.read_parquet(file)
        store = _store_from_filename(file)
        if "store_name" in frame.columns:
            configured_store = next((_text(value) for value in frame["store_name"].head(20) if _text(value)), "")
            if configured_store:
                store = configured_store
        seen_line_keys: set[tuple[str, str, str]] = set()
        for _, row in frame.iterrows():
            rows_total += 1
            metrics = store_metrics[store]
            metrics["rows"] += 1
            order_id = _text(row.get("order_id"))
            product_id = _text(row.get("product_id"))
            style_id = _text(row.get("style_id"))
            merchant_code = _text(row.get("merchant_code"))
            pay_time = _text(row.get("pay_time"))
            if not order_id:
                missing_order_id += 1
                metrics["missing_order_id"] += 1
            else:
                metrics["order_ids"].add(order_id)
                all_order_ids.add(order_id)
                line_key = (order_id, product_id, style_id)
                if line_key in seen_line_keys:
                    duplicate_order_lines += 1
                    metrics["duplicate_lines"] += 1
                seen_line_keys.add(line_key)
            if not pay_time:
                missing_pay_time += 1
                metrics["missing_payment_time"] += 1

            valid = _is_true(row.get("is_valid", True))
            cancelled = _is_true(row.get("is_cancel"))
            refunded = _is_true(row.get("is_refund"))
            candidate = valid and not cancelled and not refunded
            if candidate:
                inventory_candidates += 1
                metrics["inventory_candidates"] += 1
            else:
                invalid_or_cancelled += 1
                metrics["invalid_or_cancelled"] += 1
            if not product_id:
                missing_product_id += 1
                metrics["missing_product_id"] += 1
            if not style_id:
                missing_style_id += 1
                metrics["missing_style_id"] += 1
            if not merchant_code:
                missing_merchant_code += 1
                metrics["missing_merchant_code"] += 1

            style_key = f"{product_id}::{style_id}" if product_id and style_id else ""
            mapped_code = _text(style_map.get(style_key))
            direct_cost = merchant_code in global_costs or merchant_code in (store_costs.get(store, {}) or {})
            mapped_cost = mapped_code in global_costs or mapped_code in (store_costs.get(store, {}) or {})
            if direct_cost:
                direct_cost_covered += 1
            if mapped_cost:
                style_mapping_covered += 1
            if direct_cost or mapped_cost:
                any_cost_covered += 1
                metrics["cost_covered"] += 1
            elif candidate:
                sku_counter[(store, product_id or "<missing>", style_id or "<missing>", merchant_code or "<missing>")] += 1
                metrics["cost_uncovered"] += 1
            if merchant_code:
                legacy_cost_rows += 1

    distinct_order_ids = len(all_order_ids)

    by_store = []
    for store, metrics in sorted(store_metrics.items()):
        total = metrics["rows"]
        by_store.append({
            "store_name": store,
            "order_rows": total,
            "distinct_order_ids": len(metrics["order_ids"]),
            "inventory_candidate_rows": metrics["inventory_candidates"],
            "cost_covered_rows": metrics["cost_covered"],
            "cost_coverage_rate": round(metrics["cost_covered"] / total, 6) if total else 0,
            "cost_uncovered_candidate_rows": metrics["cost_uncovered"],
            "missing_payment_time_rows": metrics["missing_payment_time"],
        })

    warnings = [
        "历史订单只迁移经营数据；库存启用日前不重放扣库。",
        "无法确认的商品/规格链接映射进入人工确认队列，禁止静默按零成本或零库存处理。",
        "历史真实批次不可反推，库存启用日需为每个仓库和单品录入期初批次；缺失来源使用 LEGACY-OPENING 虚拟批次。",
    ]
    if missing_pay_time:
        warnings.append(f"发现 {missing_pay_time} 行缺少支付时间，启用日后的这类订单需要人工修正或进入异常队列。")
    if any_cost_covered < inventory_candidates:
        warnings.append("存在成本或规格映射未覆盖的有效订单行；迁移前应补齐单品/组合/BOM/链接映射。")

    dates = _dates_from_files(files)
    return MigrationProfile(
        source=str(source),
        date_from=dates[0] if dates else None,
        date_to=dates[-1] if dates else None,
        order_files=len(files),
        stores_in_files=len(store_metrics),
        order_rows=rows_total,
        distinct_order_ids=distinct_order_ids,
        duplicate_order_lines=duplicate_order_lines,
        missing_order_id_rows=missing_order_id,
        missing_payment_time_rows=missing_pay_time,
        invalid_or_cancelled_rows=invalid_or_cancelled,
        inventory_candidate_rows=inventory_candidates,
        missing_product_id_rows=missing_product_id,
        missing_style_id_rows=missing_style_id,
        missing_merchant_code_rows=missing_merchant_code,
        direct_cost_covered_rows=direct_cost_covered,
        style_mapping_covered_rows=style_mapping_covered,
        any_cost_covered_rows=any_cost_covered,
        any_cost_coverage_rate=round(any_cost_covered / rows_total, 6) if rows_total else 0,
        legacy_cost_rows=legacy_cost_rows,
        global_cost_records=len(global_costs),
        global_style_mapping_records=len(style_map),
        stores_configured=len(stores),
        top_unmapped_skus=[
            {"store_name": store, "product_id": product_id, "style_id": style_id, "merchant_code": merchant_code, "order_rows": count}
            for (store, product_id, style_id, merchant_code), count in sku_counter.most_common(30)
        ],
        by_store=by_store,
        migration_warnings=warnings,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="只读盘点旧版 PDD BI 数据，生成 V2 迁移报告")
    parser.add_argument("--source", required=True, type=Path, help="旧版 data 目录或本地样本目录")
    parser.add_argument("--output", type=Path, help="报告 JSON 输出路径；默认输出到标准输出")
    args = parser.parse_args()
    report = asdict(profile_legacy_source(args.source))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
