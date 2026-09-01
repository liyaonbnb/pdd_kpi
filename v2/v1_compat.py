from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Header
from pydantic import BaseModel
import psycopg

from v2.test_api import DATABASE_URL, TEST_TOKEN, _verify_auth_token, _verify_jwt, _load_v2_user, _safe_user

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

