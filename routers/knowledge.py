import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator

import knowledge_service
import services
from auth import authorize_store, require_page


router = APIRouter()


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    course_id: Optional[str] = Field(default=None, max_length=32)
    topic: Optional[str] = Field(default=None, max_length=64)
    decision_only: bool = False
    limit: int = Field(default=8, ge=1, le=20)


class KnowledgeAssistRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    course_id: Optional[str] = Field(default=None, max_length=32)
    topic: Optional[str] = Field(default=None, max_length=64)
    limit: int = Field(default=8, ge=1, le=12)
    use_ai: bool = True
    store_name: Optional[str] = Field(default=None, max_length=200)
    start_date: Optional[datetime.date] = None
    end_date: Optional[datetime.date] = None

    @model_validator(mode="after")
    def validate_store_dates(self):
        dates = (self.start_date, self.end_date)
        if self.store_name and not all(dates):
            raise ValueError("选择店铺后必须同时提供开始和结束日期")
        if any(dates) and not self.store_name:
            raise ValueError("提供日期范围时必须选择店铺")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("开始日期不能晚于结束日期")
        return self


@router.get("/status", response_model=Dict[str, Any])
def status(_: dict = Depends(require_page("knowledge_assistant"))):
    return knowledge_service.get_knowledge_status()


@router.post("/search", response_model=Dict[str, Any])
def search(
    req: KnowledgeSearchRequest,
    _: dict = Depends(require_page("knowledge_assistant")),
):
    return knowledge_service.search_knowledge(
        query=req.query,
        course_id=req.course_id,
        topic=req.topic,
        decision_only=req.decision_only,
        limit=req.limit,
    )


def _business_context(req: KnowledgeAssistRequest, user: dict) -> Optional[Dict[str, Any]]:
    if not req.store_name or not req.start_date or not req.end_date:
        return None
    authorize_store(user, req.store_name)
    data = services.load_analysis_data(req.store_name, req.start_date, req.end_date)
    metrics = sorted(
        data.get("product_metrics") or [],
        key=lambda row: float(row.get("promo_spend", 0) or 0),
        reverse=True,
    )[:12]
    selected_fields = (
        "product_id",
        "product_name",
        "promo_spend",
        "promo_gmv",
        "promo_roi",
        "order_count",
        "valid_order_count",
        "valid_order_gmv",
        "valid_merchant_income",
        "real_roi_merchant_income",
        "refund_rate",
        "cancel_rate",
        "ctr",
        "click_to_order_rate",
    )
    return {
        "store_name": req.store_name,
        "start_date": req.start_date.isoformat(),
        "end_date": req.end_date.isoformat(),
        "kpis": data.get("kpis") or {},
        "top_products_by_spend": [
            {key: row.get(key) for key in selected_fields if key in row} for row in metrics
        ],
    }


@router.post("/assist", response_model=Dict[str, Any])
def assist(
    req: KnowledgeAssistRequest,
    user: dict = Depends(require_page("knowledge_assistant")),
):
    context = _business_context(req, user)
    result = knowledge_service.answer_with_knowledge(
        query=req.query,
        course_id=req.course_id,
        topic=req.topic,
        limit=req.limit,
        use_ai=req.use_ai,
        business_context=context,
    )
    result["business_context"] = context
    return result
