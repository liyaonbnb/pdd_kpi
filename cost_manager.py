"""
商品成本与物流成本管理
- 根据订单中的商家编码维护成本
- 将成本应用到商品指标，计算链接毛利与盈亏
"""

import io
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from storage import list_available_dates, load_daily_orders


DATA_DIR = Path("data")
COSTS_FILE = DATA_DIR / "costs.json"
logger = logging.getLogger(__name__)


def _ensure_dir():
    DATA_DIR.mkdir(exist_ok=True)


def load_cost_config() -> Dict:
    """加载成本配置"""
    _ensure_dir()
    if not COSTS_FILE.exists():
        return {"merchant_costs": {}}
    try:
        config = json.loads(COSTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("成本配置文件无法读取: %s", COSTS_FILE, exc_info=True)
        raise RuntimeError(f"成本配置文件损坏或不可读，请先从备份恢复: {COSTS_FILE}") from exc
    if not isinstance(config, dict):
        raise RuntimeError(f"成本配置文件格式无效，请先从备份恢复: {COSTS_FILE}")
    return config


def save_cost_config(config: Dict):
    """保存成本配置"""
    _ensure_dir()
    temp_path = COSTS_FILE.with_name(f".{COSTS_FILE.name}.tmp")
    payload = json.dumps(config, ensure_ascii=False, indent=2)
    try:
        with temp_path.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, COSTS_FILE)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def _normalize_store(store_name: Optional[str]) -> str:
    return str(store_name or "默认店铺").strip()


def _normalize_code(code) -> str:
    if pd.isna(code):
        return ""
    return str(code).strip()


def _normalize_product_id(pid) -> str:
    """把商品 ID 统一为不带 .0 的字符串"""
    if pd.isna(pid):
        return ""
    s = str(pid).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def get_cost(config: Dict, store_name: Optional[str], merchant_code: str) -> Dict:
    """获取某个商家编码的成本"""
    store = _normalize_store(store_name)
    code = _normalize_code(merchant_code)
    costs = config.get("merchant_costs", {}).get(store, {})
    return costs.get(code, {
        "product_name": "",
        "product_cost": 0.0,
        "logistics_cost": 0.0,
        "updated_at": "",
    })


def set_cost(
    config: Dict,
    store_name: Optional[str],
    merchant_code: str,
    product_name: str = "",
    product_cost: float = 0.0,
    logistics_cost: float = 0.0,
) -> Dict:
    """设置某个商家编码的成本"""
    store = _normalize_store(store_name)
    code = _normalize_code(merchant_code)
    if not code:
        return config

    if "merchant_costs" not in config:
        config["merchant_costs"] = {}
    if store not in config["merchant_costs"]:
        config["merchant_costs"][store] = {}

    config["merchant_costs"][store][code] = {
        "product_name": str(product_name or "").strip(),
        "product_cost": float(product_cost or 0),
        "logistics_cost": float(logistics_cost or 0),
        "updated_at": datetime.now().isoformat(),
    }
    return config


def delete_cost(config: Dict, store_name: Optional[str], merchant_code: str) -> Dict:
    """删除某个商家编码的成本"""
    store = _normalize_store(store_name)
    code = _normalize_code(merchant_code)
    config.get("merchant_costs", {}).get(store, {}).pop(code, None)
    return config


def list_store_costs(config: Dict, store_name: Optional[str]) -> List[Dict]:
    """列出某店铺下所有成本配置"""
    store = _normalize_store(store_name)
    costs = config.get("merchant_costs", {}).get(store, {})
    rows = []
    for code, info in costs.items():
        rows.append({"merchant_code": code, **info})
    return rows


def load_product_merchant_mapping(config: Dict, store_name: Optional[str]) -> Dict[str, str]:
    """加载用户手动维护的 product_id -> merchant_code 映射"""
    store = _normalize_store(store_name)
    return config.get("product_merchant_maps", {}).get(store, {})


def set_product_merchant_mapping(
    config: Dict,
    store_name: Optional[str],
    product_id,
    merchant_code: str,
) -> Dict:
    """保存/更新 product_id -> merchant_code 映射"""
    store = _normalize_store(store_name)
    if "product_merchant_maps" not in config:
        config["product_merchant_maps"] = {}
    if store not in config["product_merchant_maps"]:
        config["product_merchant_maps"][store] = {}

    pid = _normalize_product_id(product_id)
    code = _normalize_code(merchant_code)
    if pid and code:
        config["product_merchant_maps"][store][pid] = code
    return config


