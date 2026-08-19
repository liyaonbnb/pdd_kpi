import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

import services
from auth import authorize_store, require_master, require_page
from helpers import read_upload_file

router = APIRouter()


def _upload_args(promo_file, order_file):
    return {
        "promo_bytes": read_upload_file(promo_file) if promo_file else None,
        "promo_filename": (promo_file.filename or "promo.xlsx") if promo_file else None,
        "order_bytes": read_upload_file(order_file) if order_file else None,
        "order_filename": (order_file.filename or "order.csv") if order_file else None,
    }


@router.post("/preview", response_model=Dict[str, Any])
def preview_daily_import(
    store_name: str = Form(...),
    import_date: datetime.date = Form(...),
    promo_file: Optional[UploadFile] = File(None),
    order_file: Optional[UploadFile] = File(None),
    user: dict = Depends(require_page("import")),
):
    authorize_store(user, store_name)
    try:
        return services.preview_daily_import(
            store_name=store_name, import_date=import_date, **_upload_args(promo_file, order_file)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("", response_model=Dict[str, Any])
def import_daily_data(
    store_name: str = Form(...),
    import_date: datetime.date = Form(...),
    promo_file: Optional[UploadFile] = File(None),
    order_file: Optional[UploadFile] = File(None),
    user: dict = Depends(require_page("import")),
):
    authorize_store(user, store_name)
    if not promo_file and not order_file:
        return {"error": "请至少上传推广数据或订单数据中的一个"}
    try:
        return services.import_daily_data(
            store_name=store_name,
            import_date=import_date,
            imported_by=user.get("sub", "unknown"),
            **_upload_args(promo_file, order_file),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/records", response_model=List[Dict[str, Any]])
def list_records(
    store_name: Optional[str] = None,
    user: dict = Depends(require_page("import")),
):
    records = services.get_records(store_name)
    allowed_names = set(user.get("allowed_stores") or [])
    if user.get("role") == "master":
        return records
    return [r for r in records if r.get("store_name") in allowed_names]


@router.get("/batches", response_model=List[Dict[str, Any]])
def list_import_batches(
    store_name: Optional[str] = None,
    user: dict = Depends(require_page("import")),
):
    if store_name:
        authorize_store(user, store_name)
    records = services.get_import_batches(
        store_name, user.get("sub", "unknown"), user.get("role") == "master"
    )
    if user.get("role") == "master":
        return records
    allowed_names = set(user.get("allowed_stores") or [])
    return [record for record in records if record.get("store_name") in allowed_names]


@router.post("/batches/{batch_id}/rollback", response_model=Dict[str, Any])
def rollback_import_batch(
    batch_id: str,
    user: dict = Depends(require_page("import")),
):
    records = services.get_import_batches(
        None, user.get("sub", "unknown"), user.get("role") == "master"
    )
    target = next((record for record in records if record.get("batch_id") == batch_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    authorize_store(user, target["store_name"])
    try:
        return services.rollback_import_batch(
            batch_id, user.get("sub", "unknown"), user.get("role") == "master"
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/records/{store_name}/{date}", response_model=Dict[str, Any])
def delete_record(
    store_name: str,
    date: datetime.date,
    user: dict = Depends(require_master),
):
    authorize_store(user, store_name)
    return services.delete_record(store_name, date, user.get("sub", "unknown"))


@router.get("/cleanup/preview", response_model=Dict[str, Any])
def preview_cleanup(
    store_name: str,
    date: datetime.date,
    user: dict = Depends(require_master),
):
    authorize_store(user, store_name)
    return services.preview_cleanup(store_name, date)


@router.post("/cleanup", response_model=Dict[str, Any])
def cleanup_data(
    store_name: str = Form(...),
    date: datetime.date = Form(...),
    cleanup_type: str = Form(...),
    confirm_text: str = Form(...),
    user: dict = Depends(require_master),
):
    authorize_store(user, store_name)
    expected = f"{store_name} {date.isoformat()}"
    if confirm_text != expected:
        raise HTTPException(status_code=400, detail=f"请输入“{expected}”确认清理")
    try:
        return services.cleanup_daily_data(
            store_name, date, cleanup_type, user.get("sub", "unknown")
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
