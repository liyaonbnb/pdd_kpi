from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Header, File, Form, UploadFile
from pydantic import BaseModel
import psycopg

from v2.test_api import DATABASE_URL, TEST_TOKEN, _row_dict, _verify_auth_token, _verify_jwt, _load_v2_user, _safe_user

router = APIRouter(prefix="/api", tags=["v1-compat"])


def _require_user(authorization: str | None = Header(default=None), x_v2_test_token: str | None = Header(default=None)) -> dict[str, Any]:
    """兼容 V2 测试 token 和 JWT 登录。"""
    if TEST_TOKEN and x_v2_test_token == TEST_TOKEN:
        return {"username": "test-token", "role": "master", "allowed_stores": [], "allowed_pages": []}
    token = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None
    user = _verify_auth_token(token)
    if user:
        return user
    claims = _verify_jwt(token)
    if claims:
        return claims
    raise HTTPException(status_code=401, detail="需要登录")


@router.get("/users")
def list_users(user: dict = Depends(_require_user)):
    """V1 users page backed by v2_users."""
    if user.get("role") not in {"master", "admin"}:
        raise HTTPException(status_code=403, detail="权限不足")
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select username from v2_users where is_active=true order by username")
            return [_safe_user(_load_v2_user(name) or {"username": name}) for (name,) in cur.fetchall()]


# ---------- /api/stores ----------

class StoreCreate(BaseModel):
    name: str
    platform: str = "pdd"


@router.get("/stores")
def list_stores(platform: Optional[str] = Query(None), user: dict = Depends(_require_user)):
    """V1 兼容：返回店铺列表。"""
    sql = "select id, store_name, platform, display_name, is_active from platform_stores where is_active = true"
    params = []
    if platform:
        sql += " and platform = %s"
        params.append(platform)
    sql += " order by store_name"
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [
        {
            "id": str(r[0]),
            "name": r[1],
            "platform": r[2],
            "display_name": r[3] or r[1],
            "is_active": r[4],
        }
        for r in rows
    ]


@router.post("/stores")
def create_store(req: StoreCreate, user: dict = Depends(_require_user)):
    if user.get("role") not in ("master", "admin"):
        raise HTTPException(status_code=403, detail="权限不足")
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "insert into platform_stores(platform, store_name, display_name) values (%s, %s, %s) returning id",
                    (req.platform, req.name, req.name),
                )
                id = cur.fetchone()[0]
                conn.commit()
            except psycopg.errors.UniqueViolation:
                raise HTTPException(status_code=409, detail="店铺已存在")
    return {"id": str(id), "name": req.name, "platform": req.platform}


# ---------- /api/dashboard/summary ----------

def _safe_div(a: float, b: float) -> Optional[float]:
    if not b:
        return None
    return a / b


def _recompute_kpis(totals: Dict[str, float]) -> Dict[str, Any]:
    income = totals.get("valid_merchant_income", 0.0)
    valid_orders = totals.get("valid_order_count", 0.0)
    orders = totals.get("order_count", 0.0)
    promo_spend = totals.get("promo_spend", 0.0)
    product_cost = totals.get("total_product_cost", 0.0)
    logistics_cost = totals.get("total_logistics_cost", 0.0)
    link_profit = totals.get("link_gross_profit", 0.0)
    operating_profit = totals.get("profit_loss", 0.0)

    return {
        **totals,
        "promo_roi": _safe_div(totals.get("promo_gmv", 0.0), promo_spend),
        "real_roi": _safe_div(totals.get("order_gmv", 0.0), promo_spend),
        "ctr": _safe_div(totals.get("clicks", 0.0), totals.get("exposure", 0.0)) * 100 if totals.get("exposure") else None,
        "cpc": _safe_div(promo_spend, totals.get("clicks", 0.0)),
        "cpm": _safe_div(promo_spend, totals.get("exposure", 0.0)) * 1000 if totals.get("exposure") else None,
        "promo_cost_ratio": _safe_div(promo_spend, income) * 100 if income else None,
        "problem_rate": _safe_div(totals.get("refund_count", 0.0) + totals.get("cancel_count", 0.0), orders) * 100 if orders else None,
        "refund_rate": _safe_div(totals.get("refund_count", 0.0), orders) * 100 if orders else None,
        "cancel_rate": _safe_div(totals.get("cancel_count", 0.0), orders) * 100 if orders else None,
        "avg_valid_order_income": _safe_div(income, valid_orders),
        "gross_margin_rate": _safe_div(link_profit, income) * 100 if income else None,
        "profit_loss_rate": _safe_div(operating_profit, income) * 100 if income else None,
    }


@router.get("/dashboard/summary")
def dashboard_summary(
    start_date: date = Query(...),
    end_date: date = Query(...),
    store_names: List[str] = Query(...),
    platform: str = Query("pdd"),
    user: dict = Depends(_require_user),
):
    """V1 兼容：基于 V2 数据聚合生成 dashboard 总览 KPI。"""
    if not store_names:
        raise HTTPException(status_code=400, detail="请至少选择一个店铺")

    base_keys = [
        "promo_spend", "promo_gmv", "promo_orders", "exposure", "clicks",
        "order_count", "valid_order_count", "order_gmv", "valid_order_gmv",
        "merchant_income", "valid_merchant_income",
        "refund_count", "cancel_count",
        "refund_unshipped_count", "refund_shipped_count", "refund_received_count",
        "organic_orders", "organic_gmv", "organic_merchant_income", "organic_valid_order_count",
        "total_product_cost", "total_logistics_cost", "platform_fee", "total_cost",
        "link_gross_profit", "profit_loss",
    ]

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            # 推广日数据聚合
            cur.execute(
                """
                select metric_date, sum(spend), sum(gmv), sum(orders), sum(exposure), sum(clicks)
                from promotion_metrics_daily
                where platform = %s and store_name = any(%s) and metric_date between %s and %s
                group by metric_date
                order by metric_date
                """,
                (platform, store_names, start_date, end_date),
            )
            promo_rows = cur.fetchall()

            # 订单日数据聚合（基于支付日期）
            cur.execute(
                """
                select
                    coalesce(o.payment_time::date, o.created_at::date) as d,
                    count(distinct o.order_id) as order_count,
                    sum(case when not o.is_cancelled then 1 else 0 end) as valid_order_count,
                    sum(coalesce(ocs.total_cost, 0)) as total_cost,
                    sum(coalesce(ocs.product_cost, 0)) as product_cost,
                    sum(coalesce(ocs.shipping_fee, 0)) as shipping_fee
                from platform_orders o
                left join order_cost_snapshots ocs on o.order_id = ocs.order_id
                where o.platform = %s and o.store_name = any(%s)
                  and coalesce(o.payment_time::date, o.created_at::date) between %s and %s
                group by d
                order by d
                """,
                (platform, store_names, start_date, end_date),
            )
            order_rows = cur.fetchall()

    trend_by_date: Dict[str, Dict[str, float]] = {}
    for r in promo_rows:
        d = r[0].isoformat()
        trend_by_date.setdefault(d, {k: 0.0 for k in base_keys})
        trend_by_date[d]["promo_spend"] += float(r[1] or 0)
        trend_by_date[d]["promo_gmv"] += float(r[2] or 0)
        trend_by_date[d]["promo_orders"] += float(r[3] or 0)
        trend_by_date[d]["exposure"] += float(r[4] or 0)
        trend_by_date[d]["clicks"] += float(r[5] or 0)

    for r in order_rows:
        d = r[0].isoformat()
        trend_by_date.setdefault(d, {k: 0.0 for k in base_keys})
        trend_by_date[d]["order_count"] += float(r[1] or 0)
        trend_by_date[d]["valid_order_count"] += float(r[2] or 0)
        trend_by_date[d]["total_cost"] += float(r[3] or 0)
        trend_by_date[d]["total_product_cost"] += float(r[4] or 0)
        trend_by_date[d]["total_logistics_cost"] += float(r[5] or 0)

    # 简化假设：旧版前端需要这些字段才能正常渲染；后续用 V2 真实成本和平台费替换。
    trend_summary = []
    total = {k: 0.0 for k in base_keys}
    for d in sorted(trend_by_date.keys()):
        row = trend_by_date[d]
        row["valid_order_gmv"] = row.get("promo_gmv", 0.0)
        row["order_gmv"] = row.get("promo_gmv", 0.0)
        row["merchant_income"] = row.get("valid_order_gmv", 0.0)
        row["valid_merchant_income"] = row.get("valid_order_gmv", 0.0)
        row["link_gross_profit"] = row.get("valid_merchant_income", 0.0) - row.get("total_product_cost", 0.0)
        row["profit_loss"] = row.get("link_gross_profit", 0.0) - row.get("total_logistics_cost", 0.0)
        row["total_cost"] = row.get("total_product_cost", 0.0) + row.get("total_logistics_cost", 0.0)
        row["platform_fee"] = 0.0
        computed = _recompute_kpis(row)
        computed["date"] = d
        trend_summary.append(computed)
        for k in base_keys:
            total[k] += row.get(k, 0.0)

    summary_kpis = _recompute_kpis(total)

    return {
        "store_count": len(store_names),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "kpis": summary_kpis,
        "trend": trend_summary,
    }



# ---------- 公共工具：V1 店铺权限 / 订单状态判定 / raw_payload 取值 ----------

def _user_allowed_store_names(user: dict, platform: str = "pdd") -> set[str]:
    """从用户 claims 提取允许访问的店铺名集合。

    兼容三种 token 形态：
    - 测试 token：allowed_stores=[]（但 role=master，走全量分支，不会用到本函数结果）
    - V2 token（_load_v2_user）：allowed_stores=[{"platform": ..., "store_name": ...}]
    - V1 形态 JWT：allowed_stores=["店铺A", ...]
    """
    names: set[str] = set()
    for item in user.get("allowed_stores") or []:
        if isinstance(item, dict):
            if item.get("platform") in (None, platform):
                name = item.get("store_name")
                if name:
                    names.add(str(name))
        elif item:
            names.add(str(item))
    return names


def _v1_authorize_stores(user: dict, store_names: List[str]) -> List[str]:
    """V1 auth.authorize_stores 语义：master 返回全部，其余按 allowed_stores 过滤。"""
    if user.get("role") == "master":
        return list(store_names)
    allowed = _user_allowed_store_names(user)
    return [s for s in store_names if s in allowed]


def _v1_authorize_store(user: dict, store_name: str) -> None:
    """V1 auth.authorize_store 语义：无权访问抛 403。"""
    if user.get("role") == "master":
        return
    if store_name not in _user_allowed_store_names(user):
        raise HTTPException(status_code=403, detail="无权访问该店铺")


def _v1_is_refund(order_status: str, aftersales_status: str) -> int:
    """V1 data_processor._is_refund 口径。"""
    if "退款成功" in order_status or "退款成功" in aftersales_status or "售后中" in order_status:
        return 1
    return 0


def _v1_is_cancel(order_status: str) -> int:
    """V1 data_processor._is_cancel 口径。"""
    if any(s in order_status for s in ("已取消", "取消", "交易关闭")):
        return 1
    return 0


def _v1_is_unpaid(order_status: str) -> int:
    """V1 data_processor._is_unpaid 口径。"""
    if "待付款" in order_status or "未付款" in order_status:
        return 1
    return 0


def _v1_refund_stage(order_status: str, confirm_time: str, ship_time: str) -> str:
    """V1 data_processor._classify_refund_stage 口径：unshipped / shipped / received。"""
    if "未发货" in order_status:
        return "unshipped"
    if "已收货" in order_status:
        return "received"
    if "已发货" in order_status:
        return "shipped"
    # 仅售后状态为退款成功但订单状态未明确时，用发货/收货时间推断
    invalid = {"", "-", "NaT", "None", "nan", "\t"}
    if confirm_time not in invalid:
        return "received"
    if ship_time not in invalid:
        return "shipped"
    return "unshipped"


def _raw_text(payload: Optional[dict], *keys: str) -> str:
    """从 raw_payload 取文本值，按候选 key 顺序查找（兼容中英文列名）。

    raw_payload 的 key 形态取决于写入路径：
    - 迁移脚本（scripts/migrate_legacy_to_v2.py）：规范化英文 key（item_total / user_paid / ...）
    - V2 导入接口（v2/test_api.py）：原始中文列名（商品总价(元) / 用户实付金额(元) / ...）
    """
    if not payload:
        return ""
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() not in {"nan", "nat", "none", "null"}:
            return text
    return ""


