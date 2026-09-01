"""V2 导入批次的幂等与校验契约。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


class ImportValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ImportCheck:
    rows: int
    unique_order_ids: int
    missing_order_ids: int
    missing_payment_times: int
    duplicate_order_lines: int
    valid_rows: int
    invalid_rows: int
    source_sha256: str

    @property
    def status(self) -> str:
        if self.rows == 0:
            return "failed"
        if self.missing_order_ids or self.duplicate_order_lines:
            return "partial"
        return "succeeded" if self.invalid_rows == 0 else "partial"


def source_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if text in {"", "\\t", "nan", "NaN", "None", "null", "NULL"}:
        return ""
    return text[:-2] if text.endswith(".0") else text


def validate_order_frame(frame: pd.DataFrame, *, source_path: str | Path | None = None) -> ImportCheck:
    if frame is None or frame.empty:
        raise ImportValidationError("订单文件为空")
    required = {"order_id", "product_id", "quantity"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ImportValidationError(f"订单文件缺少必要列：{', '.join(missing)}")

    keys: set[tuple[str, str, str]] = set()
    missing_order_ids = missing_payment_times = duplicate_lines = valid_rows = invalid_rows = 0
    order_ids: set[str] = set()
    for _, row in frame.iterrows():
        order_id = _text(row.get("order_id"))
        product_id = _text(row.get("product_id"))
        style_id = _text(row.get("style_id"))
        payment_time = _text(row.get("pay_time"))
        if not order_id:
            missing_order_ids += 1
        else:
            order_ids.add(order_id)
            key = (order_id, product_id, style_id)
            if key in keys:
                duplicate_lines += 1
            keys.add(key)
        if not payment_time:
            missing_payment_times += 1
        try:
            qty = float(row.get("quantity", 0))
            valid = qty > 0
        except (TypeError, ValueError):
            valid = False
        if valid:
            valid_rows += 1
        else:
            invalid_rows += 1

    if source_path:
        sha = source_sha256(source_path)
    else:
        sha = hashlib.sha256(pd.util.hash_pandas_object(frame, index=True).values.tobytes()).hexdigest()
    return ImportCheck(
        rows=len(frame),
        unique_order_ids=len(order_ids),
        missing_order_ids=missing_order_ids,
        missing_payment_times=missing_payment_times,
        duplicate_order_lines=duplicate_lines,
        valid_rows=valid_rows,
        invalid_rows=invalid_rows,
        source_sha256=sha,
    )
