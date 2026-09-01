"""Migrate legacy PDD BI data into the V2 PostgreSQL schema.

Strategy (v2/MIGRATION.md):
- Historical orders are imported as legacy business data only.
- inventory_status is set to ''legacy''; no automatic inventory deduction is performed.
- Existing global costs become inventory items + 1:1 bundles + global cost versions.
- Stores share the default KUNSHAN warehouse unless configured otherwise.
- Promotion parquet files are inserted into promotion_metrics_daily.

The script is idempotent via source_sha256 and ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

import pandas as pd
import psycopg
from psycopg.types.json import Json
from psycopg.rows import dict_row


LEGACY_BASE = Path(os.getenv("LEGACY_BASE", "/opt/pdd_bi_v2_test/legacy_full"))
DATABASE_URL = os.getenv(
    "V2_DATABASE_URL",
    "postgresql://pdd_v2_test:pdd_v2_test_local_2026@127.0.0.1:5432/pdd_v2_test",
)
DEFAULT_WAREHOUSE = "KUNSHAN"
BUNDLE_VERSION_EFFECTIVE_FROM = date(2020, 1, 1)
COST_VERSION_EFFECTIVE_FROM = date(2020, 1, 1)


MONEY_CTX = Decimal("0.000001")


def money(value: Any) -> Decimal:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return Decimal("0")
    try:
        d = Decimal(str(value))
    except Exception:
        return Decimal("0")
    return d.quantize(MONEY_CTX, rounding=ROUND_HALF_UP)


def qty(value: Any) -> Decimal:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    rendered = str(value).strip()
    if rendered in {"", "nan", "NaN", "None", "null", "NULL", "\t"}:
        return ""
    return rendered[:-2] if rendered.endswith(".0") else rendered


def parse_datetime(value: Any) -> Optional[datetime]:
    s = text(value)
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def date_from_filename(path: Path) -> Optional[date]:
    match = re.search(r"(\d{4}-\d{2}-\d{2})\.parquet$", path.name)
    if match:
        return datetime.strptime(match.group(1), "%Y-%m-%d").date()
    return None


@dataclass
class MigrationState:
    warehouses: Dict[str, UUID]
    stores: Dict[str, UUID]  # key = platform|store_name
    items: Dict[str, UUID]  # key = merchant_code
    bundles: Dict[str, UUID]  # key = merchant_code
    bundle_versions: Dict[str, UUID]  # key = merchant_code -> active version id


def _load_warehouses(cur: psycopg.Cursor) -> Dict[str, UUID]:
    cur.execute("select id, code from warehouses")
    return {row[1]: row[0] for row in cur.fetchall()}


def migrate_stores(cur: psycopg.Cursor, state: MigrationState, stores_data: Dict[str, Any]) -> int:
    inserted = 0
    for key, info in stores_data.items():
        platform = text(info.get("platform", "pdd")).lower() or "pdd"
        store_name = text(info.get("name", key)) or key
        if not store_name:
            continue
        cur.execute(
            """
            insert into platform_stores (platform, store_name, display_name, legacy_key, metadata)
            values (%s, %s, %s, %s, %s)
            on conflict (platform, store_name) do update set
                display_name = excluded.display_name,
                legacy_key = excluded.legacy_key,
                metadata = excluded.metadata,
                updated_at = now()
            returning id
            """,
            (platform, store_name, store_name, key, Json({"legacy_id": key})),
        )
        store_id = cur.fetchone()[0]
        state.stores[f"{platform}|{store_name}"] = store_id
        # Assign to default warehouse
        cur.execute(
            """
            insert into store_warehouse_assignments (platform, store_name, warehouse_id, effective_from)
            values (%s, %s, %s, %s)
            on conflict (platform, store_name, effective_from) do nothing
            """,
            (platform, store_name, state.warehouses[DEFAULT_WAREHOUSE], BUNDLE_VERSION_EFFECTIVE_FROM),
        )
        inserted += 1
    return inserted


def migrate_costs(cur: psycopg.Cursor, state: MigrationState, costs_data: Dict[str, Any]) -> int:
    global_costs = costs_data.get("global_merchant_costs", {}) or {}
    style_map = costs_data.get("global_style_merchant_map", {}) or {}

    inserted_items = 0
    # 1. global_merchant_costs -> inventory_item + bundle + cost_version
    for merchant_code, info in sorted(global_costs.items()):
        if not merchant_code:
            continue
        name = text(info.get("product_name")) or merchant_code
        product_cost = money(info.get("product_cost", 0))
        logistics_cost = money(info.get("logistics_cost", 0))

        # Inventory item
        cur.execute(
            """
            insert into inventory_items (code, name, base_unit, category, tracks_inventory)
            values (%s, %s, %s, %s, %s)
            on conflict (code) do update set name = excluded.name, updated_at = now()
            returning id
            """,
            (merchant_code, name, "件", None, True),
        )
        item_id = cur.fetchone()[0]
        state.items[merchant_code] = item_id

        # Bundle (composition 1:1)
        cur.execute(
            """
            insert into bundles (code, name, estimated_shipping_fee)
            values (%s, %s, %s)
            on conflict (code) do update set name = excluded.name, estimated_shipping_fee = excluded.estimated_shipping_fee, updated_at = now()
            returning id
            """,
            (merchant_code, name, logistics_cost),
        )
        bundle_id = cur.fetchone()[0]
        state.bundles[merchant_code] = bundle_id

        # Bundle version 1:1
        cur.execute(
            """
            insert into bundle_versions (bundle_id, version_no, effective_from, status)
            values (%s, %s, %s, %s)
            on conflict (bundle_id, version_no) do update set effective_from = excluded.effective_from, status = excluded.status
            returning id
            """,
            (bundle_id, 1, BUNDLE_VERSION_EFFECTIVE_FROM, "active"),
        )
        version_id = cur.fetchone()[0]
        state.bundle_versions[merchant_code] = version_id

        cur.execute(
            """
            insert into bundle_components (bundle_version_id, item_id, quantity)
            values (%s, %s, %s)
            on conflict (bundle_version_id, item_id) do update set quantity = excluded.quantity
            """,
            (version_id, item_id, Decimal("1")),
        )

        # Global cost version
        cur.execute(
            """
            insert into item_cost_versions (item_id, warehouse_id, unit_cost, effective_from, source_type, source_id)
            values (%s, %s, %s, %s, %s, %s)
            on conflict do nothing
            """,
            (item_id, state.warehouses[DEFAULT_WAREHOUSE], product_cost, COST_VERSION_EFFECTIVE_FROM, "legacy_migration", "global_cost"),
        )
        inserted_items += 1

    # 2. style map entries ensure bundle exists even if merchant code only appears in style map
    for style_key, merchant_code in sorted(style_map.items()):
        if not merchant_code or merchant_code in state.bundles:
            continue
        name = text(global_costs.get(merchant_code, {}).get("product_name")) or merchant_code
        product_cost = money(global_costs.get(merchant_code, {}).get("product_cost", 0))
        logistics_cost = money(global_costs.get(merchant_code, {}).get("logistics_cost", 0))

        cur.execute(
            "insert into inventory_items (code, name, base_unit, tracks_inventory) values (%s, %s, %s, %s) on conflict (code) do update set name = excluded.name returning id",
            (merchant_code, name, "件", True),
        )
        item_id = cur.fetchone()[0]
        state.items[merchant_code] = item_id

        cur.execute(
            "insert into bundles (code, name, estimated_shipping_fee) values (%s, %s, %s) on conflict (code) do update set name = excluded.name, estimated_shipping_fee = excluded.estimated_shipping_fee returning id",
            (merchant_code, name, logistics_cost),
        )
        bundle_id = cur.fetchone()[0]
        state.bundles[merchant_code] = bundle_id

        cur.execute(
            "insert into bundle_versions (bundle_id, version_no, effective_from, status) values (%s, %s, %s, %s) on conflict (bundle_id, version_no) do update set effective_from = excluded.effective_from returning id",
            (bundle_id, 1, BUNDLE_VERSION_EFFECTIVE_FROM, "active"),
        )
        version_id = cur.fetchone()[0]
        state.bundle_versions[merchant_code] = version_id

        cur.execute(
            "insert into bundle_components (bundle_version_id, item_id, quantity) values (%s, %s, %s) on conflict (bundle_version_id, item_id) do update set quantity = excluded.quantity",
            (version_id, item_id, Decimal("1")),
        )
        cur.execute(
            "insert into item_cost_versions (item_id, warehouse_id, unit_cost, effective_from, source_type, source_id) values (%s, %s, %s, %s, %s, %s) on conflict do nothing",
            (item_id, state.warehouses[DEFAULT_WAREHOUSE], product_cost, COST_VERSION_EFFECTIVE_FROM, "legacy_migration", "style_map"),
        )

    return inserted_items


def resolve_merchant_code(
    row: pd.Series,
    style_map: Dict[str, str],
) -> Optional[str]:
    merchant_code = text(row.get("merchant_code"))
    if merchant_code:
        return merchant_code
    product_id = text(row.get("product_id"))
    style_id = text(row.get("style_id"))
    if product_id and style_id:
        return style_map.get(f"{product_id}::{style_id}")
    return None


def migrate_orders_for_file(
    cur: psycopg.Cursor,
    state: MigrationState,
    style_map: Dict[str, str],
    file_path: Path,
) -> Tuple[int, int]:
    frame = pd.read_parquet(file_path)
    if frame.empty:
        return 0, 0

    sha = file_sha256(file_path)
    metric_date = date_from_filename(file_path)
    store_name = text(frame["store_name"].iloc[0]) if "store_name" in frame.columns else ""
    if not store_name:
        store_name = _store_from_filename(file_path)
    platform = "pdd"

    # Deduplicate import batch by sha
    cur.execute(
        "select id from data_import_batches where source_sha256 = %s",
        (sha,),
    )
    row = cur.fetchone()
    if row:
        return 0, 0  # already imported

    cur.execute(
        """
        insert into data_import_batches (platform, store_name, data_type, source_filename, source_sha256, period_from, period_to, status, row_count, created_by)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        returning id
        """,
        (platform, store_name, "orders", file_path.name, sha, metric_date, metric_date, "succeeded", len(frame), "legacy_migration"),
    )
    batch_id = cur.fetchone()[0]

    # Pre-compute warehouse id
    warehouse_id = state.warehouses[DEFAULT_WAREHOUSE]

    rows_inserted = 0
    # Group by order to avoid duplicate inserts (same order may appear in multiple rows)
    for order_id, group in frame.groupby("order_id", sort=False):
        order_id = text(order_id)
        if not order_id:
            continue
        first = group.iloc[0]
        payment_time = parse_datetime(first.get("pay_time"))
        order_status = text(first.get("order_status"))

        cur.execute(
            """
            insert into platform_orders (import_batch_id, platform, store_name, order_id, payment_time, order_status, warehouse_id, inventory_status)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (platform, store_name, order_id) do update set
                payment_time = excluded.payment_time,
                order_status = excluded.order_status,
                warehouse_id = excluded.warehouse_id,
                updated_at = now()
            returning id
            """,
            (batch_id, platform, store_name, order_id, payment_time, order_status, warehouse_id, "legacy"),
        )
        order_uuid = cur.fetchone()[0]

        for _, line in group.iterrows():
            merchant_code = resolve_merchant_code(line, style_map)
            bundle_id = state.bundles.get(merchant_code) if merchant_code else None
            bom_version_id = state.bundle_versions.get(merchant_code) if merchant_code else None
            product_id = text(line.get("product_id"))
            style_id = text(line.get("style_id"))
            quantity_val = qty(line.get("quantity"))
            if quantity_val <= 0:
                quantity_val = Decimal("1")

            raw_payload = {
                "product_name": text(line.get("product_name")),
                "style_name": text(line.get("style_name")),
                "item_total": float(money(line.get("item_total"))),
                "user_paid": float(money(line.get("user_paid"))),
                "merchant_income": float(money(line.get("merchant_income"))),
                "aftersales_status": text(line.get("aftersales_status")),
                "source_type": text(line.get("_source_type")),
                "merchant_code": merchant_code,
            }

            cur.execute(
                """
                insert into platform_order_lines (order_id, product_id, style_id, bundle_id, bom_version_id, quantity, expected_shipping_fee, raw_payload)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (order_id, product_id, style_id) do update set
                    bundle_id = excluded.bundle_id,
                    bom_version_id = excluded.bom_version_id,
                    quantity = excluded.quantity,
                    expected_shipping_fee = excluded.expected_shipping_fee,
                    raw_payload = excluded.raw_payload
                """,
                (order_uuid, product_id, style_id, bundle_id, bom_version_id, quantity_val, Decimal("0"), Json(raw_payload)),
            )
            rows_inserted += 1

    return len(frame), rows_inserted


def _store_from_filename(path: Path) -> str:
    name = path.stem
    if name.startswith("orders_"):
        name = name[len("orders_"):]
    elif name.startswith("promo_"):
        name = name[len("promo_"):]
    return re.sub(r"_\d{4}-\d{2}-\d{2}$", "", name)


def migrate_promos_for_file(
    cur: psycopg.Cursor,
    state: MigrationState,
    file_path: Path,
) -> Tuple[int, int]:
    frame = pd.read_parquet(file_path)
    if frame.empty:
        return 0, 0

    sha = file_sha256(file_path)
    metric_date = date_from_filename(file_path)
    store_name = text(frame["store_name"].iloc[0]) if "store_name" in frame.columns else ""
    if not store_name:
        store_name = _store_from_filename(file_path)
    platform = "pdd"

    cur.execute(
        "select id from data_import_batches where source_sha256 = %s",
        (sha,),
    )
    if cur.fetchone():
        return 0, 0

    cur.execute(
        """
        insert into data_import_batches (platform, store_name, data_type, source_filename, source_sha256, period_from, period_to, status, row_count, created_by)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        returning id
        """,
        (platform, store_name, "promotions", file_path.name, sha, metric_date, metric_date, "succeeded", len(frame), "legacy_migration"),
    )
    batch_id = cur.fetchone()[0]

    rows_inserted = 0
    for _, row in frame.iterrows():
        product_id = text(row.get("product_id"))
        if not product_id:
            continue
        spend = money(row.get("promo_spend", 0))
        gmv = money(row.get("promo_gmv", 0))
        orders_val = money(row.get("promo_orders", 0))
        exposure = money(row.get("exposure", 0))
        clicks_val = money(row.get("clicks", 0))

        raw_payload = {
            "product_name": text(row.get("product_name")),
            "plan_name": text(row.get("plan_name")),
            "bid_method": text(row.get("bid_method")),
            "promo_net_gmv": float(money(row.get("promo_net_gmv", 0))),
            "promo_settle_gmv": float(money(row.get("promo_settle_gmv", 0))),
            "source_type": text(row.get("_source_type")),
        }

        cur.execute(
            """
            insert into promotion_metrics_daily (import_batch_id, platform, store_name, metric_date, product_id, style_id, spend, gmv, orders, exposure, clicks, raw_payload)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (import_batch_id, product_id, style_id) do update set
                spend = excluded.spend,
                gmv = excluded.gmv,
                orders = excluded.orders,
                exposure = excluded.exposure,
                clicks = excluded.clicks,
                raw_payload = excluded.raw_payload
            """,
            (batch_id, platform, store_name, metric_date, product_id, None, spend, gmv, orders_val, exposure, clicks_val, Json(raw_payload)),
        )
        rows_inserted += 1

    return len(frame), rows_inserted


def run_migration() -> Dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    state = MigrationState(warehouses={}, stores={}, items={}, bundles={}, bundle_versions={})

    with psycopg.connect(DATABASE_URL) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            state.warehouses = _load_warehouses(cur)
            if DEFAULT_WAREHOUSE not in state.warehouses:
                raise RuntimeError(f"Default warehouse {DEFAULT_WAREHOUSE} not found")

            stores_data = json.loads((LEGACY_BASE / "stores.json").read_text(encoding="utf-8"))
            costs_data = json.loads((LEGACY_BASE / "costs.json").read_text(encoding="utf-8"))
            style_map = costs_data.get("global_style_merchant_map", {}) or {}

            store_count = migrate_stores(cur, state, stores_data)
            item_count = migrate_costs(cur, state, costs_data)
            conn.commit()

            order_files = sorted((LEGACY_BASE / "processed").glob("orders_*.parquet"))
            promo_files = sorted((LEGACY_BASE / "processed").glob("promo_*.parquet"))

            total_order_rows = 0
            total_order_lines = 0
            for idx, file_path in enumerate(order_files, 1):
                rows, lines = migrate_orders_for_file(cur, state, style_map, file_path)
                total_order_rows += rows
                total_order_lines += lines
                if idx % 50 == 0:
                    conn.commit()
                    print(f"  orders {idx}/{len(order_files)}: {rows} rows, {lines} lines")
            conn.commit()

            total_promo_rows = 0
            total_promo_lines = 0
            for idx, file_path in enumerate(promo_files, 1):
                rows, lines = migrate_promos_for_file(cur, state, file_path)
                total_promo_rows += rows
                total_promo_lines += lines
                if idx % 50 == 0:
                    conn.commit()
                    print(f"  promos {idx}/{len(promo_files)}: {rows} rows, {lines} lines")
            conn.commit()

            # Summary counts
            cur.execute("select count(*) from platform_stores")
            platform_stores_count = cur.fetchone()[0]
            cur.execute("select count(*) from data_import_batches")
            batches_count = cur.fetchone()[0]
            cur.execute("select count(*) from platform_orders")
            orders_count = cur.fetchone()[0]
            cur.execute("select count(*) from platform_order_lines")
            order_lines_count = cur.fetchone()[0]
            cur.execute("select count(*) from promotion_metrics_daily")
            promo_count = cur.fetchone()[0]
            cur.execute("select count(*) from inventory_items")
            items_count = cur.fetchone()[0]
            cur.execute("select count(*) from bundles")
            bundles_count = cur.fetchone()[0]

    return {
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "legacy_base": str(LEGACY_BASE),
        "database_url": DATABASE_URL.replace(":pdd_v2_test_local_2026", ":***"),
        "store_count": store_count,
        "item_count": item_count,
        "order_files": len(order_files),
        "promo_files": len(promo_files),
        "total_order_rows": total_order_rows,
        "total_order_lines": total_order_lines,
        "total_promo_rows": total_promo_rows,
        "total_promo_lines": total_promo_lines,
        "platform_stores_count": platform_stores_count,
        "data_import_batches_count": batches_count,
        "platform_orders_count": orders_count,
        "platform_order_lines_count": order_lines_count,
        "promotion_metrics_daily_count": promo_count,
        "inventory_items_count": items_count,
        "bundles_count": bundles_count,
    }


if __name__ == "__main__":
    summary = run_migration()
    print(json.dumps(summary, ensure_ascii=False, indent=2))

