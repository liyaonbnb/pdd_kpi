"""
抖音业务服务层
"""

import datetime
import json as _json
from pathlib import Path as _Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import wecom as wecom_sender
from wecom_report_drafts import create_report_draft, get_report_draft, mark_report_draft_sent

from douyin_loader import read_order_file, read_promotion_file
from douyin_metrics import aggregate_product_metrics, build_product_metrics_from_orders, compute_overall_kpis
from douyin_cost_manager import apply_costs_to_metrics, compute_cost_kpis, refresh_global_cost_codes
from douyin_storage import (
    delete_daily_data,
    list_available_dates,
    list_douyin_records,
    load_daily_data,
    save_daily_data,
)
from services import bump_data_version, cached_with_ttl


def _date_str(d: datetime.date) -> str:
    return d.strftime("%Y-%m-%d")


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.integer, np.floating, np.bool_)):
        return obj.item()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if pd.isna(obj):
        return None
    return obj


def _build_order_summary(orders_df: pd.DataFrame) -> pd.DataFrame:
    """按商品汇总订单数据，作为商品指标的业务数据基准。"""
    if orders_df is None or orders_df.empty:
        return pd.DataFrame(
            columns=[
                "product_id", "product_name", "order_gmv", "order_actual_revenue",
                "order_count", "valid_order_count", "quantity", "valid_quantity",
                "refund_orders", "refund_amount",
            ]
        )

    df = orders_df.copy()
    df["product_id"] = df["product_id"].astype(str)
    # 过滤空商品ID
    df = df[df["product_id"].str.strip() != ""].copy()
    if df.empty:
        return pd.DataFrame(
            columns=[
                "product_id", "product_name", "order_gmv", "order_actual_revenue",
                "order_count", "valid_order_count", "quantity", "valid_quantity",
                "refund_orders", "refund_amount",
            ]
        )
    df["amount"] = pd.to_numeric(df.get("amount", 0), errors="coerce").fillna(0)
    df["actual_revenue"] = pd.to_numeric(df.get("actual_revenue", 0), errors="coerce").fillna(0)
    df["quantity"] = pd.to_numeric(df.get("quantity", 0), errors="coerce").fillna(0)

    # 标记有效订单与退款订单
    df["is_valid"] = True
    df["is_refund"] = False
    if "order_status" in df.columns:
        invalid_mask = df["order_status"].astype(str).str.contains("关闭|取消|交易关闭", na=False)
        df.loc[invalid_mask, "is_valid"] = False
        df.loc[invalid_mask, "is_refund"] = True
    if "aftersale_status" in df.columns:
        refund_mask = df["aftersale_status"].astype(str).str.contains("退款成功", na=False)
        df.loc[refund_mask, "is_valid"] = False
        df.loc[refund_mask, "is_refund"] = True

    grouped = (
        df.groupby("product_id")
        .agg(
            product_name=("product_name", lambda x: x.dropna().astype(str).iloc[0] if len(x) else ""),
            order_gmv=("amount", "sum"),
            order_actual_revenue=("actual_revenue", "sum"),
            order_count=("order_id", "size"),
            quantity=("quantity", "sum"),
            valid_order_gmv=("amount", lambda x: x[df.loc[x.index, "is_valid"]].sum()),
            valid_order_count=("order_id", lambda x: x[df.loc[x.index, "is_valid"]].size),
            valid_quantity=("quantity", lambda x: x[df.loc[x.index, "is_valid"]].sum()),
            refund_orders=("order_id", lambda x: x[df.loc[x.index, "is_refund"]].size),
            refund_amount=("amount", lambda x: x[df.loc[x.index, "is_refund"]].sum()),
        )
        .reset_index()
    )
    for col in ["valid_order_gmv", "valid_order_count", "valid_quantity", "refund_orders", "refund_amount"]:
        grouped[col] = pd.to_numeric(grouped[col], errors="coerce").fillna(0)
    return grouped


