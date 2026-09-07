"""V2 API for the isolated deployment environment.

The API is additive and remains isolated from the legacy production database.
Existing test-token access is retained while V2 account authentication is
introduced incrementally.
"""

import os
import hashlib
import json
import io
import base64
import hmac
import time
from pathlib import Path
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Json
from fastapi import FastAPI, File, Form, Header, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
try:
    import bcrypt
except Exception:
    bcrypt = None

from v2.local_workflow import run_workflow



DATABASE_URL = os.getenv(
    "V2_DATABASE_URL",
    "postgresql://pdd_v2_test:pdd_v2_test_local_2026@127.0.0.1:55432/pdd_v2_test",
)
TEST_TOKEN = os.getenv("V2_TEST_TOKEN", "")
AUTH_SECRET = os.getenv("V2_AUTH_SECRET", TEST_TOKEN or "pdd-bi-v2-test-auth-secret")

app = FastAPI(
    title="PDD BI V2 Test API",
    version="0.1.0",
    description="隔离测试环境 API；不连接旧版生产数据。",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _ensure_metadata_tables() -> None:
    """Apply additive V2 metadata migration to an already-created test database."""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                create table if not exists platform_stores (
                    id uuid primary key default gen_random_uuid(),
                    platform varchar(32) not null,
                    store_name varchar(255) not null,
                    display_name varchar(255),
                    is_active boolean not null default true,
                    legacy_key varchar(255),
                    metadata jsonb not null default '{}'::jsonb,
                    created_at timestamptz not null default now(),
                    updated_at timestamptz not null default now(),
                    unique (platform, store_name)
                )
            """)
            cur.execute("insert into platform_stores(platform,store_name,display_name,legacy_key) values('pdd','测试店','测试店','测试店') on conflict(platform,store_name) do nothing")
            cur.execute("""
                create table if not exists v2_users (
                    id uuid primary key default gen_random_uuid(),
                    username varchar(128) not null unique,
                    password_hash varchar(255) not null,
                    role varchar(16) not null default 'sub' check (role in ('master','sub','admin','operator','viewer')),
                    display_name varchar(255),
                    allowed_pages jsonb not null default '[]'::jsonb,
                    is_active boolean not null default true,
                    legacy_username varchar(128),
                    password_changed boolean not null default true,
                    created_at timestamptz not null default now(),
                    updated_at timestamptz not null default now()
                )
            """)
            cur.execute("""
                create table if not exists v2_user_store_permissions (
                    user_id uuid not null references v2_users(id) on delete cascade,
                    platform varchar(32) not null,
                    store_name varchar(255) not null,
                    primary key (user_id, platform, store_name)
                )
            """)
            cur.execute("alter table data_import_batches drop constraint if exists data_import_batches_data_type_check")
            cur.execute("alter table data_import_batches add constraint data_import_batches_data_type_check check (data_type in ('orders','promotions','inventory','costs','items','bundles','stock_in','stock_out'))")
            cur.execute("""
                create table if not exists promotion_metrics_daily (
                    id uuid primary key default gen_random_uuid(),
                    import_batch_id uuid not null references data_import_batches(id) on delete cascade,
                    platform varchar(32) not null,
                    store_name varchar(255) not null,
                    metric_date date not null,
                    product_id varchar(128),
                    style_id varchar(128),
                    spend numeric(20,6) not null default 0,
                    gmv numeric(20,6) not null default 0,
                    orders numeric(20,6) not null default 0,
                    exposure numeric(20,6) not null default 0,
                    clicks numeric(20,6) not null default 0,
                    raw_payload jsonb not null default '{}'::jsonb,
                    created_at timestamptz not null default now(),
                    unique (import_batch_id, product_id, style_id)
                )
            """)
        conn.commit()


@app.on_event("startup")
def _startup_migrations() -> None:
    _ensure_metadata_tables()


class ItemIn(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    base_unit: str = Field(default="件", max_length=32)
    category: str | None = None
    safety_stock: Decimal = Decimal("0")


class BundleComponentIn(BaseModel):
    item_code: str = Field(min_length=1)
    quantity: Decimal = Field(gt=0)


class BundleIn(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    estimated_shipping_fee: Decimal = Decimal("0")
    effective_from: str
    components: list[BundleComponentIn] = Field(min_length=1)


class PurchaseLineIn(BaseModel):
    item_code: str
    batch_no: str
    quantity: Decimal = Field(gt=0)
    base_unit_cost: Decimal = Field(ge=0)
    line_amount: Decimal = Field(ge=0)


class PurchaseIn(BaseModel):
    receipt_no: str
    warehouse_code: str
    supplier_name: str | None = None
    freight_fee: Decimal = Decimal("0")
    other_fee: Decimal = Decimal("0")
    lines: list[PurchaseLineIn] = Field(min_length=1)


class OpeningIn(BaseModel):
    warehouse_code: str
    item_code: str
    batch_no: str
    quantity: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)


class ReturnIn(BaseModel):
    return_no: str
    order_id: str
    warehouse_code: str
    item_code: str
    quantity: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)


class ReturnInspectIn(BaseModel):
    target_status: str


class OrderLineIn(BaseModel):
    bundle_code: str
    quantity: Decimal = Field(gt=0)
    product_id: str | None = None
    style_id: str | None = None


class OrderIn(BaseModel):
    order_id: str
    platform: str = "pdd"
    store_name: str
    warehouse_code: str
    payment_time: datetime
    order_status: str = "支付成功"
    lines: list[OrderLineIn] = Field(min_length=1)


class InventoryAdjustmentIn(BaseModel):
    warehouse_code: str
    item_code: str
    transaction_type: str
    quantity: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)
    reference_id: str = Field(min_length=1, max_length=128)
    batch_no: str | None = None


class ListingMappingIn(BaseModel):
    platform: str = "pdd"
    store_name: str
    product_id: str
    style_id: str | None = None
    bundle_code: str
    effective_from: str | None = None
    effective_to: str | None = None


class StoreIn(BaseModel):
    platform: str = "pdd"
    store_name: str = Field(min_length=1, max_length=255)
    display_name: str | None = None
    legacy_key: str | None = None


class StoreWarehouseIn(BaseModel):
    platform: str = "pdd"
    store_name: str
    warehouse_code: str
    effective_from: str


class V2LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class V2UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str | None = Field(default=None, min_length=1, max_length=256)
    password_hash: str | None = None
    role: str = "sub"
    display_name: str | None = None
    allowed_stores: list[str] = Field(default_factory=list)
    allowed_pages: list[str] = Field(default_factory=list)
    legacy_username: str | None = None
    password_changed: bool = True


class LegacyUsersImportIn(BaseModel):
    users: list[V2UserIn] = Field(min_length=1)
    effective_to: str | None = None


class LegacyLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class ImportRowIn(BaseModel):
    order_id: str | None = None
    product_id: str | None = None
    style_id: str | None = None
    bundle_code: str | None = None
    quantity: Decimal = Decimal("0")
    payment_time: datetime | None = None
    order_status: str | None = None
    spend: Decimal = Decimal("0")
    gmv: Decimal = Decimal("0")
    orders: Decimal = Decimal("0")
    exposure: Decimal = Decimal("0")
    clicks: Decimal = Decimal("0")
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class ImportPayload(BaseModel):
    platform: str = "pdd"
    store_name: str
    data_type: str
    metric_date: date | None = None
    source_filename: str | None = None
    source_sha256: str | None = None
    rows: list[ImportRowIn] = Field(min_length=1)


_COLUMN_ALIASES = {
    "order_id": ["订单号", "订单编号", "子订单号", "order_id"],
    "product_id": ["商品ID", "商品id", "宝贝ID", "product_id"],
    "style_id": ["样式ID", "SKUID", "SKU ID", "style_id"],
    "quantity": ["商品数量(件)", "数量", "购买数量", "quantity"],
    "payment_time": ["支付时间", "付款时间", "pay_time", "payment_time"],
    "order_status": ["订单状态", "状态", "order_status"],
    "spend": ["成交花费(元)", "总花费(元)", "花费(元)", "推广花费", "spend"],
    "gmv": ["交易额(元)", "成交金额(元)", "GMV(元)", "gmv"],
    "orders": ["成交笔数", "成交订单数", "订单数", "orders"],
    "exposure": ["曝光量", "曝光次数", "展现量", "exposure"],
    "clicks": ["点击量", "点击次数", "点击数", "clicks"],
}


def _find_column(columns: list[str], aliases: list[str]) -> str | None:
    normalized = {str(column).strip(): str(column) for column in columns}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    compact = {str(column).replace(" ", "").replace("（", "(").replace("）", ")"): str(column) for column in columns}
    for alias in aliases:
        alias_compact = alias.replace(" ", "").replace("（", "(").replace("）", ")")
        for column, original in compact.items():
            if alias_compact in column or column in alias_compact:
                return original
    return None


def _cell(row: Any, column: str | None, default: Any = None) -> Any:
    if not column:
        return default
    value = row.get(column, default)
    if value is None:
        return default
    try:
        if value != value:
            return default
    except Exception:
        pass
    return value


def _text(value: Any) -> str | None:
    try:
        import pandas as pd
        if pd.isna(value):
            return None
    except Exception:
        pass
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "null"}:
        return None
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def _raw_value(value: Any) -> Any:
    text = _text(value)
    if text is not None:
        return text
    return None


def _number(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        text = str(value).replace(",", "").strip()
        return Decimal(text) if text else default
    except Exception:
        return default


def _parse_uploaded_file(filename: str, content: bytes, data_type: str) -> list[ImportRowIn]:
    import pandas as pd

    suffix = Path(filename or "upload.csv").suffix.lower()
    if suffix in {".xls", ".xlsx"}:
        frame = pd.read_excel(io.BytesIO(content))
    elif suffix == ".csv":
        frame = None
        errors = []
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
            try:
                first_line = content.splitlines()[0] if content.splitlines() else b""
                separator = "\t" if b"\t" in first_line and b"," not in first_line else ","
                frame = pd.read_csv(io.BytesIO(content), encoding=encoding, sep=separator, low_memory=False)
                break
            except Exception as exc:
                errors.append(str(exc))
        if frame is None:
            raise HTTPException(status_code=400, detail=f"CSV 无法读取：{errors[-1] if errors else '未知错误'}")
    else:
        raise HTTPException(status_code=400, detail="仅支持 CSV、XLS、XLSX 文件")
    if frame.empty:
        raise HTTPException(status_code=400, detail="文件没有数据行")
    if frame.columns.duplicated().any():
        raise HTTPException(status_code=400, detail="文件存在重复列名，请先整理表头")
    columns = [str(column) for column in frame.columns]
    mapping = {key: _find_column(columns, aliases) for key, aliases in _COLUMN_ALIASES.items()}
    rows: list[ImportRowIn] = []
    for _, raw in frame.iterrows():
        payload: dict[str, Any] = {
            "order_id": _text(_cell(raw, mapping["order_id"], None)),
            "product_id": _text(_cell(raw, mapping["product_id"], None)),
            "style_id": _text(_cell(raw, mapping["style_id"], None)),
            "quantity": _number(_cell(raw, mapping["quantity"], 0)),
            "order_status": _text(_cell(raw, mapping["order_status"], None)),
            "spend": _number(_cell(raw, mapping["spend"], 0)),
            "gmv": _number(_cell(raw, mapping["gmv"], 0)),
            "orders": _number(_cell(raw, mapping["orders"], 0)),
            "exposure": _number(_cell(raw, mapping["exposure"], 0)),
            "clicks": _number(_cell(raw, mapping["clicks"], 0)),
            "raw_payload": {str(key): _raw_value(value) for key, value in raw.to_dict().items()},
        }
        if data_type == "orders":
            value = _cell(raw, mapping["payment_time"], None)
            if value is not None and str(value).strip():
                try:
                    payload["payment_time"] = pd.to_datetime(value).to_pydatetime()
                except Exception:
                    payload["payment_time"] = None
        rows.append(ImportRowIn(**payload))
    return rows


def _db_status() -> dict[str, Any]:
    _ensure_metadata_tables()
    with psycopg.connect(DATABASE_URL, connect_timeout=3) as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from information_schema.tables where table_schema = 'public'")
            table_count = int(cur.fetchone()[0])
            cur.execute("select code, name from warehouses where is_active = true order by code")
            warehouses = [{"code": code, "name": name} for code, name in cur.fetchall()]
            cur.execute("select inventory_enabled_from, is_locked from inventory_settings where id = 1")
            row = cur.fetchone()
            inventory = {
                "enabled_from": row[0].isoformat() if row and row[0] else None,
                "locked": bool(row[1]) if row else False,
            }
    return {"table_count": table_count, "warehouses": warehouses, "inventory": inventory}


def _warehouse_id(cur: Any, code: str) -> str:
    cur.execute("select id from warehouses where upper(code) = upper(%s) and is_active = true", (code,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=400, detail=f"仓库不存在：{code}")
    return str(row[0])


def _item_id(cur: Any, code: str) -> str:
    cur.execute("select id from inventory_items where code = %s and is_active = true", (code,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=400, detail=f"单品不存在：{code}")
    return str(row[0])


def _row_dict(cur: Any) -> list[dict[str, Any]]:
    names = [desc.name for desc in cur.description]
    rows = []
    for row in cur.fetchall():
        value = {}
        for name, item in zip(names, row):
            if isinstance(item, UUID):
                item = str(item)
            elif isinstance(item, Decimal):
                item = str(item)
            elif hasattr(item, "isoformat"):
                item = item.isoformat()
            value[name] = item
        rows.append(value)
    return rows


def _token_part(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _token_unpart(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _issue_auth_token(user: dict[str, Any]) -> str:
    payload = {
        "sub": user["username"],
        "role": user["role"],
        "allowed_stores": user.get("allowed_stores", []),
        "allowed_pages": user.get("allowed_pages", []),
        "exp": int(time.time()) + 7 * 24 * 3600,
    }
    body = _token_part(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    signature = _token_part(hmac.new(AUTH_SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    return f"v2.{body}.{signature}"


def _verify_auth_token(token: str | None) -> dict[str, Any] | None:
    if not token or not token.startswith("v2."):
        return None
    try:
        _, body, signature = token.split(".", 2)
        expected = _token_part(hmac.new(AUTH_SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_token_unpart(body).decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def _legacy_user_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    username, role, display_name, allowed_pages, is_active, legacy_username, password_changed = row
    allowed_stores: list[dict[str, Any]] = []
    return {
        "username": username,
        "role": role,
        "display_name": display_name,
        "allowed_pages": allowed_pages or [],
        "allowed_stores": allowed_stores,
        "is_active": bool(is_active),
        "legacy_username": legacy_username,
        "password_changed": bool(password_changed),
    }



def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _issue_jwt(user: dict[str, Any]) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    stores = user.get("allowed_stores", [])
    flat_stores = [s.get("store_name") if isinstance(s, dict) else s for s in stores]
    payload = _b64url(json.dumps({
        "sub": user["username"],
        "role": user.get("role", "sub"),
        "allowed_stores": flat_stores,
        "allowed_pages": user.get("allowed_pages", []),
        "exp": int(time.time()) + 86400 * 7,
    }, separators=(",", ":")).encode("utf-8"))
    signature = _b64url(hmac.new(AUTH_SECRET.encode("utf-8"), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def _verify_jwt(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    header, payload, signature = parts
    expected = _b64url(hmac.new(AUTH_SECRET.encode("utf-8"), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        pad = (-len(payload)) % 4
        decoded = base64.urlsafe_b64decode(payload + ("=" * pad))
        claims = json.loads(decoded.decode("utf-8"))
    except Exception:
        return None
    if claims.get("exp") and claims["exp"] < time.time():
        return None
    return claims
def _load_v2_user(username: str) -> dict[str, Any] | None:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select id, username, password_hash, role, display_name, allowed_pages, is_active, legacy_username, password_changed from v2_users where username=%s", (username,))
            row = cur.fetchone()
            if not row:
                return None
            user_id, name, password_hash, role, display_name, allowed_pages, is_active, legacy_username, password_changed = row
            cur.execute("select platform, store_name from v2_user_store_permissions where user_id=%s order by platform, store_name", (user_id,))
            stores = [{"platform": p, "store_name": s} for p, s in cur.fetchall()]
            return {
                "id": str(user_id), "username": name, "password_hash": password_hash, "role": role,
                "display_name": display_name, "allowed_pages": allowed_pages or [],
                "allowed_stores": stores, "is_active": bool(is_active),
                "legacy_username": legacy_username, "password_changed": bool(password_changed),
            }


def _safe_user(user: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in user.items() if k not in {"id", "password_hash"}}


def _require_v2_admin(x_v2_test_token: str | None, authorization: str | None) -> dict[str, Any]:
    if TEST_TOKEN and x_v2_test_token == TEST_TOKEN:
        return {"username": "test-token", "role": "master", "allowed_stores": [], "allowed_pages": []}
    token = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None
    user = _verify_auth_token(token)
    if not user or user.get("role") not in {"master", "admin"}:
        raise HTTPException(status_code=401, detail="需要 V2 管理员权限")
    return user


def _require_user_token(x_v2_test_token: str | None, authorization: str | None) -> dict[str, Any]:
    """写操作鉴权（合并后统一入口）：测试令牌 或 Bearer（V2 token / V1 形态 JWT）。"""
    if TEST_TOKEN and x_v2_test_token == TEST_TOKEN:
        return {"username": "test-token", "role": "master"}
    token = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None
    claims = _verify_auth_token(token) or _verify_jwt(token)
    if not claims:
        raise HTTPException(status_code=401, detail="需要登录")
    return claims


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        db = _db_status()
        paths = {getattr(route, "path", "") for route in app.routes}
        return {"status": "ok", "service": "pdd-bi-v2-test", "database": "ok", "compat_routes": {"users": "/api/users" in paths, "operations_daily": "/api/dashboard/operations-daily" in paths}, **db}
    except Exception as exc:  # pragma: no cover - exercised by deployment checks
        return {"status": "degraded", "service": "pdd-bi-v2-test", "database": "error", "detail": str(exc)}


@app.get("/api/v2/config")
def config() -> dict[str, Any]:
    return _db_status()


@app.post("/api/v2/auth/login")
def v2_login(payload: V2LoginIn) -> dict[str, Any]:
    if bcrypt is None:
        raise HTTPException(status_code=503, detail="认证组件尚未安装")
    user = _load_v2_user(payload.username)
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    try:
        matched = bcrypt.checkpw(payload.password.encode("utf-8"), user["password_hash"].encode("utf-8"))
    except Exception:
        matched = False
    if not matched:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    return {"access_token": _issue_auth_token(user), "token_type": "bearer", "user": _safe_user(user)}


@app.get("/api/v2/auth/me")
def v2_me(x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if TEST_TOKEN and x_v2_test_token == TEST_TOKEN:
        return {"username": "test-token", "role": "master", "allowed_stores": [], "allowed_pages": [], "is_active": True}
    token = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None
    claims = _verify_auth_token(token)
    if not claims:
        raise HTTPException(status_code=401, detail="登录已失效")
    user = _load_v2_user(str(claims.get("sub") or ""))
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="账号不可用")
    return _safe_user(user)




@app.post("/api/auth/login")
def legacy_login(payload: LegacyLoginIn) -> dict[str, Any]:
    if bcrypt is None:
        raise HTTPException(status_code=503, detail="认证组件尚未安装")
    user = _load_v2_user(payload.username)
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    try:
        matched = bcrypt.checkpw(payload.password.encode("utf-8"), user["password_hash"].encode("utf-8"))
    except Exception:
        matched = False
    if not matched:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    return {"access_token": _issue_jwt(user), "token_type": "bearer", "role": user.get("role", "sub"), "require_password_change": not user["password_changed"], "user": _safe_user(user)}


@app.get("/api/auth/me")
def legacy_me(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    token = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None
    claims = _verify_jwt(token)
    if not claims:
        raise HTTPException(status_code=401, detail="登录已失效")
    user = _load_v2_user(str(claims.get("sub") or ""))
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="账号不可用")
    result = _safe_user(user)
    result["allowed_stores"] = [s["store_name"] if isinstance(s, dict) else s for s in user["allowed_stores"]]
    result["require_password_change"] = not user["password_changed"]
    return result


@app.post("/api/auth/change-password")
def legacy_change_password(payload: dict[str, str], authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """V1 兼容改密：校验旧密码后更新 v2_users，并重新签发 JWT。"""
    if bcrypt is None:
        raise HTTPException(status_code=503, detail="认证组件尚未安装")
    token = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None
    claims = _verify_jwt(token) or _verify_auth_token(token)
    if not claims:
        raise HTTPException(status_code=401, detail="登录已失效")
    user = _load_v2_user(str(claims.get("sub") or ""))
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="账号不可用")
    old_password = str(payload.get("old_password") or "")
    new_password = str(payload.get("new_password") or "")
    if not bcrypt.checkpw(old_password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        raise HTTPException(status_code=400, detail="原密码错误")
    if len(new_password) < 8 or new_password.isalpha() or new_password.isdigit():
        raise HTTPException(status_code=400, detail="新密码至少 8 位且需包含字母和数字")
    new_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("update v2_users set password_hash=%s, password_changed=true where username=%s", (new_hash, user["username"]))
    return {"access_token": _issue_jwt(user), "token_type": "bearer"}


@app.get("/api/v2/users")
def list_v2_users(
    x_v2_test_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    _require_v2_admin(x_v2_test_token, authorization)
    _ensure_metadata_tables()
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select username from v2_users order by role desc, username")
            return [_safe_user(user) for (username,) in cur.fetchall() if (user := _load_v2_user(username))]


def _save_v2_user(payload: V2UserIn, preserve_existing_password: bool = False) -> dict[str, Any]:
    if payload.role not in {"master", "sub", "admin", "operator", "viewer"}:
        raise HTTPException(status_code=400, detail="不支持的角色")
    if payload.password_hash:
        password_hash = payload.password_hash
    elif payload.password:
        if bcrypt is None:
            raise HTTPException(status_code=503, detail="认证组件尚未安装")
        password_hash = bcrypt.hashpw(payload.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    elif preserve_existing_password:
        existing = _load_v2_user(payload.username)
        if not existing:
            raise HTTPException(status_code=400, detail="新账号必须设置密码")
        password_hash = existing["password_hash"]
    else:
        raise HTTPException(status_code=400, detail="必须设置密码")
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                insert into v2_users(username,password_hash,role,display_name,allowed_pages,legacy_username,password_changed)
                values(%s,%s,%s,%s,%s,%s,%s)
                on conflict(username) do update set password_hash=excluded.password_hash, role=excluded.role,
                  display_name=excluded.display_name, allowed_pages=excluded.allowed_pages,
                  legacy_username=excluded.legacy_username, password_changed=excluded.password_changed,
                  updated_at=now()
                returning id
            """, (payload.username, password_hash, payload.role, payload.display_name, Json(payload.allowed_pages), payload.legacy_username, payload.password_changed))
            user_id = cur.fetchone()[0]
            cur.execute("delete from v2_user_store_permissions where user_id=%s", (user_id,))
            for store_name in sorted(set(payload.allowed_stores)):
                cur.execute("select platform from platform_stores where store_name=%s order by platform", (store_name,))
                platforms = [row[0] for row in cur.fetchall()] or ["pdd"]
                for platform in platforms:
                    cur.execute("insert into v2_user_store_permissions(user_id,platform,store_name) values(%s,%s,%s) on conflict do nothing", (user_id, platform, store_name))
        conn.commit()
    return _safe_user(_load_v2_user(payload.username) or {"username": payload.username})


