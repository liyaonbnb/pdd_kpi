"""Compatibility read APIs for non-PDD platforms backed by V2 tables."""
from datetime import date
from decimal import Decimal
from typing import Any
import psycopg
from fastapi import APIRouter, Depends, Query
from v2.test_api import DATABASE_URL
from v2.v1_compat import _require_user, _v1_authorize_stores, _row_dict

router = APIRouter(prefix="/api", tags=["platform-compat"])
PLATFORMS = {"douyin", "tmall", "wechat"}

def _check(platform: str) -> str:
    return platform if platform in PLATFORMS else platform

def _stores(cur, platform, user, selected=None):
    cur.execute("select store_name from platform_stores where platform=%s and is_active=true order by store_name", (platform,))
    names=[r[0] for r in cur.fetchall()]
    if selected: names=[n for n in names if n in selected]
    if user.get("role") not in {"master","admin"}:
        allowed={x.get("store_name") if isinstance(x,dict) else x for x in user.get("allowed_stores",[])}
        names=[n for n in names if not allowed or n in allowed]
    return names

@router.get("/{platform}/dashboard")
def dashboard(platform: str, start_date: date|None=None, end_date: date|None=None, store_names: list[str]|None=Query(None), user: dict=Depends(_require_user)):
    _check(platform); start=start_date or date.today(); end=end_date or start
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        stores=_stores(cur,platform,user,store_names)
        cur.execute("""select count(distinct o.order_id), coalesce(sum(l.quantity),0), coalesce(sum(l.line_amount),0), coalesce(sum(c.total_cost),0), coalesce(sum(c.product_cost),0), coalesce(sum(c.shipping_fee),0) from platform_orders o join platform_order_lines l on l.order_id=o.id left join order_cost_snapshots c on c.order_id=o.order_id where o.platform=%s and o.store_name=any(%s) and coalesce(o.payment_time::date,o.created_at::date) between %s and %s and not o.is_cancelled""",(platform,stores,start,end))
        r=cur.fetchone() or (0,0,0,0,0,0)
    return {"platform":platform,"start_date":start.isoformat(),"end_date":end.isoformat(),"store_count":len(stores),"kpis":{"order_count":r[0],"quantity":r[1],"order_gmv":float(r[2] or 0),"total_cost":float(r[3] or 0),"total_product_cost":float(r[4] or 0),"total_logistics_cost":float(r[5] or 0)}}

@router.get("/{platform}/orders")
def orders(platform: str, store_name: str, date: date, user: dict=Depends(_require_user)):
    _check(platform)
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("select o.order_id,o.order_status,o.payment_time,l.product_id,l.style_id,l.quantity,l.line_amount,l.raw_payload from platform_orders o join platform_order_lines l on l.order_id=o.id where o.platform=%s and o.store_name=%s and coalesce(o.payment_time::date,o.created_at::date)=%s order by o.payment_time nulls last,o.order_id",(platform,store_name,date))
        return _row_dict(cur)

@router.get("/{platform}/trend")
def trend(platform: str, store_names: list[str]=Query(...), start_date: date=Query(...), end_date: date=Query(...), user: dict=Depends(_require_user)):
    _check(platform)
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("select metric_date as date,coalesce(sum(spend),0) promo_spend,coalesce(sum(gmv),0) promo_gmv,coalesce(sum(orders),0) promo_orders,coalesce(sum(exposure),0) exposure,coalesce(sum(clicks),0) clicks from promotion_metrics_daily where platform=%s and store_name=any(%s) and metric_date between %s and %s group by metric_date order by metric_date",(platform,store_names,start_date,end_date))
        return _row_dict(cur)

@router.get("/{platform}/analysis")
def analysis(platform: str, store_name: str, start_date: date, end_date: date, user: dict=Depends(_require_user)):
    _check(platform)
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("select l.product_id,coalesce(sum(l.quantity),0) order_count,coalesce(sum(l.line_amount),0) gmv from platform_orders o join platform_order_lines l on l.order_id=o.id where o.platform=%s and o.store_name=%s and coalesce(o.payment_time::date,o.created_at::date) between %s and %s and not o.is_cancelled group by l.product_id order by gmv desc",(platform,store_name,start_date,end_date))
        rows=_row_dict(cur)
    return {"product_metrics":rows,"style_metrics":[],"kpis":{}}

@router.get("/{platform}/costs")
def costs(platform: str, user: dict=Depends(_require_user)):
    _check(platform)
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("select b.code as merchant_code,b.name as product_name,b.estimated_shipping_fee as logistics_cost,coalesce(sum(bc.quantity*ic.unit_cost),0) as product_cost from bundles b left join bundle_components bc on bc.bundle_id=b.id left join item_cost_versions ic on ic.item_id=bc.item_id and ic.is_current=true group by b.code,b.name,b.estimated_shipping_fee order by b.code")
        return _row_dict(cur)

@router.get("/{platform}/records")
def records(platform: str, user: dict=Depends(_require_user)):
    _check(platform)
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("select platform,store_name,min(coalesce(payment_time::date,created_at::date)) start_date,max(coalesce(payment_time::date,created_at::date)) end_date,count(*) order_count from platform_orders where platform=%s group by platform,store_name order by store_name",(platform,))
        return _row_dict(cur)

