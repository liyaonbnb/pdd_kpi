"""V2 cost endpoints that expose single-item cost through the legacy /costs/global API shape.

Design:
- merchant_code maps to bundle.code (single-item bundles are also bundles).
- product_cost = sum(component_qty * item weighted-average cost) from inventory_balances.
- logistics_cost = bundle.estimated_shipping_fee.
- Unmapped products come from platform_order_lines without a platform_listing_mapping.
"""

import os
import hashlib
from datetime import date
from decimal import Decimal
from typing import Any

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, File, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import PlainTextResponse

DATABASE_URL = os.getenv(
    "V2_DATABASE_URL",
    "postgresql://pdd_v2_test:pdd_v2_test_local_2026@127.0.0.1:55432/pdd_v2_test",
)

router = APIRouter(prefix="/api/costs", tags=["costs"])


class CostRecord(BaseModel):
    merchant_code: str = Field(min_length=1)
    product_name: str = ""
    product_cost: float = 0.0
    logistics_cost: float = 0.0


class SaveGlobalCostsRequest(BaseModel):
    costs: list[CostRecord]


class ProductMappingRequest(BaseModel):
    product_id: str = Field(min_length=1)
    merchant_code: str = Field(min_length=1)
    style_id: str | None = None
    product_name: str | None = None
    platform: str = "pdd"
    store_name: str = "默认店铺"


def _require_costs_user(authorization: str | None = Header(None)) -> dict[str, Any]:
    from v2.test_api import _verify_jwt
    user = _verify_jwt(authorization.replace("Bearer ", "") if authorization else None)
    if not user:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    allowed = set(user.get("allowed_pages") or [])
    if user.get("role") != "master" and "costs" not in allowed:
        raise HTTPException(status_code=403, detail="无成本页面权限")
    return user


def _row_dict(cur) -> list[dict[str, Any]]:
    names = [desc.name for desc in cur.description]
    rows = []
    for row in cur.fetchall():
        value = {}
        for name, item in zip(names, row):
            if isinstance(item, Decimal):
                item = float(item)
            elif hasattr(item, "isoformat"):
                item = item.isoformat()
            value[name] = item
        rows.append(value)
    return rows


def _bundle_cost_rows(cur) -> list[dict[str, Any]]:
    """List every active bundle as a legacy merchant_code cost row.

    单品成本口径：优先按各仓库存量加权的平均成本；无库存时回退到最新 item_cost_versions。
    """
    cur.execute("""
        select b.id as bundle_id, b.code, b.name, b.estimated_shipping_fee,
               coalesce(sum(bc.quantity * ic.unit_cost), 0) as product_cost
        from bundles b
        left join lateral (
            select * from bundle_versions where bundle_id = b.id and status = 'active'
            order by version_no desc limit 1
        ) bv on true
        left join bundle_components bc on bc.bundle_version_id = bv.id
        left join lateral (
            select coalesce(
                (select sum(ib.sellable_qty * ib.average_unit_cost) / nullif(sum(ib.sellable_qty), 0)
                 from inventory_balances ib where ib.item_id = bc.item_id),
                (select cv.unit_cost from item_cost_versions cv where cv.item_id = bc.item_id
                 order by cv.effective_from desc, cv.created_at desc limit 1),
                0
            ) as unit_cost
        ) ic on true
        where b.is_active = true
        group by b.id, b.code, b.name, b.estimated_shipping_fee
        order by b.code
    """)
    rows = _row_dict(cur)
    return [
        {
            "merchant_code": r["code"],
            "product_name": r["name"],
            "product_cost": float(r["product_cost"] or 0),
            "logistics_cost": float(r["estimated_shipping_fee"] or 0),
        }
        for r in rows
    ]


@router.get("/global")
def list_global_costs(_: dict[str, Any] = Depends(_require_costs_user)) -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            return _bundle_cost_rows(cur)


