"""
本地数据持久化：保存每日处理结果，支持历史趋势查询，支持多店铺
"""

import os
import json
import pandas as pd
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple


DATA_DIR = Path("data")
PROCESSED_DIR = DATA_DIR / "processed"
META_FILE = DATA_DIR / "meta.json"


def init_storage():
    """初始化存储目录"""
    DATA_DIR.mkdir(exist_ok=True)
    PROCESSED_DIR.mkdir(exist_ok=True)


def _date_to_str(d) -> str:
    if d is None:
        return datetime.now().strftime("%Y-%m-%d")
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, date):
        return d.strftime("%Y-%m-%d")
    return str(d)


def _store_to_str(store_name: Optional[str]) -> str:
    """店铺名称文件名安全化"""
    if not store_name:
        return "default"
    return str(store_name).strip().replace("/", "_").replace("\\", "_").replace(" ", "_")


def _record_key(store_str: str, date_str: str) -> str:
    return f"{store_str}_{date_str}"


def save_daily_data(
    product_metrics: pd.DataFrame,
    style_metrics: pd.DataFrame,
    orders: pd.DataFrame,
    date: Optional[str] = None,
    store_name: Optional[str] = None,
    meta: Optional[Dict] = None,
):
    """保存每日处理后的数据"""
    init_storage()
    date_str = _date_to_str(date)
    store_str = _store_to_str(store_name)

    # 注册店铺
    try:
        from store_manager import ensure_store
        ensure_store(store_name or "默认店铺")
    except Exception:
        pass

    # 添加店铺列
    for df in [product_metrics, style_metrics, orders]:
        if not df.empty and "store_name" not in df.columns:
            df["store_name"] = store_name or "默认店铺"

    # 保存为 parquet（若 pyarrow 不可用则 CSV）
    try:
        product_metrics.to_parquet(PROCESSED_DIR / f"product_{store_str}_{date_str}.parquet", index=False)
        style_metrics.to_parquet(PROCESSED_DIR / f"style_{store_str}_{date_str}.parquet", index=False)
        orders.to_parquet(PROCESSED_DIR / f"orders_{store_str}_{date_str}.parquet", index=False)
    except Exception:
        product_metrics.to_csv(PROCESSED_DIR / f"product_{store_str}_{date_str}.csv", index=False, encoding="utf-8-sig")
        style_metrics.to_csv(PROCESSED_DIR / f"style_{store_str}_{date_str}.csv", index=False, encoding="utf-8-sig")
        orders.to_csv(PROCESSED_DIR / f"orders_{store_str}_{date_str}.csv", index=False, encoding="utf-8-sig")

    # 更新元数据
    meta_data = {}
    if META_FILE.exists():
        try:
            meta_data = json.loads(META_FILE.read_text(encoding="utf-8"))
        except Exception:
            meta_data = {}

    if "records" not in meta_data:
        meta_data["records"] = {}

    record_key = _record_key(store_str, date_str)
    meta_data["records"][record_key] = {
        "date": date_str,
        "store_name": store_name or "默认店铺",
        "store_safe": store_str,
        "saved_at": datetime.now().isoformat(),
        "product_rows": len(product_metrics),
        "style_rows": len(style_metrics),
        "order_rows": len(orders),
        **(meta or {}),
    }

    META_FILE.write_text(json.dumps(meta_data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_available_stores() -> List[str]:
    """列出已保存的店铺（注册表 + 历史数据合并）"""
    init_storage()
    stores = set()

    # 从注册表读取
    try:
        from store_manager import list_store_names
        stores.update(list_store_names())
    except Exception:
        pass

    # 从历史 meta 读取（兼容旧数据）
    if META_FILE.exists():
        try:
            meta = json.loads(META_FILE.read_text(encoding="utf-8"))
            for record in meta.get("records", {}).values():
                stores.add(record.get("store_name", "默认店铺"))
        except Exception:
            pass
    return sorted(stores)


def list_available_dates(store_name: Optional[str] = None) -> List[str]:
    """列出已保存的日期"""
    init_storage()
    dates = set()
    if META_FILE.exists():
        try:
            meta = json.loads(META_FILE.read_text(encoding="utf-8"))
            for record in meta.get("records", {}).values():
                if store_name is None or record.get("store_name") == store_name:
                    dates.add(record.get("date"))
        except Exception:
            pass
    return sorted(dates)


def list_store_records(store_name: Optional[str] = None) -> List[dict]:
    """列出所有保存记录"""
    init_storage()
    records = []
    if META_FILE.exists():
        try:
            meta = json.loads(META_FILE.read_text(encoding="utf-8"))
            for key, record in meta.get("records", {}).items():
                if store_name is None or record.get("store_name") == store_name:
                    records.append(record)
        except Exception:
            pass
    return sorted(records, key=lambda x: (x.get("store_name", ""), x.get("date", "")))


def record_exists(store_name: Optional[str], date) -> bool:
    """判断某店铺某日是否已有数据"""
    store_str = _store_to_str(store_name)
    date_str = _date_to_str(date)
    if META_FILE.exists():
        try:
            meta = json.loads(META_FILE.read_text(encoding="utf-8"))
            return _record_key(store_str, date_str) in meta.get("records", {})
        except Exception:
            pass
    return False


def load_daily_data(date, store_name: Optional[str] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """加载某日某店铺的商品和样式指标"""
    date_str = _date_to_str(date)
    store_str = _store_to_str(store_name)

    product_path_parquet = PROCESSED_DIR / f"product_{store_str}_{date_str}.parquet"
    product_path_csv = PROCESSED_DIR / f"product_{store_str}_{date_str}.csv"
    style_path_parquet = PROCESSED_DIR / f"style_{store_str}_{date_str}.parquet"
    style_path_csv = PROCESSED_DIR / f"style_{store_str}_{date_str}.csv"

    if product_path_parquet.exists():
        product_df = pd.read_parquet(product_path_parquet)
    elif product_path_csv.exists():
        product_df = pd.read_csv(product_path_csv)
    else:
        raise FileNotFoundError(f"未找到 {store_name or '默认店铺'} {date_str} 的数据文件")

    if style_path_parquet.exists():
        style_df = pd.read_parquet(style_path_parquet)
    elif style_path_csv.exists():
        style_df = pd.read_csv(style_path_csv)
    else:
        style_df = pd.DataFrame()

    return product_df, style_df


def load_daily_orders(date, store_name: Optional[str] = None) -> pd.DataFrame:
    """加载某日某店铺的订单明细"""
    date_str = _date_to_str(date)
    store_str = _store_to_str(store_name)

    orders_path_parquet = PROCESSED_DIR / f"orders_{store_str}_{date_str}.parquet"
    orders_path_csv = PROCESSED_DIR / f"orders_{store_str}_{date_str}.csv"

    if orders_path_parquet.exists():
        return pd.read_parquet(orders_path_parquet)
    elif orders_path_csv.exists():
        return pd.read_csv(orders_path_csv)
    else:
        raise FileNotFoundError(f"未找到 {store_name or '默认店铺'} {date_str} 的订单文件")


def save_daily_promo(promo: pd.DataFrame, date: Optional[str] = None, store_name: Optional[str] = None):
    """单独保存某日某店铺的原始推广数据"""
    init_storage()
    date_str = _date_to_str(date)
    store_str = _store_to_str(store_name)
    if not promo.empty and "store_name" not in promo.columns:
        promo = promo.copy()
        promo["store_name"] = store_name or "默认店铺"
    try:
        promo.to_parquet(PROCESSED_DIR / f"promo_{store_str}_{date_str}.parquet", index=False)
    except Exception:
        promo.to_csv(PROCESSED_DIR / f"promo_{store_str}_{date_str}.csv", index=False, encoding="utf-8-sig")


def load_daily_promo(date, store_name: Optional[str] = None) -> pd.DataFrame:
    """加载某日某店铺的原始推广数据"""
    date_str = _date_to_str(date)
    store_str = _store_to_str(store_name)

    promo_path_parquet = PROCESSED_DIR / f"promo_{store_str}_{date_str}.parquet"
    promo_path_csv = PROCESSED_DIR / f"promo_{store_str}_{date_str}.csv"

    if promo_path_parquet.exists():
        return pd.read_parquet(promo_path_parquet)
    elif promo_path_csv.exists():
        return pd.read_csv(promo_path_csv)
    else:
        raise FileNotFoundError(f"未找到 {store_name or '默认店铺'} {date_str} 的推广文件")


def delete_daily_promo(store_name: Optional[str], date) -> None:
    """删除某店铺某日的原始推广文件，不影响订单文件。"""
    init_storage()
    store_str = _store_to_str(store_name)
    date_str = _date_to_str(date)
    for extension in ("parquet", "csv"):
        path = PROCESSED_DIR / f"promo_{store_str}_{date_str}.{extension}"
        if path.exists():
            path.unlink()


def delete_daily_data(store_name: Optional[str], date):
    """删除某日某店铺的数据文件和 meta 记录"""
    init_storage()
    store_str = _store_to_str(store_name)
    date_str = _date_to_str(date)
    record_key = _record_key(store_str, date_str)

    # 删除文件
    for prefix in ["product", "style", "orders", "promo"]:
        for ext in ["parquet", "csv"]:
            f = PROCESSED_DIR / f"{prefix}_{store_str}_{date_str}.{ext}"
            if f.exists():
                try:
                    f.unlink()
                except Exception:
                    pass

    # 删除 meta 记录
    if META_FILE.exists():
        try:
            meta = json.loads(META_FILE.read_text(encoding="utf-8"))
            meta.get("records", {}).pop(record_key, None)
            META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


def remove_order_ids_from_store(store_name: Optional[str], order_ids: List[str]) -> List[str]:
    """从某店铺所有日期的订单文件中移除指定 order_id，并返回受影响的日期列表"""
    init_storage()
    store_str = _store_to_str(store_name)
    target_ids = set(str(o) for o in order_ids)
    affected_dates: List[str] = []

    for path in PROCESSED_DIR.glob(f"orders_{store_str}_*"):
        if path.suffix not in (".parquet", ".csv"):
            continue
        # 从文件名提取日期：orders_{store}_{date}.parquet
        try:
            date_str = path.stem.split(f"orders_{store_str}_", 1)[1]
        except Exception:
            continue
        try:
            df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
        except Exception:
            continue
        if df.empty or "order_id" not in df.columns:
            continue
        df["order_id"] = df["order_id"].astype(str)
        before = len(df)
        df = df[~df["order_id"].isin(target_ids)].copy()
        if len(df) == before:
            continue
        affected_dates.append(date_str)
        try:
            if path.suffix == ".parquet":
                df.to_parquet(path, index=False)
            else:
                df.to_csv(path, index=False, encoding="utf-8-sig")
        except Exception:
            continue
        # 同步更新 meta 中的 order_rows
        if META_FILE.exists():
            try:
                meta = json.loads(META_FILE.read_text(encoding="utf-8"))
                record_key = _record_key(store_str, date_str)
                if record_key in meta.get("records", {}):
                    meta["records"][record_key]["order_rows"] = len(df)
                    META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
    return sorted(affected_dates)


def load_all_product_history(store_names: Optional[List[str]] = None) -> pd.DataFrame:
    """加载所有历史商品级数据用于趋势分析"""
    dates = list_available_dates()
    stores = store_names or list_available_stores()
    dfs = []
    for store in stores:
        store_str = _store_to_str(store)
        for d in dates:
            try:
                df, _ = load_daily_data(d, store)
                dfs.append(df)
            except Exception:
                continue
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)
