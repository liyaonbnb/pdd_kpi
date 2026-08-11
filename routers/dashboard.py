import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import services
from auth import accessible_stores, authorize_stores, require_master, require_page
from store_manager import list_store_names

router = APIRouter()


class OperationsDailySendRequest(BaseModel):
    start_date: datetime.date
    end_date: datetime.date
    draft_id: str


@router.get("/summary", response_model=Dict[str, Any])
def dashboard_summary(
    start_date: datetime.date = Query(...),
    end_date: datetime.date = Query(...),
    store_names: Optional[List[str]] = Query(None),
    user: dict = Depends(require_page("overview")),
):
    allowed = accessible_stores(user, list_store_names("pdd"))
    if store_names:
        selected = authorize_stores(user, store_names)
    else:
        selected = allowed
    return services.get_dashboard_summary(start_date, end_date, store_names=selected)


@router.get("/operations-daily", response_model=Dict[str, Any])
def operations_daily_report(
    start_date: Optional[datetime.date] = Query(None),
    end_date: Optional[datetime.date] = Query(None),
    store_names: Optional[List[str]] = Query(None),
    _: dict = Depends(require_master),
):
    """主账号查看全平台运营日报和拼多多店铺矩阵。"""
    all_stores = list_store_names("pdd")
    selected = [name for name in (store_names or all_stores) if name in all_stores]
    try:
        return services.get_all_platform_operations_daily(start_date, end_date, selected)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/operations-daily/wecom/preview", response_model=Dict[str, Any])
def preview_operations_daily_wecom(
    start_date: datetime.date = Query(...),
    end_date: datetime.date = Query(...),
    _: dict = Depends(require_master),
):
    try:
        return services.preview_all_platform_operations_wecom_report(start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/operations-daily/wecom/send", response_model=Dict[str, Any])
def send_operations_daily_wecom(
    request: OperationsDailySendRequest,
    _: dict = Depends(require_master),
):
    try:
        return services.send_all_platform_operations_wecom_report(
            request.start_date,
            request.end_date,
            request.draft_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        if "errcode=846607" in str(exc) or "frequency limit exceeded" in str(exc):
            raise HTTPException(
                status_code=429,
                detail="企业微信拒绝主动推送，请确认目标群已先 @机器人 发送过消息；若刚刚连续重试，请稍后再试。",
            ) from exc
        raise
