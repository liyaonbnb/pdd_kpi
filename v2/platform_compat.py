"""Compatibility read APIs for non-PDD platforms backed by V2 tables."""
from datetime import date
from decimal import Decimal
from typing import Any
import psycopg
import csv
import io
from fastapi import APIRouter, Depends, Query, File, UploadFile, Form
from pydantic import BaseModel
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

@router.post("/{platform}/costs")
def save_platform_costs(platform: str, req: dict[str, Any], user: dict = Depends(_require_user)):
    _check(platform)
    from v2.costs import save_global_costs, SaveGlobalCostsRequest, CostRecord
    records = req.get("costs")
    if not isinstance(records, list):
        raise HTTPException(status_code=422, detail="costs 必须是数组")
    return save_global_costs(SaveGlobalCostsRequest(costs=[CostRecord(**item) for item in records]), user)
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

# ---------- platform-level cost sub-routes (V1 shape -> V2 PG) ----------

class _costs_map_req(BaseModel):
    product_id: str
    merchant_code: str
    style_id: str | None = None
    product_name: str | None = None
    store_name: str = ""
def _costs_hub():
    from v2 import costs as c
    return c


@router.get("/{platform}/costs/unmapped")
def platform_unmapped(platform: str, start_date: date | None = None, end_date: date | None = None, store_name: str | None = None, user: dict = Depends(_require_user)):
    hub = _costs_hub()
    sql = """
        select o.platform, o.store_name, l.product_id,
               max(l.raw_payload->>'product_name') as product_name,
               l.style_id, max(l.raw_payload->>'style_name') as style_name,
               count(distinct o.order_id) as order_count,
               min(o.payment_time::date) as first_date
        from platform_order_lines l
        join platform_orders o on o.id = l.order_id
        where o.platform = %s
          and not exists (
            select 1 from platform_listing_mappings m
            where m.platform = o.platform and m.store_name = o.store_name
              and m.product_id = l.product_id and coalesce(m.style_id,'') = coalesce(l.style_id,'')
          )
    """
    params = [platform]
    if store_name:
        sql += " and o.store_name = %s"; params.append(store_name)
    if start_date:
        sql += " and o.payment_time::date >= %s"; params.append(start_date)
    if end_date:
        sql += " and o.payment_time::date <= %s"; params.append(end_date)
    sql += " group by o.platform, o.store_name, l.product_id, l.style_id order by count(distinct o.order_id) desc"
    import psycopg as _pg
    with _pg.connect(hub.DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            r.setdefault("style_id", "-"); r.setdefault("style_name", "-")
            r.pop("platform", None)
    return rows


@router.get("/{platform}/costs/unmapped/count")
def platform_unmapped_count(platform: str, store_name: str | None = None, start_date: date | None = None, end_date: date | None = None, user: dict = Depends(_require_user)):
    hub = _costs_hub()
    import psycopg as _pg
    sql = """
        select count(distinct (o.store_name, l.product_id, coalesce(l.style_id,'')) )
        from platform_order_lines l join platform_orders o on o.id = l.order_id
        where o.platform = %s
          and not exists (
            select 1 from platform_listing_mappings m
            where m.platform = o.platform and m.store_name = o.store_name
              and m.product_id = l.product_id and coalesce(m.style_id,'') = coalesce(l.style_id,'')
          )
    """
    params=[platform]
    if store_name: sql += " and o.store_name = %s"; params.append(store_name)
    if start_date: sql += " and o.payment_time::date >= %s"; params.append(start_date)
    if end_date: sql += " and o.payment_time::date <= %s"; params.append(end_date)
    with _pg.connect(hub.DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params); unmapped = int(cur.fetchone()[0])
    return {"pending": 0, "unmapped": unmapped}


@router.post("/{platform}/costs/refresh")
def platform_costs_refresh(platform: str, user: dict = Depends(_require_user)):
    _check(platform)
    hub = _costs_hub()
    return hub.refresh_global_cost_codes(user)


@router.post("/{platform}/costs/map")
def platform_costs_map(platform: str, req: _costs_map_req, user: dict = Depends(_require_user)):
    _check(platform)
    hub = _costs_hub()
    mapping = hub.ProductMappingRequest(
        product_id=req.product_id, merchant_code=req.merchant_code,
        style_id=req.style_id or None, product_name=req.product_name or None,
        platform=platform, store_name=req.store_name or "",
    )
    return hub.map_product_to_merchant_code(mapping, user)


# ---------- /api/wechat/kol-stats ----------

@router.get("/wechat/kol-stats")
def wechat_kol_stats(store_name: str | None = None, start_date: date | None = None, end_date: date | None = None, user: dict = Depends(_require_user)):
    import psycopg as _pg
    from v2 import costs as hub
    sql = """
        select l.raw_payload->>'kol_name' as kol_name,
               l.raw_payload->>'kol_id' as kol_id,
               l.raw_payload->>'channel' as channel,
               count(distinct o.order_id) as order_count,
               coalesce(sum((l.raw_payload->>'net_revenue')::numeric), 0) as net_revenue,
               coalesce(sum((l.raw_payload->>'commission')::numeric), 0) as commission,
               coalesce(sum((l.raw_payload->>'refund_amount')::numeric), 0) as refund_amount,
               coalesce(sum((l.raw_payload->>'user_paid')::numeric),0) as gmv
        from platform_order_lines l join platform_orders o on o.id = l.order_id
        where o.platform = 'wechat'
          and coalesce(l.raw_payload->>'kol_name','') <> ''
    """
    params=[]
    if store_name: sql += " and o.store_name = %s"; params.append(store_name)
    if start_date: sql += " and o.payment_time::date >= %s"; params.append(start_date)
    if end_date: sql += " and o.payment_time::date <= %s"; params.append(end_date)
    sql += " group by 1,2,3 order by order_count desc"
    with _pg.connect(hub.DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows=[{"kol_name":r[0],"kol_id":r[1],"channel":r[2],"order_count":int(r[3]),"net_revenue":float(r[4] or 0),"commission":float(r[5] or 0),"refund_amount":float(r[6] or 0),"gmv":float(r[7] or 0)} for r in cur.fetchall()]
    return rows

# ---------- platform record deletion / cost export-import / system update ----------

def _v1_helpers():
    from v2.v1_compat import _require_master_v1, _v1_authorize_store, _actor_name, _ORDER_DATE_SQL
    return _require_master_v1, _v1_authorize_store, _actor_name, _ORDER_DATE_SQL


@router.delete("/{platform}/records/{store_name}/{day}")
def platform_delete_record(platform: str, store_name: str, day: date, user: dict = Depends(_require_user)):
    _check(platform)
    master, auth_store, _, date_sql = _v1_helpers()
    master(user); auth_store(user, store_name)
    import psycopg as _pg
    from v2 import costs as hub
    with _pg.connect(hub.DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(f"delete from platform_orders o where o.platform=%s and o.store_name=%s and {date_sql} = %s", (platform, store_name, day))
        cur.execute("delete from promotion_metrics_daily where platform=%s and store_name=%s and metric_date=%s", (platform, store_name, day))
        conn.commit()
    return {"deleted": True, "platform": platform, "store_name": store_name, "date": day.isoformat()}


@router.get("/{platform}/costs/export")
def platform_costs_export(platform: str, pending_only: bool = False, user: dict = Depends(_require_user)):
    _check(platform)
    from fastapi.responses import Response as _Resp
    hub = _costs_hub()
    import psycopg as _pg
    sql = "select code, name, estimated_shipping_fee from bundles where is_active = true order by code"
    with _pg.connect(hub.DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql); rows = cur.fetchall()
    lines = ["merchant_code,product_name,logistics_cost"]
    for code, name, fee in rows:
        lines.append(f"{code},{name or ''},{float(fee or 0)}")
    return _Resp(content=("\n".join(lines)).encode("utf-8"), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={platform}_costs.csv"})


@router.post("/{platform}/costs/import")
def platform_costs_import(platform: str, file: UploadFile = File(...), user: dict = Depends(_require_user)):
    _check(platform)
    raw = file.file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("gb18030")
    rows = list(csv.DictReader(io.StringIO(text)))
    updated = 0
    from v2 import costs as hub
    with psycopg.connect(hub.DATABASE_URL) as conn, conn.cursor() as cur:
        for row in rows:
            code = (row.get("merchant_code") or row.get("商品编码") or row.get("商家编码") or "").strip()
            if not code:
                continue
            name = (row.get("product_name") or row.get("商品名称") or code).strip()
            fee_text = (row.get("logistics_cost") or row.get("物流成本") or "0").strip()
            try:
                fee = float(fee_text or 0)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"物流成本不是数字：{fee_text}")
            cur.execute("update bundles set name=%s, estimated_shipping_fee=%s, updated_at=now() where code=%s returning id", (name, fee, code))
            if cur.fetchone():
                updated += 1
            else:
                cur.execute("insert into bundles(code,name,estimated_shipping_fee) values(%s,%s,%s) on conflict(code) do update set name=excluded.name,estimated_shipping_fee=excluded.estimated_shipping_fee", (code, name, fee))
                updated += 1
        conn.commit()
    return {"updated": updated}


@router.post("/system/update")
def system_update(user: dict = Depends(_require_user)):
    if user.get("role") not in {"master", "admin"}:
        raise HTTPException(status_code=403, detail="权限不足")
    return {"success": False, "up_to_date": True, "message": "测试环境不支持自动更新，请在服务器执行 git pull 后重启服务", "steps": ["cd /opt/pdd_bi_v2_test", "git pull origin master", "systemctl restart pdd-bi-v2-test pdd-bi-v2-test-web"]}


# ---------- /{platform}/import (upload orders + promo into V2 PG) ----------

def _import_platform_files(platform: str, store_name: str, import_date: date, order_bytes, order_filename, promo_bytes, promo_filename, actor: str):
    import hashlib
    import uuid as _uuid
    import pandas as pd
    from psycopg.types.json import Json
    from scripts.migrate_legacy_to_v2 import insert_orders_frame, insert_promo_frame, _normalize_order_frame, _aggregate_order_lines, _load_warehouses, parse_datetime
    import scripts.migrate_legacy_to_v2 as mig

    loader = {"douyin": "douyin_loader", "tmall": "tmall_loader", "wechat": "wechat_loader"}[platform]
    mod = __import__(loader)
    promo_df = None
    order_df = None
    if promo_bytes:
        promo_df = mod.read_promotion_file(promo_bytes, promo_filename or "")
    if order_bytes:
        order_df = mod.read_order_file(order_bytes, order_filename or "")
    if promo_df is None and order_df is None:
        raise ValueError("请至少上传推广数据或订单数据中的一个")
    if order_df is not None and not order_df.empty:
        order_df = _aggregate_order_lines(order_df, platform)
        order_df = _normalize_order_frame(order_df, platform)

    order_hash = hashlib.sha256(order_bytes).hexdigest() if order_bytes else None
    promo_hash = hashlib.sha256(promo_bytes).hexdigest() if promo_bytes else None

    batch_id = _uuid.uuid4()
    results = []
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        warehouses = _load_warehouses(cur)
        warehouse_id = warehouses.get("KUNSHAN")
        if not warehouse_id:
            cur.execute("select id from warehouses where code='KUNSHAN'")
            row = cur.fetchone()
            if row:
                warehouse_id = row[0]
        from v2.v1_compat import _load_bundle_maps, _load_listing_style_map
        bundles, bundle_versions = _load_bundle_maps(cur)
        style_map = _load_listing_style_map(cur, platform)

        # promo
        if promo_df is not None and not promo_df.empty:
            cur.execute("insert into data_import_batches (platform,store_name,data_type,source_filename,source_sha256,period_from,period_to,status,row_count,created_by) values (%s,%s,'promotions',%s,%s,%s,%s,'succeeded',%s,%s) returning id",(platform,store_name,promo_filename or "",promo_hash,import_date,import_date,len(promo_df),actor))
            p_batch=cur.fetchone()[0]
            inserted=insert_promo_frame(cur,batch_id=p_batch,platform=platform,store_name=store_name,metric_date=import_date,frame=promo_df)
            results.append({"date": import_date.isoformat(), "promo_saved": True})
        # orders
        if order_df is not None and not order_df.empty and "order_id" in order_df.columns:
            period_min = parse_datetime(str(order_df.get("pay_time").dropna().min())) if "pay_time" in order_df.columns else None
            period_max = parse_datetime(str(order_df.get("pay_time").dropna().max())) if "pay_time" in order_df.columns else None
            cur.execute("insert into data_import_batches (platform,store_name,data_type,source_filename,source_sha256,period_from,period_to,status,row_count,created_by) values (%s,%s,'orders',%s,%s,%s,%s,'succeeded',%s,%s) returning id",(platform,store_name,order_filename or "",order_hash,(period_min or import_date),(period_max or import_date),len(order_df),actor))
            o_batch=cur.fetchone()[0]
            inserted=insert_orders_frame(cur,batch_id=o_batch,platform=platform,store_name=store_name,frame=order_df,style_map=style_map,bundles=bundles,bundle_versions=bundle_versions,warehouse_id=warehouse_id,reassign_batch=True,full_payload=True)
            results.append({"date": import_date.isoformat(), "orders_saved": True})
        conn.commit()
    return results


@router.post("/{platform}/import")
def platform_import(platform: str, store_name: str = Form(...), import_date: date = Form(...), promo_file: UploadFile = File(None), order_file: UploadFile = File(None), user: dict = Depends(_require_user)):
    _check(platform)
    from v2.v1_compat import _v1_authorize_store, _actor_name
    _v1_authorize_store(user, store_name)
    order_bytes = order_file.file.read() if order_file else None
    promo_bytes = promo_file.file.read() if promo_file else None
    order_filename = order_file.filename or "" if order_file else ""
    promo_filename = promo_file.filename or "" if promo_file else ""
    try:
        results = _import_platform_files(platform, store_name, import_date, order_bytes, order_filename, promo_bytes, promo_filename, _actor_name(user))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"platform": platform, "store_name": store_name, "import_date": import_date.isoformat(), "results": results}
