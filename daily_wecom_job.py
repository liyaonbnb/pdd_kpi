"""Generate and send the PDD daily report from a server-side scheduled job."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional
from zoneinfo import ZoneInfo

from config_manager import get_config_defaults
from report_builder import build_daily_report
from services import preview_wecom_report_service, send_wecom_report_service
from wecom import load_wecom_config


DATA_DIR = Path("data")
STATE_FILE = DATA_DIR / "wecom_daily_job_state.json"
LOCK_FILE = DATA_DIR / "wecom_daily_job.lock"
LOG_FILE = DATA_DIR / "wecom_daily_cron.log"
LOCK_MAX_AGE_SECONDS = 3 * 60 * 60
SCHEDULE_EXPRESSION = "30 10 * * *"
SCHEDULE_TIME = "10:30"
SCHEDULE_TIMEZONE = "Asia/Shanghai"


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


def _cron_is_enabled() -> bool:
    try:
        result = subprocess.run(
            ["/usr/bin/crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and "daily_wecom_job.py" in result.stdout


def _last_log_result() -> Dict[str, Any]:
    if not LOG_FILE.exists():
        return {}
    try:
        lines = [line.strip() for line in LOG_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
        result = json.loads(lines[-1]) if lines else {}
        if not isinstance(result, dict):
            return {}
        result["last_run_at"] = datetime.datetime.fromtimestamp(
            LOG_FILE.stat().st_mtime,
            tz=ZoneInfo(SCHEDULE_TIMEZONE),
        ).isoformat()
        return result
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def get_daily_wecom_schedule_status() -> Dict[str, Any]:
    now = datetime.datetime.now(ZoneInfo(SCHEDULE_TIMEZONE))
    next_run = now.replace(hour=10, minute=30, second=0, microsecond=0)
    if next_run <= now:
        next_run += datetime.timedelta(days=1)

    try:
        state = _load_state()
    except RuntimeError:
        state = {"last_status": "failed", "last_error": "定时任务状态文件损坏"}
    fallback = _last_log_result()
    last_status = state.get("last_status") or fallback.get("status") or "never"
    return {
        "enabled": _cron_is_enabled(),
        "schedule": SCHEDULE_EXPRESSION,
        "schedule_time": SCHEDULE_TIME,
        "timezone": SCHEDULE_TIMEZONE,
        "next_run_at": next_run.isoformat(),
        "last_status": last_status,
        "last_run_at": state.get("last_run_at") or fallback.get("last_run_at"),
        "last_report_date": state.get("last_report_date") or fallback.get("report_date"),
        "last_data_date": state.get("last_data_date") or fallback.get("data_date"),
        "last_error": state.get("last_error") or fallback.get("error"),
    }


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

        attempted_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        sent_report_dates = set(state.get("sent_report_dates") or [])
        if state.get("last_report_date") and state.get("last_status") in (None, "sent"):
            sent_report_dates.add(state["last_report_date"])
        if report_date_text in sent_report_dates:
            result = {
                "status": "skipped",
                "reason": "already_sent",
                "report_date": report_date_text,
                "data_date": data_date_text,
            }
            _save_state({
                **state,
                "last_status": "skipped",
                "last_error": None,
                "last_run_at": attempted_at,
            })
            return result

        try:
            config = load_wecom_config()
            _validate_wecom_config(config)
            draft = preview_wecom_report_service(report_date)
            response = send_wecom_report_service(
                report_date,
                config,
                draft["draft_id"],
            )
        except Exception as exc:
            _save_state({
                **state,
                "last_status": "failed",
                "last_error": str(exc),
                "last_run_at": attempted_at,
                "last_report_date": report_date_text,
                "last_data_date": data_date_text,
            })
            raise
        sent_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        sent_report_dates.add(report_date_text)
        _save_state(
            {
                "last_report_date": report_date_text,
                "last_data_date": data_date_text,
                "last_draft_id": draft["draft_id"],
                "last_sent_at": sent_at,
                "last_status": "sent",
                "last_error": None,
                "last_run_at": attempted_at,
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