def delete_product_merchant_mapping(
    config: Dict,
    store_name: Optional[str],
    product_id,
) -> Dict:
    """删除 product_id -> merchant_code 映射"""
    store = _normalize_store(store_name)
    pid = _normalize_product_id(product_id)
    if pid:
        config.get("product_merchant_maps", {}).get(store, {}).pop(pid, None)
    return config


def _find_merchant_code_column(orders: pd.DataFrame) -> Optional[str]:
    """兼容新旧数据，找到商家编码所在列"""
    if "merchant_code" in orders.columns:
        return "merchant_code"
    for col in orders.columns:
        col_str = str(col).strip()
        if col_str in ("商家编码", "商家代码", "商品编码", "链接编码"):
            return col_str
    return None


def extract_merchant_codes_from_orders(store_name: Optional[str]) -> pd.DataFrame:
    """
    从历史订单中提取所有商家编码（仅用于追加新编码，不考虑商品名称）
    兼容旧数据：原始列名如「商家编码」也能识别。
    返回 DataFrame：merchant_code
    """
    store = _normalize_store(store_name)
    dates = list_available_dates(store)
    codes = set()

    for d in dates:
        try:
            orders = load_daily_orders(d, store)
            if orders.empty:
                continue
            code_col = _find_merchant_code_column(orders)
            if not code_col:
                continue
            for _, r in orders.iterrows():
                code = _normalize_code(r.get(code_col))
                if not code:
                    continue
                codes.add(code)
        except Exception:
            continue

    if not codes:
        return pd.DataFrame(columns=["merchant_code"])

    return pd.DataFrame(sorted(codes), columns=["merchant_code"])


def append_new_merchant_codes(store_name: Optional[str]) -> int:
    """
    把订单中出现、但成本配置里还不存在的商家编码追加进去。
    已存在的编码不会被覆盖（成本、名称都保留）。
    返回新增编码数量。
    """
    store = _normalize_store(store_name)
    cfg = load_cost_config()
    saved = cfg.get("merchant_costs", {}).get(store, {})
    detected_df = extract_merchant_codes_from_orders(store)

    # 同时把用户手动维护的映射里的商家编码也加入成本表
    mapping = load_product_merchant_mapping(cfg, store)
    detected_codes = set()
    if not detected_df.empty:
        detected_codes = set(detected_df["merchant_code"].astype(str).tolist())
    mapped_codes = set(str(v) for v in mapping.values() if v)
    all_codes = detected_codes | mapped_codes

    if not all_codes:
        return 0

    added = 0
    for code in all_codes:
        code = _normalize_code(code)
        if not code or code in saved:
            continue
        cfg = set_cost(cfg, store_name=store, merchant_code=code)
        added += 1

    if added:
        save_cost_config(cfg)
    return added


def _build_product_id_to_merchant_code(store_name: Optional[str]) -> Dict[str, str]:
    """从历史订单中建立 product_id -> merchant_code 映射（用于旧数据回退）"""
    store = _normalize_store(store_name)
    mapping = {}
    dates = list_available_dates(store)
    for d in dates:
        try:
            orders = load_daily_orders(d, store)
            code_col = _find_merchant_code_column(orders)
            if not code_col or "product_id" not in orders.columns:
                continue
            for _, r in orders.iterrows():
                pid = _normalize_product_id(r.get("product_id"))
                code = _normalize_code(r.get(code_col))
                if pid and code and pid not in mapping:
                    mapping[pid] = code
        except Exception:
            continue
    return mapping


