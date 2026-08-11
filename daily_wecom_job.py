"""Generate and send the PDD daily report from a server-side scheduled job."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from config_manager import get_config_defaults
from report_builder import build_daily_report
from services import preview_wecom_report_service, send_wecom_report_service
from wecom import load_wecom_config


DATA_DIR = Path("data")
STATE_FILE = DATA_DIR / "wecom_daily_job_state.json"
LOCK_FILE = DATA_DIR / "wecom_daily_job.lock"
LOCK_MAX_AGE_SECONDS = 3 * 60 * 60


def _load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("企微日报任务状态文件损坏，请检查后再执行") from exc


def _save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = STATE_FILE.with_suffix(".tmp")
    temp_file.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temp_file, STATE_FILE)


@contextmanager
def _job_lock() -> Iterator[None]:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(2):
        try:
            fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as lock_handle:
                lock_handle.write(
                    json.dumps(
                        {
                            "pid": os.getpid(),
                            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        }
                    )
                )
            break
        except FileExistsError:
            lock_age = datetime.datetime.now().timestamp() - LOCK_FILE.stat().st_mtime
            if attempt == 0 and lock_age > LOCK_MAX_AGE_SECONDS:
                LOCK_FILE.unlink(missing_ok=True)
                continue
            raise RuntimeError("企微日报定时任务正在运行，本次执行已取消")

    try:
        yield
    finally:
        LOCK_FILE.unlink(missing_ok=True)


def _validate_wecom_config(config: Dict[str, Any]) -> None:
    missing = [
        field
        for field in ("bot_id", "secret")
        if not str(config.get(field) or "").strip()
    ]
    chat_id = str(config.get("chat_id") or config.get("chatid") or "").strip()
    if not chat_id:
        missing.append("chat_id")
    if missing:
        raise ValueError(f"企微配置缺少必填项：{', '.join(missing)}")


def run_daily_wecom_job(
    report_date: Optional[datetime.date] = None,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Send yesterday's report once for the given report-date boundary."""
    report_date = report_date or datetime.date.today()
    report_date_text = report_date.isoformat()
    data_date_text = (report_date - datetime.timedelta(days=1)).isoformat()

    with _job_lock():
        state = _load_state()
        if dry_run:
            content = build_daily_report(report_date, ai_config=get_config_defaults())
            return {
                "status": "dry_run",
                "report_date": report_date_text,
                "data_date": data_date_text,
                "content_length": len(content),
            }

        sent_report_dates = set(state.get("sent_report_dates") or [])
        if state.get("last_report_date"):
            sent_report_dates.add(state["last_report_date"])
        if report_date_text in sent_report_dates:
            return {
                "status": "skipped",
                "reason": "already_sent",
                "report_date": report_date_text,
                "data_date": data_date_text,
            }

        config = load_wecom_config()
        _validate_wecom_config(config)
        draft = preview_wecom_report_service(report_date)
        response = send_wecom_report_service(
            report_date,
            config,
            draft["draft_id"],
        )
        sent_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        sent_report_dates.add(report_date_text)
        _save_state(
            {
                "last_report_date": report_date_text,
                "last_data_date": data_date_text,
                "last_draft_id": draft["draft_id"],
                "last_sent_at": sent_at,
                "sent_report_dates": sorted(sent_report_dates)[-90:],
            }
        )
        return {
            "status": "sent",
            "report_date": report_date_text,
            "data_date": data_date_text,
            "draft_id": draft["draft_id"],
            "sent_at": sent_at,
            "wecom_response": response,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成并发送拼多多企微日报")
    parser.add_argument(
        "--report-date",
        type=datetime.date.fromisoformat,
        help="报告日期边界 YYYY-MM-DD；默认今天，实际统计昨天数据",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只生成报告并输出长度，不发送企微消息",
    )
    args = parser.parse_args()

    try:
        result = run_daily_wecom_job(args.report_date, dry_run=args.dry_run)
    except Exception as exc:
        print(
            json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