def _merge_order_metrics(product_df: pd.DataFrame, orders_df: pd.DataFrame) -> pd.DataFrame:
    """
    将订单数据合并到商品指标中。
    当订单数据存在时，订单是业务指标（GMV/订单数/实际收入/数量）的基准；
    推广指标（消耗/曝光/点击/退款订单数）仍以推广数据为准。
    """
    order_summary = _build_order_summary(orders_df)

    # 只有订单数据时，直接用订单汇总作为商品指标
    if product_df is None or product_df.empty:
        if order_summary.empty:
            return pd.DataFrame()
        result = order_summary.rename(columns={
            "order_gmv": "gmv",
            "order_actual_revenue": "actual_revenue",
            "valid_order_gmv": "valid_gmv",
        })
        result["spend"] = 0.0
        result["exposure"] = 0.0
        result["clicks"] = 0.0
        # 退款指标已从订单汇总中计算
        refund_orders_col = result.get("refund_orders", 0)
        refund_amount_col = result.get("refund_amount", 0)
        result["refund_orders"] = refund_orders_col.fillna(0) if hasattr(refund_orders_col, "fillna") else float(refund_orders_col)
        result["refund_amount"] = refund_amount_col.fillna(0) if hasattr(refund_amount_col, "fillna") else float(refund_amount_col)
        return result

    df = product_df.copy()
    df["product_id"] = df["product_id"].astype(str)

    if order_summary.empty:
        for col in ["actual_revenue", "quantity", "valid_quantity"]:
            if col not in df.columns:
                df[col] = 0.0
        return df

    order_summary = order_summary.copy()
    order_summary["product_id"] = order_summary["product_id"].astype(str)

    # 删除会被订单数据覆盖/补充的列（包括旧数据里可能残留的 order_* 列）
    for col in [
        "gmv", "valid_gmv", "order_count", "valid_order_count", "actual_revenue",
        "quantity", "valid_quantity", "refund_orders", "refund_amount",
        "order_gmv", "order_actual_revenue", "valid_order_gmv",
    ]:
        if col in df.columns:
            df = df.drop(columns=[col])

    merged = df.merge(order_summary, on="product_id", how="outer")

    # 商品名称：优先用推广数据的，缺失时补订单里的
    if "product_name_x" in merged.columns and "product_name_y" in merged.columns:
        merged["product_name"] = merged["product_name_x"].replace("", pd.NA).fillna(merged["product_name_y"]).fillna("").astype(str)
        merged = merged.drop(columns=["product_name_x", "product_name_y"])
    elif "product_name_y" in merged.columns:
        merged["product_name"] = merged["product_name_y"]
        merged = merged.drop(columns=["product_name_y"])

    # 业务指标以订单为准
    def _safe_fill(col):
        return col.fillna(0) if hasattr(col, "fillna") else float(col)

    merged["gmv"] = _safe_fill(merged.get("order_gmv", 0))
    merged["valid_gmv"] = _safe_fill(merged.get("valid_order_gmv", 0))
    merged["order_count"] = _safe_fill(merged.get("order_count", 0))
    merged["valid_order_count"] = _safe_fill(merged.get("valid_order_count", 0))
    merged["actual_revenue"] = _safe_fill(merged.get("order_actual_revenue", 0))
    merged["quantity"] = _safe_fill(merged.get("quantity", 0))
    merged["valid_quantity"] = _safe_fill(merged.get("valid_quantity", 0))
    # 退款指标：推广数据缺失时用订单数据兜底
    refund_orders_col = merged.get("refund_orders", 0)
    refund_amount_col = merged.get("refund_amount", 0)
    merged["refund_orders"] = refund_orders_col.fillna(0) if hasattr(refund_orders_col, "fillna") else float(refund_orders_col)
    merged["refund_amount"] = refund_amount_col.fillna(0) if hasattr(refund_amount_col, "fillna") else float(refund_amount_col)

    # 推广指标缺失时填 0
    for col in ["spend", "exposure", "clicks"]:
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0)
        else:
            merged[col] = 0.0

    return merged


def _merge_merchant_code_from_orders(product_df: pd.DataFrame, orders_df: pd.DataFrame) -> pd.DataFrame:
    """把订单中的商家编码合并到商品指标（取每个商品出现次数最多的编码）。"""
    if product_df is None or product_df.empty:
        return product_df
    df = product_df.copy()
    if orders_df is None or orders_df.empty or "merchant_code" not in orders_df.columns:
        return df
    mc = orders_df[orders_df["merchant_code"].astype(str).str.strip() != ""]
    if mc.empty:
        return df
    mode = mc.groupby("product_id")["merchant_code"].agg(lambda x: x.mode().iloc[0] if not x.mode().empty else "").reset_index()
    if "merchant_code" in df.columns:
        df = df.drop(columns=["merchant_code"])
    df = df.merge(mode, on="product_id", how="left")
    df["merchant_code"] = df["merchant_code"].fillna("").astype(str)
    return df