def _build_style_weighted_cost(
    store_name: Optional[str],
    style_map: Dict[str, str],
    costs: Dict[str, Dict],
) -> Dict[str, Dict[str, float]]:
    """
    当指标表是商品级、但映射是规格级时，按历史订单中各规格的销量加权，
    推算出每个 product_id 的平均单位成本。
    """
    if not style_map:
        return {}
    store = _normalize_store(store_name)
    style_qty: Dict[str, float] = {}
    for d in list_available_dates(store):
        try:
            orders = load_daily_orders(d, store)
            if orders.empty or "product_id" not in orders.columns:
                continue
            style_cols = _find_style_columns(orders)
            sid_col = style_cols.get("style_id_col") or "style_id"
            if sid_col not in orders.columns:
                continue
            qty_col = "valid_quantity" if "valid_quantity" in orders.columns else "quantity"
            if qty_col not in orders.columns:
                continue
            for _, r in orders.iterrows():
                pid = _normalize_product_id(r.get("product_id"))
                sid = _normalize_style_id(r.get(sid_col))
                qty = pd.to_numeric(r.get(qty_col, 0), errors="coerce") or 0
                if not pid or not sid or qty <= 0:
                    continue
                key = f"{pid}::{sid}"
                style_qty[key] = style_qty.get(key, 0.0) + float(qty)
        except Exception:
            continue

    product_costs: Dict[str, Dict[str, float]] = {}
    for key, code in style_map.items():
        if "::" not in key:
            continue
        pid, sid = key.split("::", 1)
        qty = style_qty.get(key, 0.0)
        if qty <= 0:
            continue
        cost = costs.get(code, {})
        pc = float(cost.get("product_cost", 0) or 0)
        lc = float(cost.get("logistics_cost", 0) or 0)
        entry = product_costs.setdefault(pid, {"product_cost": 0.0, "logistics_cost": 0.0, "qty": 0.0})
        entry["product_cost"] += pc * qty
        entry["logistics_cost"] += lc * qty
        entry["qty"] += qty

    result: Dict[str, Dict[str, float]] = {}
    for pid, entry in product_costs.items():
        qty = entry["qty"]
        if qty > 0:
            result[pid] = {
                "product_cost": entry["product_cost"] / qty,
                "logistics_cost": entry["logistics_cost"] / qty,
            }
    return result


def compute_order_level_costs(orders: pd.DataFrame, store_name: Optional[str]) -> pd.DataFrame:
    """按订单规格（商家编码）分别计价，并汇总到商品维度。
    返回列：product_id, [date], total_product_cost, total_logistics_cost。
    未录入成本的编码按 0 计（与商品级缺失成本行为一致）。"""
    if orders is None or orders.empty or "merchant_code" not in orders.columns:
        return pd.DataFrame()
    o = orders.copy()
    if "is_valid" in o.columns:
        o = o[o["is_valid"] == 1]
    if o.empty or "product_id" not in o.columns:
        return pd.DataFrame()

    config = load_cost_config()
    store = _normalize_store(store_name)
    merged_costs = {**config.get("merchant_costs", {}).get(store, {}), **load_global_costs(config)}

    o["_pid"] = o["product_id"].apply(_normalize_product_id)
    o["_code"] = o["merchant_code"].astype(str).str.strip().replace(["None", "nan", "NaN"], "")
    # 手动维护的映射优先（规格 > 商品）
    style_col = "style_id" if "style_id" in o.columns else None
    o["_code"] = o.apply(
        lambda r: lookup_global_merchant_code(
            r["product_id"], r.get(style_col) if style_col else None, config
        ) or r["_code"],
        axis=1,
    )
    pc_map = {k: float(v.get("product_cost", 0) or 0) for k, v in merged_costs.items()}
    lc_map = {k: float(v.get("logistics_cost", 0) or 0) for k, v in merged_costs.items()}
    o["_qty"] = pd.to_numeric(o.get("quantity", 0), errors="coerce").fillna(0)
    o["_pc"] = o["_code"].map(pc_map).fillna(0) * o["_qty"]
    o["_lc"] = o["_code"].map(lc_map).fillna(0) * o["_qty"]

    group_cols = ["_pid"] + (["date"] if "date" in o.columns else [])
    g = o.groupby(group_cols, as_index=False).agg(
        total_product_cost=("_pc", "sum"),
        total_logistics_cost=("_lc", "sum"),
    )
    return g.rename(columns={"_pid": "product_id"})


