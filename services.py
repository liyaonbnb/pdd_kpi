"""
业务服务层：把 Streamlit 无关的核心逻辑封装成纯函数，供 FastAPI routers 调用。
"""

import io
import datetime
import hashlib
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from data_loader import read_promotion_file, read_order_file
from data_processor import match_promotion_and_orders, filter_orders_by_date, extract_order_dates
from metrics import (
    safe_div,
    compute_product_metrics,
    compute_overall_kpis,
    aggregate_product_metrics,
    aggregate_style_metrics,
    merge_refund_stage_counts,
)
from cost_manager import (
    apply_costs_to_metrics,
    compute_cost_kpis,
    load_cost_config,
    save_cost_config,
    set_cost,
    append_new_merchant_codes,
    import_costs_from_csv,
    export_costs_to_csv,
    _normalize_product_id,
    import_global_costs_from_csv,
    export_global_costs_to_csv,
    set_product_merchant_mapping,
    load_product_merchant_mapping,
    list_global_cost_rows,
    save_global_cost,
    load_global_costs,
    load_global_product_mapping,
    save_global_product_mapping,
    get_all_merchant_codes,
    get_products_without_merchant_code,
    refresh_global_cost_codes,
)
from storage import (
    save_daily_data,
    load_daily_data,
    load_daily_orders,
    save_daily_promo,
    load_daily_promo,
    remove_order_ids_from_store,
    list_available_stores,
    list_available_dates,
    list_store_records,
    record_exists,
    delete_daily_data,
)
from store_manager import add_store, rename_store, delete_store, list_stores, update_store_platform
from config_manager import load_config, save_config, get_config_defaults
from ai_analyzer import generate_ai_report
from api_client import test_connection
from wecom import send_wecom_report, save_wecom_config, listen_wecom_chatid
from wecom_report_drafts import create_report_draft, get_report_draft, mark_report_draft_sent
from report_builder import build_daily_report
from import_batches import (
    IMPORT_LOCK,
    begin_batch,
    find_duplicate_batch,
    invalidate_store_batches,
    list_batches,
    restore_batch_snapshot,
    rollback_batch,
    update_batch,
)


# ---------- 内存缓存 ----------

_CACHE_TTL_SECONDS = 300  # 5 分钟
_DATA_VERSION = 0
_CACHE: Dict[str, tuple] = {}
_CACHE_LOCK = threading.Lock()


def bump_data_version():
    """数据发生变更（导入/删除）时递增版本号并清空缓存"""
    global _DATA_VERSION
    with _CACHE_LOCK:
        _DATA_VERSION += 1
        _CACHE.clear()


def _make_hashable(obj: Any) -> Any:
    if isinstance(obj, list):
        return tuple(_make_hashable(x) for x in obj)
    if isinstance(obj, tuple):
        return tuple(_make_hashable(x) for x in obj)
    if isinstance(obj, dict):
        return tuple((k, _make_hashable(v)) for k, v in sorted(obj.items()))
    return obj


def _cache_key(func_name: str, args: tuple, kwargs: dict) -> str:
    return str(
        (
            func_name,
            tuple(_make_hashable(a) for a in args),
            tuple((k, _make_hashable(v)) for k, v in sorted(kwargs.items())),
            _DATA_VERSION,
        )
    )


def cached_with_ttl(ttl_seconds: float):
    def decorator(func):
        def wrapper(*args, **kwargs):
            key = _cache_key(func.__name__, args, kwargs)
            with _CACHE_LOCK:
                entry = _CACHE.get(key)
                if entry and entry[0] > time.monotonic():
                    return entry[1]
            result = func(*args, **kwargs)
            with _CACHE_LOCK:
                _CACHE[key] = (time.monotonic() + ttl_seconds, result)
            return result

        return wrapper

    return decorator


def _date_str(d) -> str:
    if isinstance(d, datetime.date):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, datetime.datetime):
        return d.strftime("%Y-%m-%d")
    return str(d)


def _convert_value(v):
    if isinstance(v, (np.integer, np.floating, np.bool_)):
        return v.item()
    return v


def _df_to_records(df: pd.DataFrame) -> List[Dict]:
    if df is None or df.empty:
        return []
    records = df.replace({pd.NA: None, float("nan"): None}).to_dict("records")
    return [{k: _convert_value(v) for k, v in row.items()} for row in records]


def _json_safe(obj: Any) -> Any:
    """递归把 numpy/pandas 标量转成 Python 原生类型，避免 FastAPI JSON 序列化报错"""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.integer, np.floating, np.bool_)):
        return obj.item()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    return obj


# ---------- 店铺 ----------

def get_stores(platform: Optional[str] = None) -> List[Dict[str, Any]]:
    return list_stores(platform=platform)


def create_store(name: str, platform: str = "pdd") -> Dict[str, Any]:
    return add_store(name, platform=platform)


def rename_store_service(store_id: str, new_name: str) -> Optional[Dict[str, Any]]:
    return rename_store(store_id, new_name)


def update_store_platform_service(store_id: str, platform: str) -> Optional[Dict[str, Any]]:
    return update_store_platform(store_id, platform)


def delete_store_service(store_id: str) -> bool:
    return delete_store(store_id)


# ---------- 导入 ----------

def _file_hash(content: Optional[bytes]) -> Optional[str]:
    return hashlib.sha256(content).hexdigest() if content else None


