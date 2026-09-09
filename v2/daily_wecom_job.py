"""V2 原生企业微信日报任务。

用 V2 PostgreSQL 聚合生成“昨日运营日报”，并通过企微机器人发送。
安全默认：默认 dry-run，只有显式 --send 才会真正发送。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import psycopg

from wecom import load_wecom_config, send_wecom_report

DATABASE_URL = os.getenv(
    "V2_DATABASE_URL",
    "postgresql://pdd_v2_test:pdd_v2_test_local_2026@127.0.0.1:55432/pdd_v2_test",
)
DATA_DIR = Path("data")
STATE_FILE = DATA_DIR / "wecom_daily_v2_job_state.json"
LOCK_FILE = DATA_DIR / "wecom_daily_v2_job.lock"
LOG_FILE = DATA_DIR / "wecom_daily_v2_cron.log"
LOCK_MAX_AGE_SECONDS = 3 * 60 * 60
SCHEDULE_EXPRESSION = "30 10 * * *"
SCHEDULE_TIME = "10:30"
SCHEDULE_TIMEZONE = "Asia/Shanghai"


def _build_report(report_date: datetime.date) -> Dict[str, Any]:
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            """
            select c.platform,
                   count(*) as order_count,
                   coalesce(sum(oa.order_gmv), 0) as order_gmv,
                   coalesce(sum(c.product_cost), 0) as product_cost,
                   coalesce(sum(c.shipping_fee), 0) as shipping_fee
            from order_cost_snapshots c
            left join platform_orders o on o.order_id = c.order_id
            left join (
                select o2.order_id, sum(coalesce((l2.raw_payload->>'user_paid')::numeric, 0)) as order_gmv
                from platform_orders o2
                join platform_order_lines l2 on l2.order_id = o2.id
                group by o2.order_id
            ) oa on oa.order_id = c.order_id
            where coalesce(o.payment_time::date, c.average_cost_as_of::date) = %s
            group by c.platform
            order by c.platform
        """,
            (report_date,),
        )
        rows = cur.fetchall()
    platforms = [
        {
            "platform": r[0],
            "order_count": r[1],
            "gmv": float(r[2]),
            "product_cost": float(r[3]),
            "shipping_fee": float(r[4]),
            "profit": float(r[2] - r[3] - r[4]),
        }
        for r in rows
    ]
    return {
        "report_date": report_date.isoformat(),
        "platforms": platforms,
        "totals": {
            "order_count": sum(x["order_count"] for x in platforms),
            "gmv": sum(x["gmv"] for x in platforms),
            "product_cost": sum(x["product_cost"] for x in platforms),
            "shipping_fee": sum(x["shipping_fee"] for x in platforms),
            "profit": sum(x["profit"] for x in platforms),
        },
    }


def _load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = STATE_FILE.with_suffix(".tmp")
    temp_file.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
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
                            "created_at": datetime.datetime.now(
                                datetime.timezone.utc
                            ).isoformat(),
                        }
                    )
                )
            break
        except FileExistsError:
            age = datetime.datetime.now().timestamp() - LOCK_FILE.stat().st_mtime
            if attempt == 0 and age > LOCK_MAX_AGE_SECONDS:
                LOCK_FILE.unlink(missing_ok=True)
                continue
            raise RuntimeError("企微日报任务正在运行，本次执行已取消")
    try:
        yield
    finally:
        LOCK_FILE.unlink(missing_ok=True)



def _cron_is_enabled() -> bool:
    try:
        import subprocess
        result = subprocess.run(["/usr/bin/crontab", "-l"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and "v2.daily_wecom_job" in result.stdout


def get_schedule_status() -> Dict[str, Any]:
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        "enabled": _cron_is_enabled(),
        "schedule": SCHEDULE_EXPRESSION,
        "schedule_time": SCHEDULE_TIME,
        "timezone": SCHEDULE_TIMEZONE,
        "implementation": "v2.daily_wecom_job",
        "dry_run_by_default": True,
        "next_run_at": None,
        "last_status": _load_state().get("last_status", "never"),
        "last_run_at": _load_state().get("last_run_at"),
        "last_report_date": _load_state().get("last_report_date"),
        "last_data_date": _load_state().get("last_data_date"),
        "last_error": _load_state().get("last_error"),
    }


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


def _v2_report_text(report: Dict[str, Any]) -> str:
    lines = ["V2运营日报 %s" % report["report_date"]]
    for p in report["platforms"]:
        lines.append(
            "%s：订单%d，GMV %.2f，利润 %.2f"
            % (p["platform"], p["order_count"], p["gmv"], p["profit"])
        )
    t = report["totals"]
    lines.append(
        "合计：订单%d，GMV %.2f，利润 %.2f"
        % (t["order_count"], t["gmv"], t["profit"])
    )
    return "\n".join(lines)


def run_daily_wecom_job(
    report_date: Optional[datetime.date] = None,
    *,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """默认统计“昨日”数据；dry_run=True 只生成报告不发送。"""
    report_date = report_date or datetime.date.today()
    data_date = report_date - datetime.timedelta(days=1)
    report_date_text = report_date.isoformat()
    data_date_text = data_date.isoformat()

    with _job_lock():
        state = _load_state()
        attempted_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        report = _build_report(data_date)
        content = _v2_report_text(report)

        if dry_run:
            result = {
                "status": "dry_run",
                "report_date": report_date_text,
                "data_date": data_date_text,
                "content_length": len(content),
                "preview": content,
            }
            _save_state(
                {
                    **state,
                    "last_status": "dry_run",
                    "last_run_at": attempted_at,
                    "last_report_date": report_date_text,
                    "last_data_date": data_date_text,
                }
            )
            return result

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
            _save_state(
                {
                    **state,
                    "last_status": "skipped",
                    "last_error": None,
                    "last_run_at": attempted_at,
                }
            )
            return result

        try:
            config = load_wecom_config()
            _validate_wecom_config(config)
            delivery = send_wecom_report(content, config)
        except Exception as exc:
            _save_state(
                {
                    **state,
                    "last_status": "failed",
                    "last_error": str(exc),
                    "last_run_at": attempted_at,
                    "last_report_date": report_date_text,
                    "last_data_date": data_date_text,
                }
            )
            raise
        sent_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        sent_report_dates.add(report_date_text)
        _save_state(
            {
                "last_report_date": report_date_text,
                "last_data_date": data_date_text,
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
            "sent_at": sent_at,
            "delivery": delivery,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="V2 生成并发送企业微信运营日报")
    parser.add_argument(
        "--report-date",
        type=datetime.date.fromisoformat,
        help="报告日期边界 YYYY-MM-DD；默认今天，实际统计昨日数据",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只生成报告不发送（默认即此行为）",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="显式开启真实发送（需已配置企微）",
    )
    args = parser.parse_args()
    dry_run = not args.send or args.dry_run
    try:
        result = run_daily_wecom_job(args.report_date, dry_run=dry_run)
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