def import_douyin_daily_data(
    store_name: str,
    import_date: Optional[datetime.date] = None,
    promo_bytes: Optional[bytes] = None,
    promo_filename: Optional[str] = None,
    order_bytes: Optional[bytes] = None,
    order_filename: Optional[str] = None,
) -> Dict[str, Any]:
    """导入抖音每日数据。

    支持两种文件：
    - 单日文件：只包含一个日期，按该日期保存。
    - 全数据文件：包含多个日期，自动按日期拆分保存。
    """
    processed_dates: set = set()
    total_product_rows = 0
    total_order_rows = 0

    if promo_bytes:
        promo_df = read_promotion_file(promo_bytes, promo_filename or "promo.xlsx")
        if not promo_df.empty:
            # 如果指定了日期且文件里有该日期，优先按指定日期处理；否则处理文件内所有日期
            promo_dates = promo_df["date"].dropna().unique()
            if import_date and _date_str(import_date) in promo_dates:
                promo_dates = [_date_str(import_date)]
            for d in promo_dates:
                day_df = promo_df[promo_df["date"] == d]
                if day_df.empty:
                    continue
                existing_orders = load_daily_data(store_name, d)[1]
                meta = {
                    "promo_file": promo_filename or "",
                    "order_file": order_filename or "",
                    "product_rows": len(day_df),
                    "order_rows": len(existing_orders),
                    "saved_at": datetime.datetime.now().isoformat(),
                }
                save_daily_data(store_name, d, day_df, existing_orders, meta=meta)
                processed_dates.add(d)
                total_product_rows += len(day_df)

    if order_bytes:
        order_df = read_order_file(order_bytes, order_filename or "order.csv")
        if not order_df.empty:
            order_dates = order_df["order_date"].dropna().unique()
            if import_date and _date_str(import_date) in order_dates:
                order_dates = [_date_str(import_date)]
            for d in order_dates:
                day_orders = order_df[order_df["order_date"] == d]
                if day_orders.empty:
                    continue
                existing_product = load_daily_data(store_name, d)[0]
                # 把订单数据合并到商品指标：订单是 GMV/订单数/实际收入/数量的基准
                existing_product = _merge_order_metrics(existing_product, day_orders)
                existing_product["date"] = d
                meta = {
                    "promo_file": promo_filename or "",
                    "order_file": order_filename or "",
                    "product_rows": len(existing_product),
                    "order_rows": len(day_orders),
                    "saved_at": datetime.datetime.now().isoformat(),
                }
                save_daily_data(store_name, d, existing_product, day_orders, meta=meta)
                processed_dates.add(d)
                total_order_rows += len(day_orders)

    # 导入订单后自动把新出现的商家编码刷新到成本配置
    refreshed_codes = {"added": 0}
    if order_bytes:
        try:
            refreshed_codes = refresh_global_cost_codes()
        except Exception:
            pass

    bump_data_version()

    return {
        "store_name": store_name,
        "date": _date_str(import_date) if import_date else None,
        "processed_dates": sorted(processed_dates),
        "product_rows": total_product_rows,
        "order_rows": total_order_rows,
        "refreshed_codes": refreshed_codes.get("added", 0),
    }


def _load_douyin_daily_merged(store_name: str, date: str) -> pd.DataFrame:
    """读取当日商品指标并按最新规则重新合并订单（保证净订单等口径与代码一致）。"""
    p, o = load_daily_data(store_name, date)
    p = _merge_order_metrics(p, o)
    p = _merge_merchant_code_from_orders(p, o)
    return p


@cached_with_ttl(300)
def load_douyin_analysis(
    store_name: str,
    start_date: datetime.date,
    end_date: datetime.date,
) -> Dict[str, Any]:
    start_s = _date_str(start_date)
    end_s = _date_str(end_date)
    dates = [d for d in list_available_dates(store_name) if start_s <= d <= end_s]

    product_dfs = [_load_douyin_daily_merged(store_name, d) for d in dates]
    product_dfs = [p for p in product_dfs if not p.empty]

    product_metrics = aggregate_product_metrics(product_dfs)
    product_metrics = apply_costs_to_metrics(product_metrics, store_name=store_name)
    overall = compute_overall_kpis(product_metrics)
    cost_kpis = compute_cost_kpis(product_metrics)

    return _json_safe({
        "product_metrics": product_metrics.replace({pd.NA: None, float("nan"): None}).to_dict("records"),
        "kpis": overall,
        "cost_kpis": cost_kpis,
    })


@cached_with_ttl(300)
def load_douyin_trend(
    store_name: str,
    start_date: datetime.date,
    end_date: datetime.date,
) -> List[Dict[str, Any]]:
    """按店铺汇总后再按日期分组，避免逐日重复合并订单与计算成本。"""
    start_s = _date_str(start_date)
    end_s = _date_str(end_date)
    dates = [d for d in list_available_dates(store_name) if start_s <= d <= end_s]

    dfs: List[pd.DataFrame] = []
    for d in dates:
        p = _load_douyin_daily_merged(store_name, d)
        if not p.empty:
            p = p.copy()
            p["date"] = d
            dfs.append(p)
    if not dfs:
        return []

    combined = pd.concat(dfs, ignore_index=True)
    combined_cost = apply_costs_to_metrics(combined, store_name=store_name)

    rows = []
    for d, g in combined_cost.groupby("date", sort=True):
        kpis = compute_overall_kpis(g)
        cost = compute_cost_kpis(g)
        rows.append(_json_safe({"date": d, **kpis, **cost}))
    return rows