def _raw_num(payload: Optional[dict], *keys: str) -> float:
    """从 raw_payload 取数值（值可能是 float 也可能是带千分位的文本）。"""
    text = _raw_text(payload, *keys)
    if not text:
        return 0.0
    try:
        return float(text.replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


# V1 平台技术服务费率（与 metrics.PLATFORM_FEE_RATE 一致）：有效商家实收 * 0.6%
_PLATFORM_FEE_RATE = 0.006

# raw_payload 数值/文本候选列名（英文规范化 key 优先，兼容原始中文列名）
_ITEM_TOTAL_KEYS = ("item_total", "商品总价(元)", "商品总价")
_USER_PAID_KEYS = ("user_paid", "用户实付金额(元)", "用户实付", "实付金额")
_MERCHANT_INCOME_KEYS = ("merchant_income", "商家实收金额(元)", "商家实收", "实收金额")
_AFTERSALES_KEYS = ("aftersales_status", "售后状态", "售后")
_ORDER_STATUS_KEYS = ("order_status", "订单状态", "状态")
_PRODUCT_NAME_KEYS = ("product_name", "商品名称", "商品", "商品名")
_STYLE_NAME_KEYS = ("style_name", "商品规格", "规格", "SKU名称", "样式名称")
_MERCHANT_CODE_KEYS = ("merchant_code", "商家编码", "商家代码", "商品编码", "链接编码")
_PAY_TIME_KEYS = ("pay_time", "支付时间", "付款时间")
_ORDER_TIME_KEYS = ("order_time", "订单成交时间", "成交时间", "下单时间")
_SHIP_TIME_KEYS = ("发货时间",)
_CONFIRM_TIME_KEYS = ("确认收货时间",)


# 订单归属日期口径：V1 以订单成交/支付日期归档（parquet 文件日期）。
# 迁移脚本与 V2 导入均把中国本地墙上时间按 UTC 写入 timestamptz，
# 因此 payment_time 需按 UTC 取回原始本地日期；created_at 是真实 UTC 时间，按 Asia/Shanghai 换算。
_ORDER_DATE_SQL = "coalesce(o.payment_time at time zone 'UTC', o.created_at at time zone 'Asia/Shanghai')::date"


def _normalize_id_text(value: Any) -> str:
    """V1 前端 normId 口径：去掉浮点 .0 后缀。"""
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return "" if text.lower() in {"nan", "none", "null"} else text


# ---------- /api/metrics/trend ----------

def _trend_safe_div(a: float, b: float) -> float:
    """V1 metrics.safe_div 口径：分母为 0 返回 0.0。"""
    return (a / b) if b else 0.0


@router.get("/metrics/trend")
def metrics_trend(
    store_names: List[str] = Query(...),
    start_date: date = Query(...),
    end_date: date = Query(...),
    user: dict = Depends(_require_user),
):
    """V1 兼容：拼多多趋势（services.load_trend_data 口径），数据改从 PostgreSQL 聚合。

    数据来源：
    - 推广侧：promotion_metrics_daily（spend/gmv/orders/exposure/clicks，按店铺+日期+商品聚合）
    - 订单侧：platform_orders + platform_order_lines（金额/状态从 raw_payload 按 V1 规则判定）
    - 成本侧：order_cost_snapshots（有效订单的商品成本/物流费）

    与 V1 的关键口径对齐：
    - 退款/取消/有效标记按 V1 data_processor 的状态文本规则逐行计算；
    - 自然流量字段沿用 V1 的“先按商品逐条估算（clip 下限 0）再按日期求和”口径，
      而非按日汇总后直接相减（两者在 promo_gmv > order_gmv 的商品上会有差异）；
    - platform_fee = 有效商家实收 * 0.6%。
    """
    allowed = _v1_authorize_stores(user, store_names)
    if not allowed:
        return []

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            # 推广：按 店铺+日期+商品 聚合（V1 product parquet 是商品粒度）
            cur.execute(
                """
                select store_name, metric_date, product_id,
                       sum(spend), sum(gmv), sum(orders), sum(exposure), sum(clicks)
                from promotion_metrics_daily
                where platform = 'pdd' and store_name = any(%s) and metric_date between %s and %s
                group by store_name, metric_date, product_id
                """,
                (allowed, start_date, end_date),
            )
            promo_rows = cur.fetchall()

            # 订单行：金额/状态需要从 raw_payload 按 V1 规则逐行判定，拉回 Python 聚合
            cur.execute(
                f"""
                select o.store_name, {_ORDER_DATE_SQL} as d, o.order_id,
                       o.order_status, o.is_cancelled,
                       l.product_id, l.quantity, l.raw_payload
                from platform_orders o
                join platform_order_lines l on l.order_id = o.id
                where o.platform = 'pdd' and o.store_name = any(%s)
                  and {_ORDER_DATE_SQL} between %s and %s
                """,
                (allowed, start_date, end_date),
            )
            line_rows = cur.fetchall()

            # 成本快照：按订单号取商品成本/物流费（V2 订单级成本，仅统计有效订单）
            cur.execute(
                f"""
                select o.store_name, {_ORDER_DATE_SQL} as d, o.order_id,
                       ocs.product_cost, ocs.shipping_fee
                from order_cost_snapshots ocs
                join platform_orders o
                  on o.platform = ocs.platform and o.store_name = ocs.store_name
                 and o.order_id = ocs.order_id
                where o.platform = 'pdd' and o.store_name = any(%s)
                  and {_ORDER_DATE_SQL} between %s and %s
                """,
                (allowed, start_date, end_date),
            )
            cost_rows = cur.fetchall()

    # per (store, date, product_key) 商品级聚合，复刻 V1 compute_product_metrics 前的明细行
    products: Dict[tuple, Dict[str, float]] = {}

    def _bucket(store: str, day: str, pid: str) -> Dict[str, float]:
        key = (store, day, pid)
        if key not in products:
            products[key] = {
                "promo_spend": 0.0, "promo_gmv": 0.0, "promo_orders": 0.0,
                "exposure": 0.0, "clicks": 0.0,
                "order_count": 0.0, "valid_order_count": 0.0,
                "quantity": 0.0, "valid_quantity": 0.0,
                "order_gmv": 0.0, "valid_order_gmv": 0.0,
                "merchant_income": 0.0, "valid_merchant_income": 0.0,
                "refund_count": 0.0, "cancel_count": 0.0,
                "refund_unshipped_count": 0.0, "refund_shipped_count": 0.0,
                "refund_received_count": 0.0,
            }
        return products[key]

    for store_name, metric_date, product_id, spend, gmv, orders, exposure, clicks in promo_rows:
        pid = _normalize_id_text(product_id) or "__no_product__"
        b = _bucket(store_name, metric_date.isoformat(), pid)
        b["promo_spend"] += float(spend or 0)
        b["promo_gmv"] += float(gmv or 0)
        b["promo_orders"] += float(orders or 0)
        b["exposure"] += float(exposure or 0)
        b["clicks"] += float(clicks or 0)

    # 记录每个 (store, date) 下含有效行的订单号，用于成本快照去重统计
    valid_order_ids: Dict[tuple, set] = {}

    for store_name, day, order_id, order_status, is_cancelled, product_id, quantity, payload in line_rows:
        day_s = day.isoformat() if hasattr(day, "isoformat") else str(day)
        pid = _normalize_id_text(product_id) or _normalize_id_text(
            _raw_text(payload, "product_id", "商品ID", "商品id")
        ) or "__no_product__"
        status = str(order_status or _raw_text(payload, *_ORDER_STATUS_KEYS) or "")
        aftersales = _raw_text(payload, *_AFTERSALES_KEYS)

        is_refund = _v1_is_refund(status, aftersales)
        # V2 取消接口会置 is_cancelled；导入/迁移数据靠状态文本判定（V1 口径）
        is_cancel = 1 if (is_cancelled or _v1_is_cancel(status)) else 0
        is_unpaid = _v1_is_unpaid(status)
        is_valid = 1 if (not is_refund and not is_cancel and not is_unpaid) else 0

        qty = float(quantity or 0)
        item_total = _raw_num(payload, *_ITEM_TOTAL_KEYS)
        income = _raw_num(payload, *_MERCHANT_INCOME_KEYS)

        b = _bucket(store_name, day_s, pid)
        b["order_count"] += 1.0  # V1: count(order_id)，按订单行计
        b["valid_order_count"] += is_valid
        b["quantity"] += qty
        b["valid_quantity"] += qty * is_valid
        b["order_gmv"] += item_total
        b["valid_order_gmv"] += item_total * is_valid
        b["merchant_income"] += income
        b["valid_merchant_income"] += income * is_valid
        b["refund_count"] += is_refund
        b["cancel_count"] += is_cancel
        if is_refund:
            stage = _v1_refund_stage(
                status,
                _raw_text(payload, *_CONFIRM_TIME_KEYS),
                _raw_text(payload, *_SHIP_TIME_KEYS),
            )
            b[f"refund_{stage}_count"] += 1.0
        if is_valid and order_id:
            valid_order_ids.setdefault((store_name, day_s), set()).add(order_id)

    # 成本：order_cost_snapshots 为订单级金额，按有效订单去重后计入当日。
    # 与 V1 差异：V1 按有效订单行的 商家编码单价 × 件数 计算；快照缺单的订单成本计 0（注释见报告）。
    day_costs: Dict[tuple, Dict[str, float]] = {}
    for store_name, day, order_id, product_cost, shipping_fee in cost_rows:
        day_s = day.isoformat() if hasattr(day, "isoformat") else str(day)
        key = (store_name, day_s)
        if order_id not in valid_order_ids.get(key, set()):
            continue  # V1 口径：退款/取消/未付款订单不计成本
        entry = day_costs.setdefault(key, {"orders": set(), "product": 0.0, "logistics": 0.0})
        if order_id in entry["orders"]:
            continue
        entry["orders"].add(order_id)
        entry["product"] += float(product_cost or 0)
        entry["logistics"] += float(shipping_fee or 0)

    # 按 (store, date) 汇总商品级行：先算 V1 商品级衍生字段（自然流量等），再按日求和
    days: Dict[tuple, Dict[str, float]] = {}

    def _day(store: str, day_s: str) -> Dict[str, float]:
        key = (store, day_s)
        if key not in days:
            days[key] = {
                "promo_spend": 0.0, "promo_gmv": 0.0, "promo_orders": 0.0,
                "exposure": 0.0, "clicks": 0.0,
                "order_count": 0.0, "valid_order_count": 0.0,
                "order_gmv": 0.0, "valid_order_gmv": 0.0,
                "merchant_income": 0.0, "valid_merchant_income": 0.0,
                "platform_fee": 0.0,
                "refund_count": 0.0, "cancel_count": 0.0,
                "refund_unshipped_count": 0.0, "refund_shipped_count": 0.0,
                "refund_received_count": 0.0,
                "organic_orders": 0.0, "organic_gmv": 0.0,
                "organic_merchant_income": 0.0, "organic_valid_order_count": 0.0,
            }
        return days[key]

    for (store_name, day_s, _pid), p in products.items():
        # V1 compute_product_metrics 的商品级衍生字段（clip 下限 0 后再汇总）
        organic_orders = max(p["order_count"] - p["promo_orders"], 0.0)
        organic_gmv = max(p["order_gmv"] - p["promo_gmv"], 0.0)
        promo_income = p["promo_gmv"] * _trend_safe_div(p["valid_merchant_income"], p["order_gmv"])
        organic_income = max(p["valid_merchant_income"] - promo_income, 0.0)
        promo_valid = round(p["promo_orders"] * p["valid_order_count"] / p["order_count"]) if p["order_count"] else 0
        organic_valid = max(p["valid_order_count"] - promo_valid, 0.0)

        d = _day(store_name, day_s)
        for k in ("promo_spend", "promo_gmv", "promo_orders", "exposure", "clicks",
                  "order_count", "valid_order_count", "order_gmv", "valid_order_gmv",
                  "merchant_income", "valid_merchant_income",
                  "refund_count", "cancel_count",
                  "refund_unshipped_count", "refund_shipped_count", "refund_received_count"):
            d[k] += p[k]
        d["platform_fee"] += p["valid_merchant_income"] * _PLATFORM_FEE_RATE
        d["organic_orders"] += organic_orders
        d["organic_gmv"] += organic_gmv
        d["organic_merchant_income"] += organic_income
        d["organic_valid_order_count"] += organic_valid

    # 成本只影响有快照的日期；订单/推广都没有的日期不会产生行
    for (store_name, day_s), cost in day_costs.items():
        d = _day(store_name, day_s)
        d["total_product_cost"] = d.get("total_product_cost", 0.0) + cost["product"]
        d["total_logistics_cost"] = d.get("total_logistics_cost", 0.0) + cost["logistics"]

    rows: List[Dict[str, Any]] = []
    for (store_name, day_s) in sorted(days.keys(), key=lambda k: (k[0], k[1])):
        t = days[(store_name, day_s)]
        total_product_cost = t.get("total_product_cost", 0.0)
        total_logistics_cost = t.get("total_logistics_cost", 0.0)
        total_cost = total_product_cost + total_logistics_cost
        platform_fee = t["platform_fee"]
        income = t["valid_merchant_income"]
        # V1 apply_costs_to_metrics：毛利 = 有效实收 - 总成本 - 平台费；盈亏 = 毛利 - 推广花费
        link_gross_profit = income - total_cost - platform_fee
        profit_loss = link_gross_profit - t["promo_spend"]
        order_count = t["order_count"]

        row: Dict[str, Any] = {"store_name": store_name, "date": day_s}
        # 以下字段顺序与 V1 compute_overall_kpis + compute_cost_kpis 输出保持一致
        row.update({
            "promo_spend": t["promo_spend"],
            "promo_gmv": t["promo_gmv"],
            "order_gmv": t["order_gmv"],
            "valid_order_gmv": t["valid_order_gmv"],
            "merchant_income": t["merchant_income"],
            "valid_merchant_income": income,
            "platform_fee": platform_fee,
            "promo_roi": _trend_safe_div(t["promo_gmv"], t["promo_spend"]),
            "real_roi": _trend_safe_div(income, t["promo_spend"]),
            "valid_order_gmv_roi": _trend_safe_div(t["valid_order_gmv"], t["promo_spend"]),
            "refund_rate": _trend_safe_div(t["refund_count"], order_count) * 100,
            "cancel_rate": _trend_safe_div(t["cancel_count"], order_count) * 100,
            "problem_rate": _trend_safe_div(t["refund_count"] + t["cancel_count"], order_count) * 100,
            "refund_unshipped_rate": _trend_safe_div(t["refund_unshipped_count"], order_count) * 100,
            "refund_shipped_rate": _trend_safe_div(t["refund_shipped_count"], order_count) * 100,
            "refund_received_rate": _trend_safe_div(t["refund_received_count"], order_count) * 100,
            "ctr": _trend_safe_div(t["clicks"], t["exposure"]) * 100,
            "click_to_order_rate": _trend_safe_div(t["promo_orders"], t["clicks"]) * 100,
            "exposure_to_order_rate": _trend_safe_div(t["promo_orders"], t["exposure"]) * 100,
            "cpc": _trend_safe_div(t["promo_spend"], t["clicks"]),
            "cpm": _trend_safe_div(t["promo_spend"], t["exposure"]) * 1000,
            "organic_ratio_gmv": _trend_safe_div(t["organic_gmv"], t["order_gmv"]) * 100,
            "organic_ratio_orders": _trend_safe_div(t["organic_orders"], order_count) * 100,
            "organic_merchant_income": t["organic_merchant_income"],
            "organic_valid_order_count": t["organic_valid_order_count"],
            "organic_ratio_income": _trend_safe_div(t["organic_merchant_income"], income) * 100,
            "organic_ratio_valid_orders": _trend_safe_div(t["organic_valid_order_count"], t["valid_order_count"]) * 100,
            "promo_gmv_ratio": _trend_safe_div(t["promo_gmv"], t["order_gmv"]) * 100,
            "valid_order_gmv_ratio": _trend_safe_div(t["valid_order_gmv"], t["order_gmv"]) * 100,
            "promo_order_ratio": _trend_safe_div(t["promo_orders"], order_count) * 100,
            "promo_cost_ratio": _trend_safe_div(t["promo_spend"], income) * 100,
            "exposure": t["exposure"],
            "clicks": t["clicks"],
            "order_count": order_count,
            "valid_order_count": t["valid_order_count"],
            "promo_orders": t["promo_orders"],
            "organic_orders": t["organic_orders"],
            "organic_gmv": t["organic_gmv"],
            "refund_count": t["refund_count"],
            "cancel_count": t["cancel_count"],
            "refund_unshipped_count": t["refund_unshipped_count"],
            "refund_shipped_count": t["refund_shipped_count"],
            "refund_received_count": t["refund_received_count"],
            # 成本汇总（V1 compute_overall_kpis 的 cost_totals + compute_cost_kpis）
            "total_product_cost": total_product_cost,
            "total_logistics_cost": total_logistics_cost,
            "total_cost": total_cost,
            "link_gross_profit": link_gross_profit,
            "profit_loss": profit_loss,
            "gross_margin_rate": (link_gross_profit / income * 100) if income else 0.0,
            "profit_loss_rate": (profit_loss / income * 100) if income else 0.0,
        })
        rows.append(row)
    return rows


# ---------- /api/orders ----------

@router.get("/dashboard/operations-daily")
def operations_daily(start_date: Optional[date] = Query(None), end_date: Optional[date] = Query(None), store_names: Optional[List[str]] = Query(None), user: dict = Depends(_require_user)):
    """V2-backed operations daily compatibility endpoint."""
    start = start_date or date.today()
    end = end_date or start
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select distinct platform, store_name from platform_stores where is_active=true order by platform, store_name")
            available = cur.fetchall()
    allowed = set(user.get("allowed_stores") or [])
    selected = [(p, s) for p, s in available if (not store_names or s in store_names) and (user.get("role") in {"master", "admin"} or not allowed or s in allowed)]
    dates = [date.fromordinal(n).isoformat() for n in range(start.toordinal(), end.toordinal() + 1)]
    stores = []
    for platform, store_name in selected:
        daily, totals = {}, {}
        for day in dates:
            result = dashboard_summary(date.fromisoformat(day), date.fromisoformat(day), [store_name], platform, user)
            row = result.get("kpis", {})
            daily[day] = row or None
            for key, value in row.items():
                if isinstance(value, (int, float)):
                    totals[key] = totals.get(key, 0) + value
        stores.append({"store_name": store_name, "platform": platform, "totals": totals, "daily": daily})
    total = {"store_name": "全部店铺", "totals": {}, "daily": {}}
    for row in stores:
        for key, value in row["totals"].items():
            if isinstance(value, (int, float)):
                total["totals"][key] = total["totals"].get(key, 0) + value
        for day, metrics in row["daily"].items():
            if metrics:
                bucket = total["daily"].setdefault(day, {})
                for key, value in metrics.items():
                    if isinstance(value, (int, float)):
                        bucket[key] = bucket.get(key, 0) + value
    income = total["totals"].get("valid_merchant_income", 0)
    profit = total["totals"].get("profit_loss", 0)
    return {"start_date": start.isoformat(), "end_date": end.isoformat(), "dates": dates, "summary": total["totals"], "total": total, "stores": stores, "platform_summary": {"income": income, "order_count": total["totals"].get("valid_order_count", 0), "promo_spend": total["totals"].get("promo_spend", 0), "profit_loss": profit, "profit_loss_rate": profit / income * 100 if income else 0, "store_count": len(stores), "platform_count": len(set(p for p, _ in selected)), "data_platform_count": len(set(p for p, _ in selected))}, "platforms": []}


@router.get("/orders")
def list_orders(
    store_name: str = Query(...),
    date: date = Query(...),
    user: dict = Depends(_require_user),
):
    """V1 兼容：订单明细（services.get_orders 口径），数据从 PostgreSQL 读。

    响应形状对齐 V1 orders parquet 的记录（frontend orders.tsx 动态取 Object.keys 渲染，
    前 10 列为默认展示列）：优先从 raw_payload 取原始中文列，缺失字段补 None 占位，
    末尾追加 V1 预处理计算列（is_refund/is_cancel/is_valid 等，按 V1 状态规则重算）。

    数据缺口说明：迁移脚本写入的 raw_payload 只有裁剪子集（product_name/style_name/
    item_total/user_paid/merchant_income/aftersales_status/merchant_code），
    原始中文列（承诺发货时间、快递单号、省市区等）只有经 V2 导入接口写入的数据才完整。
    """
    _v1_authorize_store(user, store_name)

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select o.order_id, o.order_status, o.is_cancelled,
                       o.payment_time at time zone 'UTC' as payment_local,
                       l.product_id, l.style_id, l.quantity, l.raw_payload
                from platform_orders o
                join platform_order_lines l on l.order_id = o.id
                where o.platform = 'pdd' and o.store_name = %s
                  and {_ORDER_DATE_SQL} = %s
                order by payment_local nulls last, o.order_id
                """,
                (store_name, date),
            )
            rows = cur.fetchall()

    records: List[Dict[str, Any]] = []
    for order_id, order_status, is_cancelled, payment_local, product_id, style_id, quantity, payload in rows:
        payload = payload or {}
        status = str(order_status or _raw_text(payload, *_ORDER_STATUS_KEYS) or "")
        aftersales = _raw_text(payload, *_AFTERSALES_KEYS)

        is_refund = _v1_is_refund(status, aftersales)
        is_cancel = 1 if (is_cancelled or _v1_is_cancel(status)) else 0
        is_unpaid = _v1_is_unpaid(status)
        is_valid = 1 if (not is_refund and not is_cancel and not is_unpaid) else 0
        stage = _v1_refund_stage(
            status,
            _raw_text(payload, *_CONFIRM_TIME_KEYS),
            _raw_text(payload, *_SHIP_TIME_KEYS),
        ) if is_refund else ""

        pay_time = _raw_text(payload, *_PAY_TIME_KEYS)
        if not pay_time and payment_local is not None:
            pay_time = payment_local.strftime("%Y-%m-%d %H:%M:%S")

        qty = float(quantity or 0)

        # 列顺序对齐 V1 parquet：前 10 个 key 为前端默认展示列
        record: Dict[str, Any] = {
            "product_name": _raw_text(payload, *_PRODUCT_NAME_KEYS) or None,
            "order_id": order_id,
            "order_status": status or None,
            "quantity": int(qty) if qty == int(qty) else qty,
            "是否先用后付": _raw_text(payload, "是否先用后付") or None,
            "pay_time": pay_time or None,
            "承诺发货时间": _raw_text(payload, "承诺发货时间") or None,
            "承诺送达时间": _raw_text(payload, "承诺送达时间") or None,
            "发货时间": _raw_text(payload, *_SHIP_TIME_KEYS) or None,
            "确认收货时间": _raw_text(payload, *_CONFIRM_TIME_KEYS) or None,
            "product_id": _normalize_id_text(product_id) or _normalize_id_text(
                _raw_text(payload, "product_id", "商品ID", "商品id")
            ) or None,
            "style_name": _raw_text(payload, *_STYLE_NAME_KEYS) or None,
            "style_id": _normalize_id_text(style_id) or _normalize_id_text(
                _raw_text(payload, "style_id", "样式ID", "SKUID")
            ) or None,
            "merchant_code": _raw_text(payload, *_MERCHANT_CODE_KEYS) or None,
            "aftersales_status": aftersales or None,
            "order_time": _raw_text(payload, *_ORDER_TIME_KEYS) or None,
            "item_total": _raw_num(payload, *_ITEM_TOTAL_KEYS),
            "shop_discount": _raw_num(payload, "shop_discount", "店铺优惠折扣(元)", "店铺优惠"),
            "platform_discount": _raw_num(payload, "platform_discount", "平台优惠折扣(元)", "平台优惠"),
            "user_paid": _raw_num(payload, *_USER_PAID_KEYS),
            "merchant_income": _raw_num(payload, *_MERCHANT_INCOME_KEYS),
            "store_name": store_name,
            # V1 预处理计算列（按 V1 状态规则从 PG 数据重算）
            "is_refund": is_refund,
            "is_cancel": is_cancel,
            "is_valid": is_valid,
            "is_unpaid": is_unpaid,
            "is_refund_unshipped": 1 if stage == "unshipped" else 0,
            "is_refund_shipped": 1 if stage == "shipped" else 0,
            "is_refund_received": 1 if stage == "received" else 0,
        }
        # 原始列透传（V2 导入路径下 raw_payload 含完整原始行；不覆盖上面的规范化 key）
        for key, value in payload.items():
            if key not in record:
                record[key] = value
        records.append(record)
    return records


# ---------- /api/metrics/analysis ----------

def _fetch_order_facts(cur, store_names: List[str], start_date: date, end_date: date) -> List[Dict[str, Any]]:
    """拉取订单行并按 V1 规则预计算标记/金额（analysis 与成本回退共用）。

    比 trend 的内联查询多取 warehouse_id / bundle_id / bom_version_id（成本回退需要）。
    """
    cur.execute(
        f"""
        select o.store_name, {_ORDER_DATE_SQL} as d, o.order_id,
               o.order_status, o.is_cancelled, o.warehouse_id,
               l.product_id, l.style_id, l.quantity, l.bundle_id, l.bom_version_id, l.raw_payload
        from platform_orders o
        join platform_order_lines l on l.order_id = o.id
        where o.platform = 'pdd' and o.store_name = any(%s)
          and {_ORDER_DATE_SQL} between %s and %s
        """,
        (store_names, start_date, end_date),
    )
    facts: List[Dict[str, Any]] = []
    for (store_name, day, order_id, order_status, is_cancelled, warehouse_id,
         product_id, style_id, quantity, bundle_id, bom_version_id, payload) in cur.fetchall():
        payload = payload or {}
        day_s = day.isoformat() if hasattr(day, "isoformat") else str(day)
        status = str(order_status or _raw_text(payload, *_ORDER_STATUS_KEYS) or "")
        aftersales = _raw_text(payload, *_AFTERSALES_KEYS)
        is_refund = _v1_is_refund(status, aftersales)
        # V2 取消接口会置 is_cancelled；导入/迁移数据靠状态文本判定（V1 口径）
        is_cancel = 1 if (is_cancelled or _v1_is_cancel(status)) else 0
        is_unpaid = _v1_is_unpaid(status)
        is_valid = 1 if (not is_refund and not is_cancel and not is_unpaid) else 0
        refund_stage = ""
        if is_refund:
            refund_stage = _v1_refund_stage(
                status,
                _raw_text(payload, *_CONFIRM_TIME_KEYS),
                _raw_text(payload, *_SHIP_TIME_KEYS),
            )
        facts.append({
            "store_name": store_name,
            "day": day_s,
            "order_id": order_id,
            "warehouse_id": str(warehouse_id) if warehouse_id else "",
            "product_id": _normalize_id_text(product_id) or _normalize_id_text(
                _raw_text(payload, "product_id", "商品ID", "商品id")
            ),
            "style_id": _normalize_id_text(style_id) or _normalize_id_text(
                _raw_text(payload, "style_id", "样式ID", "SKUID")
            ),
            "quantity": float(quantity or 0),
            "bundle_id": str(bundle_id) if bundle_id else "",
            "bom_version_id": str(bom_version_id) if bom_version_id else "",
            "product_name": _raw_text(payload, *_PRODUCT_NAME_KEYS),
            "style_name": _raw_text(payload, *_STYLE_NAME_KEYS),
            "merchant_code": _raw_text(payload, *_MERCHANT_CODE_KEYS),
            "item_total": _raw_num(payload, *_ITEM_TOTAL_KEYS),
            "user_paid": _raw_num(payload, *_USER_PAID_KEYS),
            "merchant_income": _raw_num(payload, *_MERCHANT_INCOME_KEYS),
            "is_refund": is_refund,
            "is_cancel": is_cancel,
            "is_unpaid": is_unpaid,
            "is_valid": is_valid,
            "refund_stage": refund_stage,
        })
    return facts


def _fetch_snapshot_costs(cur, store_names: List[str], start_date: date, end_date: date) -> Dict[str, tuple]:
    """order_cost_snapshots：order_id -> (product_cost, shipping_fee)。"""
    cur.execute(
        f"""
        select o.order_id, ocs.product_cost, ocs.shipping_fee
        from order_cost_snapshots ocs
        join platform_orders o
          on o.platform = ocs.platform and o.store_name = ocs.store_name
         and o.order_id = ocs.order_id
        where o.platform = 'pdd' and o.store_name = any(%s)
          and {_ORDER_DATE_SQL} between %s and %s
        """,
        (store_names, start_date, end_date),
    )
    return {str(r[0]): (float(r[1] or 0), float(r[2] or 0)) for r in cur.fetchall()}


def _pick_unit_cost(versions: List[tuple], warehouse_id: str, day: date) -> float:
    """从 item_cost_versions 选订单日生效的单价：优先本仓，缺仓取任意仓（注释见报告）。

    versions: [(warehouse_id, unit_cost, effective_from, effective_to), ...]
    """
    def _hit(v) -> bool:
        _, _, ef, et = v
        if ef and ef > day:
            return False
        if et and et < day:
            return False
        return True

    effective = [v for v in versions if _hit(v)]
    if not effective:
        return 0.0
    own = [v for v in effective if v[0] == warehouse_id]
    pool = own or effective
    pool.sort(key=lambda v: (v[2] or date.min), reverse=True)
    return pool[0][1]


def _estimate_fallback_line_costs(cur, facts: List[Dict[str, Any]], snapshot_ids: set) -> Dict[int, tuple]:
    """无 order_cost_snapshots 的有效订单行：按 bom_version_id → bundle_components →
    item_cost_versions（订单日生效版本）估算商品成本，物流费用 bundles.estimated_shipping_fee。

    返回 {fact_index: (product_cost, shipping_fee)}。
    """
    targets = [
        (idx, f) for idx, f in enumerate(facts)
        if f["is_valid"] and f["order_id"] not in snapshot_ids and (f["bom_version_id"] or f["bundle_id"])
    ]
    if not targets:
        return {}

    # 缺 bom_version_id 时用 bundle 的当前 active 版本兜底
    bundle_ids = list({f["bundle_id"] for _, f in targets if not f["bom_version_id"] and f["bundle_id"]})
    if bundle_ids:
        cur.execute(
            "select id, bundle_id from bundle_versions where bundle_id = any(%s::uuid[]) and status = 'active' order by version_no desc",
            (bundle_ids,),
        )
        bv_by_bundle: Dict[str, str] = {}
        for bv_id, b_id in cur.fetchall():
            bv_by_bundle.setdefault(str(b_id), str(bv_id))
        for _, f in targets:
            if not f["bom_version_id"] and f["bundle_id"]:
                f["bom_version_id"] = bv_by_bundle.get(f["bundle_id"], "")

    version_ids = list({f["bom_version_id"] for _, f in targets if f["bom_version_id"]})
    if not version_ids:
        return {}

    cur.execute(
        "select bundle_version_id, item_id, quantity from bundle_components where bundle_version_id = any(%s::uuid[])",
        (version_ids,),
    )
    comps: Dict[str, List[tuple]] = {}
    for bv, item, q in cur.fetchall():
        comps.setdefault(str(bv), []).append((str(item), float(q or 0)))
    item_ids = list({item for rows in comps.values() for item, _ in rows})
    if not item_ids:
        return {}

    cur.execute(
        "select item_id, warehouse_id, unit_cost, effective_from, effective_to from item_cost_versions where item_id = any(%s::uuid[])",
        (item_ids,),
    )
    versions: Dict[str, List[tuple]] = {}
    for item, wh, cost, ef, et in cur.fetchall():
        versions.setdefault(str(item), []).append((str(wh) if wh else "", float(cost or 0), ef, et))

    cur.execute(
        "select bv.id, b.estimated_shipping_fee from bundle_versions bv join bundles b on b.id = bv.bundle_id where bv.id = any(%s::uuid[])",
        (version_ids,),
    )
    ship = {str(bv): float(fee or 0) for bv, fee in cur.fetchall()}

    result: Dict[int, tuple] = {}
    for idx, f in targets:
        bv = f["bom_version_id"]
        if not bv or bv not in comps:
            continue
        day = date.fromisoformat(f["day"])
        unit_cost = 0.0
        for item, comp_qty in comps[bv]:
            unit_cost += comp_qty * _pick_unit_cost(versions.get(item, []), f["warehouse_id"], day)
        result[idx] = (unit_cost * f["quantity"], ship.get(bv, 0.0) * f["quantity"])
    return result


def _v1_product_derived(p: Dict[str, float]) -> Dict[str, Any]:
    """V1 compute_product_metrics 的全部商品级衍生字段（safe_div 分母 0 -> 0.0）。"""
    div = _trend_safe_div
    organic_orders = max(p["order_count"] - p["promo_orders"], 0.0)
    organic_gmv = max(p["order_gmv"] - p["promo_gmv"], 0.0)
    promo_income = p["promo_gmv"] * div(p["valid_merchant_income"], p["order_gmv"])
    organic_income = max(p["valid_merchant_income"] - promo_income, 0.0)
    promo_valid = round(p["promo_orders"] * p["valid_order_count"] / p["order_count"]) if p["order_count"] else 0
    organic_valid = max(p["valid_order_count"] - promo_valid, 0.0)
    return {
        "promo_roi": div(p["promo_gmv"], p["promo_spend"]),
        "promo_cost_per_order": div(p["promo_spend"], p["promo_orders"]),
        "ctr": div(p["clicks"], p["exposure"]) * 100,
        "click_to_order_rate": div(p["promo_orders"], p["clicks"]) * 100,
        "exposure_to_order_rate": div(p["promo_orders"], p["exposure"]) * 100,
        "cpc": div(p["promo_spend"], p["clicks"]),
        "cpm": div(p["promo_spend"], p["exposure"]) * 1000,
        "promo_gmv_ratio": div(p["promo_gmv"], p["order_gmv"]) * 100,
        "valid_order_gmv_ratio": div(p["valid_order_gmv"], p["order_gmv"]) * 100,
        "promo_order_ratio": div(p["promo_orders"], p["order_count"]) * 100,
        "refund_rate": div(p["refund_count"], p["order_count"]) * 100,
        "cancel_rate": div(p["cancel_count"], p["order_count"]) * 100,
        "problem_rate": div(p["refund_count"] + p["cancel_count"], p["order_count"]) * 100,
        "refund_unshipped_rate": div(p["refund_unshipped_count"], p["order_count"]) * 100,
        "refund_shipped_rate": div(p["refund_shipped_count"], p["order_count"]) * 100,
        "refund_received_rate": div(p["refund_received_count"], p["order_count"]) * 100,
        "real_roi_merchant_income": div(p["valid_merchant_income"], p["promo_spend"]),
        "valid_order_gmv_roi": div(p["valid_order_gmv"], p["promo_spend"]),
        "promo_cost_ratio": div(p["promo_spend"], p["valid_merchant_income"]) * 100,
        "organic_orders": organic_orders,
        "organic_gmv": organic_gmv,
        "organic_ratio_gmv": div(organic_gmv, p["order_gmv"]) * 100,
        "organic_ratio_orders": div(organic_orders, p["order_count"]) * 100,
        "promo_merchant_income": promo_income,
        "organic_merchant_income": organic_income,
        "organic_ratio_income": div(organic_income, p["valid_merchant_income"]) * 100,
        "promo_valid_order_count": promo_valid,
        "organic_valid_order_count": organic_valid,
        "organic_ratio_valid_orders": div(organic_valid, p["valid_order_count"]) * 100,
        "avg_order_gmv": div(p["order_gmv"], p["order_count"]),
        "avg_valid_order_gmv": div(p["valid_order_gmv"], p["valid_order_count"]),
        "avg_order_income": div(p["merchant_income"], p["order_count"]),
        "avg_valid_order_income": div(p["valid_merchant_income"], p["valid_order_count"]),
        "platform_fee": p["valid_merchant_income"] * _PLATFORM_FEE_RATE,
    }


_ORDER_AGG_KEYS = (
    "order_count", "valid_order_count", "quantity", "valid_quantity",
    "order_gmv", "valid_order_gmv", "user_paid", "valid_user_paid",
    "merchant_income", "valid_merchant_income",
    "refund_count", "cancel_count",
    "refund_unshipped_count", "refund_shipped_count", "refund_received_count",
)


def _new_order_bucket() -> Dict[str, float]:
    return {k: 0.0 for k in _ORDER_AGG_KEYS}


def _accumulate_order_fact(bucket: Dict[str, float], f: Dict[str, Any]) -> None:
    """把一条订单行事实累加进聚合桶（V1 aggregate_orders_by_* 口径）。"""
    valid = f["is_valid"]
    bucket["order_count"] += 1.0  # V1: count(order_id)，按订单行计
    bucket["valid_order_count"] += valid
    bucket["quantity"] += f["quantity"]
    bucket["valid_quantity"] += f["quantity"] * valid
    bucket["order_gmv"] += f["item_total"]
    bucket["valid_order_gmv"] += f["item_total"] * valid
    bucket["user_paid"] += f["user_paid"]
    bucket["valid_user_paid"] += f["user_paid"] * valid
    bucket["merchant_income"] += f["merchant_income"]
    bucket["valid_merchant_income"] += f["merchant_income"] * valid
    bucket["refund_count"] += f["is_refund"]
    bucket["cancel_count"] += f["is_cancel"]
    if f["refund_stage"]:
        bucket[f"refund_{f['refund_stage']}_count"] += 1.0


@router.get("/metrics/analysis")
def metrics_analysis(
    store_name: str = Query(...),
    start_date: date = Query(...),
    end_date: date = Query(...),
    user: dict = Depends(_require_user),
):
    """V1 兼容：指标分析（services.load_analysis_data 口径），数据从 PostgreSQL 聚合。

    响应形状：{"product_metrics": [...], "style_metrics": [...], "kpis": {...}}。

    数据来源：
    - 推广侧：promotion_metrics_daily 按商品聚合；
    - 订单侧：platform_orders ⋈ platform_order_lines，状态/金额按 V1 规则逐行判定；
    - 成本侧：order_cost_snapshots 优先（多行订单按有效件数占比分摊到商品，近似口径）；
      无快照的有效订单行按 bom_version_id → bundle_components → item_cost_versions
      （订单日生效版本）回退估算，物流费 = bundles.estimated_shipping_fee × 件数。

    与 V1 的已知差异（保形状填 0 的字段）：
    - product_cost_unit / logistics_cost_unit：V1 是成本配置的单价，V2 快照是订单级金额，
      无法反推配置单价，保 key 填 0（前端商品明细不展示这两列）；
    - merchant_code 只取订单 raw_payload 里的商家编码，V1 的手动映射/历史反查回退未迁移。
    """
    _v1_authorize_store(user, store_name)

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            # 推广：按商品聚合（附带商品名用于展示）
            cur.execute(
                """
                select product_id,
                       sum(spend), sum(gmv), sum(orders), sum(exposure), sum(clicks),
                       max(raw_payload->>'product_name')
                from promotion_metrics_daily
                where platform = 'pdd' and store_name = %s and metric_date between %s and %s
                group by product_id
                """,
                (store_name, start_date, end_date),
            )
            promo_rows = cur.fetchall()

            facts = _fetch_order_facts(cur, [store_name], start_date, end_date)
            snapshots = _fetch_snapshot_costs(cur, [store_name], start_date, end_date)
            fallback_costs = _estimate_fallback_line_costs(cur, facts, set(snapshots.keys()))

    if not promo_rows and not facts:
        return {"product_metrics": [], "style_metrics": [], "kpis": {}}

    # ---- 商品级聚合（V1：先按商品汇总基础字段，再算衍生，再挂成本）----
    products: Dict[str, Dict[str, Any]] = {}

    def _p_bucket(pid: str) -> Dict[str, Any]:
        if pid not in products:
            products[pid] = {
                "promo_spend": 0.0, "promo_gmv": 0.0, "promo_orders": 0.0,
                "exposure": 0.0, "clicks": 0.0,
                **_new_order_bucket(),
                "_names": [],  # 商品名拼接（V1: " / ".join(unique)）
                "_merchant_code": "",
                "total_product_cost": 0.0, "total_logistics_cost": 0.0,
            }
        return products[pid]

    for product_id, spend, gmv, orders, exposure, clicks, promo_name in promo_rows:
        pid = _normalize_id_text(product_id) or "__no_product__"
        b = _p_bucket(pid)
        b["promo_spend"] += float(spend or 0)
        b["promo_gmv"] += float(gmv or 0)
        b["promo_orders"] += float(orders or 0)
        b["exposure"] += float(exposure or 0)
        b["clicks"] += float(clicks or 0)
        if promo_name and promo_name not in b["_names"]:
            b["_names"].append(promo_name)

    # 每个订单的有效件数（快照成本按有效件数占比分摊到商品）
    order_valid_qty: Dict[str, float] = {}
    for f in facts:
        if f["is_valid"] and f["order_id"]:
            order_valid_qty[f["order_id"]] = order_valid_qty.get(f["order_id"], 0.0) + f["quantity"]

    styles: Dict[tuple, Dict[str, Any]] = {}
    for idx, f in enumerate(facts):
        pid = f["product_id"] or "__no_product__"
        b = _p_bucket(pid)
        _accumulate_order_fact(b, f)
        if f["product_name"] and f["product_name"] not in b["_names"]:
            b["_names"].append(f["product_name"])
        if f["merchant_code"] and not b["_merchant_code"]:
            b["_merchant_code"] = f["merchant_code"]

        # 成本：快照优先，按有效件数占比分摊；无快照走 BOM 回退估算
        if f["is_valid"]:
            if f["order_id"] in snapshots:
                total_qty = order_valid_qty.get(f["order_id"], 0.0)
                share = (f["quantity"] / total_qty) if total_qty else 0.0
                snap_pc, snap_ship = snapshots[f["order_id"]]
                b["total_product_cost"] += snap_pc * share
                b["total_logistics_cost"] += snap_ship * share
            elif idx in fallback_costs:
                pc, ship = fallback_costs[idx]
                b["total_product_cost"] += pc
                b["total_logistics_cost"] += ship

        # 规格级聚合（V1 compute_style_metrics 口径：仅订单侧）
        skey = (pid, f["style_id"], f["product_name"], f["style_name"])
        if skey not in styles:
            styles[skey] = _new_order_bucket()
        _accumulate_order_fact(styles[skey], f)

    # ---- 组装 product_metrics（key 集合对齐 V1 aggregate+compute+apply_costs 输出）----
    product_metrics: List[Dict[str, Any]] = []
    totals = _new_order_bucket()
    totals.update({
        "promo_spend": 0.0, "promo_gmv": 0.0, "promo_orders": 0.0,
        "exposure": 0.0, "clicks": 0.0, "platform_fee": 0.0,
        "organic_orders": 0.0, "organic_gmv": 0.0,
        "organic_merchant_income": 0.0, "organic_valid_order_count": 0.0,
        "total_product_cost": 0.0, "total_logistics_cost": 0.0,
        "total_cost": 0.0, "link_gross_profit": 0.0, "profit_loss": 0.0,
    })

    for pid, b in products.items():
        derived = _v1_product_derived(b)
        income = b["valid_merchant_income"]
        platform_fee = derived["platform_fee"]
        total_product_cost = b["total_product_cost"]
        total_logistics_cost = b["total_logistics_cost"]
        total_cost = total_product_cost + total_logistics_cost
        # V1 apply_costs_to_metrics：毛利 = 有效实收 - 总成本 - 平台费；盈亏 = 毛利 - 推广花费
        link_gross_profit = income - total_cost - platform_fee
        profit_loss = link_gross_profit - b["promo_spend"]

        record: Dict[str, Any] = {
            "product_id": pid,
            "product_name": " / ".join(b["_names"]),
            "promo_spend": b["promo_spend"],
            "promo_gmv": b["promo_gmv"],
            "promo_orders": b["promo_orders"],
            "exposure": b["exposure"],
            "clicks": b["clicks"],
            **{k: b[k] for k in _ORDER_AGG_KEYS},
            **derived,
            "merchant_code": b["_merchant_code"],
            # 保形状填 0：V1 为成本配置单价，V2 无法从订单级快照反推（见 docstring）
            "product_cost_unit": 0.0,
            "logistics_cost_unit": 0.0,
            "cost_quantity": b["valid_quantity"],
            "total_product_cost": total_product_cost,
            "total_logistics_cost": total_logistics_cost,
            "total_cost": total_cost,
            "link_gross_profit": link_gross_profit,
            "profit_loss": profit_loss,
            "gross_margin_rate": (link_gross_profit / income * 100) if income else 0.0,
            "profit_loss_rate": (profit_loss / income * 100) if income else 0.0,
        }
        product_metrics.append(record)

        for k in _ORDER_AGG_KEYS:
            totals[k] += b[k]
        for k in ("promo_spend", "promo_gmv", "promo_orders", "exposure", "clicks"):
            totals[k] += b[k]
        totals["platform_fee"] += platform_fee
        totals["organic_orders"] += derived["organic_orders"]
        totals["organic_gmv"] += derived["organic_gmv"]
        totals["organic_merchant_income"] += derived["organic_merchant_income"]
        totals["organic_valid_order_count"] += derived["organic_valid_order_count"]
        totals["total_product_cost"] += total_product_cost
        totals["total_logistics_cost"] += total_logistics_cost
        totals["total_cost"] += total_cost
        totals["link_gross_profit"] += link_gross_profit
        totals["profit_loss"] += profit_loss

    # 排序与 V1 一致（groupby product_id 默认按 key 排序）
    product_metrics.sort(key=lambda r: r["product_id"])

    # ---- style_metrics（V1 compute_style_metrics 输出列）----
    style_metrics: List[Dict[str, Any]] = []
    for (pid, sid, pname, sname), s in styles.items():
        div = _trend_safe_div
        style_metrics.append({
            "product_id": pid,
            "product_name": pname or None,
            "style_id": sid or None,
            "style_name": sname or None,
            **{k: s[k] for k in _ORDER_AGG_KEYS},
            "refund_rate": div(s["refund_count"], s["order_count"]) * 100,
            "cancel_rate": div(s["cancel_count"], s["order_count"]) * 100,
            "refund_unshipped_rate": div(s["refund_unshipped_count"], s["order_count"]) * 100,
            "refund_shipped_rate": div(s["refund_shipped_count"], s["order_count"]) * 100,
            "refund_received_rate": div(s["refund_received_count"], s["order_count"]) * 100,
            "avg_order_gmv": div(s["order_gmv"], s["order_count"]),
            "avg_valid_order_gmv": div(s["valid_order_gmv"], s["valid_order_count"]),
            "avg_order_income": div(s["merchant_income"], s["order_count"]),
            "avg_valid_order_income": div(s["valid_merchant_income"], s["valid_order_count"]),
        })
    style_metrics.sort(key=lambda r: (r["product_id"], r["style_id"] or ""))

    # ---- kpis（V1 compute_overall_kpis 口径，基于商品级汇总值重算比率）----
    income = totals["valid_merchant_income"]
    link_profit = totals["link_gross_profit"]
    kpis = {
        "promo_spend": totals["promo_spend"],
        "promo_gmv": totals["promo_gmv"],
        "order_gmv": totals["order_gmv"],
        "valid_order_gmv": totals["valid_order_gmv"],
        "merchant_income": totals["merchant_income"],
        "valid_merchant_income": income,
        "platform_fee": totals["platform_fee"],
        "promo_roi": _trend_safe_div(totals["promo_gmv"], totals["promo_spend"]),
        "real_roi": _trend_safe_div(income, totals["promo_spend"]),
        "valid_order_gmv_roi": _trend_safe_div(totals["valid_order_gmv"], totals["promo_spend"]),
        "refund_rate": _trend_safe_div(totals["refund_count"], totals["order_count"]) * 100,
        "cancel_rate": _trend_safe_div(totals["cancel_count"], totals["order_count"]) * 100,
        "problem_rate": _trend_safe_div(totals["refund_count"] + totals["cancel_count"], totals["order_count"]) * 100,
        "refund_unshipped_rate": _trend_safe_div(totals["refund_unshipped_count"], totals["order_count"]) * 100,
        "refund_shipped_rate": _trend_safe_div(totals["refund_shipped_count"], totals["order_count"]) * 100,
        "refund_received_rate": _trend_safe_div(totals["refund_received_count"], totals["order_count"]) * 100,
        "ctr": _trend_safe_div(totals["clicks"], totals["exposure"]) * 100,
        "click_to_order_rate": _trend_safe_div(totals["promo_orders"], totals["clicks"]) * 100,
        "exposure_to_order_rate": _trend_safe_div(totals["promo_orders"], totals["exposure"]) * 100,
        "cpc": _trend_safe_div(totals["promo_spend"], totals["clicks"]),
        "cpm": _trend_safe_div(totals["promo_spend"], totals["exposure"]) * 1000,
        "organic_ratio_gmv": _trend_safe_div(totals["organic_gmv"], totals["order_gmv"]) * 100,
        "organic_ratio_orders": _trend_safe_div(totals["organic_orders"], totals["order_count"]) * 100,
        "organic_merchant_income": totals["organic_merchant_income"],
        "organic_valid_order_count": totals["organic_valid_order_count"],
        "organic_ratio_income": _trend_safe_div(totals["organic_merchant_income"], income) * 100,
        "organic_ratio_valid_orders": _trend_safe_div(totals["organic_valid_order_count"], totals["valid_order_count"]) * 100,
        "promo_gmv_ratio": _trend_safe_div(totals["promo_gmv"], totals["order_gmv"]) * 100,
        "valid_order_gmv_ratio": _trend_safe_div(totals["valid_order_gmv"], totals["order_gmv"]) * 100,
        "promo_order_ratio": _trend_safe_div(totals["promo_orders"], totals["order_count"]) * 100,
        "promo_cost_ratio": _trend_safe_div(totals["promo_spend"], income) * 100,
        "exposure": totals["exposure"],
        "clicks": totals["clicks"],
        "order_count": totals["order_count"],
        "valid_order_count": totals["valid_order_count"],
        "promo_orders": totals["promo_orders"],
        "organic_orders": totals["organic_orders"],
        "organic_gmv": totals["organic_gmv"],
        "refund_count": totals["refund_count"],
        "cancel_count": totals["cancel_count"],
        "refund_unshipped_count": totals["refund_unshipped_count"],
        "refund_shipped_count": totals["refund_shipped_count"],
        "refund_received_count": totals["refund_received_count"],
        "total_product_cost": totals["total_product_cost"],
        "total_logistics_cost": totals["total_logistics_cost"],
        "total_cost": totals["total_cost"],
        "link_gross_profit": link_profit,
        "profit_loss": totals["profit_loss"],
        "gross_margin_rate": (link_profit / income * 100) if income else 0.0,
        "profit_loss_rate": (totals["profit_loss"] / income * 100) if income else 0.0,
    }

    return {"product_metrics": product_metrics, "style_metrics": style_metrics, "kpis": kpis}


# ---------- /api/imports ----------

# V1 批次表（V1 形状的导入批次记录；数据本体在 data_import_batches/platform_orders/promotion_metrics_daily，
# 本表只保存 V1 前端需要的批次元数据与回滚状态）。
_V1_IMPORT_BATCHES_DDL = """
create table if not exists v1_import_batches (
    batch_id varchar(64) primary key,
    platform varchar(32) not null default 'pdd',
    store_name varchar(255) not null,
    import_date date,
    imported_by varchar(128),
    status varchar(16) not null default 'importing'
        check (status in ('importing','imported','rolled_back','failed','invalidated')),
    promo_filename varchar(512) not null default '',
    order_filename varchar(512) not null default '',
    promo_hash char(64),
    order_hash char(64),
    stats jsonb not null default '{}'::jsonb,
    affected_dates jsonb not null default '[]'::jsonb,
    pg_promo_batch_id uuid references data_import_batches(id),
    pg_order_batch_id uuid references data_import_batches(id),
    error text,
    created_at timestamptz not null default now(),
    completed_at timestamptz,
    rolled_back_at timestamptz,
    rolled_back_by varchar(128)
)
"""


def _ensure_v1_import_tables(cur) -> None:
    cur.execute(_V1_IMPORT_BATCHES_DDL)


def _actor_name(user: dict) -> str:
    return user.get("sub") or user.get("username") or "unknown"


def _parse_upload_files(promo_bytes, promo_filename, order_bytes, order_filename):
    """用 V1 data_loader 的解析逻辑读上传文件（懒加载，避免模块级引入 pandas）。"""
    import io as _io

    from data_loader import read_order_file, read_promotion_file

    promo_df = None
    order_df = None
    if promo_bytes:
        f = _io.BytesIO(promo_bytes)
        f.name = promo_filename or "promo.xlsx"
        promo_df, _ = read_promotion_file(f)
    if order_bytes:
        f = _io.BytesIO(order_bytes)
        f.name = order_filename or "order.csv"
        order_df, _ = read_order_file(f)
    return promo_df, order_df


def _order_dates_series(order_df):
    """V1 data_processor.extract_order_dates：订单实际成交/支付日期（yyyy-mm-dd 或 None）。"""
    from data_processor import extract_order_dates

    return extract_order_dates(order_df)


def _v1_payment_times(order_df, import_date: date) -> Dict[str, Optional[datetime]]:
    """按 V1 口径为每个订单计算支付时间（写入 platform_orders.payment_time）。

    口径：order_time 优先，其次 pay_time，再退到订单号前 6 位日期；
    非取消但完全无法解析日期的订单归到 import_date 零点（V1 里归入用户选择的导入日期，
    PG 没有独立的归属日期列，借 payment_time 承载，属合成值）。
    返回值是“中国墙上时间按 UTC 存储”的约定（与本文件 _ORDER_DATE_SQL 读取口径一致）。
    """
    from scripts.migrate_legacy_to_v2 import parse_datetime

    dates = _order_dates_series(order_df)
    result: Dict[str, Optional[datetime]] = {}
    for order_id, group in order_df.groupby("order_id", sort=False):
        oid = str(order_id)
        first = group.iloc[0]
        dt = parse_datetime(first.get("order_time")) or parse_datetime(first.get("pay_time"))
        if dt is None:
            d = dates.loc[group.index[0]]
            if d is not None and str(d) != "NaT":
                dt = datetime.strptime(str(d), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            else:
                status = str(first.get("order_status") or "")
                if _v1_is_cancel(status):
                    result[oid] = None  # 已取消且无日期：V1 直接丢弃
                    continue
                dt = datetime(import_date.year, import_date.month, import_date.day, tzinfo=timezone.utc)
        result[oid] = dt
    return result


def _pg_order_locations(cur, store_name: str, order_ids: List[str]) -> Dict[str, str]:
    """查询已存在订单当前的归属日期：order_id -> yyyy-mm-dd。"""
    if not order_ids:
        return {}
    cur.execute(
        f"""
        select o.order_id, {_ORDER_DATE_SQL}::text
        from platform_orders o
        where o.platform = 'pdd' and o.store_name = %s and o.order_id = any(%s)
        """,
        (store_name, order_ids),
    )
    return {str(r[0]): str(r[1]) for r in cur.fetchall()}


def _build_preview(store_name: str, import_date: date, promo_df, order_df,
                   promo_hash, order_hash, promo_filename, order_filename,
                   existing_locations: Dict[str, str], duplicate) -> Dict[str, Any]:
    """复刻 services.preview_daily_import 的统计与响应形状。"""
    import pandas as pd

    import_date_str = import_date.isoformat()
    blockers: List[str] = []
    warnings: List[str] = []
    affected_dates = {import_date_str} if promo_df is not None else set()
    order_stats: Dict[str, Any] = {
        "total_rows": 0, "valid_orders": 0, "new_orders": 0, "existing_orders": 0,
        "migrated_orders": 0, "duplicate_order_ids": 0, "missing_order_ids": 0,
        "unresolved_dates": 0,
    }

    if duplicate:
        created = duplicate.get("created_at") or ""
        blockers.append(f"相同文件已于 {created} 导入，批次 {str(duplicate.get('batch_id', ''))[:8]}")

    if promo_df is not None and promo_df.empty:
        blockers.append("推广文件没有可导入的数据")

    if order_df is not None:
        order_stats["total_rows"] = len(order_df)
        if "order_id" not in order_df.columns:
            order_stats["missing_order_ids"] = len(order_df)
            blockers.append("订单文件缺少订单号列")
        else:
            ids = order_df["order_id"].astype("string").str.strip()
            missing_ids = ids.isna() | ids.isin(["", "nan", "None", "<NA>"])
            order_stats["missing_order_ids"] = int(missing_ids.sum())
            if missing_ids.any():
                blockers.append(f"有 {int(missing_ids.sum())} 行缺少订单号")

            valid_df = order_df.loc[~missing_ids].copy()
            valid_df["order_id"] = ids.loc[~missing_ids].astype(str)
            duplicate_ids = int(valid_df["order_id"].duplicated().sum())
            order_stats["duplicate_order_ids"] = duplicate_ids
            if duplicate_ids:
                blockers.append(f"文件内有 {duplicate_ids} 条重复订单号，请先清理文件")

            parsed_dates = _order_dates_series(valid_df)
            if "order_status" in valid_df.columns:
                cancelled = valid_df["order_status"].astype(str).str.contains("取消|交易关闭", na=False, regex=True)
            else:
                cancelled = pd.Series(False, index=valid_df.index)
            unresolved = parsed_dates.isna() & ~cancelled
            order_stats["unresolved_dates"] = int(unresolved.sum())
            if unresolved.any():
                blockers.append(f"有 {int(unresolved.sum())} 条非取消订单无法识别日期")

            accepted = valid_df.loc[~(parsed_dates.isna() & cancelled)].copy()
            accepted_dates = parsed_dates.loc[accepted.index].dropna()
            affected_dates.update(str(value) for value in accepted_dates.unique())
            unique_ids = set(accepted["order_id"].astype(str))
            order_stats["valid_orders"] = len(unique_ids)
            if not unique_ids:
                blockers.append("订单文件没有可导入的有效订单")

            uploaded_ids = set(valid_df["order_id"].astype(str))
            incoming_locations = {
                str(accepted.loc[index, "order_id"]): str(parsed_dates.loc[index])
                for index in accepted.index
                if pd.notna(parsed_dates.loc[index])
            }
            existing_ids = uploaded_ids.intersection(existing_locations)
            migrated_ids = {
                oid for oid in existing_ids
                if incoming_locations.get(oid) and incoming_locations[oid] != existing_locations[oid]
            }
            affected_dates.update(existing_locations[oid] for oid in existing_ids)
            order_stats["existing_orders"] = len(existing_ids)
            order_stats["new_orders"] = len(unique_ids - existing_ids)
            order_stats["migrated_orders"] = len(migrated_ids)
            if migrated_ids:
                warnings.append(f"有 {len(migrated_ids)} 条订单将从原日期迁移")

    return {
        "store_name": store_name,
        "import_date": import_date_str,
        "promo_filename": promo_filename or "",
        "order_filename": order_filename or "",
        "promo_hash": promo_hash,
        "order_hash": order_hash,
        "orders": order_stats,
        "affected_dates": sorted(affected_dates),
        "blockers": blockers,
        "warnings": warnings,
        "can_import": not blockers,
    }


def _find_duplicate_v1_batch(cur, store_name: str, promo_hash, order_hash):
    """V1 find_duplicate_batch 口径：同店铺 status=imported 且双 hash 相同的批次。"""
    cur.execute(
        """
        select batch_id, created_at from v1_import_batches
        where store_name = %s and status = 'imported'
          and promo_hash is not distinct from %s and order_hash is not distinct from %s
        order by created_at desc limit 1
        """,
        (store_name, promo_hash, order_hash),
    )
    row = cur.fetchone()
    return {"batch_id": row[0], "created_at": row[1].isoformat()} if row else None


def _load_bundle_maps(cur) -> tuple:
    """merchant_code -> bundle_id / active bom_version_id。"""
    cur.execute(
        """
        select b.code, b.id, bv.id
        from bundles b
        left join lateral (
            select id from bundle_versions bv
            where bv.bundle_id = b.id and bv.status = 'active'
            order by bv.version_no desc limit 1
        ) bv on true
        where b.is_active = true
        """
    )
    bundles: Dict[str, str] = {}
    bundle_versions: Dict[str, str] = {}
    for code, bundle_id, bv_id in cur.fetchall():
        bundles[code] = bundle_id
        if bv_id:
            bundle_versions[code] = bv_id
    return bundles, bundle_versions


def _load_listing_style_map(cur, platform: str = "pdd") -> Dict[str, str]:
    """V2 platform_listing_mappings -> V1 风格的 "product_id::style_id" -> merchant_code 映射。"""
    cur.execute(
        """
        select m.product_id, m.style_id, b.code
        from platform_listing_mappings m
        join bundles b on b.id = m.bundle_id
        where m.platform = %s and m.style_id is not null
        """,
        (platform,),
    )
    return {f"{pid}::{sid}": code for pid, sid, code in cur.fetchall()}


def _store_warehouse_id(cur, store_name: str, on_date: date):
    """店铺当天生效的仓库；无配置时回退默认仓 KUNSHAN（与迁移脚本一致）。"""
    cur.execute(
        """
        select warehouse_id from store_warehouse_assignments
        where platform = 'pdd' and store_name = %s and effective_from <= %s
          and (effective_to is null or effective_to >= %s)
        order by effective_from desc limit 1
        """,
        (store_name, on_date, on_date),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("select id from warehouses where code = 'KUNSHAN'")
    row = cur.fetchone()
    if not row:
        raise ValueError("仓库配置缺失：KUNSHAN")
    return row[0]


@router.post("/imports/preview")
def import_preview(
    store_name: str = Form(...),
    import_date: date = Form(...),
    promo_file: Optional[UploadFile] = File(None),
    order_file: Optional[UploadFile] = File(None),
    user: dict = Depends(_require_user),
):
    """V1 兼容：导入前检查（services.preview_daily_import 口径，PG 版）。"""
    _v1_authorize_store(user, store_name)
    if not promo_file and not order_file:
        raise HTTPException(status_code=400, detail="请至少上传推广数据或订单数据中的一个")

    import hashlib

    promo_bytes = promo_file.file.read() if promo_file else None
    order_bytes = order_file.file.read() if order_file else None
    promo_hash = hashlib.sha256(promo_bytes).hexdigest() if promo_bytes else None
    order_hash = hashlib.sha256(order_bytes).hexdigest() if order_bytes else None

    try:
        promo_df, order_df = _parse_upload_files(
            promo_bytes, promo_file.filename if promo_file else None,
            order_bytes, order_file.filename if order_file else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            _ensure_v1_import_tables(cur)
            duplicate = _find_duplicate_v1_batch(cur, store_name, promo_hash, order_hash)
            if order_df is not None and "order_id" in order_df.columns:
                ids = order_df["order_id"].astype("string").str.strip()
                valid_ids = sorted(set(ids[~ids.isna() & ~ids.isin(["", "nan", "None", "<NA>"])].astype(str)))
                existing_locations = _pg_order_locations(cur, store_name, valid_ids)
            else:
                existing_locations = {}

    return _build_preview(
        store_name, import_date, promo_df, order_df,
        promo_hash, order_hash,
        (promo_file.filename or "") if promo_file else "",
        (order_file.filename or "") if order_file else "",
        existing_locations, duplicate,
    )


@router.post("/imports")
def import_daily(
    store_name: str = Form(...),
    import_date: date = Form(...),
    promo_file: Optional[UploadFile] = File(None),
    order_file: Optional[UploadFile] = File(None),
    user: dict = Depends(_require_user),
):
    """V1 兼容：上传导入（orders + promo），写路径改为 PostgreSQL。

    落库逻辑复用 scripts/migrate_legacy_to_v2.py 抽出的 insert_orders_frame / insert_promo_frame：
    - 订单按 (platform, store_name, order_id) upsert（覆盖导入=更新状态/时间/明细行），
      并把 import_batch_id 重指向本次批次，使“回滚 = 删除该批次的行”可工作
      （与 V1 快照恢复不同：被覆盖的旧订单在回滚后整体删除而非恢复旧版本，见报告）；
    - 推广按店铺+日期先删后插（V1 语义：新文件覆盖当天推广数据）；
    - 批次记录写入 v1_import_batches（V1 形状）+ data_import_batches（PG 审计）。
    """
    import hashlib
    import uuid as _uuid

    from psycopg.types.json import Json
    from scripts.migrate_legacy_to_v2 import insert_orders_frame, insert_promo_frame

    _v1_authorize_store(user, store_name)
    if not promo_file and not order_file:
        return {"error": "请至少上传推广数据或订单数据中的一个"}

    actor = _actor_name(user)
    promo_bytes = promo_file.file.read() if promo_file else None
    order_bytes = order_file.file.read() if order_file else None
    promo_hash = hashlib.sha256(promo_bytes).hexdigest() if promo_bytes else None
    order_hash = hashlib.sha256(order_bytes).hexdigest() if order_bytes else None
    promo_filename = (promo_file.filename or "") if promo_file else ""
    order_filename = (order_file.filename or "") if order_file else ""

    try:
        promo_df, order_df = _parse_upload_files(promo_bytes, promo_filename, order_bytes, order_filename)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    original_order_rows = len(order_df) if order_df is not None else 0
    batch_id = _uuid.uuid4().hex

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                _ensure_v1_import_tables(cur)

                # 预览校验（含重复批次检测与订单统计），blockers 非空则拒绝导入
                if order_df is not None and "order_id" in order_df.columns:
                    ids = order_df["order_id"].astype("string").str.strip()
                    valid_ids = sorted(set(ids[~ids.isna() & ~ids.isin(["", "nan", "None", "<NA>"])].astype(str)))
                    existing_locations = _pg_order_locations(cur, store_name, valid_ids)
                else:
                    existing_locations = {}
                duplicate = _find_duplicate_v1_batch(cur, store_name, promo_hash, order_hash)
                preview = _build_preview(
                    store_name, import_date, promo_df, order_df,
                    promo_hash, order_hash, promo_filename, order_filename,
                    existing_locations, duplicate,
                )
                if not preview["can_import"]:
                    raise ValueError("；".join(preview["blockers"]))

                warehouse_id = _store_warehouse_id(cur, store_name, import_date)
                bundles, bundle_versions = _load_bundle_maps(cur)
                style_map = _load_listing_style_map(cur)

                results: List[Dict[str, Any]] = []
                pg_promo_batch = None
                pg_order_batch = None

                # ---- 推广：新文件整体覆盖当天（V1 save_daily_promo 覆盖 parquet 的语义）----
                if promo_df is not None and not promo_df.empty:
                    cur.execute(
                        """
                        insert into data_import_batches (platform, store_name, data_type, source_filename, source_sha256, period_from, period_to, status, row_count, created_by)
                        values ('pdd', %s, 'promotions', %s, %s, %s, %s, 'processing', %s, %s)
                        returning id
                        """,
                        (store_name, promo_filename, promo_hash, import_date, import_date, len(promo_df), actor),
                    )
                    pg_promo_batch = cur.fetchone()[0]
                    cur.execute(
                        "delete from promotion_metrics_daily where platform = 'pdd' and store_name = %s and metric_date = %s and import_batch_id <> %s",
                        (store_name, import_date, pg_promo_batch),
                    )
                    inserted = insert_promo_frame(
                        cur, batch_id=pg_promo_batch, platform="pdd", store_name=store_name,
                        metric_date=import_date, frame=promo_df,
                    )
                    cur.execute(
                        "update data_import_batches set status='succeeded', row_count=%s, completed_at=now() where id=%s",
                        (inserted, pg_promo_batch),
                    )
                    results.append({"date": import_date.isoformat(), "promo_saved": True, "orders_saved": False, "computed": False})

                # ---- 订单：按 V1 口径解析归属时间后 upsert ----
                order_dates_rows: Dict[str, int] = {}
                if order_df is not None and not order_df.empty and "order_id" in order_df.columns:
                    payment_times = _v1_payment_times(order_df, import_date)
                    accepted_df = order_df[order_df["order_id"].astype(str).isin(
                        {oid for oid, ts in payment_times.items() if ts is not None}
                    )].copy()

                    cur.execute(
                        """
                        insert into data_import_batches (platform, store_name, data_type, source_filename, source_sha256, period_from, period_to, status, row_count, created_by)
                        values ('pdd', %s, 'orders', %s, %s, %s, %s, 'processing', %s, %s)
                        returning id
                        """,
                        (store_name, order_filename, order_hash,
                         min((ts.date() for ts in payment_times.values() if ts), default=import_date),
                         max((ts.date() for ts in payment_times.values() if ts), default=import_date),
                         len(accepted_df), actor),
                    )
                    pg_order_batch = cur.fetchone()[0]

                    inserted = insert_orders_frame(
                        cur,
                        batch_id=pg_order_batch,
                        platform="pdd",
                        store_name=store_name,
                        frame=accepted_df,
                        style_map=style_map,
                        bundles=bundles,
                        bundle_versions=bundle_versions,
                        warehouse_id=warehouse_id,
                        reassign_batch=True,
                        full_payload=True,
                        payment_times=payment_times,
                    )
                    cur.execute(
                        "update data_import_batches set status='succeeded', row_count=%s, completed_at=now() where id=%s",
                        (inserted, pg_order_batch),
                    )
                    for oid, ts in payment_times.items():
                        if ts is None:
                            continue
                        day_s = ts.date().isoformat()
                        order_dates_rows[day_s] = order_dates_rows.get(day_s, 0) + 1
                    for day_s in sorted(order_dates_rows):
                        results.append({
                            "date": day_s,
                            # V2 指标是查询时即时计算的，没有每日 product/style 落库，product_rows/style_rows 填 0
                            "product_rows": 0, "style_rows": 0,
                            "order_rows": order_dates_rows[day_s],
                            "promo_saved": False, "orders_saved": True, "computed": False,
                        })

                processed_dates = sorted({r["date"] for r in results})

                # ---- V1 批次记录 ----
                cur.execute(
                    """
                    insert into v1_import_batches
                        (batch_id, store_name, import_date, imported_by, status,
                         promo_filename, order_filename, promo_hash, order_hash,
                         stats, affected_dates, pg_promo_batch_id, pg_order_batch_id, completed_at)
                    values (%s, %s, %s, %s, 'imported', %s, %s, %s, %s, %s, %s, %s, %s, now())
                    """,
                    (batch_id, store_name, import_date, actor,
                     promo_filename, order_filename, promo_hash, order_hash,
                     Json(preview["orders"]), Json(preview["affected_dates"]),
                     pg_promo_batch, pg_order_batch),
                )
            conn.commit()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        # 记录失败批次（V1 也会留下 failed 批次记录）
        try:
            from psycopg.types.json import Json as _Json
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    _ensure_v1_import_tables(cur)
                    cur.execute(
                        """
                        insert into v1_import_batches
                            (batch_id, store_name, import_date, imported_by, status,
                             promo_filename, order_filename, promo_hash, order_hash, error, completed_at)
                        values (%s, %s, %s, %s, 'failed', %s, %s, %s, %s, %s, now())
                        on conflict (batch_id) do nothing
                        """,
                        (batch_id, store_name, import_date, actor,
                         promo_filename, order_filename, promo_hash, order_hash, str(exc)[:500]),
                    )
                conn.commit()
        except Exception:
            pass
        raise

    return {
        "store_name": store_name,
        "import_date": import_date.isoformat(),
        "original_order_rows": original_order_rows,
        "processed_dates": processed_dates,
        # V2 无每日指标落库（查询时即时计算），保形状填 0
        "product_rows": 0,
        "order_rows": sum(order_dates_rows.values()),
        "promo_saved": promo_df is not None and not promo_df.empty,
        "results": results,
        # V1 会把新商家编码刷新到成本配置；V2 成本走 bundles/item_cost_versions，该自动刷新未迁移（TODO）
        "refreshed_codes": 0,
        "batch_id": batch_id,
        "preview": preview,
    }


def _v1_batch_dict(row: Dict[str, Any], latest_by_store: Dict[str, str], actor: str, is_master: bool) -> Dict[str, Any]:
    """V1 services.get_import_batches 的输出形状（含 can_rollback / rollback_reason）。"""
    item = {
        "batch_id": row["batch_id"],
        "store_name": row["store_name"],
        "import_date": row["import_date"].isoformat() if hasattr(row["import_date"], "isoformat") else row["import_date"],
        "imported_by": row["imported_by"],
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"],
        "status": row["status"],
        "promo_filename": row["promo_filename"],
        "order_filename": row["order_filename"],
        "stats": row["stats"] or {},
        "affected_dates": row["affected_dates"] or [],
    }
    is_latest = latest_by_store.get(row["store_name"]) == row["batch_id"]
    owns_batch = row.get("imported_by") == actor
    item["can_rollback"] = row["status"] == "imported" and is_latest and (is_master or owns_batch)
    if row["status"] != "imported":
        item["rollback_reason"] = "该批次已撤销或已失效"
    elif not is_latest:
        item["rollback_reason"] = "只能撤销该店铺最近一次成功导入"
    elif not is_master and not owns_batch:
        item["rollback_reason"] = "只能撤销自己导入的批次"
    else:
        item["rollback_reason"] = ""
    return item


@router.get("/imports/batches")
def list_import_batches_v1(
    store_name: Optional[str] = Query(None),
    user: dict = Depends(_require_user),
):
    """V1 兼容：导入批次列表。"""
    if store_name:
        _v1_authorize_store(user, store_name)
    actor = _actor_name(user)
    is_master = user.get("role") == "master"

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            _ensure_v1_import_tables(cur)
            sql = """
                select batch_id, store_name, import_date, imported_by, created_at, status,
                       promo_filename, order_filename, stats, affected_dates
                from v1_import_batches
            """
            params: List[Any] = []
            if store_name:
                sql += " where store_name = %s"
                params.append(store_name)
            sql += " order by created_at desc"
            cur.execute(sql, params)
            rows = _row_dict(cur)

    latest_by_store: Dict[str, str] = {}
    for row in rows:
        if row["status"] == "imported" and row["store_name"] not in latest_by_store:
            latest_by_store[row["store_name"]] = row["batch_id"]

    result = [_v1_batch_dict(row, latest_by_store, actor, is_master) for row in rows]
    if is_master:
        return result
    allowed = _user_allowed_store_names(user)
    return [r for r in result if r["store_name"] in allowed]


@router.post("/imports/batches/{batch_id}/rollback")
def rollback_import_batch_v1(batch_id: str, user: dict = Depends(_require_user)):
    """V1 兼容：回滚 = 删除该批次写入的 PG 行（订单行随 platform_orders 级联删除）。

    与 V1 差异：V1 恢复快照（被覆盖的旧数据可还原）；PG 无快照，被本批次覆盖过的
    旧订单在回滚后被整体删除。仅限该店铺最近一次成功导入（与 V1 一致）。
    """
    actor = _actor_name(user)
    is_master = user.get("role") == "master"

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            _ensure_v1_import_tables(cur)
            cur.execute(
                """
                select batch_id, store_name, status, imported_by, affected_dates,
                       pg_promo_batch_id, pg_order_batch_id
                from v1_import_batches where batch_id = %s
                """,
                (batch_id,),
            )
            rows = _row_dict(cur)
            if not rows:
                raise HTTPException(status_code=404, detail="导入批次不存在")
            target = rows[0]
            _v1_authorize_store(user, target["store_name"])
            if target["status"] != "imported":
                raise HTTPException(status_code=409, detail="该导入批次当前不可撤销")
            if not is_master and target.get("imported_by") != actor:
                raise HTTPException(status_code=403, detail="只能撤销自己导入的批次")
            cur.execute(
                """
                select batch_id from v1_import_batches
                where store_name = %s and status = 'imported'
                order by created_at desc limit 1
                """,
                (target["store_name"],),
            )
            latest = cur.fetchone()
            if not latest or str(latest[0]) != batch_id:
                raise HTTPException(status_code=409, detail="只能撤销该店铺最近一次成功导入")

            deleted_orders = 0
            deleted_promo = 0
            if target.get("pg_order_batch_id"):
                cur.execute(
                    "delete from platform_orders where import_batch_id = %s",
                    (target["pg_order_batch_id"],),
                )
                deleted_orders = cur.rowcount
                cur.execute(
                    "update data_import_batches set status='rolled_back', completed_at=now() where id=%s",
                    (target["pg_order_batch_id"],),
                )
            if target.get("pg_promo_batch_id"):
                cur.execute(
                    "delete from promotion_metrics_daily where import_batch_id = %s",
                    (target["pg_promo_batch_id"],),
                )
                deleted_promo = cur.rowcount
                cur.execute(
                    "update data_import_batches set status='rolled_back', completed_at=now() where id=%s",
                    (target["pg_promo_batch_id"],),
                )
            cur.execute(
                "update v1_import_batches set status='rolled_back', rolled_back_at=now(), rolled_back_by=%s where batch_id=%s",
                (actor, batch_id),
            )
        conn.commit()

    return {
        "rolled_back": True,
        "batch_id": batch_id,
        "store_name": target["store_name"],
        "affected_dates": target.get("affected_dates") or [],
        "deleted_orders": deleted_orders,
        "deleted_promo_rows": deleted_promo,
    }


@router.get("/imports/records")
def list_import_records_v1(
    store_name: Optional[str] = Query(None),
    user: dict = Depends(_require_user),
):
    """V1 兼容：每日数据记录（master 的“整日数据管理”列表）。

    V1 从 meta.json 读 product_rows/style_rows（每日指标落库的行数）；V2 指标即时计算，
    这里用当日 distinct 商品数/规格数近似，saved_at 取覆盖该日期的最近批次时间。
    """
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select o.store_name, {_ORDER_DATE_SQL}::text as d,
                       count(*) as order_rows,
                       count(distinct l.product_id) as products,
                       count(distinct l.style_id) as styles
                from platform_orders o
                join platform_order_lines l on l.order_id = o.id
                where o.platform = 'pdd'
                group by o.store_name, d
                """,
            )
            order_days = cur.fetchall()
            cur.execute(
                """
                select store_name, metric_date::text as d, count(*) as promo_rows,
                       count(distinct product_id) as products
                from promotion_metrics_daily where platform = 'pdd'
                group by store_name, metric_date
                """,
            )
            promo_days = cur.fetchall()
            cur.execute(
                """
                select store_name, data_type, source_filename, period_from, period_to, created_at
                from data_import_batches
                where platform = 'pdd' and status in ('succeeded', 'partial')
                order by created_at desc
                """,
            )
            batches = cur.fetchall()

    records: Dict[tuple, Dict[str, Any]] = {}

    def _rec(store: str, day: str) -> Dict[str, Any]:
        key = (store, day)
        if key not in records:
            records[key] = {
                "store_name": store, "date": day, "saved_at": "",
                "product_rows": 0, "style_rows": 0, "order_rows": 0,
                "promo_file": "", "order_file": "",
            }
        return records[key]

    for store, day, order_rows, products, styles in order_days:
        r = _rec(store, day)
        r["order_rows"] += int(order_rows)
        r["_pcount_orders"] = int(products)
        r["_scount"] = int(styles)
    for store, day, promo_rows, products in promo_days:
        r = _rec(store, day)
        r["_pcount_promo"] = int(products)

    for r in records.values():
        # product_rows/style_rows 近似：订单侧与推广侧 distinct 商品数取大者
        r["product_rows"] = max(r.get("_pcount_orders", 0), r.get("_pcount_promo", 0))
        r["style_rows"] = r.get("_scount", 0)

    for store, data_type, filename, period_from, period_to, created_at in batches:
        if period_from is None:
            continue
        end = period_to or period_from
        for r in records.values():
            if r["store_name"] != store:
                continue
            d = date.fromisoformat(r["date"])
            if period_from <= d <= end:
                ts = created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
                if ts > r["saved_at"]:
                    r["saved_at"] = ts
                if data_type == "orders" and not r["order_file"]:
                    r["order_file"] = filename or ""
                if data_type == "promotions" and not r["promo_file"]:
                    r["promo_file"] = filename or ""

    result = []
    for r in records.values():
        r.pop("_pcount_orders", None)
        r.pop("_pcount_promo", None)
        r.pop("_scount", None)
        result.append(r)
    result.sort(key=lambda r: (r["store_name"], r["date"]))

    if store_name:
        _v1_authorize_store(user, store_name)
        result = [r for r in result if r["store_name"] == store_name]
    if user.get("role") == "master":
        return result
    allowed = _user_allowed_store_names(user)
    return [r for r in result if r["store_name"] in allowed]


