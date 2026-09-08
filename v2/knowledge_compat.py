"""Knowledge base compatibility routes backed by the legacy sqlite knowledge service."""
from typing import Any
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from v2.v1_compat import _require_user
import knowledge_service

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class KnowledgeSearchIn(BaseModel):
    query: str = Field(min_length=1)
    course_id: str | None = None
    topic: str | None = None
    decision_only: bool = False
    limit: int = Field(default=8, ge=1, le=20)


class KnowledgeAssistIn(BaseModel):
    query: str = Field(min_length=1)
    course_id: str | None = None
    topic: str | None = None
    limit: int = Field(default=8, ge=1, le=20)
    use_ai: bool = True
    store_name: str | None = None


@router.get("/status")
def status(user: dict = Depends(_require_user)):
    return knowledge_service.get_knowledge_status()


@router.post("/search")
def search(payload: KnowledgeSearchIn, user: dict = Depends(_require_user)):
    return knowledge_service.search_knowledge(
        payload.query,
        course_id=payload.course_id,
        topic=payload.topic,
        decision_only=payload.decision_only,
        limit=payload.limit,
    )


@router.post("/assist")
def assist(payload: KnowledgeAssistIn, user: dict = Depends(_require_user)):
    business_context = {"store_name": payload.store_name} if payload.store_name else None
    return knowledge_service.answer_with_knowledge(
        payload.query,
        course_id=payload.course_id,
        topic=payload.topic,
        limit=payload.limit,
        use_ai=payload.use_ai,
        business_context=business_context,
    )
