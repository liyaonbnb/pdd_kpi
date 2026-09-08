"""Compatibility read APIs for non-PDD platforms backed by V2 tables."""
from datetime import date
from decimal import Decimal
from typing import Any
import psycopg
from fastapi import APIRouter, Depends, Query
from v2.test_api import DATABASE_URL
from v2.v1_compat import _require_user, _v1_authorize_stores, _row_dict, _raw_text, _raw_num

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
        cur.execute("""select count(distinct o.order_id), coalesce(sum(l.quantity),0),
                                  coalesce(sum(coalesce((l.raw_payload->>'user_paid')::numeric,0)),0),
                                  coalesce(sum(c.total_cost),0), coalesce(sum(c.product_cost),0), coalesce(sum(c.shipping_fee),0)
                          from platform_orders o join platform_order_lines l on l.order_id=o.id
                          left join order_cost_snapshots c on c.order_id=o.order_id
                          where o.platform=%s and o.store_name=any(%s)
                            and coalesce(o.payment_time::date,o.created_at::date) between %s and %s and not o.is_cancelled""",(platform,stores,start,end))
        r=cur.fetchone() or (0,0,0,0,0,0)
    return {"platform":platform,"start_date":start.isoformat(),"end_date":end.isoformat(),"store_count":len(stores),"kpis":{"order_count":r[0],"quantity":r[1],"order_gmv":float(r[2] or 0),"total_cost":float(r[3] or 0),"total_product_cost":float(r[4] or 0),"total_logistics_cost":float(r[5] or 0)}}

@router.get("/{platform}/orders")
def orders(platform: str, store_name: str, date: date, user: dict=Depends(_require_user)):
    _check(platform)
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("select o.order_id,o.order_status,o.payment_time,l.product_id,l.style_id,l.quantity,l.raw_payload from platform_orders o join platform_order_lines l on l.order_id=o.id where o.platform=%s and o.store_name=%s and coalesce(o.payment_time::date,o.created_at::date)=%s order by o.payment_time nulls last,o.order_id",(platform,store_name,date))
        rows=cur.fetchall()
    records=[]
    for order_id, order_status, payment_local, product_id, style_id, quantity, payload in rows:
        payload = payload or {}
        pay_time = _raw_text(payload, "pay_time", "order_time", "订单时间")
        if not pay_time and payment_local is not None:
            pay_time = payment_local.strftime("%Y-%m-%d %H:%M:%S")
        record = {
            "order_id": order_id,
            "product_id": product_id,
            "product_name": _raw_text(payload, "product_name", "商品名称") or None,
            "style_id": style_id,
            "style_name": _raw_text(payload, "style_name", "spec") or None,
            "merchant_code": _raw_text(payload, "merchant_code") or None,
            "quantity": float(quantity or 0),
            "order_status": order_status or None,
            "order_time": pay_time or None,
            # canonical money (migration maps amount->item_total, actual_revenue->user_paid)
            "item_total": _raw_num(payload, "item_total", "amount", "商品金额", "商品总价(元)"),
            "user_paid": _raw_num(payload, "user_paid", "actual_revenue", "实付金额"),
            "amount": _raw_num(payload, "item_total", "amount", "商品金额", "商品总价(元)"),
            "actual_revenue": _raw_num(payload, "user_paid", "actual_revenue", "实付金额"),
        }
        # passthrough any remaining original columns for platform-specific fields
        for key, value in payload.items():
            if key not in record:
                record[key] = value
        records.append(record)
    return records

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
        cur.execute("select l.product_id,coalesce(sum(l.quantity),0) order_count,coalesce(sum(coalesce((l.raw_payload->>'user_paid')::numeric,0)),0) gmv from platform_orders o join platform_order_lines l on l.order_id=o.id where o.platform=%s and o.store_name=%s and coalesce(o.payment_time::date,o.created_at::date) between %s and %s and not o.is_cancelled group by l.product_id order by gmv desc",(platform,store_name,start_date,end_date))
        rows=_row_dict(cur)
    return {"product_metrics":rows,"style_metrics":[],"kpis":{}}

@router.get("/{platform}/costs")
def costs(platform: str, user: dict=Depends(_require_user)):
    _check(platform)
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("select b.code as merchant_code,b.name as product_name,b.estimated_shipping_fee as logistics_cost,coalesce(sum(bc.quantity*ic.unit_cost),0) as product_cost from bundles b left join bundle_versions bv on bv.bundle_id=b.id left join bundle_components bc on bc.bundle_version_id=bv.id left join item_cost_versions ic on ic.item_id=bc.item_id and ic.effective_to is null group by b.code,b.name,b.estimated_shipping_fee order by b.code")
        return _row_dict(cur)

@router.get("/{platform}/records")
def records(platform: str, user: dict=Depends(_require_user)):
    _check(platform)
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("select platform,store_name,min(coalesce(payment_time::date,created_at::date)) start_date,max(coalesce(payment_time::date,created_at::date)) end_date,count(*) order_count from platform_orders where platform=%s group by platform,store_name order by store_name",(platform,))
        return _row_dict(cur)


@router.get("/{platform}/ai/config")
def ai_config(platform: str, user: dict = Depends(_require_user)):
    _check(platform)
    return {"platform": platform}

@router.post("/{platform}/ai/config")
def ai_update(platform: str, config: dict[str, Any], user: dict = Depends(_require_user)):
    _check(platform)
    if user.get("role") not in {"master", "admin"}:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="仅管理员可修改 AI 配置")
    return {"platform": platform, **config}

@router.post("/{platform}/ai/test")
def ai_test(platform: str, config: dict[str, Any], user: dict = Depends(_require_user)):
    _check(platform)
    return {"success": False, "error": "V2 AI 提供商尚未配置"}

@router.post("/{platform}/ai/report")
def ai_report(platform: str, store_name: str, start_date: date, end_date: date, config: dict[str, Any], user: dict = Depends(_require_user)):
    _check(platform)
    return {"platform": platform, "store_name": store_name, "start_date": start_date.isoformat(), "end_date": end_date.isoformat(), "content": "V2 AI 分析尚未配置提供商"}

@router.get("/{platform}/wecom/config")
def platform_wecom_config(platform: str, user: dict = Depends(_require_user)):
    _check(platform)
    return {"platform": platform}

@router.post("/{platform}/wecom/config")
def platform_wecom_update(platform: str, config: dict[str, Any], user: dict = Depends(_require_user)):
    _check(platform)
    if user.get("role") not in {"master", "admin"}:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="仅管理员可修改企业微信配置")
    return {"platform": platform, **config}

@router.post("/{platform}/wecom/preview")
def platform_wecom_preview(platform: str, report_date: date, user: dict = Depends(_require_user)):
    _check(platform)
    return {"draft_id": "%s-%s" % (platform, report_date), "report_date": report_date.isoformat(), "content": "%s 运营日报待发送" % platform}

@router.post("/{platform}/wecom/send")
def platform_wecom_send(platform: str, report_date: date, config: dict[str, Any], user: dict = Depends(_require_user)):
    _check(platform)
    return {"success": False, "error": "该平台企业微信发送配置尚未完成"}
