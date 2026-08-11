"""企业微信日报草稿持久化。

生成和发送拆成两步后，草稿必须落盘，避免 FastAPI 多 worker 之间的内存状态不一致。
"""

import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional


DATA_DIR = Path("data")
DRAFTS_FILE = DATA_DIR / "wecom_report_drafts.json"
DRAFT_TTL_SECONDS = 30 * 60
_DRAFTS_LOCK = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_all() -> Dict[str, Dict[str, Any]]:
    _ensure_dir()
    if not DRAFTS_FILE.exists():
        return {}
    try:
        data = json.loads(DRAFTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_all(drafts: Dict[str, Dict[str, Any]]) -> None:
    _ensure_dir()
    temp_path = DRAFTS_FILE.with_name(f".{DRAFTS_FILE.name}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(drafts, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, DRAFTS_FILE)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def _prune(drafts: Dict[str, Dict[str, Any]], now: datetime) -> Dict[str, Dict[str, Any]]:
    active: Dict[str, Dict[str, Any]] = {}
    for draft_id, draft in drafts.items():
        try:
            expires_at = datetime.fromisoformat(str(draft.get("expires_at", "")))
        except ValueError:
            continue
        if expires_at > now:
            active[draft_id] = draft
    return active


def create_report_draft(content: str, report_date: str, platform: str = "pdd") -> Dict[str, Any]:
    now = _now()
    draft_id = uuid.uuid4().hex
    draft = {
        "draft_id": draft_id,
        "platform": platform,
        "report_date": report_date,
        "content": content,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(),
        "sent_at": None,
    }
    with _DRAFTS_LOCK:
        drafts = _prune(_read_all(), now)
        drafts[draft_id] = draft
        _write_all(drafts)
    return draft


def get_report_draft(draft_id: str, report_date: Optional[str] = None, platform: Optional[str] = None) -> Dict[str, Any]:
    now = _now()
    with _DRAFTS_LOCK:
        stored = _read_all()
        drafts = _prune(stored, now)
        if len(drafts) != len(stored):
            _write_all(drafts)
    draft = drafts.get(str(draft_id))
    if not draft:
        raise ValueError("日报草稿不存在或已过期，请重新生成")
    if platform and draft.get("platform") != platform:
        raise ValueError("日报草稿平台不匹配，请重新生成")
    if report_date and draft.get("report_date") != report_date:
        raise ValueError("日报草稿日期已变化，请重新生成")
    if draft.get("sent_at"):
        raise ValueError("这份日报草稿已经发送过，请重新生成后再发")
    return draft


def mark_report_draft_sent(draft_id: str) -> None:
    now = _now()
    with _DRAFTS_LOCK:
        drafts = _prune(_read_all(), now)
        draft = drafts.get(str(draft_id))
        if draft:
            draft["sent_at"] = now.isoformat()
            _write_all(drafts)
