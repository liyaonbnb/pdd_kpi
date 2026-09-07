"""网店管家出入库明细与单品/组合商品的批量导入。

入库 = 直接入库建批次（other_in），出库 = 按 FIFO 直接扣库（other_out），
所有变更都落 inventory_transactions 台账，幂等键防止重复导入。

模板列名（网店管家云端版导出，含常见别名）：
- 入库明细：供应商 / 登记时间 / 入库单号 / 货品货号 / 货品名称 / 数量 / 单价 / 入库原因 / 仓库
- 出库明细：出库单号 / 审核时间 / 货品编号 / 货品名称 / 数量 / 单价 / 出库原因 / 仓库 / 店铺
- 单品：单品编码 / 单品名称 / 单位 / 类别 / 参考成本
- 组合：组合编码 / 组合名称 / 单品编码 / 单品数量 / 预估快递费
"""

import hashlib
import io
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

SH_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")

import psycopg
from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile


def _database_url() -> str:
    return os.getenv(
        "V2_DATABASE_URL",
        "postgresql://pdd_v2_test:pdd_v2_test_local_2026@127.0.0.1:55432/pdd_v2_test",
    )


def _check_token(x_v2_test_token: str | None, authorization: str | None = None) -> None:
    """写操作鉴权：测试令牌 或 Bearer（V2 token / V1 形态 JWT）。"""
    test_token = os.getenv("V2_TEST_TOKEN", "")
    if test_token and x_v2_test_token == test_token:
        return
    from v2.test_api import _verify_auth_token, _verify_jwt

    token = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None
    if _verify_auth_token(token) or _verify_jwt(token):
        return
    raise HTTPException(status_code=401, detail="需要登录")


def _find_column(columns: list[str], aliases: list[str]) -> str | None:
    normalized = {str(column).strip(): str(column) for column in columns}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    compact = {str(column).replace(" ", "").replace("（", "(").replace("）", ")"): str(column) for column in columns}
    for alias in aliases:
        alias_compact = alias.replace(" ", "").replace("（", "(").replace("）", ")")
        for column, original in compact.items():
            if alias_compact in column or column in alias_compact:
                return original
    return None


def _cell(row: Any, column: str | None, default: Any = None) -> Any:
    if not column:
        return default
    value = row.get(column, default)
    if value is None:
        return default
    try:
        if value != value:
            return default
    except Exception:
        pass
    return value