def apply_costs_to_metrics(metrics: pd.DataFrame, store_name: Optional[str], orders: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    将成本配置合并到商品指标表，并计算链接毛利与盈亏。
    优先使用全局成本配置，再回退到店铺级成本配置。
    如果指标表里没有 merchant_code，会尝试用 product_id 从历史订单反查。
    传入 orders 时，成本按订单规格（商家编码）分别计价，覆盖商品级估算。
    """
    if metrics is None or metrics.empty:
        return metrics

    df = metrics.copy()
    config = load_cost_config()
    store = _normalize_store(store_name)

    # 合并全局成本和店铺成本，全局优先
    global_costs = load_global_costs(config)
    store_costs = config.get("merchant_costs", {}).get(store, {})
    merged_costs = {**store_costs, **global_costs}

    if not merged_costs:
        df["product_cost_unit"] = 0.0
        df["logistics_cost_unit"] = 0.0
        df["total_cost"] = 0.0
        df["link_gross_profit"] = df.get("valid_merchant_income", 0)
        df["profit_loss"] = df["link_gross_profit"] - df.get("promo_spend", 0)
        df["gross_margin_rate"] = 0.0
        return df

    cost_df = pd.DataFrame([
        {"merchant_code": code, **info}
        for code, info in merged_costs.items()
    ])

    # 确保 merchant_code 列为字符串，并把缺失标记统一成空字符串
    if "merchant_code" in df.columns:
        df["merchant_code"] = (
            df["merchant_code"].astype(str).str.strip()
            .replace(["None", "nan", "NaN"], "")
            .fillna("")
        )
    else:
        df["merchant_code"] = ""

    # 用户手动维护的映射优先（覆盖订单中的编码）：规格 > 商品 > 店铺级
    if "product_id" in df.columns:
        style_id_col = None
        for col in df.columns:
            if str(col).lower() in ("style_id", "样式id", "款式id"):
                style_id_col = col
                break
        if style_id_col:
            df["merchant_code"] = df.apply(
                lambda r: lookup_global_merchant_code(r["product_id"], r.get(style_id_col), config) or r["merchant_code"],
                axis=1,
            )
        else:
            df["merchant_code"] = df.apply(
                lambda r: lookup_global_merchant_code(r["product_id"], None, config) or r["merchant_code"],
                axis=1,
            )
        # 兼容旧店铺级映射
        store_mapping = load_product_merchant_mapping(config, store)
        if store_mapping:
            blank = df["merchant_code"].replace("", pd.NA).isna()
            if blank.any():
                mapped_codes = df.loc[blank, "product_id"].apply(_normalize_product_id).map(store_mapping)
                df.loc[blank, "merchant_code"] = mapped_codes

    # 旧数据回退：用 product_id 从历史订单反查商家编码
    merchant_codes_blank = df["merchant_code"].replace("", pd.NA).isna()
    if merchant_codes_blank.any() and "product_id" in df.columns:
        mapping = _build_product_id_to_merchant_code(store_name)
        if mapping:
            df.loc[merchant_codes_blank, "merchant_code"] = (
                df.loc[merchant_codes_blank, "product_id"]
                .apply(_normalize_product_id)
                .map(mapping)
            )
    df["merchant_code"] = df["merchant_code"].fillna("").astype(str).str.strip()

    df = df.merge(
        cost_df[["merchant_code", "product_cost", "logistics_cost"]],
        on="merchant_code",
        how="left",
        suffixes=("", "_cost"),
    )

    df["product_cost_unit"] = pd.to_numeric(df.get("product_cost_cost", df.get("product_cost", 0)), errors="coerce").fillna(0)
    df["logistics_cost_unit"] = pd.to_numeric(df.get("logistics_cost_cost", df.get("logistics_cost", 0)), errors="coerce").fillna(0)

    # 兜底：商品级指标缺少 style_id 时，用全局规格映射的销量加权平均成本回退
    blank_code_mask = df["merchant_code"].replace("", pd.NA).isna()
    if blank_code_mask.any() and "product_id" in df.columns:
        style_map = config.get(GLOBAL_STYLE_MAP_KEY, {})
        if style_map:
            style_weighted = _build_style_weighted_cost(store_name, style_map, merged_costs)
            if style_weighted:
                pc_map = {k: v["product_cost"] for k, v in style_weighted.items()}
                lc_map = {k: v["logistics_cost"] for k, v in style_weighted.items()}
                df.loc[blank_code_mask, "product_cost_unit"] = (
                    df.loc[blank_code_mask, "product_id"]
                    .apply(_normalize_product_id)
                    .map(pc_map)
                    .fillna(df.loc[blank_code_mask, "product_cost_unit"])
                )
                df.loc[blank_code_mask, "logistics_cost_unit"] = (
                    df.loc[blank_code_mask, "product_id"]
                    .apply(_normalize_product_id)
                    .map(lc_map)
                    .fillna(df.loc[blank_code_mask, "logistics_cost_unit"])
                )

    # 成本按有效件数计算；如果没有件数则按有效订单数
    quantity_col = "valid_quantity" if "valid_quantity" in df.columns else "valid_order_count"
    df["cost_quantity"] = pd.to_numeric(df.get(quantity_col, 0), errors="coerce").fillna(0)

    df["total_product_cost"] = df["product_cost_unit"] * df["cost_quantity"]
    df["total_logistics_cost"] = df["logistics_cost_unit"] * df["cost_quantity"]

    # 按规格分别计价：提供订单数据时，以订单实际成本覆盖商品级估算
    if orders is not None and not orders.empty and "product_id" in df.columns:
        oc = compute_order_level_costs(orders, store_name)
        if not oc.empty:
            use_date = "date" in df.columns and "date" in oc.columns
            if use_date:
                keys = list(zip(oc["product_id"], oc["date"].astype(str)))
            else:
                keys = oc["product_id"].tolist()
            pc_dict = dict(zip(keys, oc["total_product_cost"]))
            lc_dict = dict(zip(keys, oc["total_logistics_cost"]))
            df["_pid"] = df["product_id"].apply(_normalize_product_id)
            if use_date:
                df_keys = list(zip(df["_pid"], df["date"].astype(str)))
                df["total_product_cost"] = pd.Series([pc_dict.get(k, 0.0) for k in df_keys], index=df.index)
                df["total_logistics_cost"] = pd.Series([lc_dict.get(k, 0.0) for k in df_keys], index=df.index)
            else:
                df["total_product_cost"] = df["_pid"].map(pc_dict).fillna(0.0)
                df["total_logistics_cost"] = df["_pid"].map(lc_dict).fillna(0.0)
            df = df.drop(columns=["_pid"])

    df["total_cost"] = df["total_product_cost"] + df["total_logistics_cost"]

    df["valid_merchant_income"] = pd.to_numeric(df.get("valid_merchant_income", 0), errors="coerce").fillna(0)
    df["promo_spend"] = pd.to_numeric(df.get("promo_spend", 0), errors="coerce").fillna(0)
    # 平台技术服务费在毛利中扣除（不影响有效商家实收）
    df["platform_fee"] = pd.to_numeric(df.get("platform_fee", 0), errors="coerce").fillna(0)

    df["link_gross_profit"] = df["valid_merchant_income"] - df["total_cost"] - df["platform_fee"]
    df["profit_loss"] = df["link_gross_profit"] - df["promo_spend"]
    df["gross_margin_rate"] = df.apply(
        lambda r: (r["link_gross_profit"] / r["valid_merchant_income"] * 100)
        if r["valid_merchant_income"] else 0.0,
        axis=1,
    )
    df["profit_loss_rate"] = df.apply(
        lambda r: (r["profit_loss"] / r["valid_merchant_income"] * 100)
        if r["valid_merchant_income"] else 0.0,
        axis=1,
    )

    # 清理临时列
    for col in ["product_cost_cost", "logistics_cost_cost"]:
        if col in df.columns:
            df = df.drop(columns=[col])

    return df


def compute_cost_kpis(metrics: pd.DataFrame) -> Dict[str, float]:
    """从已应用成本的成本指标中汇总成本相关 KPI"""
    if metrics is None or metrics.empty:
        return {
            "total_cost": 0.0,
            "link_gross_profit": 0.0,
            "profit_loss": 0.0,
            "gross_margin_rate": 0.0,
        }

    cols = ["total_cost", "link_gross_profit", "profit_loss", "valid_merchant_income"]
    for c in cols:
        if c not in metrics.columns:
            metrics[c] = 0.0
        else:
            metrics[c] = pd.to_numeric(metrics[c], errors="coerce").fillna(0)

    income = metrics["valid_merchant_income"].sum()
    profit = metrics["link_gross_profit"].sum()
    return {
        "total_cost": metrics["total_cost"].sum(),
        "link_gross_profit": profit,
        "profit_loss": metrics["profit_loss"].sum(),
        "gross_margin_rate": (profit / income * 100) if income else 0.0,
    }


def export_costs_to_csv(store_name: Optional[str]) -> str:
    """导出某店铺成本配置为 CSV 字符串（UTF-8-sig，含 BOM）"""
    rows = list_store_costs(load_cost_config(), store_name)
    df = pd.DataFrame(rows, columns=["merchant_code", "product_name", "product_cost", "logistics_cost"])
    df.columns = ["商家编码", "商品名称", "商品成本/件", "物流成本/件"]
    return df.to_csv(index=False, encoding="utf-8-sig")


def export_global_costs_to_csv(pending_only: bool = False) -> str:
    """导出全局成本配置为 CSV 字符串（UTF-8-sig，含 BOM）"""
    rows = list_global_cost_rows()
    if pending_only:
        rows = [
            r
            for r in rows
            if (r.get("product_cost") or 0) <= 0 or (r.get("logistics_cost") or 0) <= 0
        ]
    df = pd.DataFrame(rows, columns=["merchant_code", "product_name", "product_cost", "logistics_cost"])
    df.columns = ["商家编码", "商品名称", "商品成本/件", "物流成本/件"]
    return df.to_csv(index=False, encoding="utf-8-sig")


def import_global_costs_from_csv(file_obj) -> int:
    """从 CSV 导入全局成本配置"""
    if hasattr(file_obj, "read"):
        bytes_data = file_obj.read()
        file_obj.seek(0)
    else:
        with open(file_obj, "rb") as f:
            bytes_data = f.read()

    df = None
    for enc in ["utf-8-sig", "utf-8", "gbk", "gb18030"]:
        try:
            df = pd.read_csv(io.BytesIO(bytes_data), encoding=enc)
            break
        except Exception:
            continue
    if df is None:
        raise ValueError("无法读取 CSV，请检查编码")

    rename = {}
    for col in df.columns:
        norm = _normalize_cost_column_name(col)
        if norm in ["merchant_code", "product_name", "product_cost", "logistics_cost"]:
            rename[col] = norm
    df = df.rename(columns=rename)

    required = ["merchant_code", "product_cost", "logistics_cost"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"CSV 缺少必要列：{col}")

    cfg = load_cost_config()
    count = 0
    for _, rec in df.iterrows():
        code = _normalize_code(rec.get("merchant_code"))
        if not code:
            continue
        cfg = save_global_cost(
            cfg,
            merchant_code=code,
            product_name=str(rec.get("product_name", "") or ""),
            product_cost=pd.to_numeric(rec.get("product_cost", 0), errors="coerce") or 0,
            logistics_cost=pd.to_numeric(rec.get("logistics_cost", 0), errors="coerce") or 0,
        )
        count += 1

    if count:
        save_cost_config(cfg)
    return count


def _normalize_cost_column_name(name: str) -> str:
    """识别导入 CSV 的列名"""
    name = str(name).strip().replace(" ", "").replace("(元)", "").replace("（元）", "")
    mapping = {
        "商家编码": "merchant_code",
        "商家代码": "merchant_code",
        "商品编码": "merchant_code",
        "链接编码": "merchant_code",
        "merchantcode": "merchant_code",
        "merchant_code": "merchant_code",
        "商品名称": "product_name",
        "商品名": "product_name",
        "productname": "product_name",
        "product_name": "product_name",
        "商品成本": "product_cost",
        "商品成本/件": "product_cost",
        "成本": "product_cost",
        "productcost": "product_cost",
        "product_cost": "product_cost",
        "物流成本": "logistics_cost",
        "物流成本/件": "logistics_cost",
        "logisticscost": "logistics_cost",
        "logistics_cost": "logistics_cost",
    }
    return mapping.get(name, name)


def import_costs_from_csv(store_name: Optional[str], file_obj) -> int:
    """
    从 CSV 导入成本配置，按商家编码更新/追加，不删除未在 CSV 中出现的编码。
    返回更新/新增的记录数。
    """
    if hasattr(file_obj, "read"):
        bytes_data = file_obj.read()
        file_obj.seek(0)
    else:
        with open(file_obj, "rb") as f:
            bytes_data = f.read()

    # 尝试常见编码
    df = None
    for enc in ["utf-8-sig", "utf-8", "gbk", "gb18030"]:
        try:
            df = pd.read_csv(io.BytesIO(bytes_data), encoding=enc)
            break
        except Exception:
            continue
    if df is None:
        raise ValueError("无法读取 CSV，请检查编码")

    # 标准化列名
    rename = {}
    for col in df.columns:
        norm = _normalize_cost_column_name(col)
        if norm in ["merchant_code", "product_name", "product_cost", "logistics_cost"]:
            rename[col] = norm
    df = df.rename(columns=rename)

    required = ["merchant_code", "product_cost", "logistics_cost"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"CSV 缺少必要列：{col}")

    cfg = load_cost_config()
    count = 0
    for _, rec in df.iterrows():
        code = _normalize_code(rec.get("merchant_code"))
        if not code:
            continue
        cfg = set_cost(
            cfg,
            store_name=store_name,
            merchant_code=code,
            product_name=str(rec.get("product_name", "") or ""),
            product_cost=pd.to_numeric(rec.get("product_cost", 0), errors="coerce") or 0,
            logistics_cost=pd.to_numeric(rec.get("logistics_cost", 0), errors="coerce") or 0,
        )
        count += 1

    if count:
        save_cost_config(cfg)
    return count


# ==================== 全局成本管理（不区分店铺） ====================

GLOBAL_COSTS_KEY = "global_merchant_costs"
GLOBAL_PRODUCT_MAP_KEY = "global_product_merchant_map"
GLOBAL_STYLE_MAP_KEY = "global_style_merchant_map"


def _normalize_style_id(sid) -> str:
    if pd.isna(sid):
        return ""
    s = str(sid).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def _style_map_key(product_id, style_id) -> str:
    return f"{_normalize_product_id(product_id)}::{_normalize_style_id(style_id)}"


def load_global_costs(config: Optional[Dict] = None) -> Dict[str, Dict]:
    """加载全局商家编码成本配置"""
    cfg = config or load_cost_config()
    return cfg.get(GLOBAL_COSTS_KEY, {})


def save_global_cost(
    config: Dict,
    merchant_code: str,
    product_name: str = "",
    product_cost: float = 0.0,
    logistics_cost: float = 0.0,
) -> Dict:
    """保存全局商家编码成本"""
    code = _normalize_code(merchant_code)
    if not code:
        return config
    if GLOBAL_COSTS_KEY not in config:
        config[GLOBAL_COSTS_KEY] = {}
    config[GLOBAL_COSTS_KEY][code] = {
        "product_name": str(product_name or "").strip(),
        "product_cost": float(product_cost or 0),
        "logistics_cost": float(logistics_cost or 0),
        "updated_at": datetime.now().isoformat(),
    }
    return config


def delete_global_cost(config: Dict, merchant_code: str) -> Dict:
    """删除全局商家编码成本"""
    code = _normalize_code(merchant_code)
    config.get(GLOBAL_COSTS_KEY, {}).pop(code, None)
    return config


def list_global_cost_rows(config: Optional[Dict] = None) -> List[Dict]:
    """列出全局成本配置行"""
    costs = load_global_costs(config)
    return [{"merchant_code": code, **info} for code, info in costs.items()]


def load_global_product_mapping(config: Optional[Dict] = None) -> Dict[str, str]:
    """加载全局 product_id -> merchant_code 映射"""
    cfg = config or load_cost_config()
    return cfg.get(GLOBAL_PRODUCT_MAP_KEY, {})


def save_global_product_mapping(
    config: Dict,
    product_id,
    merchant_code: str,
    style_id=None,
    product_name: str = "",
) -> Dict:
    """保存全局 product_id / style_id -> merchant_code 映射"""
    pid = _normalize_product_id(product_id)
    sid = _normalize_style_id(style_id)
    code = _normalize_code(merchant_code)
    if not code or not pid:
        return config

    if sid:
        if GLOBAL_STYLE_MAP_KEY not in config:
            config[GLOBAL_STYLE_MAP_KEY] = {}
        config[GLOBAL_STYLE_MAP_KEY][_style_map_key(pid, sid)] = code
    else:
        if GLOBAL_PRODUCT_MAP_KEY not in config:
            config[GLOBAL_PRODUCT_MAP_KEY] = {}
        config[GLOBAL_PRODUCT_MAP_KEY][pid] = code

    # 如果该商家编码还没有成本记录，自动创建一个记录；如果已有但商品名称为空，则补全商品名称
    existing = load_global_costs(config)
    if code not in existing:
        config = save_global_cost(config, code, product_name=product_name or "")
    elif product_name and not existing[code].get("product_name"):
        config[GLOBAL_COSTS_KEY][code]["product_name"] = str(product_name).strip()
    return config


def delete_global_product_mapping(config: Dict, product_id, style_id=None) -> Dict:
    """删除全局 product_id / style_id -> merchant_code 映射"""
    pid = _normalize_product_id(product_id)
    sid = _normalize_style_id(style_id)
    if pid:
        config.get(GLOBAL_PRODUCT_MAP_KEY, {}).pop(pid, None)
    if pid and sid:
        config.get(GLOBAL_STYLE_MAP_KEY, {}).pop(_style_map_key(pid, sid), None)
    return config


def lookup_global_merchant_code(product_id, style_id=None, config: Optional[Dict] = None) -> str:
    """按 style_id 优先、product_id 次之查找映射的商家编码"""
    cfg = config or load_cost_config()
    pid = _normalize_product_id(product_id)
    sid = _normalize_style_id(style_id)
    if sid:
        style_code = cfg.get(GLOBAL_STYLE_MAP_KEY, {}).get(_style_map_key(pid, sid))
        if style_code:
            return style_code
    return cfg.get(GLOBAL_PRODUCT_MAP_KEY, {}).get(pid, "")


def get_all_merchant_codes() -> pd.DataFrame:
    """
    从所有店铺的历史订单中提取所有商家编码并去重。
    返回 DataFrame：merchant_code
    """
    from storage import list_available_stores
    codes = set()
    stores = list_available_stores() or []
    for store in stores:
        df = extract_merchant_codes_from_orders(store)
        if not df.empty:
            codes.update(df["merchant_code"].astype(str).tolist())
    # 也包含手动映射中的商家编码（商品级 + 规格级）
    config = load_cost_config()
    mapping = load_global_product_mapping(config)
    codes.update(str(v) for v in mapping.values() if v)
    style_mapping = config.get(GLOBAL_STYLE_MAP_KEY, {})
    codes.update(str(v) for v in style_mapping.values() if v)
    global_costs = load_global_costs(config)
    codes.update(str(k) for k in global_costs.keys() if k)

    if not codes:
        return pd.DataFrame(columns=["merchant_code"])
    return pd.DataFrame(sorted(codes), columns=["merchant_code"])


def _find_style_columns(orders: pd.DataFrame) -> Dict[str, Optional[str]]:
    """找出样式相关列，返回 {style_id_col, style_name_col, spec_col}"""
    result = {"style_id_col": None, "style_name_col": None, "spec_col": None}
    cols = [str(c).strip() for c in orders.columns]
    for col in cols:
        if col.lower() in ("style_id", "样式id", "款式id", "styleid"):
            result["style_id_col"] = col
        if col in ("style_name", "样式名称", "款式名称", "商品规格"):
            result["style_name_col"] = col
        if col in ("商品规格", "规格", "sku", "specification"):
            result["spec_col"] = col
    return result


def get_products_without_merchant_code() -> pd.DataFrame:
    """
    找出历史订单中出现、但还没有商家编码的商品（按商品规格区分）。
    返回 DataFrame 包含 product_id, product_name, style_id, style_name, store_name, order_count 等。
    """
    from storage import list_available_stores, list_available_dates, load_daily_orders
    stores = list_available_stores() or []
    config = load_cost_config()
    rows = []

    for store in stores:
        dates = list_available_dates(store)
        for d in dates:
            try:
                orders = load_daily_orders(d, store)
                if orders.empty:
                    continue
                code_col = _find_merchant_code_column(orders)
                style_cols = _find_style_columns(orders)
                if "product_id" not in orders.columns:
                    continue
                for _, r in orders.iterrows():
                    pid = _normalize_product_id(r.get("product_id"))
                    pname = str(r.get("product_name", "") or "").strip()
                    sid = _normalize_style_id(r.get(style_cols.get("style_id_col") or "style_id"))
                    sname = str(r.get(style_cols.get("style_name_col") or "style_name") or r.get(style_cols.get("spec_col")) or "").strip()
                    if not pid:
                        continue
                    # 已有商家编码的跳过
                    if code_col and _normalize_code(r.get(code_col)):
                        continue
                    # 已有全局映射的跳过（按规格或按商品）
                    if lookup_global_merchant_code(pid, sid, config):
                        continue
                    rows.append({
                        "product_id": pid,
                        "product_name": pname,
                        "style_id": sid or "-",
                        "style_name": sname or "-",
                        "store_name": store,
                        "date": d,
                    })
            except Exception:
                continue

    if not rows:
        return pd.DataFrame(columns=["product_id", "product_name", "style_id", "style_name", "store_name", "order_count"])

    df = pd.DataFrame(rows)
    agg = df.groupby(["product_id", "product_name", "style_id", "style_name", "store_name"], as_index=False).agg(
        order_count=("date", "count"),
        first_date=("date", "min"),
    )
    return agg.sort_values(["order_count", "product_id"], ascending=[False, True])


def refresh_global_cost_codes() -> Dict[str, int]:
    """
    刷新全局商家编码：把订单中出现、但成本配置里还不存在的编码追加进去。
    返回 {added: 新增数量}
    """
    config = load_cost_config()
    existing = load_global_costs(config)
    detected = get_all_merchant_codes()
    added = 0
    for code in detected["merchant_code"].astype(str).tolist():
        code = _normalize_code(code)
        if not code or code in existing:
            continue
        config = save_global_cost(config, code)
        added += 1
    if added:
        save_cost_config(config)
    return {"added": added}
