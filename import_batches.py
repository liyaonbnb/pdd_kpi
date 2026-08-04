"""Import batch audit records and reversible store snapshots."""

from __future__ import annotations

import json
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from storage import DATA_DIR, META_FILE, PROCESSED_DIR, _store_to_str, init_storage


BATCH_DIR = DATA_DIR / "import_batches"
BATCH_INDEX = BATCH_DIR / "batches.json"
IMPORT_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now().isoformat(timespec="microseconds")


def _read_index() -> List[Dict[str, Any]]:
    if not BATCH_INDEX.exists():
        return []
    try:
        data = json.loads(BATCH_INDEX.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_index(records: List[Dict[str, Any]]) -> None:
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    temp = BATCH_INDEX.with_suffix(".tmp")
    temp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(BATCH_INDEX)


def list_batches(store_name: Optional[str] = None) -> List[Dict[str, Any]]:
    records = _read_index()
    if store_name is not None:
        records = [record for record in records if record.get("store_name") == store_name]
    return sorted(records, key=lambda record: record.get("created_at", ""), reverse=True)


def find_duplicate_batch(
    store_name: str, promo_hash: Optional[str], order_hash: Optional[str]
) -> Optional[Dict[str, Any]]:
    for record in list_batches(store_name):
        if record.get("status") != "imported":
            continue
        if record.get("promo_hash") == promo_hash and record.get("order_hash") == order_hash:
            return record
    return None


def _store_meta_records(
    store_name: str, store_safe: str, affected_dates: List[str]
) -> Dict[str, Any]:
    if not META_FILE.exists():
        return {}
    try:
        meta = json.loads(META_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {
        key: value
        for key, value in meta.get("records", {}).items()
        if (value.get("store_name") == store_name or value.get("store_safe") == store_safe)
        and value.get("date") in affected_dates
    }


def _snapshot_store(batch_id: str, store_name: str, affected_dates: List[str]) -> None:
    init_storage()
    store_safe = _store_to_str(store_name)
    snapshot_dir = BATCH_DIR / batch_id / "snapshot"
    snapshot_dir.mkdir(parents=True, exist_ok=False)

    filenames: List[str] = []
    for date_str in affected_dates:
        for prefix in ("product", "style", "orders", "promo"):
            for extension in ("parquet", "csv"):
                source = PROCESSED_DIR / f"{prefix}_{store_safe}_{date_str}.{extension}"
                if source.exists():
                    shutil.copy2(source, snapshot_dir / source.name)
                    filenames.append(source.name)

    state = {
        "store_name": store_name,
        "store_safe": store_safe,
        "affected_dates": affected_dates,
        "files": sorted(filenames),
        "meta_records": _store_meta_records(store_name, store_safe, affected_dates),
    }
    (BATCH_DIR / batch_id / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def restore_batch_snapshot(batch_id: str) -> None:
    batch_path = BATCH_DIR / batch_id
    state_path = batch_path / "state.json"
    if not state_path.exists():
        raise ValueError("该导入批次没有可用快照")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    store_name = state["store_name"]
    store_safe = state["store_safe"]

    affected_dates = state.get("affected_dates", [])
    for date_str in affected_dates:
        for prefix in ("product", "style", "orders", "promo"):
            for extension in ("parquet", "csv"):
                current = PROCESSED_DIR / f"{prefix}_{store_safe}_{date_str}.{extension}"
                if current.exists():
                    current.unlink()

    snapshot_dir = batch_path / "snapshot"
    for filename in state.get("files", []):
        source = snapshot_dir / filename
        if source.exists():
            shutil.copy2(source, PROCESSED_DIR / filename)

    meta: Dict[str, Any] = {}
    if META_FILE.exists():
        try:
            meta = json.loads(META_FILE.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    records = meta.setdefault("records", {})
    for key, value in list(records.items()):
        if (value.get("store_name") == store_name or value.get("store_safe") == store_safe) and value.get("date") in affected_dates:
            records.pop(key, None)
    records.update(state.get("meta_records", {}))
    META_FILE.parent.mkdir(parents=True, exist_ok=True)
    META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def begin_batch(
    *,
    store_name: str,
    import_date: str,
    imported_by: str,
    preview: Dict[str, Any],
    promo_filename: Optional[str],
    order_filename: Optional[str],
) -> str:
    batch_id = uuid.uuid4().hex
    affected_dates = list(preview.get("affected_dates", []))
    _snapshot_store(batch_id, store_name, affected_dates)
    record = {
        "batch_id": batch_id,
        "store_name": store_name,
        "import_date": import_date,
        "imported_by": imported_by,
        "created_at": _now(),
        "status": "importing",
        "promo_filename": promo_filename or "",
        "order_filename": order_filename or "",
        "promo_hash": preview.get("promo_hash"),
        "order_hash": preview.get("order_hash"),
        "stats": preview.get("orders", {}),
        "affected_dates": preview.get("affected_dates", []),
    }
    records = _read_index()
    records.append(record)
    _write_index(records)
    return batch_id


def update_batch(batch_id: str, **updates: Any) -> Dict[str, Any]:
    records = _read_index()
    for record in records:
        if record.get("batch_id") == batch_id:
            record.update(updates)
            _write_index(records)
            return record
    raise ValueError("导入批次不存在")


def rollback_batch(batch_id: str, actor: str, is_master: bool = False) -> Dict[str, Any]:
    with IMPORT_LOCK:
        records = _read_index()
        target = next((record for record in records if record.get("batch_id") == batch_id), None)
        if not target:
            raise ValueError("导入批次不存在")
        if target.get("status") != "imported":
            raise ValueError("该导入批次当前不可撤销")
        if not is_master and target.get("imported_by") != actor:
            raise PermissionError("只能撤销自己导入的批次")

        latest = next(
            (record for record in list_batches(target["store_name"]) if record.get("status") == "imported"),
            None,
        )
        if not latest or latest.get("batch_id") != batch_id:
            raise ValueError("只能撤销该店铺最近一次成功导入")

        restore_batch_snapshot(batch_id)
        target["status"] = "rolled_back"
        target["rolled_back_at"] = _now()
        target["rolled_back_by"] = actor
        _write_index(records)
        return target


def invalidate_store_batches(store_name: str, actor: str, reason: str) -> None:
    records = _read_index()
    changed = False
    for record in records:
        if record.get("store_name") == store_name and record.get("status") == "imported":
            record["status"] = "invalidated"
            record["invalidated_at"] = _now()
            record["invalidated_by"] = actor
            record["invalidated_reason"] = reason
            changed = True
    if changed:
        _write_index(records)
