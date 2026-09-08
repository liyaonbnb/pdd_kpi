"""Gap-filling V1-compat routes that were missing from the V2 API.

These cover the legacy React pages that still call the old V1 endpoint shapes
(/costs, /orders/mappings, /users/{username}, /stores/{id}, /system/update).
All reads/writes go through the same V2 PostgreSQL tables as the rest of V2.
"""
from datetime import date
from typing import Any
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from v2 import costs as _costs
from v2.v1_compat import _require_user, _safe_user, _load_v2_user

router = APIRouter(prefix="/api", tags=["gap-compat"])


# ---------- /api/users/{username} ----------

class UserUpdateIn(BaseModel):
    password: str | None = None
    allowed_stores: list[str] | None = None
    allowed_pages: list[str] | None = None


def _admin(user: dict):
    if user.get("role") not in {"master", "admin"}:
        raise HTTPException(status_code=403, detail="权限不足")


@router.patch("/users/{username}")
def update_user(username: str, req: UserUpdateIn, user: dict = Depends(_require_user)):
    _admin(user)
    existing = _load_v2_user(username)
    if not existing:
        raise HTTPException(status_code=404, detail="用户不存在")
    with psycopg.connect(_costs.DATABASE_URL) as conn, conn.cursor() as cur:
        if req.password:
            cur.execute("update v2_users set password_hash=%s,password_changed=false,updated_at=now() where username=%s", (req.password, username))
        if req.allowed_pages is not None:
            cur.execute("update v2_users set allowed_pages=%s,updated_at=now() where username=%s", (req.allowed_pages, username))
        if req.allowed_stores is not None:
            cur.execute("delete from v2_user_store_permissions where user_id=(select id from v2_users where username=%s)", (username,))
            for store in req.allowed_stores:
                cur.execute("insert into v2_user_store_permissions(user_id,platform,store_name) select id,'pdd',%s from v2_users where username=%s on conflict do nothing", (store, username))
        conn.commit()
    return _safe_user(_load_v2_user(username) or existing)


@router.delete("/users/{username}")
def delete_user(username: str, user: dict = Depends(_require_user)):
    _admin(user)
    if username == user.get("username"):
        raise HTTPException(status_code=400, detail="不能删除当前登录账号")
    with psycopg.connect(_costs.DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("delete from v2_users where username=%s returning username", (username,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="用户不存在")
        conn.commit()
    return {"ok": True}


class StoreRenameIn(BaseModel):
    new_name: str = Field(min_length=1)


class StorePlatformIn(BaseModel):
    platform: str = Field(min_length=1)


@router.patch("/stores/{store_id}")
def rename_store(store_id: str, req: StoreRenameIn, user: dict = Depends(_require_user)):
    _admin(user)
    with psycopg.connect(_costs.DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("select platform,store_name from platform_stores where id=%s", (store_id,)); row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="店铺不存在")
        platform, old = row
        cur.execute("update platform_stores set store_name=%s,display_name=%s,updated_at=now() where id=%s", (req.new_name, req.new_name, store_id))
        cur.execute("update platform_orders set store_name=%s where platform=%s and store_name=%s", (req.new_name, platform, old))
        conn.commit()
    return {"id": store_id, "name": req.new_name, "platform": platform}


@router.patch("/stores/{store_id}/platform")
def change_platform(store_id: str, req: StorePlatformIn, user: dict = Depends(_require_user)):
    _admin(user)
    with psycopg.connect(_costs.DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("update platform_stores set platform=%s,updated_at=now() where id=%s returning id", (req.platform, store_id))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="店铺不存在")
        conn.commit()
    return {"id": store_id, "platform": req.platform}


@router.delete("/stores/{store_id}")
def delete_store(store_id: str, user: dict = Depends(_require_user)):
    _admin(user)
    with psycopg.connect(_costs.DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("update platform_stores set is_active=false,updated_at=now() where id=%s returning id", (store_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="店铺不存在")
        conn.commit()
    return {"ok": True}


class OrderMappingIn(BaseModel):
    store_name: str
    product_id: str = Field(min_length=1)
    merchant_code: str = Field(min_length=1)


@router.post("/orders/mappings")
def save_mapping(req: OrderMappingIn, user: dict = Depends(_require_user)):
    with psycopg.connect(_costs.DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("select id from bundles where code=%s", (req.merchant_code,)); row = cur.fetchone()
        if not row:
            cur.execute("insert into bundles(code,name) values(%s,%s) returning id", (req.merchant_code, req.merchant_code)); row = cur.fetchone()
        cur.execute("insert into platform_listing_mappings(platform,store_name,product_id,bundle_id) values('pdd',%s,%s,%s) on conflict (platform,store_name,product_id,style_id,effective_from) do update set bundle_id=excluded.bundle_id", (req.store_name, req.product_id, row[0]))
        conn.commit()
    return {"ok": True}


@router.get("/costs")
def list_costs(user: dict = Depends(_costs._require_costs_user)):
    with psycopg.connect(_costs.DATABASE_URL) as conn, conn.cursor() as cur:
        return _costs._bundle_cost_rows(cur)


@router.post("/costs")
def save_costs(req: _costs.SaveGlobalCostsRequest, user: dict = Depends(_costs._require_costs_user)):
    return _costs.save_global_costs(req, user)


@router.post("/costs/refresh")
def refresh_costs(user: dict = Depends(_costs._require_costs_user)):
    return _costs.refresh_global_cost_codes(user)