@router.post("/global")
def save_global_costs(
    req: SaveGlobalCostsRequest,
    user: dict[str, Any] = Depends(_require_costs_user),
) -> dict[str, Any]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            updated = 0
            for rec in req.costs:
                cur.execute(
                    "update bundles set estimated_shipping_fee = %s, name = %s, updated_at = now() where code = %s returning id",
                    (Decimal(str(rec.logistics_cost)), rec.product_name, rec.merchant_code),
                )
                row = cur.fetchone()
                if row:
                    updated += 1
                else:
                    cur.execute(
                        "insert into inventory_items (code, name, base_unit) values (%s, %s, '件') on conflict (code) do update set name = excluded.name returning id",
                        (rec.merchant_code, rec.product_name or rec.merchant_code),
                    )
                    item_id = cur.fetchone()[0]
                    cur.execute(
                        "insert into bundles (code, name, estimated_shipping_fee) values (%s, %s, %s) returning id",
                        (rec.merchant_code, rec.product_name or rec.merchant_code, Decimal(str(rec.logistics_cost))),
                    )
                    bundle_id = cur.fetchone()[0]
                    cur.execute(
                        "insert into bundle_versions (bundle_id, version_no, effective_from, status) values (%s, 1, %s, 'active') returning id",
                        (bundle_id, date.today()),
                    )
                    version_id = cur.fetchone()[0]
                    cur.execute(
                        "insert into bundle_components (bundle_version_id, item_id, quantity) values (%s, %s, 1)",
                        (version_id, item_id),
                    )
                    updated += 1
            conn.commit()
    return {"updated": updated}


@router.post("/global/refresh")
def refresh_global_cost_codes(
    user: dict[str, Any] = Depends(_require_costs_user),
) -> dict[str, int]:
    """Create bundles for product_id/style_id combos seen in orders but not yet mapped."""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                select distinct o.platform, o.store_name, l.product_id, l.style_id
                from platform_order_lines l
                join platform_orders o on o.id = l.order_id
                where not exists (
                    select 1 from platform_listing_mappings m
                    where m.platform = o.platform and m.store_name = o.store_name
                      and m.product_id = l.product_id
                      and coalesce(m.style_id, '') = coalesce(l.style_id, '')
                )
            """)
            unmapped = _row_dict(cur)
            added = 0
            for row in unmapped:
                raw_code = f"{row['product_id']}-{row['store_name']}"
                code = raw_code if len(raw_code) <= 128 else raw_code[:95] + "-" + hashlib.sha1(raw_code.encode("utf-8")).hexdigest()[:32]
                cur.execute("select 1 from bundles where code = %s", (code,))
                if cur.fetchone():
                    continue
                name = f"自动-{row['product_id']}"
                cur.execute(
                    "insert into inventory_items (code, name, base_unit) values (%s, %s, '件') on conflict (code) do nothing returning id",
                    (code, name),
                )
                cur.execute("select id from inventory_items where code = %s", (code,))
                item_id = cur.fetchone()[0]
                cur.execute(
                    "insert into bundles (code, name, estimated_shipping_fee) values (%s, %s, 0) returning id",
                    (code, name),
                )
                bundle_id = cur.fetchone()[0]
                cur.execute(
                    "insert into bundle_versions (bundle_id, version_no, effective_from, status) values (%s, 1, %s, 'active') returning id",
                    (bundle_id, date.today()),
                )
                version_id = cur.fetchone()[0]
                cur.execute(
                    "insert into bundle_components (bundle_version_id, item_id, quantity) values (%s, %s, 1)",
                    (version_id, item_id),
                )
                cur.execute(
                    """insert into platform_listing_mappings (platform, store_name, product_id, style_id, bundle_id)
                        values (%s, %s, %s, %s, %s)""",
                    (row["platform"], row["store_name"], row["product_id"], row["style_id"], bundle_id),
                )
                added += 1
            conn.commit()
    return {"added": added}


@router.get("/global/unmapped")
def list_unmapped_products(
    user: dict[str, Any] = Depends(_require_costs_user),
) -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                select o.platform, o.store_name, l.product_id,
                       max(l.raw_payload->>'product_name') as product_name,
                       l.style_id,
                       max(l.raw_payload->>'style_name') as style_name,
                       count(distinct o.order_id) as order_count,
                       min(o.payment_time::date) as first_date
                from platform_order_lines l
                join platform_orders o on o.id = l.order_id
                where not exists (
                    select 1 from platform_listing_mappings m
                    where m.platform = o.platform and m.store_name = o.store_name
                      and m.product_id = l.product_id
                      and coalesce(m.style_id, '') = coalesce(l.style_id, '')
                )
                group by o.platform, o.store_name, l.product_id, l.style_id
                order by order_count desc
            """)
            rows = _row_dict(cur)
            for r in rows:
                r.setdefault("style_id", "-")
                r.setdefault("style_name", "-")
            return rows


