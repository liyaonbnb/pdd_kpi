import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

import services
from auth import accessible_stores, authorize_stores, require_master, require_page
from store_manager import list_store_names

router = APIRouter()


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
    """主账号查看全部拼多多店铺的运营日报。"""
    all_stores = list_store_names("pdd")
    selected = [name for name in (store_names or all_stores) if name in all_stores]
    try:
        return services.get_operations_daily_report(start_date, end_date, selected)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
