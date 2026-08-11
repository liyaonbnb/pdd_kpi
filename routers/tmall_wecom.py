import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

import tmall_services
from auth import get_current_user, require_master, require_page

router = APIRouter()


@router.get("/config", response_model=Dict[str, Any])
def get_config(user: dict = Depends(require_page("ai_wecom"))):
    return tmall_services.get_tmall_wecom_config()


@router.post("/config", response_model=Dict[str, Any])
def update_config(
    config: Dict[str, Any],
    user: dict = Depends(require_master),
):
    return tmall_services.update_tmall_wecom_config(config)


@router.post("/preview", response_model=Dict[str, Any])
def preview_report(
    report_date: datetime.date,
    user: dict = Depends(require_page("ai_wecom")),
):
    return tmall_services.preview_tmall_wecom_report(report_date)


@router.post("/send", response_model=Dict[str, Any])
def send_report(
    report_date: datetime.date,
    config: Dict[str, Any],
    draft_id: Optional[str] = None,
    user: dict = Depends(require_page("ai_wecom")),
):
    try:
        return tmall_services.send_tmall_wecom_report(report_date, config, draft_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