@router.get("/global/unmapped/count")
def count_unmapped_products(
    user: dict[str, Any] = Depends(_require_costs_user),
) -> dict[str, int]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                select count(distinct (o.platform, o.store_name, l.product_id, coalesce(l.style_id, '')))
                from platform_order_lines l
                join platform_orders o on o.id = l.order_id
                where not exists (
                    select 1 from platform_listing_mappings m
                    where m.platform = o.platform and m.store_name = o.store_name
                      and m.product_id = l.product_id
                      and coalesce(m.style_id, '') = coalesce(l.style_id, '')
                )
            """)
            unmapped = int(cur.fetchone()[0])
            cur.execute("""
                select count(*) from bundles b
                left join bundle_versions bv on bv.bundle_id = b.id and bv.status = 'active'
                left join bundle_components bc on bc.bundle_version_id = bv.id
                left join inventory_balances ib on ib.item_id = bc.item_id
                where b.is_active = true
                group by b.id
                having coalesce(sum(bc.quantity * ib.average_unit_cost), 0) <= 0
                   or b.estimated_shipping_fee <= 0
            """)
            pending = len(cur.fetchall()) if cur.description else 0
    return {"pending": pending, "unmapped": unmapped}


@router.post("/global/map")
def map_product_to_merchant_code(
    req: ProductMappingRequest,
    user: dict[str, Any] = Depends(_require_costs_user),
) -> dict[str, Any]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select id from bundles where code = %s and is_active = true", (req.merchant_code,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=400, detail=f"商家编码不存在：{req.merchant_code}")
            bundle_id = row[0]
            cur.execute(
                """insert into platform_listing_mappings (platform, store_name, product_id, style_id, bundle_id)
                    values (%s, %s, %s, %s, %s)
                    on conflict (platform, store_name, product_id, style_id, effective_from) do update
                    set bundle_id = excluded.bundle_id""",
                (req.platform, req.store_name, req.product_id, req.style_id, bundle_id),
            )
            conn.commit()
    return {"success": True}


@router.get("/global/export", response_class=PlainTextResponse)
def export_global_costs(pending_only: bool = False, user: dict[str, Any] = Depends(_require_costs_user)) -> str:
    import csv
    import io as string_io
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            rows = _bundle_cost_rows(cur)
    if pending_only:
        rows = [row for row in rows if float(row.get("product_cost") or 0) <= 0 or float(row.get("logistics_cost") or 0) <= 0]
    output = string_io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["商家编码", "商品名称", "商品成本/件", "物流成本/件"])
    for row in rows:
        writer.writerow([row.get("merchant_code", ""), row.get("product_name", ""), row.get("product_cost", 0), row.get("logistics_cost", 0)])
    return "\ufeff" + output.getvalue()


@router.post("/global/import")
async def import_global_costs(file: UploadFile = File(...), user: dict[str, Any] = Depends(_require_costs_user)) -> dict[str, int]:
    import csv
    import io as string_io
    raw = await file.read()
    decoded = None
    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise HTTPException(status_code=400, detail="无法读取 CSV，请检查编码")
    reader = csv.DictReader(string_io.StringIO(decoded))
    aliases = {
        "商家编码": "merchant_code", "商家代码": "merchant_code", "商品编码": "merchant_code", "链接编码": "merchant_code", "merchant_code": "merchant_code",
        "商品名称": "product_name", "商品名": "product_name", "product_name": "product_name",
        "商品成本/件": "product_cost", "商品成本": "product_cost", "product_cost": "product_cost",
        "物流成本/件": "logistics_cost", "物流成本": "logistics_cost", "logistics_cost": "logistics_cost",
    }
    records = []
    for original in reader:
        row = {aliases.get(str(key).strip().replace(" ", ""), key): value for key, value in original.items()}
        code = str(row.get("merchant_code") or "").strip()
        if not code:
            continue
        try:
            product_cost = float(row.get("product_cost") or 0)
            logistics_cost = float(row.get("logistics_cost") or 0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"成本数值无效：{code}")
        records.append(CostRecord(merchant_code=code, product_name=str(row.get("product_name") or ""), product_cost=product_cost, logistics_cost=logistics_cost))
    if not records:
        raise HTTPException(status_code=400, detail="CSV 缺少有效成本记录")
    result = save_global_costs(SaveGlobalCostsRequest(costs=records), user)
    return {"updated": int(result.get("updated", 0))}