@app.post("/api/v2/users")
def create_v2_user(
    payload: V2UserIn,
    x_v2_test_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_v2_admin(x_v2_test_token, authorization)
    _ensure_metadata_tables()
    return _save_v2_user(payload, preserve_existing_password=False)


@app.post("/api/v2/users/import-legacy")
def import_legacy_users(
    payload: LegacyUsersImportIn,
    x_v2_test_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_v2_admin(x_v2_test_token, authorization)
    _ensure_metadata_tables()
    migrated = [_save_v2_user(user, preserve_existing_password=False) for user in payload.users]
    return {"migrated": len(migrated), "users": migrated}


@app.get("/api/v2/stores")
def list_stores(platform: str | None = None) -> list[dict[str, Any]]:
    _ensure_metadata_tables()
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select s.id,s.platform,s.store_name,s.display_name,s.is_active,s.legacy_key,s.created_at, w.code warehouse_code, a.effective_from, a.effective_to from platform_stores s left join lateral (select * from store_warehouse_assignments a where a.platform=s.platform and a.store_name=s.store_name order by a.effective_from desc limit 1) a on true left join warehouses w on w.id=a.warehouse_id where (%s::varchar is null or s.platform=%s::varchar) order by s.platform,s.store_name", (platform, platform))
            return _row_dict(cur)


@app.post("/api/v2/stores")
def create_store(payload: StoreIn, x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_user_token(x_v2_test_token, authorization)
    platform = payload.platform.strip().lower()
    if platform not in {"pdd", "douyin", "tmall", "wechat"}:
        raise HTTPException(status_code=400, detail="平台类型无效")
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                try:
                    cur.execute("insert into platform_stores(platform,store_name,display_name,legacy_key) values(%s,%s,%s,%s) returning id,platform,store_name,display_name,is_active,legacy_key,created_at", (platform, payload.store_name.strip(), payload.display_name or payload.store_name.strip(), payload.legacy_key or payload.store_name.strip()))
                except psycopg.errors.UniqueViolation:
                    raise HTTPException(status_code=409, detail="该平台店铺已存在")
                return _row_dict(cur)[0]


@app.post("/api/v2/stores/warehouse")
def assign_store_warehouse(payload: StoreWarehouseIn, x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_user_token(x_v2_test_token, authorization)
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                warehouse_id = _warehouse_id(cur, payload.warehouse_code)
                cur.execute("select 1 from platform_stores where platform=%s and store_name=%s and is_active=true", (payload.platform, payload.store_name))
                if not cur.fetchone():
                    raise HTTPException(status_code=400, detail="店铺不存在，请先建立店铺")
                cur.execute("insert into store_warehouse_assignments(platform,store_name,warehouse_id,effective_from,effective_to) values(%s,%s,%s,%s,%s) on conflict(platform,store_name,effective_from) do update set warehouse_id=excluded.warehouse_id,effective_to=excluded.effective_to returning id", (payload.platform, payload.store_name, warehouse_id, payload.effective_from, payload.effective_to))
                assignment_id = cur.fetchone()[0]
    return {"id": str(assignment_id), "status": "created"}


def _import_fingerprint(payload: ImportPayload) -> str:
    if payload.source_sha256:
        return payload.source_sha256
    raw = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@app.post("/api/v2/imports/file")
def import_file(
    store_name: str = Form(...),
    data_type: str = Form(...),
    platform: str = Form("pdd"),
    metric_date: date | None = Form(None),
    mode: str = Form("preview"),
    file: UploadFile = File(...),
    x_v2_test_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_user_token(x_v2_test_token, authorization)
    if mode not in {"preview", "import"}:
        raise HTTPException(status_code=400, detail="mode 只能是 preview 或 import")
    if data_type not in {"orders", "promotions"}:
        raise HTTPException(status_code=400, detail="当前支持订单或推广数据")
    if data_type == "promotions" and not metric_date:
        raise HTTPException(status_code=400, detail="推广数据必须提供数据日期")
    try:
        content = file.file.read()
        rows = _parse_uploaded_file(file.filename or "upload.csv", content, data_type)
        payload = ImportPayload(platform=platform, store_name=store_name, data_type=data_type, metric_date=metric_date, source_filename=file.filename, source_sha256=hashlib.sha256(content).hexdigest(), rows=rows)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"文件解析失败：{exc}") from exc
    preview = preview_import(payload, x_v2_test_token)
    preview["filename"] = file.filename
    preview["column_mapping"] = {key: _find_column([str(c) for c in rows[0].raw_payload.keys()], aliases) for key, aliases in _COLUMN_ALIASES.items()} if rows else {}
    if mode == "preview":
        return preview
    return import_rows(payload, x_v2_test_token)


@app.post("/api/v2/imports/preview")
def preview_import(payload: ImportPayload, x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_user_token(x_v2_test_token, authorization)
    if payload.data_type not in {"orders", "promotions"}:
        raise HTTPException(status_code=400, detail="当前支持订单或推广数据")
    if payload.data_type == "promotions" and not payload.metric_date:
        raise HTTPException(status_code=400, detail="推广数据必须提供 metric_date")
    missing_key = sum(1 for row in payload.rows if not (row.order_id if payload.data_type == "orders" else (row.product_id or row.style_id)))
    invalid_qty = sum(1 for row in payload.rows if payload.data_type == "orders" and row.quantity <= 0)
    return {"data_type": payload.data_type, "store_name": payload.store_name, "rows": len(payload.rows), "missing_key": missing_key, "invalid_quantity": invalid_qty, "source_sha256": _import_fingerprint(payload), "ready": missing_key == 0 and invalid_qty == 0}


@app.get("/api/v2/imports/batches")
def list_import_batches(x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
    _require_user_token(x_v2_test_token, authorization)
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select id,platform,store_name,data_type,source_filename,period_from,period_to,status,row_count,error_count,error_message,created_at,completed_at from data_import_batches order by created_at desc limit 200")
            return _row_dict(cur)


@app.get("/api/v2/promotions")
def list_promotions(store_name: str | None = None, metric_date: date | None = None, x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
    _require_user_token(x_v2_test_token, authorization)
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select id,import_batch_id,platform,store_name,metric_date,product_id,style_id,spend,gmv,orders,exposure,clicks,created_at from promotion_metrics_daily where (%s::varchar is null or store_name=%s::varchar) and (%s::date is null or metric_date=%s::date) order by metric_date desc, store_name, product_id limit 5000", (store_name,store_name,metric_date,metric_date))
            return _row_dict(cur)


@app.post("/api/v2/imports")
def import_rows(payload: ImportPayload, x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_user_token(x_v2_test_token, authorization)
    if payload.data_type not in {"orders", "promotions"}:
        raise HTTPException(status_code=400, detail="当前支持订单或推广数据")
    preview = preview_import(payload, x_v2_test_token)
    if not preview["ready"]:
        raise HTTPException(status_code=422, detail=f"数据校验失败：缺少主键 {preview['missing_key']} 行，数量无效 {preview['invalid_quantity']} 行")
    source_sha = preview["source_sha256"]
    period = payload.metric_date or (min((r.payment_time.date() for r in payload.rows if r.payment_time), default=None))
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("select id,status from data_import_batches where source_sha256=%s order by created_at desc limit 1", (source_sha,))
                existing = cur.fetchone()
                if existing:
                    return {"batch_id": str(existing[0]), "status": "duplicate", "existing_status": existing[1]}
                cur.execute("insert into data_import_batches(platform,store_name,data_type,source_filename,source_sha256,period_from,period_to,status,row_count,created_by,completed_at) values(%s,%s,%s,%s,%s,%s,%s,'processing',%s,'v2-test',now()) returning id", (payload.platform.lower(), payload.store_name, payload.data_type, payload.source_filename, source_sha, period, period, len(payload.rows)))
                batch_id = cur.fetchone()[0]
                inserted = 0
                skipped = 0
                errors = []
                for row in payload.rows:
                    if payload.data_type == "promotions":
                        cur.execute("insert into promotion_metrics_daily(import_batch_id,platform,store_name,metric_date,product_id,style_id,spend,gmv,orders,exposure,clicks,raw_payload) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict(import_batch_id,product_id,style_id) do nothing", (batch_id,payload.platform.lower(),payload.store_name,payload.metric_date or period,row.product_id,row.style_id,row.spend,row.gmv,row.orders,row.exposure,row.clicks,Json(row.raw_payload)))
                        inserted += cur.rowcount
                        continue
                    cur.execute("select id from platform_orders where platform=%s and store_name=%s and order_id=%s", (payload.platform.lower(),payload.store_name,row.order_id))
                    if cur.fetchone():
                        skipped += 1
                        continue
                    cur.execute("insert into platform_orders(import_batch_id,platform,store_name,order_id,payment_time,order_status,inventory_status) values(%s,%s,%s,%s,%s,%s,'legacy') returning id", (batch_id,payload.platform.lower(),payload.store_name,row.order_id,row.payment_time,row.order_status or '历史导入'))
                    internal_id = cur.fetchone()[0]
                    cur.execute("insert into platform_order_lines(order_id,product_id,style_id,quantity,raw_payload) values(%s,%s,%s,%s,%s)", (internal_id,row.product_id,row.style_id,row.quantity,Json(row.raw_payload)))
                    inserted += 1
                status = 'succeeded' if not errors else 'partial'
                cur.execute("update data_import_batches set status=%s,error_count=%s,error_message=%s,completed_at=now() where id=%s", (status,len(errors),'; '.join(errors) or None,batch_id))
    return {"batch_id": str(batch_id), "status": status, "inserted": inserted, "skipped": skipped, "rows": len(payload.rows), "inventory": "历史导入不自动扣库" if payload.data_type == "orders" else "推广原始明细已保存"}


@app.post("/api/v2/imports/batches/{batch_id}/rollback")
def rollback_import_batch(batch_id: UUID, x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_user_token(x_v2_test_token, authorization)
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("select data_type,status from data_import_batches where id=%s for update", (batch_id,))
                batch = cur.fetchone()
                if not batch:
                    raise HTTPException(status_code=404, detail="导入批次不存在")
                data_type, status = batch
                if status == "rolled_back":
                    return {"batch_id": str(batch_id), "status": "rolled_back", "deleted": 0}
                if status not in {"succeeded", "partial"}:
                    raise HTTPException(status_code=409, detail=f"当前批次状态为 {status}，不能撤销")
                if data_type == "orders":
                    cur.execute("select count(*) from platform_orders where import_batch_id=%s and inventory_status not in ('legacy','not_applicable')", (batch_id,))
                    protected = int(cur.fetchone()[0])
                    if protected:
                        raise HTTPException(status_code=409, detail="该批次已有库存动作，不能直接撤销，请走库存冲销流程")
                    cur.execute("delete from platform_orders where import_batch_id=%s", (batch_id,))
                elif data_type == "promotions":
                    cur.execute("delete from promotion_metrics_daily where import_batch_id=%s", (batch_id,))
                deleted = cur.rowcount
                cur.execute("update data_import_batches set status='rolled_back',completed_at=now() where id=%s", (batch_id,))
    return {"batch_id": str(batch_id), "status": "rolled_back", "deleted": deleted}


@app.put("/api/v2/config/inventory-date")
def set_inventory_date(payload: dict[str, str], x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_user_token(x_v2_test_token, authorization)
    enabled_from = payload.get("enabled_from")
    if not enabled_from:
        raise HTTPException(status_code=400, detail="请填写库存启用日")
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("update inventory_settings set inventory_enabled_from=%s, enabled_at=now(), updated_at=now() where id=1 and is_locked=false", (enabled_from,))
            if cur.rowcount != 1:
                raise HTTPException(status_code=409, detail="库存启用日已锁定，不能修改")
        conn.commit()
    return config()


@app.get("/api/v2/items")
def list_items() -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select id, code, name, base_unit, category, safety_stock, is_active, created_at from inventory_items order by code")
            return _row_dict(cur)


@app.post("/api/v2/items")
def create_item(payload: ItemIn, x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_user_token(x_v2_test_token, authorization)
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("insert into inventory_items(code,name,base_unit,category,safety_stock) values (%s,%s,%s,%s,%s) returning id,code,name,base_unit,category,safety_stock,is_active,created_at", (payload.code, payload.name, payload.base_unit, payload.category, payload.safety_stock))
            except psycopg.errors.UniqueViolation:
                raise HTTPException(status_code=409, detail="单品编码已存在")
            result = _row_dict(cur)[0]
        conn.commit()
    return result


@app.get("/api/v2/bundles")
def list_bundles() -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                select b.id, b.code, b.name, b.estimated_shipping_fee, b.is_active,
                       v.version_no, v.effective_from,
                       coalesce(jsonb_agg(jsonb_build_object('item_code', i.code, 'item_name', i.name, 'quantity', bc.quantity) order by i.code) filter (where i.id is not null), '[]') components
                from bundles b left join lateral (select * from bundle_versions where bundle_id=b.id order by version_no desc limit 1) v on true
                left join bundle_components bc on bc.bundle_version_id=v.id left join inventory_items i on i.id=bc.item_id
                group by b.id,b.code,b.name,b.estimated_shipping_fee,b.is_active,v.version_no,v.effective_from order by b.code
            """)
            return _row_dict(cur)


@app.post("/api/v2/bundles")
def create_bundle(payload: BundleIn, x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_user_token(x_v2_test_token, authorization)
    with psycopg.connect(DATABASE_URL) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("insert into bundles(code,name,estimated_shipping_fee) values(%s,%s,%s) returning id", (payload.code,payload.name,payload.estimated_shipping_fee))
                bundle_id = cur.fetchone()[0]
                cur.execute("insert into bundle_versions(bundle_id,version_no,effective_from) values(%s,1,%s) returning id", (bundle_id,payload.effective_from))
                version_id = cur.fetchone()[0]
                for component in payload.components:
                    cur.execute("insert into bundle_components(bundle_version_id,item_id,quantity) values(%s,%s,%s)", (version_id,_item_id(cur,component.item_code),component.quantity))
            conn.commit()
        except psycopg.errors.UniqueViolation:
            conn.rollback()
            raise HTTPException(status_code=409, detail="组合编码或版本已存在")
    return {"id": str(bundle_id), "version_id": str(version_id), "code": payload.code}


class BundleUpdateIn(BaseModel):
    name: str | None = None
    estimated_shipping_fee: float | None = None


@app.patch("/api/v2/bundles/{bundle_code}")
def update_bundle(bundle_code: str, payload: BundleUpdateIn, x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """更新组合基础属性（名称/预估快递费），不触碰 BOM 版本。"""
    _require_user_token(x_v2_test_token, authorization)
    if payload.name is None and payload.estimated_shipping_fee is None:
        raise HTTPException(status_code=400, detail="没有要更新的字段")
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            if payload.name is not None:
                cur.execute("update bundles set name=%s, updated_at=now() where code=%s and is_active=true", (payload.name, bundle_code))
            if payload.estimated_shipping_fee is not None:
                if payload.estimated_shipping_fee < 0:
                    raise HTTPException(status_code=400, detail="快递费不能为负")
                cur.execute("update bundles set estimated_shipping_fee=%s, updated_at=now() where code=%s and is_active=true", (Decimal(str(payload.estimated_shipping_fee)), bundle_code))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"组合不存在：{bundle_code}")
        conn.commit()
    return {"code": bundle_code, "status": "updated"}


@app.get("/api/v2/listings")
def list_listings() -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select m.id,m.platform,m.store_name,m.product_id,m.style_id,b.code bundle_code,m.effective_from,m.effective_to from platform_listing_mappings m join bundles b on b.id=m.bundle_id order by m.platform,m.store_name,m.product_id")
            return _row_dict(cur)


@app.post("/api/v2/listings")
def create_listing(payload: ListingMappingIn, x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_user_token(x_v2_test_token, authorization)
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("select id from bundles where code=%s and is_active=true", (payload.bundle_code,))
                bundle = cur.fetchone()
                if not bundle:
                    raise HTTPException(status_code=400, detail=f"组合不存在：{payload.bundle_code}")
                try:
                    cur.execute("insert into platform_listing_mappings(platform,store_name,product_id,style_id,bundle_id,effective_from,effective_to) values(%s,%s,%s,%s,%s,%s,%s) returning id", (payload.platform, payload.store_name, payload.product_id, payload.style_id, bundle[0], payload.effective_from, payload.effective_to))
                    mapping_id = cur.fetchone()[0]
                except psycopg.errors.UniqueViolation:
                    raise HTTPException(status_code=409, detail="该链接映射已存在")
    return {"id": str(mapping_id), "status": "created"}


@app.get("/api/v2/costs/bundles")
def list_bundle_costs() -> list[dict[str, Any]]:
    """组合成本（只读）：产品成本 = Σ组件×各仓存量加权均价，无库存回退最新成本版本；物流成本 = 预估快递费。"""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                select b.code bundle_code, b.name bundle_name, b.estimated_shipping_fee,
                       coalesce(sum(bc.quantity * ic.unit_cost), 0) as product_cost
                from bundles b
                left join lateral (
                    select * from bundle_versions where bundle_id = b.id and status = 'active'
                    order by version_no desc limit 1
                ) bv on true
                left join bundle_components bc on bc.bundle_version_id = bv.id
                left join lateral (
                    select coalesce(
                        (select sum(ib.sellable_qty * ib.average_unit_cost) / nullif(sum(ib.sellable_qty), 0)
                         from inventory_balances ib where ib.item_id = bc.item_id),
                        (select cv.unit_cost from item_cost_versions cv where cv.item_id = bc.item_id
                         order by cv.effective_from desc, cv.created_at desc limit 1),
                        0
                    ) as unit_cost
                ) ic on true
                where b.is_active = true
                group by b.id, b.code, b.name, b.estimated_shipping_fee
                order by b.code
            """)
            return _row_dict(cur)


@app.get("/api/v2/costs/unmapped")
def list_unmapped_listings() -> dict[str, Any]:
    """未映射链接治理（只读）：订单里出现但没有链接映射的 product_id 组合。"""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                select o.platform, o.store_name, l.product_id,
                       max(l.raw_payload->>'product_name') as product_name,
                       l.style_id,
                       max(l.raw_payload->>'style_name') as style_name,
                       count(distinct o.order_id) as order_count,
                       min(o.payment_time::date) as first_date
                from platform_order_lines l
                join platform_orders o on o.id = l.order_id
                where not exists (
                    select 1 from platform_listing_mappings m
                    where m.platform = o.platform and m.store_name = o.store_name
                      and m.product_id = l.product_id
                      and coalesce(m.style_id, '') = coalesce(l.style_id, '')
                )
                group by o.platform, o.store_name, l.product_id, l.style_id
                order by order_count desc
            """)
            rows = _row_dict(cur)
            return {"rows": rows, "total": len(rows)}


@app.get("/api/v2/inventory/balances")
def list_balances() -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""with out7 as (select warehouse_id,item_id,sum(-quantity) out_qty from inventory_transactions where transaction_type='other_out' and (occurred_at at time zone 'Asia/Shanghai')::date between (now() at time zone 'Asia/Shanghai')::date - 7 and (now() at time zone 'Asia/Shanghai')::date - 1 group by warehouse_id,item_id) select w.code warehouse_code,w.name warehouse_name,i.code item_code,i.name item_name,ib.sellable_qty,ib.average_unit_cost,ib.total_average_cost,ib.updated_at,round(coalesce(o.out_qty,0)/7.0,4) avg_daily_out,round(coalesce(o.out_qty,0)/7.0*3,4) threshold_qty from inventory_balances ib join warehouses w on w.id=ib.warehouse_id join inventory_items i on i.id=ib.item_id left join out7 o on o.warehouse_id=ib.warehouse_id and o.item_id=ib.item_id order by w.code,i.code""")
            return _row_dict(cur)


@app.get("/api/v2/inventory/batches")
def list_batches(status: str | None = None) -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""select b.id,b.batch_no,w.code warehouse_code,i.code item_code,b.received_qty,b.remaining_qty,b.unit_cost,b.stock_status,b.received_at from inventory_batches b join warehouses w on w.id=b.warehouse_id join inventory_items i on i.id=b.item_id where (%s::varchar is null or b.stock_status=%s::varchar) order by w.code,i.code,b.received_at,b.id""", (status,status))
            return _row_dict(cur)


@app.get("/api/v2/inventory/ledger")
def list_ledger(
    limit: int = 200,
    offset: int = 0,
    start_date: date | None = None,
    end_date: date | None = None,
    warehouse: str | None = None,
    item_code: str | None = None,
    transaction_type: str | None = None,
    biz_type: str | None = None,
) -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""select t.id,t.transaction_type,t.biz_type,w.code warehouse_code,i.code item_code,t.quantity,t.batch_unit_cost,t.average_unit_cost,t.reference_type,t.reference_id,t.occurred_at from inventory_transactions t join warehouses w on w.id=t.warehouse_id join inventory_items i on i.id=t.item_id where (%s::date is null or (t.occurred_at at time zone 'Asia/Shanghai')::date >= %s::date) and (%s::date is null or (t.occurred_at at time zone 'Asia/Shanghai')::date <= %s::date) and (%s::varchar is null or w.code = upper(%s::varchar) or w.name = %s::varchar) and (%s::varchar is null or i.code = %s::varchar) and (%s::varchar is null or t.transaction_type = %s::varchar) and (%s::varchar is null or t.biz_type = %s::varchar) order by t.occurred_at desc limit %s offset %s""", (start_date, start_date, end_date, end_date, warehouse, warehouse, warehouse, item_code, item_code, transaction_type, transaction_type, biz_type, biz_type, min(limit, 1000), max(offset, 0)))
            return _row_dict(cur)


@app.get("/api/v2/inventory/inbound-docs")
def list_inbound_docs(
    start_date: date | None = None,
    end_date: date | None = None,
    warehouse: str | None = None,
    biz_type: str | None = None,
) -> list[dict[str, Any]]:
    """入库单报表（只读）：把入库流水按单号聚合，含网店管家导入的采购入库/其它入库单。"""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                select t.reference_id as doc_no,
                       coalesce(t.biz_type, '未标注类型') as biz_type,
                       w.code as warehouse_code, w.name as warehouse_name,
                       min((t.occurred_at at time zone 'Asia/Shanghai')::date) as doc_date,
                       count(distinct t.item_id) as line_count,
                       sum(t.quantity) as total_qty,
                       coalesce(sum(t.quantity * t.batch_unit_cost), 0) as total_amount
                from inventory_transactions t
                join warehouses w on w.id = t.warehouse_id
                where t.quantity > 0 and t.reference_id <> ''
                  and (%s::date is null or (t.occurred_at at time zone 'Asia/Shanghai')::date >= %s::date)
                  and (%s::date is null or (t.occurred_at at time zone 'Asia/Shanghai')::date <= %s::date)
                  and (%s::varchar is null or w.code = upper(%s::varchar) or w.name = %s::varchar)
                  and (%s::varchar is null or t.biz_type = %s::varchar)
                group by t.reference_id, coalesce(t.biz_type, '未标注类型'), w.code, w.name
                order by doc_date desc, t.reference_id
                limit 2000
            """, (start_date, start_date, end_date, end_date, warehouse, warehouse, warehouse, biz_type, biz_type))
            return _row_dict(cur)


@app.get("/api/v2/inventory/batches/{batch_id}/usage")
def get_batch_usage(batch_id: str) -> dict[str, Any]:
    """批次出入库明细（只读）：批次信息 + 全部出入库流水，追溯每批货出给了哪些单。"""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                select b.id, b.batch_no, w.code warehouse_code, w.name warehouse_name, i.code item_code, i.name item_name,
                       b.received_qty, b.remaining_qty, b.unit_cost, b.stock_status, b.received_at
                from inventory_batches b
                join warehouses w on w.id = b.warehouse_id
                join inventory_items i on i.id = b.item_id
                where b.id = %s
            """, (batch_id,))
            rows = _row_dict(cur)
            if not rows:
                raise HTTPException(status_code=404, detail="批次不存在")
            cur.execute("""
                select t.transaction_type, t.biz_type, t.quantity, t.batch_unit_cost, t.reference_type, t.reference_id,
                       t.store_name, t.sale_amount, t.occurred_at
                from inventory_transactions t
                where t.batch_id = %s
                order by t.occurred_at
                limit 1000
            """, (batch_id,))
            return {"batch": rows[0], "transactions": _row_dict(cur)}


@app.get("/api/v2/inventory/sales-by-store")
def sales_by_store(
    group_by: str = "store",
    start_date: date | None = None,
    end_date: date | None = None,
    store: str | None = None,
) -> list[dict[str, Any]]:
    """店铺销售报表（只读，实际发货口径）：基于出库流水的店铺与销售金额聚合。
    group_by=store 按店铺汇总；group_by=day 按店铺按天。销量/成本为批次成本口径，销售额为网店管家出库金额。"""
    if group_by not in {"store", "day", "store_item"}:
        raise HTTPException(status_code=400, detail="group_by 只能是 store、day 或 store_item")
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            if group_by == "store":
                cur.execute("""
                    select coalesce(t.store_name, '未标注店铺') as store_name,
                           sum(-t.quantity) as out_qty,
                           coalesce(sum(t.sale_amount), 0) as sale_amount,
                           coalesce(sum(-t.quantity * t.batch_unit_cost), 0) as cost_amount
                    from inventory_transactions t
                    where t.transaction_type = 'other_out'
                      and (%s::date is null or (t.occurred_at at time zone 'Asia/Shanghai')::date >= %s::date)
                      and (%s::date is null or (t.occurred_at at time zone 'Asia/Shanghai')::date <= %s::date)
                      and (%s::varchar is null or t.store_name = %s::varchar)
                    group by 1
                    order by sale_amount desc
                """, (start_date, start_date, end_date, end_date, store, store))
            elif group_by == "store_item":
                cur.execute("""
                    select coalesce(t.store_name, '未标注店铺') as store_name,
                           i.code as item_code, i.name as item_name,
                           sum(-t.quantity) as out_qty,
                           coalesce(sum(t.sale_amount), 0) as sale_amount,
                           coalesce(sum(-t.quantity * t.batch_unit_cost), 0) as cost_amount
                    from inventory_transactions t
                    join inventory_items i on i.id = t.item_id
                    where t.transaction_type = 'other_out'
                      and (%s::date is null or (t.occurred_at at time zone 'Asia/Shanghai')::date >= %s::date)
                      and (%s::date is null or (t.occurred_at at time zone 'Asia/Shanghai')::date <= %s::date)
                      and (%s::varchar is null or t.store_name = %s::varchar)
                    group by 1, 2, 3
                    order by sale_amount desc
                    limit 5000
                """, (start_date, start_date, end_date, end_date, store, store))
            else:
                cur.execute("""
                    select (t.occurred_at at time zone 'Asia/Shanghai')::date as period,
                           coalesce(t.store_name, '未标注店铺') as store_name,
                           sum(-t.quantity) as out_qty,
                           coalesce(sum(t.sale_amount), 0) as sale_amount,
                           coalesce(sum(-t.quantity * t.batch_unit_cost), 0) as cost_amount
                    from inventory_transactions t
                    where t.transaction_type = 'other_out'
                      and (%s::date is null or (t.occurred_at at time zone 'Asia/Shanghai')::date >= %s::date)
                      and (%s::date is null or (t.occurred_at at time zone 'Asia/Shanghai')::date <= %s::date)
                      and (%s::varchar is null or t.store_name = %s::varchar)
                    group by 1, 2
                    order by 1, 2
                """, (start_date, start_date, end_date, end_date, store, store))
            return _row_dict(cur)


@app.get("/api/v2/inventory/ledger/biz-types")
def list_ledger_biz_types(direction: str | None = None) -> list[str]:
    """台账中出现过的业务类型（入库原因/出库类型等原始值），供筛选下拉。direction=in 看出库为负，out 看出库。"""
    sign = ""
    if direction == "in":
        sign = "and t.quantity > 0"
    elif direction == "out":
        sign = "and t.quantity < 0"
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(f"select distinct t.biz_type from inventory_transactions t where t.biz_type is not null {sign} order by 1")
            return [row[0] for row in cur.fetchall()]


@app.get("/api/v2/inventory/ledger/summary")
def ledger_summary(
    group_by: str = "day",
    start_date: date | None = None,
    end_date: date | None = None,
    warehouse: str | None = None,
    item_code: str | None = None,
) -> list[dict[str, Any]]:
    """按天/按月汇总的库存台账：期初/入库/出库/结存（数量+金额，金额按批次成本口径）。"""
    if group_by not in {"day", "month"}:
        raise HTTPException(status_code=400, detail="group_by 只能是 day 或 month")
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                with base as (
                    select t.quantity, t.batch_unit_cost,
                           (t.occurred_at at time zone 'Asia/Shanghai') as local_ts,
                           w.code as warehouse_code, w.name as warehouse_name,
                           i.code as item_code, i.name as item_name
                    from inventory_transactions t
                    join warehouses w on w.id = t.warehouse_id
                    join inventory_items i on i.id = t.item_id
                    where (%s::varchar is null or w.code = upper(%s::varchar) or w.name = %s::varchar)
                      and (%s::varchar is null or i.code = %s::varchar)
                ),
                agg as (
                    select date_trunc(%s, local_ts)::date as period,
                           warehouse_code, warehouse_name, item_code, item_name,
                           coalesce(sum(quantity) filter (where quantity > 0), 0) as in_qty,
                           coalesce(sum(quantity * batch_unit_cost) filter (where quantity > 0), 0) as in_amount,
                           coalesce(-sum(quantity) filter (where quantity < 0), 0) as out_qty,
                           coalesce(-sum(quantity * batch_unit_cost) filter (where quantity < 0), 0) as out_amount,
                           sum(quantity) as net_qty,
                           sum(quantity * batch_unit_cost) as net_amount
                    from base
                    where (%s::date is null or local_ts::date >= %s::date)
                      and (%s::date is null or local_ts::date <= %s::date)
                    group by 1, warehouse_code, warehouse_name, item_code, item_name
                )
                select a.period, a.warehouse_code, a.warehouse_name, a.item_code, a.item_name,
                       coalesce((select sum(b.quantity) from base b where b.warehouse_code = a.warehouse_code and b.item_code = a.item_code and b.local_ts < a.period), 0) as opening_qty,
                       coalesce((select sum(b.quantity * b.batch_unit_cost) from base b where b.warehouse_code = a.warehouse_code and b.item_code = a.item_code and b.local_ts < a.period), 0) as opening_amount,
                       a.in_qty, a.in_amount, a.out_qty, a.out_amount,
                       coalesce((select sum(b.quantity) from base b where b.warehouse_code = a.warehouse_code and b.item_code = a.item_code and b.local_ts < a.period), 0) + a.net_qty as closing_qty,
                       coalesce((select sum(b.quantity * b.batch_unit_cost) from base b where b.warehouse_code = a.warehouse_code and b.item_code = a.item_code and b.local_ts < a.period), 0) + a.net_amount as closing_amount
                from agg a
                order by a.period desc, a.warehouse_code, a.item_code
                limit 5000
            """, (warehouse, warehouse, warehouse, item_code, item_code, group_by, start_date, start_date, end_date, end_date))
            return _row_dict(cur)


@app.get("/api/v2/inventory/ledger/summary/export")
def ledger_summary_export(
    group_by: str = "day",
    start_date: date | None = None,
    end_date: date | None = None,
    warehouse: str | None = None,
    item_code: str | None = None,
) -> Response:
    """台账汇总导出 Excel（只读）：与 ledger/summary 同参数、同口径。"""
    from openpyxl import Workbook

    rows = ledger_summary(group_by=group_by, start_date=start_date, end_date=end_date, warehouse=warehouse, item_code=item_code)
    wb = Workbook()
    ws = wb.active
    ws.title = "台账汇总"
    headers = ["期间", "仓库", "单品编码", "单品名称", "期初数量", "期初金额", "入库数量", "入库金额", "出库数量", "出库金额", "结存数量", "结存金额"]
    ws.append(headers)
    money_cols = {6, 8, 10, 12}
    for r in rows:
        ws.append([
            str(r["period"]), r["warehouse_name"] or r["warehouse_code"], r["item_code"], r["item_name"],
            float(r["opening_qty"]), float(r["opening_amount"]), float(r["in_qty"]), float(r["in_amount"]),
            float(r["out_qty"]), float(r["out_amount"]), float(r["closing_qty"]), float(r["closing_amount"]),
        ])
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.number_format = "#,##0.00" if cell.column in money_cols else "#,##0"
    for idx, width in enumerate([12, 14, 20, 28, 10, 12, 10, 12, 10, 12, 10, 12], start=1):
        ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = width
    buf = io.BytesIO()
    wb.save(buf)
    filename = f"台账汇总_{start_date or 'all'}_{end_date or 'all'}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@app.post("/api/v2/inventory/adjustments")
def create_inventory_adjustment(payload: InventoryAdjustmentIn, x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """支持其它入库/其它出库，所有变更都落库存台账。"""
    _require_user_token(x_v2_test_token, authorization)
    if payload.transaction_type not in {"other_in", "other_out"}:
        raise HTTPException(status_code=400, detail="只支持 other_in 或 other_out")
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                warehouse_id = _warehouse_id(cur, payload.warehouse_code)
                item_id = _item_id(cur, payload.item_code)
                cur.execute("select sellable_qty, total_average_cost, average_unit_cost from inventory_balances where warehouse_id=%s and item_id=%s for update", (warehouse_id, item_id))
                bal = cur.fetchone()
                available = Decimal(bal[0]) if bal else Decimal("0")
                average = Decimal(bal[2]) if bal else Decimal("0")
                if payload.transaction_type == "other_out" and available < payload.quantity:
                    raise HTTPException(status_code=409, detail=f"库存不足，可用 {available}，需要 {payload.quantity}")
                if payload.transaction_type == "other_in":
                    batch_no = payload.batch_no or f"OTHER-IN-{payload.reference_id}"
                    cur.execute("insert into inventory_batches(warehouse_id,item_id,batch_no,received_at,received_qty,remaining_qty,unit_cost) values(%s,%s,%s,now(),%s,%s,%s) returning id", (warehouse_id, item_id, batch_no, payload.quantity, payload.quantity, payload.unit_cost))
                    batch_id = cur.fetchone()[0]
                    new_total = (Decimal(bal[1]) if bal else Decimal("0")) + payload.quantity * payload.unit_cost
                    cur.execute("insert into inventory_balances(warehouse_id,item_id,sellable_qty,total_average_cost) values(%s,%s,%s,%s) on conflict(warehouse_id,item_id) do update set sellable_qty=inventory_balances.sellable_qty+excluded.sellable_qty,total_average_cost=inventory_balances.total_average_cost+excluded.total_average_cost,updated_at=now()", (warehouse_id, item_id, payload.quantity, payload.quantity * payload.unit_cost))
                    cur.execute("insert into inventory_transactions(warehouse_id,item_id,batch_id,transaction_type,quantity,batch_unit_cost,average_unit_cost,reference_type,reference_id,idempotency_key,occurred_at,biz_type) values(%s,%s,%s,'other_in',%s,%s,%s,'adjustment',%s,%s,now(),'其它入库')", (warehouse_id, item_id, batch_id, payload.quantity, payload.unit_cost, new_total / (available + payload.quantity) if available + payload.quantity else payload.unit_cost, payload.reference_id, f"other_in:{payload.reference_id}:{payload.item_code}"))
                else:
                    remaining = payload.quantity
                    cur.execute("select id,remaining_qty,unit_cost from inventory_batches where warehouse_id=%s and item_id=%s and stock_status='sellable' and remaining_qty>0 order by received_at,id for update", (warehouse_id, item_id))
                    for batch_id, batch_qty, batch_cost in cur.fetchall():
                        take = min(Decimal(batch_qty), remaining)
                        remaining -= take
                        cur.execute("update inventory_batches set remaining_qty=remaining_qty-%s where id=%s", (take, batch_id))
                        cur.execute("insert into inventory_transactions(warehouse_id,item_id,batch_id,transaction_type,quantity,batch_unit_cost,average_unit_cost,reference_type,reference_id,idempotency_key,occurred_at,biz_type) values(%s,%s,%s,'other_out',%s,%s,%s,'adjustment',%s,%s,now(),'其它出库')", (warehouse_id, item_id, batch_id, -take, batch_cost, average, payload.reference_id, f"other_out:{payload.reference_id}:{payload.item_code}:{batch_id}"))
                        if remaining <= 0:
                            break
                    cur.execute("update inventory_balances set sellable_qty=sellable_qty-%s,total_average_cost=greatest(0,total_average_cost-%s),updated_at=now() where warehouse_id=%s and item_id=%s", (payload.quantity, payload.quantity * average, warehouse_id, item_id))
    return {"reference_id": payload.reference_id, "transaction_type": payload.transaction_type, "quantity": str(payload.quantity)}


@app.post("/api/v2/inventory/opening")
def create_opening(payload: OpeningIn, x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_user_token(x_v2_test_token, authorization)
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                warehouse_id = _warehouse_id(cur, payload.warehouse_code); item_id = _item_id(cur, payload.item_code)
                batch_id = uuid4()
                cur.execute("insert into inventory_batches(id,warehouse_id,item_id,batch_no,received_at,received_qty,remaining_qty,unit_cost) values(%s,%s,%s,%s,now(),%s,%s,%s) returning id", (batch_id,warehouse_id,item_id,payload.batch_no,payload.quantity,payload.quantity,payload.unit_cost))
                cur.execute("insert into inventory_balances(warehouse_id,item_id,sellable_qty,total_average_cost) values(%s,%s,%s,%s) on conflict(warehouse_id,item_id) do update set sellable_qty=inventory_balances.sellable_qty+excluded.sellable_qty,total_average_cost=inventory_balances.total_average_cost+excluded.total_average_cost,updated_at=now()", (warehouse_id,item_id,payload.quantity,payload.quantity*payload.unit_cost))
                cur.execute("insert into inventory_transactions(warehouse_id,item_id,batch_id,transaction_type,quantity,batch_unit_cost,average_unit_cost,reference_type,reference_id,idempotency_key,occurred_at,biz_type) values(%s,%s,%s,'opening',%s,%s,%s,'opening',%s,%s,now(),'期初')", (warehouse_id,item_id,batch_id,payload.quantity,payload.unit_cost,payload.unit_cost,payload.batch_no,f"opening:{payload.warehouse_code}:{payload.item_code}:{payload.batch_no}"))
    return {"batch_id": str(batch_id), "status": "created"}


@app.get("/api/v2/purchases")
def list_purchases() -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select p.id,p.receipt_no,w.code warehouse_code,p.supplier_name,p.status,p.purchase_amount,p.freight_fee,p.other_fee,p.received_at,p.approved_at,p.created_at from purchase_receipts p join warehouses w on w.id=p.warehouse_id order by p.created_at desc")
            return _row_dict(cur)


@app.post("/api/v2/purchases")
def create_purchase(payload: PurchaseIn, x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_user_token(x_v2_test_token, authorization)
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                warehouse_id = _warehouse_id(cur,payload.warehouse_code)
                amount = sum((line.line_amount for line in payload.lines), Decimal("0"))
                cur.execute("insert into purchase_receipts(receipt_no,warehouse_id,supplier_name,purchase_amount,freight_fee,other_fee,status,created_by) values(%s,%s,%s,%s,%s,%s,'pending','test') returning id", (payload.receipt_no,warehouse_id,payload.supplier_name,amount,payload.freight_fee,payload.other_fee))
                receipt_id=cur.fetchone()[0]
                for line in payload.lines:
                    cur.execute("insert into purchase_receipt_lines(receipt_id,item_id,batch_no,quantity,base_unit_cost,line_amount) values(%s,%s,%s,%s,%s,%s)", (receipt_id,_item_id(cur,line.item_code),line.batch_no,line.quantity,line.base_unit_cost,line.line_amount))
    return {"receipt_no": payload.receipt_no, "status": "pending"}


@app.post("/api/v2/purchases/{receipt_no}/approve")
def approve_purchase(receipt_no: str, x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_user_token(x_v2_test_token, authorization)
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("select id,warehouse_id,purchase_amount,freight_fee,other_fee,status from purchase_receipts where receipt_no=%s for update",(receipt_no,)); receipt=cur.fetchone()
                if not receipt: raise HTTPException(status_code=404,detail="采购单不存在")
                if receipt[5] != 'pending': raise HTTPException(status_code=409,detail="采购单不是待审核状态")
                receipt_id,warehouse_id,purchase_amount,freight_fee,other_fee,_=receipt
                cur.execute("select l.id,l.item_id,l.batch_no,l.quantity,l.base_unit_cost,l.line_amount,i.code from purchase_receipt_lines l join inventory_items i on i.id=l.item_id where l.receipt_id=%s order by l.id",(receipt_id,)); lines=cur.fetchall()
                total_fee=Decimal(freight_fee)+Decimal(other_fee)
                for line_id,item_id,batch_no,qty,base_cost,line_amount,item_code in lines:
                    landed=Decimal(base_cost)+(Decimal(line_amount)/Decimal(purchase_amount)*total_fee if purchase_amount else Decimal('0'))
                    cur.execute("insert into inventory_batches(warehouse_id,item_id,batch_no,received_at,received_qty,remaining_qty,unit_cost) values(%s,%s,%s,now(),%s,%s,%s) returning id",(warehouse_id,item_id,batch_no,qty,qty,landed)); batch_id=cur.fetchone()[0]
                    cur.execute("update purchase_receipt_lines set landed_unit_cost=%s where id=%s",(landed,line_id))
                    cur.execute("insert into inventory_balances(warehouse_id,item_id,sellable_qty,total_average_cost) values(%s,%s,%s,%s) on conflict(warehouse_id,item_id) do update set sellable_qty=inventory_balances.sellable_qty+excluded.sellable_qty,total_average_cost=inventory_balances.total_average_cost+excluded.total_average_cost,updated_at=now()",(warehouse_id,item_id,qty,Decimal(qty)*landed))
                    cur.execute("insert into inventory_transactions(warehouse_id,item_id,batch_id,transaction_type,quantity,batch_unit_cost,average_unit_cost,reference_type,reference_id,idempotency_key,occurred_at,biz_type) values(%s,%s,%s,'purchase',%s,%s,%s,'purchase',%s,%s,now(),'采购入库')",(warehouse_id,item_id,batch_id,qty,landed,landed,receipt_no,f"purchase:{receipt_no}:{batch_no}"))
                cur.execute("update purchase_receipts set status='approved',approved_at=now(),approved_by='test',received_at=now(),updated_at=now() where id=%s",(receipt_id,))
    return {"receipt_no": receipt_no, "status": "approved"}


@app.get("/api/v2/exceptions")
def list_exceptions() -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select e.id,e.order_id,w.code warehouse_code,i.code item_code,e.requested_qty,e.available_qty,e.status,e.created_at from inventory_exceptions e join warehouses w on w.id=e.warehouse_id join inventory_items i on i.id=e.item_id order by e.created_at desc")
            return _row_dict(cur)


@app.get("/api/v2/orders")
def list_orders() -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select o.order_id,o.platform,o.store_name,o.payment_time,o.order_status,o.inventory_status,o.created_at from platform_orders o order by o.payment_time desc nulls last limit 500")
            return _row_dict(cur)


@app.get("/api/v2/orders/{order_id}/cost")
def get_order_cost(order_id: str) -> dict[str, Any]:
    """订单成本快照查询（只读）：快照头 + 按单品展开的成本行。"""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select s.order_id,s.platform,s.store_name,w.code warehouse_code,b.code bundle_code,s.bom_version_id,s.product_cost,s.shipping_fee,s.total_cost,s.average_cost_as_of from order_cost_snapshots s join warehouses w on w.id=s.warehouse_id left join bundles b on b.id=s.bundle_id where s.order_id=%s", (order_id,))
            rows = _row_dict(cur)
            if not rows: raise HTTPException(status_code=404, detail="订单无成本快照")
            cur.execute("select i.code item_code,i.name item_name,b.code bundle_code,l.bom_version_id,l.quantity,l.average_unit_cost,l.product_cost,l.shipping_fee from order_cost_snapshot_lines l join inventory_items i on i.id=l.item_id left join bundles b on b.id=l.bundle_id where l.order_id=%s order by i.code", (order_id,))
            return {"snapshot": rows[0], "lines": _row_dict(cur)}


@app.get("/api/v2/items/{item_code}/cost-versions")
def list_item_cost_versions(item_code: str) -> list[dict[str, Any]]:
    """单品成本版本历史（只读）。"""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select v.id,w.code warehouse_code,v.unit_cost,v.effective_from,v.effective_to,v.source_type,v.source_id,v.created_at from item_cost_versions v join inventory_items i on i.id=v.item_id join warehouses w on w.id=v.warehouse_id where i.code=%s order by v.effective_from desc,v.created_at desc", (item_code,))
            return _row_dict(cur)


@app.get("/api/v2/inventory/alerts")
def inventory_alerts(stagnant_days: int = 30) -> dict[str, Any]:
    """库存预警（只读）+ 开放异常计数。

    低库存：可售库存 < 近7天日均出库量 × 3天（即撑不过3天）。
    呆滞库存：可售天数 > stagnant_days（默认30天）或近7天完全无出库且仍有库存。
    出库口径：仅统计网店管家实际出库导入（transaction_type='other_out'），
    窗口为上海时区 [今天-7, 今天-1]（不含今天，避免当天数据未导全）。
    """
    stagnant_days = max(1, min(stagnant_days, 365))
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                with out7 as (
                    select warehouse_id, item_id, sum(-quantity) as out_qty
                    from inventory_transactions
                    where transaction_type = 'other_out'
                      and (occurred_at at time zone 'Asia/Shanghai')::date
                          between (now() at time zone 'Asia/Shanghai')::date - 7
                              and (now() at time zone 'Asia/Shanghai')::date - 1
                    group by warehouse_id, item_id
                )
                select w.code warehouse_code, w.name warehouse_name, i.code item_code, i.name item_name,
                       i.base_unit, ib.sellable_qty,
                       round(o.out_qty / 7.0, 4) as avg_daily_out,
                       round(o.out_qty / 7.0 * 3, 4) as threshold_qty,
                       round(ib.sellable_qty / (o.out_qty / 7.0), 1) as days_of_stock,
                       round(o.out_qty / 7.0 * 3 - ib.sellable_qty, 4) as gap_qty,
                       ib.average_unit_cost, ib.total_average_cost
                from inventory_balances ib
                join warehouses w on w.id = ib.warehouse_id
                join inventory_items i on i.id = ib.item_id
                join out7 o on o.warehouse_id = ib.warehouse_id and o.item_id = ib.item_id
                where i.is_active and ib.sellable_qty < o.out_qty / 7.0 * 3
                order by ib.sellable_qty / (o.out_qty / 7.0) asc
            """)
            low_stock = _row_dict(cur)
            cur.execute("""
                with out7 as (
                    select warehouse_id, item_id, sum(-quantity) as out_qty
                    from inventory_transactions
                    where transaction_type = 'other_out'
                      and (occurred_at at time zone 'Asia/Shanghai')::date
                          between (now() at time zone 'Asia/Shanghai')::date - 7
                              and (now() at time zone 'Asia/Shanghai')::date - 1
                    group by warehouse_id, item_id
                )
                select w.code warehouse_code, w.name warehouse_name, i.code item_code, i.name item_name,
                       i.base_unit, ib.sellable_qty,
                       round(coalesce(o.out_qty, 0) / 7.0, 4) as avg_daily_out,
                       case when coalesce(o.out_qty, 0) > 0
                            then round(ib.sellable_qty / (o.out_qty / 7.0), 1) end as days_of_stock,
                       ib.average_unit_cost, ib.total_average_cost
                from inventory_balances ib
                join warehouses w on w.id = ib.warehouse_id
                join inventory_items i on i.id = ib.item_id
                left join out7 o on o.warehouse_id = ib.warehouse_id and o.item_id = ib.item_id
                where i.is_active and ib.sellable_qty > 0
                  and (o.out_qty is null or ib.sellable_qty / (o.out_qty / 7.0) > %s)
                order by ib.total_average_cost desc
            """, (stagnant_days,))
            stagnant = _row_dict(cur)
            cur.execute("select count(*) from inventory_exceptions where status='open'")
            return {"low_stock": low_stock, "stagnant": stagnant, "stagnant_days": stagnant_days, "open_exceptions": cur.fetchone()[0]}


@app.post("/api/v2/orders")
def import_order(payload: OrderIn, x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_user_token(x_v2_test_token, authorization)
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("select id from platform_orders where platform=%s and store_name=%s and order_id=%s",(payload.platform,payload.store_name,payload.order_id))
                if cur.fetchone(): return {"order_id":payload.order_id,"status":"duplicate"}
                warehouse_id=_warehouse_id(cur,payload.warehouse_code)
                cur.execute("insert into platform_orders(platform,store_name,order_id,payment_time,order_status,warehouse_id,inventory_status) values(%s,%s,%s,%s,%s,%s,'pending') returning id",(payload.platform,payload.store_name,payload.order_id,payload.payment_time,payload.order_status,warehouse_id)); internal_id=cur.fetchone()[0]
                requirements: dict[str, Decimal] = {}; bundle_rows=[]; shipping=Decimal('0')
                for line in payload.lines:
                    cur.execute("select b.id,b.estimated_shipping_fee,v.id from bundles b join lateral (select * from bundle_versions where bundle_id=b.id and effective_from<=%s and (effective_to is null or effective_to>=%s) order by version_no desc limit 1) v on true where b.code=%s",(payload.payment_time.date(),payload.payment_time.date(),line.bundle_code)); bundle=cur.fetchone()
                    if not bundle: raise HTTPException(status_code=400,detail=f"组合不存在或无生效 BOM：{line.bundle_code}")
                    bundle_id,fee,version_id=bundle; shipping+=Decimal(fee)*line.quantity; cur.execute("insert into platform_order_lines(order_id,bundle_id,bom_version_id,product_id,style_id,quantity,expected_shipping_fee) values(%s,%s,%s,%s,%s,%s,%s)",(internal_id,bundle_id,version_id,line.product_id,line.style_id,line.quantity,Decimal(fee)*line.quantity))
                    cur.execute("select bc.item_id,bc.quantity,i.code from bundle_components bc join inventory_items i on i.id=bc.item_id where bc.bundle_version_id=%s",(version_id,))
                    for item_id,component_qty,item_code in cur.fetchall(): requirements[item_id]=requirements.get(item_id,Decimal('0'))+Decimal(component_qty)*line.quantity; bundle_rows.append((item_id,bundle_id,version_id,Decimal(component_qty)*line.quantity))
                allocations=[]; exceptions=[]; product_cost=Decimal('0'); average_by_item: dict[Any, Decimal] = {}
                for item_id,needed in sorted(requirements.items(), key=lambda x:str(x[0])):
                    cur.execute("select sellable_qty,average_unit_cost from inventory_balances where warehouse_id=%s and item_id=%s for update",(warehouse_id,item_id)); bal=cur.fetchone(); available=Decimal(bal[0]) if bal else Decimal('0'); average=Decimal(bal[1]) if bal else Decimal('0')
                    average_by_item[item_id] = average
                    if available < needed:
                        cur.execute("insert into inventory_exceptions(order_id,warehouse_id,item_id,requested_qty,available_qty) values(%s,%s,%s,%s,%s)",(payload.order_id,warehouse_id,item_id,needed,available)); exceptions.append({"item_id":str(item_id),"requested_qty":str(needed),"available_qty":str(available)})
                    product_cost += needed*average
                if exceptions:
                    cur.execute("update platform_orders set inventory_status='exception' where id=%s",(internal_id,)); return {"order_id":payload.order_id,"inventory_status":"exception","shipping_fee":str(shipping),"product_cost":str(product_cost),"exceptions":exceptions}
                for item_id,needed in sorted(requirements.items(), key=lambda x:str(x[0])):
                    cur.execute("select average_unit_cost from inventory_balances where warehouse_id=%s and item_id=%s for update",(warehouse_id,item_id)); average=Decimal(cur.fetchone()[0])
                    cur.execute("select id,batch_no,remaining_qty,unit_cost from inventory_batches where warehouse_id=%s and item_id=%s and stock_status='sellable' and remaining_qty>0 order by received_at,id for update",(warehouse_id,item_id)); batches=cur.fetchall(); remaining=needed
                    for batch_id,batch_no,batch_qty,batch_cost in batches:
                        take=min(Decimal(batch_qty),remaining); remaining-=take
                        cur.execute("update inventory_batches set remaining_qty=remaining_qty-%s where id=%s",(take,batch_id)); cur.execute("insert into order_batch_allocations(order_id,item_id,batch_id,quantity,batch_unit_cost) values(%s,%s,%s,%s,%s)",(payload.order_id,item_id,batch_id,take,batch_cost)); cur.execute("insert into inventory_transactions(warehouse_id,item_id,batch_id,transaction_type,quantity,batch_unit_cost,average_unit_cost,reference_type,reference_id,idempotency_key,occurred_at,biz_type) values(%s,%s,%s,'sale',%s,%s,%s,'order',%s,%s,%s,'销售出库')",(warehouse_id,item_id,batch_id,-take,batch_cost,batch_cost,payload.order_id,f"sale:{payload.order_id}:{item_id}:{batch_id}",payload.payment_time));
                        if remaining<=0: break
                    cur.execute("update inventory_balances set sellable_qty=sellable_qty-%s,total_average_cost=greatest(0,total_average_cost-%s),updated_at=now() where warehouse_id=%s and item_id=%s",(needed,needed*average,warehouse_id,item_id))
                cur.execute("update platform_orders set inventory_status='deducted' where id=%s",(internal_id,)); cur.execute("insert into order_cost_snapshots(order_id,platform,store_name,warehouse_id,product_cost,shipping_fee,total_cost,average_cost_as_of) values(%s,%s,%s,%s,%s,%s,%s,%s)",(payload.order_id,payload.platform,payload.store_name,warehouse_id,product_cost,shipping,product_cost+shipping,payload.payment_time))
                for item_id, bundle_id, version_id, line_qty in bundle_rows:
                    snapshot_average = average_by_item.get(item_id, Decimal("0"))
                    cur.execute("insert into order_cost_snapshot_lines(order_id,item_id,bundle_id,bom_version_id,quantity,average_unit_cost,product_cost,shipping_fee) values(%s,%s,%s,%s,%s,%s,%s,%s) on conflict(order_id,item_id,bundle_id) do update set quantity=order_cost_snapshot_lines.quantity+excluded.quantity,product_cost=order_cost_snapshot_lines.product_cost+excluded.product_cost,shipping_fee=order_cost_snapshot_lines.shipping_fee+excluded.shipping_fee", (payload.order_id, item_id, bundle_id, version_id, line_qty, snapshot_average, line_qty * snapshot_average, Decimal("0")))
    return {"order_id":payload.order_id,"inventory_status":"deducted","shipping_fee":str(shipping),"product_cost":str(product_cost),"total_cost":str(product_cost+shipping)}


@app.post("/api/v2/orders/{order_id}/cancel")
def cancel_order(order_id: str, x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """未发货取消冲销原批次；已发货订单不允许走自动冲销。"""
    _require_user_token(x_v2_test_token, authorization)
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("select id,warehouse_id,order_status,inventory_status,is_cancelled from platform_orders where order_id=%s for update", (order_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="订单不存在")
                internal_id, warehouse_id, order_status, inventory_status, is_cancelled = row
                if is_cancelled:
                    return {"order_id": order_id, "status": "already_cancelled"}
                if str(order_status).lower() in {"已发货", "shipped", "已完成", "completed"}:
                    raise HTTPException(status_code=409, detail="已发货/已完成订单不能自动冲销，请走退货入库")
                if inventory_status == "deducted":
                    cur.execute("select item_id,batch_id,quantity,batch_unit_cost from order_batch_allocations where order_id=%s for update", (order_id,))
                    allocations = cur.fetchall()
                    for item_id, batch_id, qty, batch_cost in allocations:
                        cur.execute("update inventory_batches set remaining_qty=remaining_qty+%s where id=%s", (qty, batch_id))
                        cur.execute("select average_unit_cost from inventory_balances where warehouse_id=%s and item_id=%s for update", (warehouse_id, item_id))
                        bal = cur.fetchone()
                        average = Decimal(bal[0]) if bal else Decimal(batch_cost)
                        cur.execute("insert into inventory_balances(warehouse_id,item_id,sellable_qty,total_average_cost) values(%s,%s,%s,%s) on conflict(warehouse_id,item_id) do update set sellable_qty=inventory_balances.sellable_qty+excluded.sellable_qty,total_average_cost=inventory_balances.total_average_cost+excluded.total_average_cost,updated_at=now()", (warehouse_id, item_id, qty, Decimal(qty) * average))
                        cur.execute("insert into inventory_transactions(warehouse_id,item_id,batch_id,transaction_type,quantity,batch_unit_cost,average_unit_cost,reference_type,reference_id,idempotency_key,occurred_at,biz_type) values(%s,%s,%s,'sale_reversal',%s,%s,%s,'order_cancel',%s,%s,now(),'销售冲销')", (warehouse_id, item_id, batch_id, qty, batch_cost, average, order_id, f"sale_reversal:{order_id}:{item_id}:{batch_id}"))
                cur.execute("update platform_orders set is_cancelled=true,order_status='已取消',inventory_status=case when %s='deducted' then 'reversed' else inventory_status end,updated_at=now() where id=%s", (inventory_status, internal_id))
                cur.execute("update inventory_exceptions set status='cancelled',resolved_at=now(),resolved_by='test' where order_id=%s and status='open'", (order_id,))
    return {"order_id": order_id, "status": "cancelled", "inventory_status": "reversed" if inventory_status == "deducted" else inventory_status}


@app.get("/api/v2/returns")
def list_returns() -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select r.id,r.return_no,r.order_id,w.code warehouse_code,r.status,r.received_at,r.inspected_at,r.created_at from return_receipts r join warehouses w on w.id=r.warehouse_id order by r.created_at desc")
            return _row_dict(cur)


@app.post("/api/v2/returns")
def create_return(payload: ReturnIn, x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_user_token(x_v2_test_token, authorization)
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                warehouse_id=_warehouse_id(cur,payload.warehouse_code); item_id=_item_id(cur,payload.item_code)
                cur.execute("insert into return_receipts(return_no,order_id,warehouse_id,status,received_at,created_by) values(%s,%s,%s,'inspected',now(),'test') returning id",(payload.return_no,payload.order_id,warehouse_id)); rid=cur.fetchone()[0]
                cur.execute("insert into return_receipt_lines(return_receipt_id,item_id,quantity,target_status) values(%s,%s,%s,'inspection')",(rid,item_id,payload.quantity))
                cur.execute("insert into inventory_batches(warehouse_id,item_id,batch_no,received_at,received_qty,remaining_qty,unit_cost,stock_status) values(%s,%s,%s,now(),%s,%s,%s,'inspection') returning id",(warehouse_id,item_id,f"RETURN-{payload.return_no}",payload.quantity,payload.quantity,payload.unit_cost)); bid=cur.fetchone()[0]
                cur.execute("update return_receipt_lines set batch_id=%s where return_receipt_id=%s",(bid,rid))
    return {"return_no":payload.return_no,"status":"inspected","batch_id":str(bid)}


@app.post("/api/v2/returns/{return_no}/inspect")
def inspect_return(return_no: str, payload: ReturnInspectIn, x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_user_token(x_v2_test_token, authorization)
    if payload.target_status not in {"sellable","defective","scrapped"}: raise HTTPException(status_code=400,detail="审核状态无效")
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("select r.id, r.warehouse_id, l.item_id, l.quantity, l.batch_id from return_receipts r join return_receipt_lines l on l.return_receipt_id=r.id where r.return_no=%s for update",(return_no,)); row=cur.fetchone()
                if not row: raise HTTPException(status_code=404,detail="退货单不存在")
                rid,warehouse_id,item_id,qty,batch_id=row; cur.execute("update return_receipts set status='completed',inspected_at=now(),inspected_by='test',updated_at=now() where id=%s",(rid,)); cur.execute("update return_receipt_lines set target_status=%s where return_receipt_id=%s",(payload.target_status,rid)); cur.execute("update inventory_batches set stock_status=%s where id=%s",(payload.target_status,batch_id))
                if payload.target_status=='sellable':
                    cur.execute("select unit_cost from inventory_batches where id=%s",(batch_id,)); cost=Decimal(cur.fetchone()[0]); cur.execute("insert into inventory_balances(warehouse_id,item_id,sellable_qty,total_average_cost) values(%s,%s,%s,%s) on conflict(warehouse_id,item_id) do update set sellable_qty=inventory_balances.sellable_qty+excluded.sellable_qty,total_average_cost=inventory_balances.total_average_cost+excluded.total_average_cost,updated_at=now()",(warehouse_id,item_id,qty,qty*cost)); cur.execute("insert into inventory_transactions(warehouse_id,item_id,batch_id,transaction_type,quantity,batch_unit_cost,average_unit_cost,reference_type,reference_id,idempotency_key,occurred_at,biz_type) values(%s,%s,%s,'customer_return',%s,%s,%s,'return',%s,%s,now(),'退货入库')",(warehouse_id,item_id,batch_id,qty,cost,cost,return_no,f"return:{return_no}:sellable"))
    return {"return_no":return_no,"status":"completed","target_status":payload.target_status}


@app.post("/api/v2/demo/run")
def run_demo_endpoint(x_v2_test_token: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_user_token(x_v2_test_token, authorization)
    return run_workflow()

import v2.costs
app.include_router(v2.costs.router)

import v2.stock_io
app.include_router(v2.stock_io.router)

from v2 import v1_compat
app.router.routes.extend(v1_compat.router.routes)