def preview_daily_import(
    store_name: str,
    import_date: datetime.date,
    promo_bytes: Optional[bytes] = None,
    promo_filename: Optional[str] = None,
    order_bytes: Optional[bytes] = None,
    order_filename: Optional[str] = None,
) -> Dict[str, Any]:
    """Parse an upload without writing data and report its import risk."""
    if not promo_bytes and not order_bytes:
        raise ValueError("请至少上传推广数据或订单数据中的一个")

    import_date_str = _date_str(import_date)
    promo_hash = _file_hash(promo_bytes)
    order_hash = _file_hash(order_bytes)
    duplicate = find_duplicate_batch(store_name, promo_hash, order_hash)
    blockers: List[str] = []
    warnings: List[str] = []
    affected_dates = {import_date_str} if promo_bytes else set()
    order_stats: Dict[str, Any] = {
        "total_rows": 0,
        "valid_orders": 0,
        "new_orders": 0,
        "existing_orders": 0,
        "migrated_orders": 0,
        "duplicate_order_ids": 0,
        "missing_order_ids": 0,
        "unresolved_dates": 0,
    }

    if duplicate:
        blockers.append(
            f"相同文件已于 {duplicate.get('created_at', '')} 导入，批次 {duplicate.get('batch_id', '')[:8]}"
        )

    if promo_bytes:
        promo_file = io.BytesIO(promo_bytes)
        promo_file.name = promo_filename or "promo.xlsx"
        promo_df, _ = read_promotion_file(promo_file)
        if promo_df.empty:
            blockers.append("推广文件没有可导入的数据")

    if order_bytes:
        order_file = io.BytesIO(order_bytes)
        order_file.name = order_filename or "order.csv"
        order_df, _ = read_order_file(order_file)
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

            parsed_dates = extract_order_dates(valid_df)
            if "order_status" in valid_df.columns:
                cancelled = valid_df["order_status"].astype(str).str.contains(
                    "取消|交易关闭", na=False, regex=True
                )
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

            existing_locations: Dict[str, str] = {}
            # The importer removes every uploaded order ID from history before
            # dropping cancelled rows without dates, so snapshot those old dates too.
            uploaded_ids = set(valid_df["order_id"].astype(str))
            for existing_date in list_available_dates(store_name):
                try:
                    existing = load_daily_orders(existing_date, store_name)
                except Exception:
                    continue
                if existing.empty or "order_id" not in existing.columns:
                    continue
                for order_id in existing["order_id"].astype(str):
                    if order_id in uploaded_ids:
                        existing_locations[order_id] = existing_date

            incoming_locations = {
                str(accepted.loc[index, "order_id"]): str(parsed_dates.loc[index])
                for index in accepted.index
                if pd.notna(parsed_dates.loc[index])
            }
            existing_ids = uploaded_ids.intersection(existing_locations)
            migrated_ids = {
                order_id
                for order_id in existing_ids
                if incoming_locations.get(order_id)
                and incoming_locations[order_id] != existing_locations[order_id]
            }
            affected_dates.update(existing_locations[order_id] for order_id in existing_ids)
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