def _require_master_v1(user: dict) -> None:
    """V1 auth.require_master 语义。"""
    if user.get("role") != "master":
        raise HTTPException(status_code=403, detail="权限不足")


@router.delete("/imports/records/{store_name}/{day}")
def delete_record_v1(store_name: str, day: date, user: dict = Depends(_require_user)):
    """V1 兼容：删除整日数据（master），并使该店铺所有成功批次失效（V1 语义）。"""
    _require_master_v1(user)
    _v1_authorize_store(user, store_name)
    actor = _actor_name(user)

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            _ensure_v1_import_tables(cur)
            cur.execute(
                f"delete from platform_orders o where o.platform='pdd' and o.store_name=%s and {_ORDER_DATE_SQL} = %s",
                (store_name, day),
            )
            cur.execute(
                "delete from promotion_metrics_daily where platform='pdd' and store_name=%s and metric_date=%s",
                (store_name, day),
            )
            cur.execute(
                "update v1_import_batches set status='invalidated' where store_name=%s and status='imported'",
                (store_name,),
            )
        conn.commit()
    return {"deleted": True, "store_name": store_name, "date": day.isoformat()}


def _cleanup_counts_v1(cur, store_name: str, day: date) -> Dict[str, Any]:
    """V1 _cleanup_counts 的 PG 版。"""
    cur.execute(
        f"""
        select count(*), count(distinct l.product_id), count(distinct l.style_id)
        from platform_orders o join platform_order_lines l on l.order_id = o.id
        where o.platform='pdd' and o.store_name=%s and {_ORDER_DATE_SQL} = %s
        """,
        (store_name, day),
    )
    order_rows, products, styles = cur.fetchone()
    cur.execute(
        "select count(*) from promotion_metrics_daily where platform='pdd' and store_name=%s and metric_date=%s",
        (store_name, day),
    )
    promo_rows = cur.fetchone()[0]
    return {
        "store_name": store_name,
        "date": day.isoformat(),
        "order_rows": int(order_rows),
        "promo_rows": int(promo_rows),
        "product_rows": int(products),
        "style_rows": int(styles),
        "has_orders": int(order_rows) > 0,
        "has_promo": int(promo_rows) > 0,
    }