def _text(value: Any) -> str | None:
    try:
        import pandas as pd
        if pd.isna(value):
            return None
    except Exception:
        pass
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "null"}:
        return None
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def _number(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        text = str(value).replace(",", "").strip()
        return Decimal(text) if text else default
    except Exception:
        return default

router = APIRouter(tags=["stock-io"])

ITEM_ALIASES = {
    "code": ["单品编码", "货品编号", "货品货号", "条码", "商品编码", "item_code", "code"],
    "name": ["单品名称", "货品名称", "品名", "商品名称", "item_name", "name"],
    "unit": ["单位", "基础单位", "base_unit"],
    "category": ["类别", "分类", "品类", "category"],
    "cost": ["参考成本", "成本价", "成本", "单价", "unit_cost", "cost"],
}

BUNDLE_ALIASES = {
    "bundle_code": ["组合编码", "组合装编号", "商家编码", "组合商品编码", "bundle_code"],
    "bundle_name": ["组合名称", "组合商品名称", "商品名称", "bundle_name"],
    "item_code": ["单品编码", "货品编号", "货品货号", "条码", "编号", "item_code"],
    "quantity": ["单品数量", "组件数量", "数量", "quantity"],
    "shipping": ["预估快递费", "快递费", "物流成本", "物流费用", "estimated_shipping_fee"],
}

STOCK_IN_ALIASES = {
    "doc_no": ["入库单号", "单号", "单据编号", "doc_no"],
    "occurred_at": ["审核时间", "登记时间", "入库时间", "日期", "occurred_at"],
    "item_code": ["货品货号", "货品编号", "条码", "单品编码", "item_code"],
    "item_name": ["货品名称", "单品名称", "item_name"],
    "quantity": ["数量", "入库数量", "quantity"],
    "unit_cost": ["单价", "成本价", "入库单价", "unit_cost"],
    "warehouse": ["仓库", "仓库名称", "warehouse"],
    "supplier": ["供应商", "supplier"],
    "reason": ["入库原因", "入库类型", "原因", "业务类型", "reason"],
}

STOCK_OUT_ALIASES = {
    "doc_no": ["出库单号", "单号", "单据编号", "doc_no"],
    "occurred_at": ["审核时间", "登记时间", "出库时间", "日期", "occurred_at"],
    "item_code": ["货品编号", "货品货号", "条码", "单品编码", "item_code"],
    "item_name": ["货品名称", "单品名称", "item_name"],
    "quantity": ["数量", "出库数量", "quantity"],
    "unit_cost": ["单价", "成本价", "unit_cost"],
    "warehouse": ["仓库", "仓库名称", "warehouse"],
    "reason": ["出库原因", "出库类型", "原因", "业务类型", "reason"],
    "store": ["店铺", "store"],
    "sale_amount": ["金额", "销售金额", "sale_amount", "amount"],
}

STOCK_ALIASES = {"in": STOCK_IN_ALIASES, "out": STOCK_OUT_ALIASES}


def read_frames(filename: str, content: bytes) -> dict[str, Any]:
    """读取 CSV/XLS/XLSX 的所有 sheet；CSV 返回单 sheet 字典。"""
    import pandas as pd

    suffix = Path(filename or "upload.csv").suffix.lower()
    if suffix in {".xls", ".xlsx"}:
        frames = pd.read_excel(io.BytesIO(content), sheet_name=None)
        frames = {str(name): frame for name, frame in frames.items()}
    elif suffix == ".csv":
        frame = None
        errors = []
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
            try:
                first_line = content.splitlines()[0] if content.splitlines() else b""
                separator = "\t" if b"\t" in first_line and b"," not in first_line else ","
                frame = pd.read_csv(io.BytesIO(content), encoding=encoding, sep=separator, low_memory=False)
                break
            except Exception as exc:
                errors.append(str(exc))
        if frame is None:
            raise HTTPException(status_code=400, detail=f"CSV 无法读取：{errors[-1] if errors else '未知错误'}")
        frames = {"数据段1": frame}
    else:
        raise HTTPException(status_code=400, detail="仅支持 CSV、XLS、XLSX 文件")
    frames = {name: frame for name, frame in frames.items() if not frame.empty}
    if not frames:
        raise HTTPException(status_code=400, detail="文件没有数据行")
    for frame in frames.values():
        if frame.columns.duplicated().any():
            raise HTTPException(status_code=400, detail="文件存在重复列名，请先整理表头")
    return frames


def read_frame(filename: str, content: bytes):
    """读取单 sheet 文件（网店管家出入库明细均为单 sheet）。"""
    return next(iter(read_frames(filename, content).values()))


def _parse_time(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        import pandas as pd

        parsed = pd.to_datetime(text)
        if pd.isna(parsed):
            return None
        result = parsed.to_pydatetime()
        # 网店管家导出的是北京时间；naive 时间一律按 Asia/Shanghai 处理，避免被当成 UTC
        if result.tzinfo is None:
            result = result.replace(tzinfo=SH_TZ)
        return result
    except Exception:
        return None


def normalize_stock_rows(frame: Any, io_type: str) -> dict[str, Any]:
    """把网店管家出入库明细规范化为行字典；纯函数，便于单测。"""
    aliases = STOCK_ALIASES[io_type]
    columns = [str(column) for column in frame.columns]
    mapping = {key: _find_column(columns, names) for key, names in aliases.items()}
    rows: list[dict[str, Any]] = []
    issues: list[str] = []
    for index, raw in frame.iterrows():
        line_no = int(index) + 2  # Excel 行号（含表头）
        doc_no = _text(_cell(raw, mapping["doc_no"], None))
        item_code = _text(_cell(raw, mapping["item_code"], None))
        quantity = _number(_cell(raw, mapping["quantity"], 0))
        row = {
            "line_no": line_no,
            "doc_no": doc_no,
            "occurred_at": _parse_time(_cell(raw, mapping["occurred_at"], None)),
            "item_code": item_code,
            "item_name": _text(_cell(raw, mapping["item_name"], None)),
            "quantity": quantity,
            "unit_cost": _number(_cell(raw, mapping["unit_cost"], 0)),
            "warehouse": _text(_cell(raw, mapping["warehouse"], None)),
            "reason": _text(_cell(raw, mapping["reason"], None)),
            "store": _text(_cell(raw, mapping.get("store"), None)) if mapping.get("store") else None,
            "sale_amount": _number(_cell(raw, mapping.get("sale_amount"), 0)) if mapping.get("sale_amount") else None,
        }
        if not item_code:
            issues.append(f"第{line_no}行缺少单品编码")
            continue
        if not doc_no:
            issues.append(f"第{line_no}行缺少单据号")
            continue
        if quantity <= 0:
            issues.append(f"第{line_no}行数量无效（{quantity}）")
            continue
        if not row["warehouse"]:
            issues.append(f"第{line_no}行缺少仓库")
            continue
        rows.append(row)
    return {"rows": rows, "issues": issues, "mapping": {key: value for key, value in mapping.items()}}


def group_stock_lines(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同单同仓同单品合并：数量求和、成本加权平均。纯函数，便于单测。"""
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["doc_no"], row["warehouse"], row["item_code"])
        if key not in grouped:
            grouped[key] = {**row, "_amount": row["quantity"] * row["unit_cost"], "_sale_amount": row.get("sale_amount") or Decimal("0")}
        else:
            grouped[key]["quantity"] += row["quantity"]
            grouped[key]["_amount"] += row["quantity"] * row["unit_cost"]
            grouped[key]["_sale_amount"] += row.get("sale_amount") or Decimal("0")
    result = []
    for row in grouped.values():
        if row["quantity"] > 0:
            row["unit_cost"] = row["_amount"] / row["quantity"]
        row["sale_amount"] = row.pop("_sale_amount", None) or None
        row.pop("_amount", None)
        result.append(row)
    return result


def normalize_item_rows(frame: Any) -> dict[str, Any]:
    columns = [str(column) for column in frame.columns]
    mapping = {key: _find_column(columns, names) for key, names in ITEM_ALIASES.items()}
    rows: list[dict[str, Any]] = []
    issues: list[str] = []
    seen: set[str] = set()
    for index, raw in frame.iterrows():
        line_no = int(index) + 2
        code = _text(_cell(raw, mapping["code"], None))
        name = _text(_cell(raw, mapping["name"], None))
        if not code:
            issues.append(f"第{line_no}行缺少单品编码")
            continue
        if code in seen:
            issues.append(f"第{line_no}行单品编码重复（{code}），已忽略")
            continue
        seen.add(code)
        rows.append({
            "line_no": line_no,
            "code": code,
            "name": name or code,
            "unit": _text(_cell(raw, mapping["unit"], None)) or "件",
            "category": _text(_cell(raw, mapping["category"], None)),
            "cost": _number(_cell(raw, mapping["cost"], 0)),
        })
    return {"rows": rows, "issues": issues, "mapping": {key: value for key, value in mapping.items()}}


def normalize_bundle_rows(frame: Any, name_map: dict[str, str] | None = None) -> dict[str, Any]:
    columns = [str(column) for column in frame.columns]
    mapping = {key: _find_column(columns, names) for key, names in BUNDLE_ALIASES.items()}
    issues: list[str] = []
    bundles: dict[str, dict[str, Any]] = {}
    for index, raw in frame.iterrows():
        line_no = int(index) + 2
        bundle_code = _text(_cell(raw, mapping["bundle_code"], None))
        item_code = _text(_cell(raw, mapping["item_code"], None))
        quantity = _number(_cell(raw, mapping["quantity"], 0))
        if not bundle_code or not item_code:
            issues.append(f"第{line_no}行缺少组合编码或单品编码")
            continue
        if quantity <= 0:
            issues.append(f"第{line_no}行单品数量无效（{quantity}）")
            continue
        bundle = bundles.setdefault(bundle_code, {
            "code": bundle_code,
            "name": _text(_cell(raw, mapping["bundle_name"], None)) or (name_map or {}).get(bundle_code) or bundle_code,
            "shipping": _number(_cell(raw, mapping["shipping"], 0)),
            "components": {},
        })
        bundle["components"][item_code] = bundle["components"].get(item_code, Decimal("0")) + quantity
    rows = [
        {**bundle, "components": [{"item_code": code, "quantity": qty} for code, qty in sorted(bundle["components"].items())]}
        for bundle in bundles.values()
    ]
    return {"rows": rows, "issues": issues, "mapping": {key: value for key, value in mapping.items()}}


def stock_io_idem_key(io_type: str, doc_no: str, warehouse_code: str, item_code: str, batch_id: str | None = None) -> str:
    base = f"stock_{io_type}:{doc_no}:{warehouse_code}:{item_code}"
    return f"{base}:{batch_id}" if batch_id else base


def _warehouse_id_flex(cur: Any, value: str) -> tuple[str, str] | None:
    """按编码或中文名解析仓库，返回 (id, code)。"""
    cur.execute(
        "select id, code from warehouses where is_active = true and (upper(code) = upper(%s) or name = %s)",
        (value, value),
    )
    row = cur.fetchone()
    return (str(row[0]), str(row[1])) if row else None


def _enabled_from(cur: Any) -> date | None:
    cur.execute("select inventory_enabled_from from inventory_settings where id = 1")
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def _batch_sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _begin_import_batch(cur: Any, data_type: str, filename: str | None, sha: str, row_count: int) -> tuple[Any | None, dict[str, Any] | None]:
    """创建导入批次；若同 sha 已存在则返回 (None, duplicate 响应)。"""
    cur.execute("select id, status from data_import_batches where source_sha256 = %s order by created_at desc limit 1", (sha,))
    existing = cur.fetchone()
    if existing:
        return None, {"batch_id": str(existing[0]), "status": "duplicate", "existing_status": existing[1]}
    cur.execute(
        "insert into data_import_batches(platform, store_name, data_type, source_filename, source_sha256, status, row_count, created_by, completed_at) values('wgd', null, %s, %s, %s, 'processing', %s, 'v2-test', now()) returning id",
        (data_type, filename, sha, row_count),
    )
    return cur.fetchone()[0], None


def _apply_stock_in(cur: Any, warehouse_id: str, item_id: str, batch_no: str, quantity: Decimal, unit_cost: Decimal, occurred_at: datetime, reference_type: str, reference_id: str, idem_key: str, biz_type: str | None = None) -> str:
    """直接入库建批次并更新永续加权平均；返回台账 idempotency_key。调用方负责事务。"""
    cur.execute(
        "insert into inventory_batches(warehouse_id, item_id, batch_no, received_at, received_qty, remaining_qty, unit_cost) values(%s,%s,%s,%s,%s,%s,%s) on conflict(warehouse_id, item_id, batch_no) do update set remaining_qty = inventory_batches.remaining_qty + excluded.remaining_qty, received_qty = inventory_batches.received_qty + excluded.received_qty returning id",
        (warehouse_id, item_id, batch_no, occurred_at, quantity, quantity, unit_cost),
    )
    batch_id = cur.fetchone()[0]
    cur.execute("select sellable_qty, total_average_cost from inventory_balances where warehouse_id=%s and item_id=%s for update", (warehouse_id, item_id))
    bal = cur.fetchone()
    available = Decimal(bal[0]) if bal else Decimal("0")
    total_cost = Decimal(bal[1]) if bal else Decimal("0")
    new_qty = available + quantity
    new_total = total_cost + quantity * unit_cost
    new_average = new_total / new_qty if new_qty else unit_cost
    cur.execute(
        "insert into inventory_balances(warehouse_id, item_id, sellable_qty, total_average_cost) values(%s,%s,%s,%s) on conflict(warehouse_id, item_id) do update set sellable_qty=inventory_balances.sellable_qty+excluded.sellable_qty, total_average_cost=inventory_balances.total_average_cost+excluded.total_average_cost, updated_at=now()",
        (warehouse_id, item_id, quantity, quantity * unit_cost),
    )
    cur.execute(
        "insert into inventory_transactions(warehouse_id, item_id, batch_id, transaction_type, quantity, batch_unit_cost, average_unit_cost, reference_type, reference_id, idempotency_key, occurred_at, created_by, biz_type) values(%s,%s,%s,'other_in',%s,%s,%s,%s,%s,%s,%s,'stock-import',%s)",
        (warehouse_id, item_id, batch_id, quantity, unit_cost, new_average, reference_type, reference_id, idem_key, occurred_at, biz_type),
    )
    return idem_key


def _apply_stock_out(cur: Any, warehouse_id: str, item_id: str, quantity: Decimal, occurred_at: datetime, reference_type: str, reference_id: str, idem_prefix: str, biz_type: str | None = None, store_name: str | None = None, sale_amount: Decimal | None = None) -> dict[str, Any]:
    """FIFO 直接扣库；库存不足时返回 shortage 且不产生负库存。调用方负责事务。"""
    cur.execute("select sellable_qty, average_unit_cost from inventory_balances where warehouse_id=%s and item_id=%s for update", (warehouse_id, item_id))
    bal = cur.fetchone()
    available = Decimal(bal[0]) if bal else Decimal("0")
    average = Decimal(bal[1]) if bal else Decimal("0")
    if available < quantity:
        return {"status": "shortage", "requested": quantity, "available": available}
    cur.execute(
        "select id, remaining_qty, unit_cost from inventory_batches where warehouse_id=%s and item_id=%s and stock_status='sellable' and remaining_qty>0 order by received_at, id for update",
        (warehouse_id, item_id),
    )
    remaining = quantity
    allocated = Decimal("0")
    for batch_id, batch_qty, batch_cost in cur.fetchall():
        take = min(Decimal(batch_qty), remaining)
        remaining -= take
        allocated += take
        # 销售金额按批次拆分比例分摊，保证事务级求和 = 行销售金额
        row_sale = None
        if sale_amount is not None and quantity:
            row_sale = (sale_amount * take / quantity).quantize(Decimal("0.000001"))
        cur.execute("update inventory_batches set remaining_qty = remaining_qty - %s where id=%s", (take, batch_id))
        cur.execute(
            "insert into inventory_transactions(warehouse_id, item_id, batch_id, transaction_type, quantity, batch_unit_cost, average_unit_cost, reference_type, reference_id, idempotency_key, occurred_at, created_by, biz_type, store_name, sale_amount) values(%s,%s,%s,'other_out',%s,%s,%s,%s,%s,%s,%s,'stock-import',%s,%s,%s)",
            (warehouse_id, item_id, batch_id, -take, batch_cost, average, reference_type, reference_id, f"{idem_prefix}:{batch_id}", occurred_at, biz_type, store_name, row_sale),
        )
        if remaining <= 0:
            break
    cur.execute(
        "update inventory_balances set sellable_qty = sellable_qty - %s, total_average_cost = greatest(0, total_average_cost - %s), updated_at=now() where warehouse_id=%s and item_id=%s",
        (quantity, quantity * average, warehouse_id, item_id),
    )
    return {"status": "deducted", "quantity": quantity, "average_unit_cost": average}


def _reverse_wangguan_doc(cur: Any, io_type: str, doc_no: str) -> bool | str | None:
    """整单撤销网店管家导入流水（覆盖导入用）。返回 None=单号不存在无需撤销；True=撤销成功；str=冲突原因。调用方负责事务。"""
    reference_type = "wangguan_in" if io_type == "in" else "wangguan_out"
    cur.execute(
        "select id, warehouse_id, item_id, batch_id, quantity, batch_unit_cost, average_unit_cost from inventory_transactions where reference_type=%s and reference_id=%s for update",
        (reference_type, doc_no),
    )
    txs = cur.fetchall()
    if not txs:
        return None
    if io_type == "in":
        # 入库单撤销前提：建的批次一件未动，且批次上没有其它单据的流水
        tx_ids = [row[0] for row in txs]
        for _tx_id, _wh, _item, batch_id, _qty, _cost, _avg in txs:
            cur.execute("select received_qty, remaining_qty from inventory_batches where id=%s for update", (batch_id,))
            batch = cur.fetchone()
            if not batch:
                return f"入库单 {doc_no} 的批次记录缺失，不能覆盖"
            if Decimal(batch[1]) != Decimal(batch[0]):
                return f"入库单 {doc_no} 的批次已被出库消耗（入库 {batch[0]}，剩 {batch[1]}），不能覆盖"
            cur.execute("select count(*) from inventory_transactions where batch_id=%s and not (id = any(%s))", (batch_id, tx_ids))
            if int(cur.fetchone()[0]):
                return f"入库单 {doc_no} 的批次存在其它单据流水，不能覆盖"
        for tx_id, warehouse_id, item_id, batch_id, qty, cost, _avg in txs:
            qty, cost = Decimal(qty), Decimal(cost)
            cur.execute("delete from inventory_transactions where id=%s", (tx_id,))
            cur.execute(
                "update inventory_balances set sellable_qty=sellable_qty-%s, total_average_cost=greatest(0,total_average_cost-%s), updated_at=now() where warehouse_id=%s and item_id=%s",
                (qty, qty * cost, warehouse_id, item_id),
            )
            cur.execute("delete from inventory_batches where id=%s", (batch_id,))
        return True
    # 出库单撤销：FIFO 吃掉的数量加回原批次，余额按当时扣减的平均成本快照加回
    for tx_id, warehouse_id, item_id, batch_id, qty, _cost, avg in txs:
        back = -Decimal(qty)
        cur.execute("update inventory_batches set remaining_qty=remaining_qty+%s where id=%s", (back, batch_id))
        cur.execute(
            "update inventory_balances set sellable_qty=sellable_qty+%s, total_average_cost=total_average_cost+%s, updated_at=now() where warehouse_id=%s and item_id=%s",
            (back, back * Decimal(avg), warehouse_id, item_id),
        )
        cur.execute("delete from inventory_transactions where id=%s", (tx_id,))
    return True


@router.post("/api/v2/imports/stock-io")
def import_stock_io(
    io_type: str = Form(...),
    mode: str = Form("preview"),
    overwrite: str = Form("false"),
    file: UploadFile = File(...),
    x_v2_test_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """导入网店管家入库/出库明细。入库直接建批次，出库 FIFO 直接扣库。overwrite=true 时同单号整单撤销重记。"""
    _check_token(x_v2_test_token, authorization)
    if io_type not in {"in", "out"}:
        raise HTTPException(status_code=400, detail="io_type 只能是 in 或 out")
    if mode not in {"preview", "import"}:
        raise HTTPException(status_code=400, detail="mode 只能是 preview 或 import")
    content = file.file.read()
    frame = read_frame(file.filename or "upload.csv", content)
    parsed = normalize_stock_rows(frame, io_type)
    lines = group_stock_lines(parsed["rows"])
    sha = _batch_sha(content)

    with psycopg.connect(_database_url()) as conn:
        with conn.cursor() as cur:
            enabled_from = _enabled_from(cur)
            cur.execute("select code from inventory_items where is_active = true")
            known_items = {row[0] for row in cur.fetchall()}
            missing_items: dict[str, str] = {}
            unknown_warehouses: set[str] = set()
            resolved: list[dict[str, Any]] = []
            for line in lines:
                warehouse = _warehouse_id_flex(cur, line["warehouse"])
                if not warehouse:
                    unknown_warehouses.add(line["warehouse"])
                    continue
                if line["item_code"] not in known_items:
                    missing_items[line["item_code"]] = line.get("item_name") or ""
                    continue
                line["warehouse_id"], line["warehouse_code"] = warehouse
                resolved.append(line)
            doc_nos = sorted({line["doc_no"] for line in resolved})
            existing_docs: list[str] = []
            if doc_nos:
                cur.execute(
                    "select reference_id from inventory_transactions where reference_type=%s and reference_id = any(%s) group by reference_id",
                    ("wangguan_in" if io_type == "in" else "wangguan_out", doc_nos),
                )
                existing_docs = [row[0] for row in cur.fetchall()]
        preview = {
            "io_type": io_type,
            "rows": len(parsed["rows"]),
            "valid_rows": len(resolved),
            "issues": parsed["issues"][:20],
            "issue_count": len(parsed["issues"]),
            "missing_items": [{"code": code, "name": name} for code, name in sorted(missing_items.items())],
            "unknown_warehouses": sorted(unknown_warehouses),
            "source_sha256": sha,
            "existing_docs": len(existing_docs),
            "ready": bool(resolved) and not parsed["issues"] and not missing_items and not unknown_warehouses,
        }
        if mode == "preview":
            return preview

        applied = 0
        skipped_lines: list[dict[str, Any]] = []
        shortages: list[dict[str, Any]] = []
        overwritten_docs: list[str] = []
        doc_conflicts: dict[str, str] = {}
        with conn.transaction():
            with conn.cursor() as cur:
                batch_id, duplicate = _begin_import_batch(cur, f"stock_{io_type}", file.filename, sha, len(resolved))
                if duplicate:
                    return duplicate
                if str(overwrite).lower() in {"1", "true", "yes", "on"}:
                    for doc_no in doc_nos:
                        reversal = _reverse_wangguan_doc(cur, io_type, doc_no)
                        if isinstance(reversal, str):
                            doc_conflicts[doc_no] = reversal
                        elif reversal:
                            overwritten_docs.append(doc_no)
                for line in resolved:
                    occurred_at = line["occurred_at"] or datetime.now()
                    if enabled_from and occurred_at.date() < enabled_from:
                        skipped_lines.append({"doc_no": line["doc_no"], "item_code": line["item_code"], "reason": f"早于库存启用日 {enabled_from}"})
                        continue
                    if line["doc_no"] in doc_conflicts:
                        skipped_lines.append({"doc_no": line["doc_no"], "item_code": line["item_code"], "reason": doc_conflicts[line["doc_no"]]})
                        continue
                    cur.execute("select id from inventory_items where code=%s and is_active=true", (line["item_code"],))
                    item_id = str(cur.fetchone()[0])
                    idem_base = stock_io_idem_key(io_type, line["doc_no"], line["warehouse_code"], line["item_code"])
                    cur.execute("select 1 from inventory_transactions where idempotency_key = %s or idempotency_key like %s limit 1", (idem_base, idem_base + ":%"))
                    if cur.fetchone():
                        skipped_lines.append({"doc_no": line["doc_no"], "item_code": line["item_code"], "reason": "该单据行已入库过，幂等跳过"})
                        continue
                    if io_type == "in":
                        _apply_stock_in(cur, line["warehouse_id"], item_id, line["doc_no"], line["quantity"], line["unit_cost"], occurred_at, "wangguan_in", line["doc_no"], idem_base, line.get("reason"))
                        applied += 1
                    else:
                        result = _apply_stock_out(cur, line["warehouse_id"], item_id, line["quantity"], occurred_at, "wangguan_out", line["doc_no"], idem_base, line.get("reason"), line.get("store"), line.get("sale_amount"))
                        if result["status"] == "shortage":
                            cur.execute(
                                "insert into inventory_exceptions(order_id, warehouse_id, item_id, requested_qty, available_qty) values(%s,%s,%s,%s,%s)",
                                (line["doc_no"], line["warehouse_id"], item_id, result["requested"], result["available"]),
                            )
                            shortages.append({"doc_no": line["doc_no"], "item_code": line["item_code"], "requested": str(result["requested"]), "available": str(result["available"])})
                        else:
                            applied += 1
                status = "succeeded" if not shortages else "partial"
                cur.execute(
                    "update data_import_batches set status=%s, error_count=%s, error_message=%s, period_from=%s, period_to=%s, completed_at=now() where id=%s",
                    (
                        status,
                        len(shortages),
                        "; ".join(f"{s['doc_no']}/{s['item_code']} 缺货" for s in shortages[:10]) or None,
                        min((l["occurred_at"].date() for l in resolved if l["occurred_at"]), default=None),
                        max((l["occurred_at"].date() for l in resolved if l["occurred_at"]), default=None),
                        batch_id,
                    ),
                )
        return {
            "batch_id": str(batch_id),
            "status": status,
            "applied": applied,
            "skipped": skipped_lines,
            "shortages": shortages,
            "overwritten_docs": overwritten_docs,
            "conflicts": [{"doc_no": doc_no, "reason": reason} for doc_no, reason in doc_conflicts.items()],
            **{key: preview[key] for key in ("rows", "valid_rows", "issue_count", "missing_items", "unknown_warehouses", "source_sha256", "existing_docs")},
        }


@router.post("/api/v2/imports/catalog")
def import_catalog(
    import_type: str = Form(...),
    mode: str = Form("preview"),
    file: UploadFile = File(...),
    x_v2_test_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """批量导入单品（items）或组合商品 BOM（bundles）。组合编码已存在时新建 BOM 版本。"""
    _check_token(x_v2_test_token, authorization)
    if import_type not in {"items", "bundles"}:
        raise HTTPException(status_code=400, detail="import_type 只能是 items 或 bundles")
    if mode not in {"preview", "import"}:
        raise HTTPException(status_code=400, detail="mode 只能是 preview 或 import")
    content = file.file.read()
    if import_type == "items":
        parsed = normalize_item_rows(read_frame(file.filename or "upload.csv", content))
    else:
        sheets = read_frames(file.filename or "upload.csv", content)
        detail = sheets.get("组合装明细")
        if detail is None:
            detail = next(iter(sheets.values()))
        name_map: dict[str, str] = {}
        main = sheets.get("组合装")
        if main is not None:
            main_columns = [str(column) for column in main.columns]
            code_col = _find_column(main_columns, ["编号", "组合装编号", "组合编码"])
            name_col = _find_column(main_columns, ["名称", "组合名称", "组合装名称"])
            if code_col and name_col:
                for _, main_row in main.iterrows():
                    code = _text(_cell(main_row, code_col, None))
                    name = _text(_cell(main_row, name_col, None))
                    if code and name:
                        name_map[code] = name
        parsed = normalize_bundle_rows(detail, name_map=name_map)
        # 明细 sheet 的「名称」列是组件名；组合名一律以主表（组合装 sheet）为准
        for bundle in parsed["rows"]:
            if bundle["code"] in name_map:
                bundle["name"] = name_map[bundle["code"]]
    sha = _batch_sha(content)

    with psycopg.connect(_database_url()) as conn:
        with conn.cursor() as cur:
            if import_type == "items":
                cur.execute("select code from inventory_items")
                existing = {row[0] for row in cur.fetchall()}
                new_count = sum(1 for row in parsed["rows"] if row["code"] not in existing)
                preview = {
                    "import_type": import_type,
                    "rows": len(parsed["rows"]),
                    "new_items": new_count,
                    "existing_items": len(parsed["rows"]) - new_count,
                    "issues": parsed["issues"][:20],
                    "issue_count": len(parsed["issues"]),
                    "source_sha256": sha,
                    "ready": bool(parsed["rows"]),
                }
            else:
                cur.execute("select code, name from inventory_items where is_active = true")
                item_rows = cur.fetchall()
                known_items = {row[0] for row in item_rows}
                name_to_code: dict[str, str] = {}
                for code, name in item_rows:
                    if name and name not in name_to_code:
                        name_to_code[name] = code
                # 网店管家组合装明细的「编号」列常是单品名称而非编码，按名称回填编码
                resolved_by_name = 0
                for bundle in parsed["rows"]:
                    for component in bundle["components"]:
                        component_code = component["item_code"]
                        if component_code not in known_items and component_code in name_to_code:
                            component["item_code"] = name_to_code[component_code]
                            resolved_by_name += 1
                cur.execute("select code from bundles")
                existing_bundles = {row[0] for row in cur.fetchall()}
                missing_items = sorted({component["item_code"] for bundle in parsed["rows"] for component in bundle["components"] if component["item_code"] not in known_items})
                preview = {
                    "import_type": import_type,
                    "rows": len(parsed["rows"]),
                    "new_bundles": sum(1 for bundle in parsed["rows"] if bundle["code"] not in existing_bundles),
                    "new_versions": sum(1 for bundle in parsed["rows"] if bundle["code"] in existing_bundles),
                    "missing_items": missing_items,
                    "resolved_by_name": resolved_by_name,
                    "issues": parsed["issues"][:20],
                    "issue_count": len(parsed["issues"]),
                    "source_sha256": sha,
                    "ready": bool(parsed["rows"]) and not missing_items,
                }
        if mode == "preview":
            return preview

        with conn.transaction():
            with conn.cursor() as cur:
                batch_id, duplicate = _begin_import_batch(cur, import_type, file.filename, sha, len(parsed["rows"]))
                if duplicate:
                    return duplicate
                if import_type == "items":
                    enabled_from = _enabled_from(cur) or date.today()
                    cur.execute("select id, code from warehouses where is_active = true")
                    warehouses = cur.fetchall()
                    for row in parsed["rows"]:
                        cur.execute(
                            "insert into inventory_items(code, name, base_unit, category) values(%s,%s,%s,%s) on conflict(code) do update set name=excluded.name, base_unit=excluded.base_unit, category=coalesce(excluded.category, inventory_items.category), updated_at=now() returning id",
                            (row["code"], row["name"], row["unit"], row["category"]),
                        )
                        item_id = cur.fetchone()[0]
                        if row["cost"] > 0:
                            for warehouse_id, _warehouse_code in warehouses:
                                cur.execute(
                                    "select 1 from item_cost_versions where item_id=%s and warehouse_id=%s and effective_from=%s and unit_cost=%s",
                                    (item_id, warehouse_id, enabled_from, row["cost"]),
                                )
                                if not cur.fetchone():
                                    cur.execute(
                                        "insert into item_cost_versions(item_id, warehouse_id, unit_cost, effective_from, source_type, source_id) values(%s,%s,%s,%s,'import',%s)",
                                        (item_id, warehouse_id, row["cost"], enabled_from, sha[:16]),
                                    )
                    imported = len(parsed["rows"])
                else:
                    today = date.today()
                    imported = 0
                    for bundle in parsed["rows"]:
                        cur.execute("select id from bundles where code=%s", (bundle["code"],))
                        existing = cur.fetchone()
                        if existing:
                            bundle_id = existing[0]
                            cur.execute("update bundles set name=%s, estimated_shipping_fee=%s, updated_at=now() where id=%s", (bundle["name"], bundle["shipping"], bundle_id))
                            cur.execute("select coalesce(max(version_no), 0) from bundle_versions where bundle_id=%s", (bundle_id,))
                            version_no = int(cur.fetchone()[0]) + 1
                            cur.execute("update bundle_versions set effective_to=%s, status='retired' where bundle_id=%s and status='active' and effective_from < %s and (effective_to is null or effective_to > %s)", (today - timedelta(days=1), bundle_id, today, today - timedelta(days=1)))
                        else:
                            cur.execute("insert into bundles(code, name, estimated_shipping_fee) values(%s,%s,%s) returning id", (bundle["code"], bundle["name"], bundle["shipping"]))
                            bundle_id = cur.fetchone()[0]
                            version_no = 1
                        cur.execute("insert into bundle_versions(bundle_id, version_no, effective_from, status) values(%s,%s,%s,'active') returning id", (bundle_id, version_no, today))
                        version_id = cur.fetchone()[0]
                        for component in bundle["components"]:
                            cur.execute("select id from inventory_items where code=%s and is_active=true", (component["item_code"],))
                            item_row = cur.fetchone()
                            if not item_row:
                                raise HTTPException(status_code=422, detail=f"组合 {bundle['code']} 的单品不存在：{component['item_code']}，请先导入单品")
                            cur.execute("insert into bundle_components(bundle_version_id, item_id, quantity) values(%s,%s,%s)", (version_id, item_row[0], component["quantity"]))
                        imported += 1
                cur.execute("update data_import_batches set status='succeeded', completed_at=now() where id=%s", (batch_id,))
        return {"batch_id": str(batch_id), "status": "succeeded", "imported": imported, **{key: preview[key] for key in preview if key not in {"issues", "ready"}}}