def _merge_orders(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """按 order_id 合并新旧订单，新数据覆盖旧数据状态。"""
    if existing.empty or "order_id" not in existing.columns or "order_id" not in new.columns:
        return new.copy()
    existing = existing.copy()
    existing["order_id"] = existing["order_id"].astype(str)
    new = new.copy()
    new["order_id"] = new["order_id"].astype(str)

    existing_indexed = existing.set_index("order_id")
    new_indexed = new.set_index("order_id")

    # 用新数据更新已有订单（相同列）
    existing_indexed.update(new_indexed)

    # 追加新订单
    new_only = new_indexed.loc[~new_indexed.index.isin(existing_indexed.index)]
    combined = pd.concat([existing_indexed.reset_index(), new_only.reset_index()], ignore_index=True)
    return combined


def _compute_and_save_daily(
    promo_df: pd.DataFrame,
    order_df: pd.DataFrame,
    promo_mapping: Dict[str, Optional[str]],
    order_mapping: Dict[str, Optional[str]],
    date_str: str,
    store_name: str,
    meta: Dict[str, Any],
) -> Dict[str, Any]:
    """用推广和订单计算每日指标并保存。"""
    merged, style_metrics, orders = match_promotion_and_orders(
        promo_df,
        order_df,
        promo_mapping,
        order_mapping,
        date=date_str,
    )
    merged["store_name"] = store_name
    style_metrics["store_name"] = store_name
    orders["store_name"] = store_name

    metrics = compute_product_metrics(merged)
    save_daily_data(
        metrics,
        style_metrics,
        orders,
        date=date_str,
        store_name=store_name,
        meta=meta,
    )
    return {
        "date": date_str,
        "product_rows": len(metrics),
        "style_rows": len(style_metrics),
        "order_rows": len(orders),
        "computed": True,
    }


def _apply_daily_import(
    store_name: str,
    import_date: datetime.date,
    promo_bytes: Optional[bytes] = None,
    promo_filename: Optional[str] = None,
    order_bytes: Optional[bytes] = None,
    order_filename: Optional[str] = None,
) -> Dict[str, Any]:
    if not promo_bytes and not order_bytes:
        raise ValueError("请至少上传推广数据或订单数据中的一个")

    date_str = _date_str(import_date)
    meta = {"promo_file": promo_filename or "", "order_file": order_filename or ""}
    results: List[Dict[str, Any]] = []

    promo_df = pd.DataFrame()
    promo_mapping: Dict[str, Optional[str]] = {}
    if promo_bytes:
        promo_file = io.BytesIO(promo_bytes)
        promo_file.name = promo_filename or ""
        promo_df, promo_mapping = read_promotion_file(promo_file)
        save_daily_promo(promo_df, date=date_str, store_name=store_name)
        results.append({"date": date_str, "promo_saved": True, "orders_saved": False, "computed": False})

        # 若该日已有订单，立即用新推广重算指标
        try:
            existing_orders = load_daily_orders(date_str, store_name)
            if not existing_orders.empty:
                order_mapping_existing = {}
                res = _compute_and_save_daily(
                    promo_df, existing_orders, promo_mapping, order_mapping_existing,
                    date_str, store_name, meta,
                )
                res["promo_saved"] = True
                res["orders_saved"] = False
                results.append(res)
        except FileNotFoundError:
            pass

    order_df = pd.DataFrame()
    order_mapping: Dict[str, Optional[str]] = {}
    original_order_rows = 0
    if order_bytes:
        order_file = io.BytesIO(order_bytes)
        order_file.name = order_filename or ""
        order_df, order_mapping = read_order_file(order_file)
        original_order_rows = len(order_df)

        # 先把本次所有订单的 order_id 从历史所有日期中移除，
        # 防止同一订单因日期修正而残留在旧日期文件里
        cleaned_dates: List[str] = []
        if "order_id" in order_df.columns and not order_df.empty:
            cleaned_dates = remove_order_ids_from_store(
                store_name, order_df["order_id"].astype(str).unique().tolist()
            )

        # 按订单实际日期拆分，逐日处理
        order_dates = extract_order_dates(order_df)
        order_df["_order_date"] = order_dates

        # 已取消且完全无法解析到日期的订单，不计入订单
        if "order_status" in order_df.columns:
            no_date = order_df["_order_date"].isna()
            is_cancel = order_df["order_status"].astype(str).str.contains(
                "取消|交易关闭", na=False, regex=True
            )
            order_df = order_df[~(no_date & is_cancel)].copy()

        # 无法解析日期的行归到用户选择的 import_date，避免丢单
        order_df["_order_date"] = order_df["_order_date"].fillna(date_str)
        unique_dates = order_df["_order_date"].dropna().unique()

        new_dates: List[str] = []
        for d in sorted(unique_dates):
            d = str(d)
            new_dates.append(d)
            day_orders = order_df[order_df["_order_date"] == d].copy()
            day_orders = day_orders.drop(columns=["_order_date"])

            # 与该日已有订单合并
            try:
                existing_orders = load_daily_orders(d, store_name)
            except Exception:
                existing_orders = pd.DataFrame()
            merged_orders = _merge_orders(existing_orders, day_orders)

            # 尝试用该日已有推广数据计算指标
            try:
                existing_promo = load_daily_promo(d, store_name)
                res = _compute_and_save_daily(
                    existing_promo, merged_orders, {}, order_mapping,
                    d, store_name, meta,
                )
                res["promo_saved"] = False
                res["orders_saved"] = True
                results.append(res)
            except FileNotFoundError:
                # 没有推广数据，只保存订单；保留已有商品/样式指标不被覆盖
                try:
                    existing_product, existing_style = load_daily_data(d, store_name)
                except Exception:
                    existing_product, existing_style = pd.DataFrame(), pd.DataFrame()
                save_daily_data(
                    existing_product, existing_style, merged_orders,
                    date=d, store_name=store_name, meta=meta,
                )
                results.append({
                    "date": d,
                    "product_rows": len(existing_product),
                    "style_rows": len(existing_style),
                    "order_rows": len(merged_orders),
                    "promo_saved": False,
                    "orders_saved": True,
                    "computed": False,
                })

        # 对仅被清理出旧订单的日期，用剩余订单重新计算指标（如有推广则联用）
        for d in sorted(set(cleaned_dates) - set(new_dates)):
            try:
                remaining_orders = load_daily_orders(d, store_name)
            except Exception:
                continue
            if remaining_orders.empty:
                continue
            try:
                existing_promo = load_daily_promo(d, store_name)
                res = _compute_and_save_daily(
                    existing_promo, remaining_orders, {}, {},
                    d, store_name, meta,
                )
                res["promo_saved"] = False
                res["orders_saved"] = True
                results.append(res)
            except FileNotFoundError:
                # 没有推广数据，只保存订单；保留已有商品/样式指标不被覆盖
                try:
                    existing_product, existing_style = load_daily_data(d, store_name)
                except Exception:
                    existing_product, existing_style = pd.DataFrame(), pd.DataFrame()
                save_daily_data(
                    existing_product, existing_style, remaining_orders,
                    date=d, store_name=store_name, meta=meta,
                )
                results.append({
                    "date": d,
                    "product_rows": len(existing_product),
                    "style_rows": len(existing_style),
                    "order_rows": len(remaining_orders),
                    "promo_saved": False,
                    "orders_saved": True,
                    "computed": False,
                })

    # 汇总结果
    computed_results = [r for r in results if r.get("computed")]
    saved_order_results = [r for r in results if r.get("orders_saved") and not r.get("computed")]
    promo_only_results = [r for r in results if r.get("promo_saved") and not r.get("orders_saved")]

    total_product_rows = sum(r.get("product_rows", 0) for r in computed_results)
    total_order_rows = sum(r.get("order_rows", 0) for r in results if r.get("orders_saved"))
    processed_dates = sorted(set(r.get("date") for r in results if r.get("date")))

    # 导入订单后自动把新出现的商家编码刷新到成本配置
    refreshed_codes = {"added": 0}
    if order_bytes:
        try:
            refreshed_codes = refresh_global_cost_codes_service()
        except Exception:
            pass

    bump_data_version()
    return {
        "store_name": store_name,
        "import_date": date_str,
        "original_order_rows": original_order_rows,
        "processed_dates": processed_dates,
        "product_rows": total_product_rows,
        "order_rows": total_order_rows,
        "promo_saved": len(promo_only_results) > 0,
        "results": results,
        "refreshed_codes": refreshed_codes.get("added", 0),
    }


def import_daily_data(
    store_name: str,
    import_date: datetime.date,
    promo_bytes: Optional[bytes] = None,
    promo_filename: Optional[str] = None,
    order_bytes: Optional[bytes] = None,
    order_filename: Optional[str] = None,
    imported_by: str = "unknown",
) -> Dict[str, Any]:
    preview = preview_daily_import(
        store_name, import_date, promo_bytes, promo_filename, order_bytes, order_filename
    )
    if not preview["can_import"]:
        raise ValueError("；".join(preview["blockers"]))

    with IMPORT_LOCK:
        # Recheck after acquiring the lock so concurrent imports cannot bypass duplicate detection.
        preview = preview_daily_import(
            store_name, import_date, promo_bytes, promo_filename, order_bytes, order_filename
        )
        if not preview["can_import"]:
            raise ValueError("；".join(preview["blockers"]))
        batch_id = begin_batch(
            store_name=store_name,
            import_date=_date_str(import_date),
            imported_by=imported_by,
            preview=preview,
            promo_filename=promo_filename,
            order_filename=order_filename,
        )
        try:
            result = _apply_daily_import(
                store_name, import_date, promo_bytes, promo_filename, order_bytes, order_filename
            )
        except Exception as exc:
            restore_batch_snapshot(batch_id)
            update_batch(
                batch_id, status="failed", completed_at=datetime.datetime.now().isoformat(timespec="seconds"),
                error=str(exc)[:500],
            )
            bump_data_version()
            raise

        completed_at = datetime.datetime.now().isoformat(timespec="seconds")
        affected_dates = sorted(
            set(preview["affected_dates"]) | set(result.get("processed_dates", []))
        )
        update_batch(
            batch_id, status="imported", completed_at=completed_at,
            affected_dates=affected_dates,
            result={
                "original_order_rows": result.get("original_order_rows", 0),
                "product_rows": result.get("product_rows", 0),
                "order_rows": result.get("order_rows", 0),
            },
        )
        result["batch_id"] = batch_id
        result["preview"] = preview
        return result


# ---------- 订单 ----------

def get_orders(store_name: str, date: datetime.date) -> List[Dict[str, Any]]:
    try:
        df = load_daily_orders(_date_str(date), store_name)
    except FileNotFoundError:
        return []
    return _df_to_records(df)


def save_merchant_mapping(store_name: str, product_id: str, merchant_code: str) -> Dict[str, Any]:
    cfg = load_cost_config()
    cfg = set_product_merchant_mapping(cfg, store_name, product_id, merchant_code)
    costs = cfg.get("merchant_costs", {}).get(store_name, {})
    if merchant_code not in costs:
        cfg = set_cost(cfg, store_name=store_name, merchant_code=merchant_code)
    save_cost_config(cfg)
    return {"product_id": product_id, "merchant_code": merchant_code}


# ---------- 指标 ----------

@cached_with_ttl(_CACHE_TTL_SECONDS)
def load_analysis_data(
    store_name: str,
    start_date: datetime.date,
    end_date: datetime.date,
) -> Dict[str, Any]:
    dates = list_available_dates(store_name)
    start_s = _date_str(start_date)
    end_s = _date_str(end_date)
    selected_dates = [d for d in dates if start_s <= d <= end_s]

    if not selected_dates:
        return {"product_metrics": [], "style_metrics": [], "kpis": {}}

    product_dfs = []
    order_dfs = []
    for d in selected_dates:
        try:
            p, _ = load_daily_data(d, store_name)
            product_dfs.append(p)
        except Exception:
            continue
        try:
            orders = load_daily_orders(d, store_name)
            if not orders.empty:
                order_dfs.append(orders)
        except Exception:
            continue

    if not product_dfs:
        return {"product_metrics": [], "style_metrics": [], "kpis": {}}

    metrics = aggregate_product_metrics(product_dfs)
    metrics = merge_refund_stage_counts(metrics, order_dfs)
    metrics = compute_product_metrics(metrics)
    all_orders = pd.concat(order_dfs, ignore_index=True) if order_dfs else None
    metrics = apply_costs_to_metrics(metrics, store_name, orders=all_orders)
    style_metrics = aggregate_style_metrics(order_dfs) if order_dfs else pd.DataFrame()
    kpis = compute_overall_kpis(metrics)

    # 商品ID按文本返回，避免前端显示成科学计数/带逗号数字
    if "product_id" in metrics.columns:
        metrics["product_id"] = metrics["product_id"].apply(_normalize_product_id)

    # 把 float nan 转为 None，避免 JSON 序列化问题
    return _json_safe({
        "product_metrics": _df_to_records(metrics),
        "style_metrics": _df_to_records(style_metrics),
        "kpis": {k: (None if pd.isna(v) else v) for k, v in kpis.items()},
    })


@cached_with_ttl(_CACHE_TTL_SECONDS)
def load_trend_data(
    store_names: List[str],
    start_date: datetime.date,
    end_date: datetime.date,
) -> List[Dict[str, Any]]:
    """按店铺汇总后再按日期分组，避免逐日重复计算指标"""
    start_s = _date_str(start_date)
    end_s = _date_str(end_date)

    rows: List[Dict[str, Any]] = []
    for store in store_names:
        dates = [d for d in list_available_dates(store) if start_s <= d <= end_s]
        if not dates:
            continue

        dfs: List[pd.DataFrame] = []
        order_dfs: List[pd.DataFrame] = []
        for d in dates:
            try:
                p, _ = load_daily_data(d, store)
                if not p.empty:
                    p = p.copy()
                    p["date"] = d
                    dfs.append(p)
            except Exception:
                continue
            try:
                o = load_daily_orders(d, store)
                if not o.empty:
                    o = o.copy()
                    o["date"] = d
                    order_dfs.append(o)
            except Exception:
                continue
        if not dfs:
            continue

        combined = pd.concat(dfs, ignore_index=True)
        combined = compute_product_metrics(combined)
        combined = merge_refund_stage_counts(combined, [])
        # 趋势统一走成本回退逻辑，确保和分析页汇总结果一致
        combined["merchant_code"] = ""
        combined_orders = pd.concat(order_dfs, ignore_index=True) if order_dfs else None
        combined = apply_costs_to_metrics(combined, store, orders=combined_orders)

        for d, g in combined.groupby("date", sort=True):
            day_kpis = compute_overall_kpis(g)
            cost = compute_cost_kpis(g)
            row = {"store_name": store, "date": d}
            row.update(day_kpis)
            row.update(cost)
            rows.append(_json_safe(row))
    return rows


def _recompute_kpis(totals: Dict[str, float]) -> Dict[str, float]:
    """从基础字段汇总值重新计算比率类 KPI"""
    from metrics import safe_div

    def _get(key: str) -> float:
        return float(totals.get(key, 0) or 0)

    income = _get("valid_merchant_income")
    profit = _get("link_gross_profit")

    return {
        **{k: _get(k) for k in [
            "promo_spend", "promo_gmv", "order_gmv", "valid_order_gmv",
            "merchant_income", "valid_merchant_income", "exposure", "clicks",
            "order_count", "valid_order_count", "promo_orders",
            "refund_count", "cancel_count",
            "refund_unshipped_count", "refund_shipped_count", "refund_received_count",
            "organic_orders", "organic_gmv", "organic_merchant_income", "organic_valid_order_count",
            "total_product_cost", "total_logistics_cost", "total_cost", "link_gross_profit", "profit_loss",
        ]},
        "promo_roi": safe_div(_get("promo_gmv"), _get("promo_spend")),
        "real_roi": safe_div(_get("valid_merchant_income"), _get("promo_spend")),
        "valid_order_gmv_roi": safe_div(_get("valid_order_gmv"), _get("promo_spend")),
        "refund_rate": safe_div(_get("refund_count"), _get("order_count")) * 100,
        "cancel_rate": safe_div(_get("cancel_count"), _get("order_count")) * 100,
        "problem_rate": safe_div(_get("refund_count") + _get("cancel_count"), _get("order_count")) * 100,
        "refund_unshipped_rate": safe_div(_get("refund_unshipped_count"), _get("order_count")) * 100,
        "refund_shipped_rate": safe_div(_get("refund_shipped_count"), _get("order_count")) * 100,
        "refund_received_rate": safe_div(_get("refund_received_count"), _get("order_count")) * 100,
        "ctr": safe_div(_get("clicks"), _get("exposure")) * 100,
        "click_to_order_rate": safe_div(_get("promo_orders"), _get("clicks")) * 100,
        "exposure_to_order_rate": safe_div(_get("promo_orders"), _get("exposure")) * 100,
        "cpc": safe_div(_get("promo_spend"), _get("clicks")),
        "cpm": safe_div(_get("promo_spend"), _get("exposure")) * 1000,
        "organic_ratio_gmv": safe_div(_get("organic_gmv"), _get("order_gmv")) * 100,
        "organic_ratio_orders": safe_div(_get("organic_orders"), _get("order_count")) * 100,
        "organic_ratio_income": safe_div(_get("organic_merchant_income"), _get("valid_merchant_income")) * 100,
        "organic_ratio_valid_orders": safe_div(_get("organic_valid_order_count"), _get("valid_order_count")) * 100,
        "promo_gmv_ratio": safe_div(_get("promo_gmv"), _get("order_gmv")) * 100,
        "valid_order_gmv_ratio": safe_div(_get("valid_order_gmv"), _get("order_gmv")) * 100,
        "promo_order_ratio": safe_div(_get("promo_orders"), _get("order_count")) * 100,
        "promo_cost_ratio": safe_div(_get("promo_spend"), _get("valid_merchant_income")) * 100,
        "gross_margin_rate": (profit / income * 100) if income else 0.0,
        "profit_loss_rate": (_get("profit_loss") / income * 100) if income else 0.0,
    }


@cached_with_ttl(_CACHE_TTL_SECONDS)
def get_dashboard_summary(
    start_date: datetime.date,
    end_date: datetime.date,
    store_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """汇总指定店铺在日期范围内的经营与推广数据"""
    store_names = store_names if store_names is not None else list_available_stores()

    base_keys = [
        "promo_spend", "promo_gmv", "promo_orders", "exposure", "clicks",
        "order_count", "valid_order_count", "order_gmv", "valid_order_gmv",
        "merchant_income", "valid_merchant_income",
        "refund_count", "cancel_count",
        "refund_unshipped_count", "refund_shipped_count", "refund_received_count",
        "organic_orders", "organic_gmv", "organic_merchant_income", "organic_valid_order_count",
        "total_product_cost", "total_logistics_cost", "total_cost", "link_gross_profit", "profit_loss",
    ]

    # 按日期汇总趋势（整体 KPI 从趋势汇总得出，避免重复读取 analysis 的订单文件）
    trend_rows = load_trend_data(store_names, start_date, end_date)

    total = {k: 0.0 for k in base_keys}
    for row in trend_rows:
        for k in base_keys:
            total[k] += float(row.get(k, 0) or 0)
    summary_kpis = _recompute_kpis(total)
    summary_kpis = {k: (None if pd.isna(v) else v) for k, v in summary_kpis.items()}

    trend_by_date: Dict[str, Dict[str, float]] = {}
    for row in trend_rows:
        d = row.get("date")
        if not d:
            continue
        if d not in trend_by_date:
            trend_by_date[d] = {k: 0.0 for k in base_keys}
        for k in base_keys:
            trend_by_date[d][k] += float(row.get(k, 0) or 0)

    trend_summary = []
    for d in sorted(trend_by_date.keys()):
        row = _recompute_kpis(trend_by_date[d])
        row["date"] = d
        trend_summary.append({k: (None if pd.isna(v) else v) for k, v in row.items()})

    return {
        "store_count": len(store_names),
        "start_date": _date_str(start_date),
        "end_date": _date_str(end_date),
        "kpis": summary_kpis,
        "trend": trend_summary,
    }


OPERATIONS_DAILY_BASE_KEYS = [
    "promo_spend",
    "order_count",
    "valid_order_count",
    "valid_merchant_income",
    "refund_count",
    "total_product_cost",
    "total_logistics_cost",
    "platform_fee",
    "link_gross_profit",
    "profit_loss",
]


def _operations_kpis(totals: Dict[str, float]) -> Dict[str, float]:
    """从可加总字段重新计算日报比率，避免直接平均百分比。"""
    income = float(totals.get("valid_merchant_income", 0) or 0)
    valid_orders = float(totals.get("valid_order_count", 0) or 0)
    orders = float(totals.get("order_count", 0) or 0)
    promo_spend = float(totals.get("promo_spend", 0) or 0)
    product_cost = float(totals.get("total_product_cost", 0) or 0)
    logistics_cost = float(totals.get("total_logistics_cost", 0) or 0)
    link_profit = float(totals.get("link_gross_profit", 0) or 0)
    operating_profit = float(totals.get("profit_loss", 0) or 0)

    return {
        **{key: float(totals.get(key, 0) or 0) for key in OPERATIONS_DAILY_BASE_KEYS},
        "avg_valid_order_income": safe_div(income, valid_orders),
        "promo_cost_ratio": safe_div(promo_spend, income) * 100,
        "product_cost_ratio": safe_div(product_cost, income) * 100,
        "logistics_cost_ratio": safe_div(logistics_cost, income) * 100,
        "gross_margin_rate": safe_div(link_profit, income) * 100,
        "profit_loss_rate": safe_div(operating_profit, income) * 100,
        "refund_rate": safe_div(float(totals.get("refund_count", 0) or 0), orders) * 100,
    }


def _operations_data_status(store_name: str, date_str: str) -> Dict[str, Any]:
    flags = {"metrics": False, "orders": False, "promotion": False}
    try:
        product_metrics, _ = load_daily_data(date_str, store_name)
        flags["metrics"] = not product_metrics.empty
    except Exception:
        pass
    try:
        flags["orders"] = not load_daily_orders(date_str, store_name).empty
    except Exception:
        pass
    try:
        flags["promotion"] = not load_daily_promo(date_str, store_name).empty
    except Exception:
        pass

    available = sum(1 for value in flags.values() if value)
    status = "complete" if available == len(flags) else "partial" if available else "missing"
    return {"status": status, **flags}


def _sum_operations_rows(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    totals = {key: 0.0 for key in OPERATIONS_DAILY_BASE_KEYS}
    for row in rows:
        for key in OPERATIONS_DAILY_BASE_KEYS:
            totals[key] += float(row.get(key, 0) or 0)
    return totals


@cached_with_ttl(_CACHE_TTL_SECONDS)
def get_operations_daily_report(
    start_date: Optional[datetime.date],
    end_date: Optional[datetime.date],
    store_names: List[str],
) -> Dict[str, Any]:
    """生成店铺 × 指标 × 日期的主账号运营日报。"""
    available_dates = sorted({
        date
        for store_name in store_names
        for date in list_available_dates(store_name)
        if date
    })

    if end_date is None:
        end_date = (
            datetime.datetime.strptime(available_dates[-1], "%Y-%m-%d").date()
            if available_dates
            else datetime.date.today()
        )
    if start_date is None:
        start_date = end_date - datetime.timedelta(days=6)
    if start_date > end_date:
        raise ValueError("开始日期不能晚于结束日期")
    if (end_date - start_date).days > 30:
        raise ValueError("运营日报单次最多查看 31 天")

    date_columns = [
        (start_date + datetime.timedelta(days=offset)).strftime("%Y-%m-%d")
        for offset in range((end_date - start_date).days + 1)
    ]
    trend_rows = load_trend_data(store_names, start_date, end_date)
    row_map = {
        (str(row.get("store_name", "")), str(row.get("date", ""))): row
        for row in trend_rows
    }

    stores: List[Dict[str, Any]] = []
    all_rows: List[Dict[str, Any]] = []
    data_issue_store_count = 0
    missing_day_count = 0

    for store_name in store_names:
        daily: Dict[str, Optional[Dict[str, Any]]] = {}
        quality: Dict[str, Dict[str, Any]] = {}
        store_rows: List[Dict[str, Any]] = []
        for date_str in date_columns:
            raw = row_map.get((store_name, date_str))
            daily[date_str] = _operations_kpis(_sum_operations_rows([raw])) if raw else None
            quality[date_str] = _operations_data_status(store_name, date_str)
            if raw:
                store_rows.append(raw)

        quality_counts = {
            status: sum(1 for value in quality.values() if value["status"] == status)
            for status in ("complete", "partial", "missing")
        }
        if quality_counts["partial"] or quality_counts["missing"]:
            data_issue_store_count += 1
        missing_day_count += quality_counts["missing"]
        all_rows.extend(store_rows)
        stores.append({
            "store_name": store_name,
            "totals": _operations_kpis(_sum_operations_rows(store_rows)),
            "daily": daily,
            "quality": quality,
            "quality_counts": quality_counts,
        })

    summary = _operations_kpis(_sum_operations_rows(all_rows))
    data_days = sum(1 for date_str in date_columns if any(
        row_map.get((store_name, date_str)) for store_name in store_names
    ))
    summary.update({
        "store_count": len(store_names),
        "data_days": data_days,
        "daily_income": safe_div(summary["valid_merchant_income"], data_days),
        "data_issue_store_count": data_issue_store_count,
        "missing_day_count": missing_day_count,
    })

    total_daily: Dict[str, Optional[Dict[str, Any]]] = {}
    for date_str in date_columns:
        date_rows = [
            row_map[(store_name, date_str)]
            for store_name in store_names
            if (store_name, date_str) in row_map
        ]
        total_daily[date_str] = (
            _operations_kpis(_sum_operations_rows(date_rows)) if date_rows else None
        )

    return _json_safe({
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "dates": date_columns,
        "summary": summary,
        "total": {"store_name": "全店汇总", "totals": summary, "daily": total_daily},
        "stores": stores,
    })


# ---------- 成本 ----------

def get_costs(store_name: str) -> List[Dict[str, Any]]:
    cfg = load_cost_config()
    costs = cfg.get("merchant_costs", {}).get(store_name, {})
    rows = []
    for code, info in costs.items():
        rows.append({
            "merchant_code": code,
            "product_name": info.get("product_name", ""),
            "product_cost": float(info.get("product_cost", 0) or 0),
            "logistics_cost": float(info.get("logistics_cost", 0) or 0),
        })
    return rows


def save_costs(store_name: str, costs: List[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = load_cost_config()
    for rec in costs:
        code = str(rec.get("merchant_code", "")).strip()
        if not code:
            continue
        cfg = set_cost(
            cfg,
            store_name=store_name,
            merchant_code=code,
            product_name=rec.get("product_name", ""),
            product_cost=rec.get("product_cost", 0),
            logistics_cost=rec.get("logistics_cost", 0),
        )
    save_cost_config(cfg)
    return {"saved": len(costs)}


def refresh_cost_codes(store_name: str) -> Dict[str, Any]:
    added = append_new_merchant_codes(store_name)
    return {"added": added}


def export_cost_csv(store_name: str) -> str:
    return export_costs_to_csv(store_name)


def import_cost_csv(store_name: str, file_bytes: bytes) -> Dict[str, Any]:
    file_obj = io.BytesIO(file_bytes)
    count = import_costs_from_csv(store_name, file_obj)
    return {"updated": count}


def export_global_cost_csv(pending_only: bool = False) -> str:
    return export_global_costs_to_csv(pending_only)


def import_global_cost_csv(file_bytes: bytes) -> Dict[str, Any]:
    file_obj = io.BytesIO(file_bytes)
    count = import_global_costs_from_csv(file_obj)
    return {"updated": count}


# ---------- 全局成本（不区分店铺） ----------

def get_global_costs() -> List[Dict[str, Any]]:
    cfg = load_cost_config()
    mapping = load_global_product_mapping(cfg)
    style_mapping = cfg.get("global_style_merchant_map", {})

    # 收集所有映射到的商家编码，并建立 code -> 商品名称 的初始映射
    code_to_name: Dict[str, str] = {}
    all_mapped_codes: Dict[str, str] = {}
    for pid, code in mapping.items():
        all_mapped_codes[pid] = code
        if code not in code_to_name:
            code_to_name[code] = ""
    for style_key, code in style_mapping.items():
        all_mapped_codes[style_key] = code
        if code not in code_to_name:
            code_to_name[code] = ""

    # 从订单中查找商品名称（按商品级 + 规格级）
    from storage import list_available_stores, list_available_dates, load_daily_orders
    for store in list_available_stores() or []:
        for d in list_available_dates(store):
            try:
                orders = load_daily_orders(d, store)
                if orders.empty or "product_id" not in orders.columns:
                    continue
                for _, r in orders.iterrows():
                    pid = str(r.get("product_id") or "").strip()
                    if pid.endswith(".0"):
                        pid = pid[:-2]
                    sid = str(r.get("style_id") or "").strip()
                    if sid.endswith(".0"):
                        sid = sid[:-2]
                    style_key = f"{pid}::{sid}" if sid else pid
                    code = style_mapping.get(style_key) if sid else mapping.get(pid)
                    if code and not code_to_name.get(code):
                        pname = str(r.get("product_name") or "").strip()
                        if pname:
                            code_to_name[code] = pname
            except Exception:
                continue

    rows = []
    existing_codes = set()
    for rec in list_global_cost_rows(cfg):
        code = rec["merchant_code"]
        existing_codes.add(code)
        pname = rec.get("product_name", "")
        if not pname:
            pname = code_to_name.get(code, "")
            if pname:
                cfg["global_merchant_costs"][code]["product_name"] = pname
        rows.append({
            "merchant_code": code,
            "product_name": pname,
            "product_cost": float(rec.get("product_cost", 0) or 0),
            "logistics_cost": float(rec.get("logistics_cost", 0) or 0),
        })

    # 已映射但还没有成本记录的编码自动补一条成本记录，方便用户维护
    for code, name in code_to_name.items():
        if code and code not in existing_codes:
            cfg = save_global_cost(cfg, code, product_name=name or "")
            rows.append({
                "merchant_code": code,
                "product_name": name,
                "product_cost": 0.0,
                "logistics_cost": 0.0,
            })

    if code_to_name:
        save_cost_config(cfg)
    return rows


def save_global_costs(costs: List[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = load_cost_config()
    for rec in costs:
        code = str(rec.get("merchant_code", "")).strip()
        if not code:
            continue
        cfg = save_global_cost(
            cfg,
            merchant_code=code,
            product_name=rec.get("product_name", ""),
            product_cost=rec.get("product_cost", 0),
            logistics_cost=rec.get("logistics_cost", 0),
        )
    save_cost_config(cfg)
    return {"saved": len(costs)}


def refresh_global_cost_codes_service() -> Dict[str, Any]:
    return refresh_global_cost_codes()


def get_unmapped_products() -> List[Dict[str, Any]]:
    df = get_products_without_merchant_code()
    return _df_to_records(df)


def save_global_product_mapping_service(
    product_id: str,
    merchant_code: str,
    style_id: Optional[str] = None,
    product_name: Optional[str] = None,
) -> Dict[str, Any]:
    cfg = load_cost_config()
    cfg = save_global_product_mapping(cfg, product_id, merchant_code, style_id=style_id, product_name=product_name or "")
    save_cost_config(cfg)
    return {"product_id": product_id, "style_id": style_id, "merchant_code": merchant_code}


# ---------- AI ----------

def get_ai_config() -> Dict[str, Any]:
    return get_config_defaults()


def update_ai_config(config: Dict[str, Any]) -> Dict[str, Any]:
    save_config(config)
    return config


def test_ai_service(config: Dict[str, Any]) -> Dict[str, Any]:
    return test_connection(
        config.get("api_key", ""),
        config.get("base_url", "https://api.kimi.com/coding/v1"),
        config.get("model", "kimi-coding"),
        timeout=30,
    )


def generate_ai_report_service(
    store_name: str,
    start_date: datetime.date,
    end_date: datetime.date,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    data = load_analysis_data(store_name, start_date, end_date)
    kpis = data["kpis"]
    metrics = pd.DataFrame(data["product_metrics"])
    if metrics.empty or not kpis:
        raise ValueError("指定日期范围内没有数据")
    return generate_ai_report(
        kpis=kpis,
        metrics=metrics,
        api_key=config.get("api_key") or None,
        base_url=config.get("base_url", "https://api.kimi.com/coding/v1"),
        model=config.get("model", "kimi-coding"),
        temperature=config.get("temperature", 1.0),
        reasoning_effort=config.get("reasoning_effort", "low"),
        timeout=config.get("timeout", 60),
        max_completion_tokens=config.get("max_completion_tokens", 16384),
        date=f"{_date_str(start_date)} ~ {_date_str(end_date)}",
    )


# ---------- 企业微信 ----------

def get_wecom_config() -> Dict[str, Any]:
    from wecom import load_wecom_config
    return load_wecom_config()


def update_wecom_config(config: Dict[str, Any]) -> Dict[str, Any]:
    save_wecom_config(config)
    return config


def listen_wecom(config: Dict[str, Any], timeout: int = 60) -> Optional[str]:
    return listen_wecom_chatid(
        config.get("bot_id", ""),
        config.get("secret", ""),
        timeout=timeout,
    )


def preview_wecom_report_service(report_date: datetime.date) -> Dict[str, Any]:
    content = build_daily_report(report_date, ai_config=get_config_defaults())
    return create_report_draft(content, report_date.strftime("%Y-%m-%d"), platform="pdd")


def send_wecom_report_service(
    report_date: datetime.date,
    config: Dict[str, Any],
    draft_id: Optional[str] = None,
) -> Dict[str, Any]:
    if draft_id:
        draft = get_report_draft(draft_id, report_date.strftime("%Y-%m-%d"), platform="pdd")
        content = draft["content"]
    else:
        # 兼容旧客户端：没有草稿 ID 时仍允许一次性生成并发送。
        content = build_daily_report(report_date, ai_config=get_config_defaults())
    result = send_wecom_report(content, config)
    if draft_id:
        mark_report_draft_sent(draft_id)
    return result


# ---------- 导出 ----------

def export_product_metrics_csv(store_name: str, start_date: datetime.date, end_date: datetime.date) -> str:
    data = load_analysis_data(store_name, start_date, end_date)
    df = pd.DataFrame(data["product_metrics"])
    return df.to_csv(index=False, encoding="utf-8-sig")


def export_style_metrics_csv(store_name: str, start_date: datetime.date, end_date: datetime.date) -> str:
    data = load_analysis_data(store_name, start_date, end_date)
    df = pd.DataFrame(data["style_metrics"])
    return df.to_csv(index=False, encoding="utf-8-sig")


# ---------- 历史记录 ----------

def get_records(store_name: Optional[str] = None) -> List[Dict[str, Any]]:
    return list_store_records(store_name)


def get_import_batches(
    store_name: Optional[str], actor: str, is_master: bool
) -> List[Dict[str, Any]]:
    records = list_batches(store_name)
    latest_by_store: Dict[str, str] = {}
    for record in records:
        if record.get("status") == "imported" and record.get("store_name") not in latest_by_store:
            latest_by_store[record["store_name"]] = record["batch_id"]

    result = []
    for record in records:
        item = dict(record)
        is_latest = latest_by_store.get(record.get("store_name")) == record.get("batch_id")
        owns_batch = record.get("imported_by") == actor
        item["can_rollback"] = (
            record.get("status") == "imported"
            and is_latest
            and (is_master or owns_batch)
        )
        if record.get("status") != "imported":
            item["rollback_reason"] = "该批次已撤销或已失效"
        elif not is_latest:
            item["rollback_reason"] = "只能撤销该店铺最近一次成功导入"
        elif not is_master and not owns_batch:
            item["rollback_reason"] = "只能撤销自己导入的批次"
        else:
            item["rollback_reason"] = ""
        result.append(item)
    return result


def rollback_import_batch(batch_id: str, actor: str, is_master: bool) -> Dict[str, Any]:
    record = rollback_batch(batch_id, actor, is_master)
    bump_data_version()
    return {
        "rolled_back": True,
        "batch_id": batch_id,
        "store_name": record.get("store_name"),
        "affected_dates": record.get("affected_dates", []),
    }


def delete_record(
    store_name: str, date: datetime.date, actor: str = "unknown"
) -> Dict[str, Any]:
    with IMPORT_LOCK:
        delete_daily_data(store_name, _date_str(date))
        invalidate_store_batches(store_name, actor, f"删除整日数据 {_date_str(date)}")
        bump_data_version()
    return {"deleted": True, "store_name": store_name, "date": _date_str(date)}