@router.get("/imports/cleanup/preview")
def cleanup_preview_v1(store_name: str = Query(...), date: date = Query(...), user: dict = Depends(_require_user)):
    """V1 兼容：清理前预览（master）。"""
    _require_master_v1(user)
    _v1_authorize_store(user, store_name)
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            return _cleanup_counts_v1(cur, store_name, date)


@router.post("/imports/cleanup")
def cleanup_v1(
    store_name: str = Form(...),
    date: date = Form(...),
    cleanup_type: str = Form(...),
    confirm_text: str = Form(...),
    user: dict = Depends(_require_user),
):
    """V1 兼容：精确清理（master）。V2 指标即时计算，无需 V1 的“删后重算落库”步骤。"""
    _require_master_v1(user)
    _v1_authorize_store(user, store_name)
    if cleanup_type not in {"orders", "promo", "all"}:
        raise HTTPException(status_code=409, detail="清理类型必须是 orders、promo 或 all")
    expected = f"{store_name} {date.isoformat()}"
    if confirm_text != expected:
        raise HTTPException(status_code=400, detail=f"请输入“{expected}”确认清理")
    actor = _actor_name(user)

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            _ensure_v1_import_tables(cur)
            before = _cleanup_counts_v1(cur, store_name, date)
            if not before["has_orders"] and not before["has_promo"]:
                raise HTTPException(status_code=409, detail=f"{store_name} {date.isoformat()} 没有可清理的数据")
            if cleanup_type in {"orders", "all"}:
                cur.execute(
                    f"delete from platform_orders o where o.platform='pdd' and o.store_name=%s and {_ORDER_DATE_SQL} = %s",
                    (store_name, date),
                )
            if cleanup_type in {"promo", "all"}:
                cur.execute(
                    "delete from promotion_metrics_daily where platform='pdd' and store_name=%s and metric_date=%s",
                    (store_name, date),
                )
            cur.execute(
                "update v1_import_batches set status='invalidated' where store_name=%s and status='imported' and affected_dates ? %s",
                (store_name, date.isoformat()),
            )
            after = _cleanup_counts_v1(cur, store_name, date)
        conn.commit()

    audit = {
        "action": "cleanup",
        "cleanup_type": cleanup_type,
        "store_name": store_name,
        "date": date.isoformat(),
        "actor": actor,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "before": before,
        "after": after,
    }
    # 审计日志沿用 V1 的本地 jsonl（轻量、无 PG 表）
    try:
        import json as _json
        from pathlib import Path as _Path

        audit_file = _Path("data/cleanup_audit.jsonl")
        audit_file.parent.mkdir(parents=True, exist_ok=True)
        with audit_file.open("a", encoding="utf-8") as fh:
            fh.write(_json.dumps(audit, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return audit
