import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import services
from auth import require_master, require_page

router = APIRouter()


class ListenRequest(BaseModel):
    config: Dict[str, Any]
    timeout: int = 60


class SendReportRequest(BaseModel):
    report_date: datetime.date
    config: Dict[str, Any]


@router.get("/config", response_model=Dict[str, Any])
def get_config(_: dict = Depends(require_page("ai_wecom"))):
    return services.get_wecom_config()


@router.post("/config", response_model=Dict[str, Any])
def update_config(
    config: Dict[str, Any],
    _: dict = Depends(require_master),
):
    return services.update_wecom_config(config)


@router.post("/listen", response_model=Optional[str])
def listen(
    req: ListenRequest,
    _: dict = Depends(require_page("ai_wecom")),
):
    return services.listen_wecom(req.config, req.timeout)


@router.post("/send", response_model=Dict[str, Any])
def send_report(
    req: SendReportRequest,
    _: dict = Depends(require_page("ai_wecom")),
):
    try:
        return services.send_wecom_report_service(req.report_date, req.config)
    except RuntimeError as exc:
        # 企业微信智能机器人频控不应显示成泛化 500，避免用户立即重复点击。
        if "errcode=846607" in str(exc) or "frequency limit exceeded" in str(exc):
            raise HTTPException(
                status_code=429,
                detail="企业微信发送频率受限，刚才的请求可能已经发送成功，请等待约 1 分钟后再试。",
            ) from exc
        raise