@cached_with_ttl(300)
def get_douyin_dashboard_summary(
    start_date: datetime.date,
    end_date: datetime.date,
    store_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """汇总指定店铺在日期范围内的经营数据；按店铺汇总后一次性应用成本并分组出趋势。"""
    from douyin_storage import list_douyin_stores

    if store_names is None:
        store_names = list_douyin_stores()

    start_s = _date_str(start_date)
    end_s = _date_str(end_date)

    all_product_dfs: List[pd.DataFrame] = []
    for store in store_names:
        for d in list_available_dates(store):
            if start_s <= d <= end_s:
                p = _load_douyin_daily_merged(store, d)
                if not p.empty:
                    p = p.copy()
                    p["date"] = d
                    all_product_dfs.append(p)

    if not all_product_dfs:
        return _json_safe({
            "store_count": len(store_names),
            "kpis": {},
            "cost_kpis": {},
            "trend": [],
        })

    combined = pd.concat(all_product_dfs, ignore_index=True)
    combined_cost = apply_costs_to_metrics(combined, store_name=None)
    overall = compute_overall_kpis(combined)
    cost_kpis = compute_cost_kpis(combined_cost)

    trend_summary = []
    for d, g in combined_cost.groupby("date", sort=True):
        kpis = compute_overall_kpis(g)
        cost = compute_cost_kpis(g)
        trend_summary.append(_json_safe({"date": d, **kpis, **cost}))

    return _json_safe({
        "store_count": len(store_names),
        "kpis": overall,
        "cost_kpis": cost_kpis,
        "trend": trend_summary,
    })


def get_douyin_orders(store_name: str, date: datetime.date) -> List[Dict[str, Any]]:
    _, orders = load_daily_data(store_name, _date_str(date))
    if orders.empty:
        return []
    return _json_safe(orders.replace({pd.NA: None, float("nan"): None}).to_dict("records"))


# ---------- AI ----------

def get_douyin_ai_config() -> Dict[str, Any]:
    return get_ai_config()


def update_douyin_ai_config(config: Dict[str, Any]) -> Dict[str, Any]:
    return update_ai_config(config)


def test_douyin_ai(config: Dict[str, Any]) -> str:
    return test_ai_connection(config)


def generate_douyin_ai_report(
    store_name: str,
    start_date: datetime.date,
    end_date: datetime.date,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    analysis = load_douyin_analysis(store_name, start_date, end_date)
    return generate_ai_report(
        kpis=analysis.get("kpis") or {},
        product_metrics=analysis.get("product_metrics") or [],
        config=config,
    )


# ---------- 企业微信 ----------

_DOUYIN_WECOM_CONFIG_FILE = _Path("data/douyin_wecom_config.json")


def _ensure_data_dir():
    _DOUYIN_WECOM_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)


def get_douyin_wecom_config() -> Dict[str, Any]:
    if not _DOUYIN_WECOM_CONFIG_FILE.exists():
        return {}
    try:
        return _json.loads(_DOUYIN_WECOM_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def update_douyin_wecom_config(config: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_data_dir()
    _DOUYIN_WECOM_CONFIG_FILE.write_text(_json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config


def preview_douyin_wecom_report(report_date: datetime.date) -> Dict[str, Any]:
    from douyin_report_builder import build_daily_report as build_douyin_daily_report
    content = build_douyin_daily_report(report_date)
    return create_report_draft(content, report_date.strftime("%Y-%m-%d"), platform="douyin")


def send_douyin_wecom_report(
    report_date: datetime.date,
    config: Dict[str, Any],
    draft_id: Optional[str] = None,
) -> Dict[str, Any]:
    if draft_id:
        draft = get_report_draft(draft_id, report_date.strftime("%Y-%m-%d"), platform="douyin")
        content = draft["content"]
    else:
        from douyin_report_builder import build_daily_report as build_douyin_daily_report
        content = build_douyin_daily_report(report_date)
    result = wecom_sender.send_wecom_report(content=content, config=config)
    if draft_id:
        mark_report_draft_sent(draft_id)
    return result


def get_douyin_records(store_name: Optional[str] = None) -> List[Dict[str, Any]]:
    return _json_safe(list_douyin_records(store_name))


def delete_douyin_record(store_name: str, date: datetime.date) -> Dict[str, Any]:
    date_str = _date_str(date)
    delete_daily_data(store_name, date_str)
    bump_data_version()
    return {"deleted": True, "store_name": store_name, "date": date_str}
