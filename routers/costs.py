from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

import cost_manager
import services
from auth import authorize_store, get_current_user, require_page
from services import bump_data_version

router = APIRouter()


class CostRecord(BaseModel):
    merchant_code: str
    product_name: str = ""
    product_cost: float = 0.0
    logistics_cost: float = 0.0


class SaveCostsRequest(BaseModel):
    store_name: str
    costs: List[CostRecord]


class SaveGlobalCostsRequest(BaseModel):
    costs: List[CostRecord]


class ProductMappingRequest(BaseModel):
    product_id: str
    merchant_code: str
    style_id: Optional[str] = None
    product_name: Optional[str] = None


# ---------- 按店铺（旧接口，保留兼容） ----------

@router.get("", response_model=List[Dict[str, Any]])
def list_costs(
    store_name: str,
    user: dict = Depends(get_current_user),
):
    authorize_store(user, store_name)
    return services.get_costs(store_name)


@router.post("", response_model=Dict[str, Any])
def save_costs(
    req: SaveCostsRequest,
    user: dict = Depends(get_current_user),
):
    authorize_store(user, req.store_name)
    result = services.save_costs(req.store_name, [c.model_dump() for c in req.costs])
    bump_data_version()
    return result


@router.post("/refresh", response_model=Dict[str, Any])
def refresh_cost_codes(
    store_name: str,
    user: dict = Depends(get_current_user),
):
    authorize_store(user, store_name)
    result = services.refresh_cost_codes(store_name)
    bump_data_version()
    return result


@router.get("/export", response_class=PlainTextResponse)
def export_costs(
    store_name: str,
    user: dict = Depends(get_current_user),
):
    authorize_store(user, store_name)
    return services.export_cost_csv(store_name)


@router.post("/import", response_model=Dict[str, Any])
def import_costs(
    store_name: str = Form(...),
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    authorize_store(user, store_name)
    file_bytes = file.file.read()
    result = services.import_cost_csv(store_name, file_bytes)
    bump_data_version()
    return result


# ---------- 全局成本（拥有成本页面权限的账号可管理） ----------

@router.get("/global", response_model=List[Dict[str, Any]])
def list_global_costs(_: dict = Depends(require_page("costs"))):
    return services.get_global_costs()


@router.post("/global", response_model=Dict[str, Any])
def save_global_costs(
    req: SaveGlobalCostsRequest,
    _: dict = Depends(require_page("costs")),
):
    result = services.save_global_costs([c.model_dump() for c in req.costs])
    bump_data_version()
    return result


@router.post("/global/refresh", response_model=Dict[str, Any])
def refresh_global_cost_codes(_: dict = Depends(require_page("costs"))):
    result = services.refresh_global_cost_codes_service()
    bump_data_version()
    return result


@router.get("/global/export", response_class=PlainTextResponse)
def export_global_costs(
    pending_only: bool = False,
    _: dict = Depends(require_page("costs")),
):
    return services.export_global_cost_csv(pending_only)


@router.post("/global/import", response_model=Dict[str, Any])
def import_global_costs(
    file: UploadFile = File(...),
    _: dict = Depends(require_page("costs")),
):
    file_bytes = read_upload_file(file)
    result = services.import_global_cost_csv(file_bytes)
    bump_data_version()
    return result


@router.get("/global/unmapped", response_model=List[Dict[str, Any]])
def list_unmapped_products(_: dict = Depends(require_page("costs"))):
    return services.get_unmapped_products()


@router.get("/global/unmapped/count", response_model=Dict[str, int])
def count_unmapped_products(_: dict = Depends(require_page("costs"))):
    unmapped = len(services.get_unmapped_products())
    pending = sum(
        1
        for c in cost_manager.list_global_cost_rows()
        if c.get("product_cost", 0) <= 0 or c.get("logistics_cost", 0) <= 0
    )
    return {"pending": pending, "unmapped": unmapped}


@router.post("/global/map", response_model=Dict[str, Any])
def map_product_to_merchant_code(
    req: ProductMappingRequest,
    _: dict = Depends(require_page("costs")),
):
    result = services.save_global_product_mapping_service(
        req.product_id, req.merchant_code, style_id=req.style_id, product_name=req.product_name
    )
    bump_data_version()
    return result
