"""V2-native report automation endpoints.

The report is generated from V2 PostgreSQL aggregates; delivery remains an explicit
operation so scheduled jobs and the UI share the same preview/send contract.
"""
from datetime import date, timedelta
from typing import Any
import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from v2.test_api import DATABASE_URL
from v2.v1_compat import _require_user

router = APIRouter(prefix="/api/v2/automation", tags=["automation"])
legacy_router = APIRouter(prefix="/api/wecom", tags=["wecom-compat"])

class SendRequest(BaseModel):
    report_date: date
    config: dict[str, Any]


def _build_report(report_date: date) -> dict[str, Any]:
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("""
            select c.platform,
                   count(*) as order_count,
                   coalesce(sum(oa.order_gmv), 0) as order_gmv,
                   coalesce(sum(c.product_cost), 0) as product_cost,
                   coalesce(sum(c.shipping_fee), 0) as shipping_fee
            from order_cost_snapshots c
            left join platform_orders o on o.order_id = c.order_id
            left join (
                select o2.order_id, sum(l2.line_amount) as order_gmv
                from platform_orders o2
                join platform_order_lines l2 on l2.order_id = o2.id
                group by o2.order_id
            ) oa on oa.order_id = c.order_id
            where coalesce(o.payment_time::date, c.average_cost_as_of::date) = %s
            group by c.platform
            order by c.platform
        """, (report_date,))`r`n        rows = cur.fetchall()
    platforms=[{"platform":r[0],"order_count":r[1],"gmv":float(r[2]),"product_cost":float(r[3]),"shipping_fee":float(r[4]),"profit":float(r[2]-r[3]-r[4])} for r in rows]
    return {"report_date":report_date.isoformat(),"platforms":platforms,"totals":{"order_count":sum(x["order_count"] for x in platforms),"gmv":sum(x["gmv"] for x in platforms),"product_cost":sum(x["product_cost"] for x in platforms),"shipping_fee":sum(x["shipping_fee"] for x in platforms),"profit":sum(x["profit"] for x in platforms)}}

@router.get("/schedule-status")
def schedule_status(user: dict = Depends(_require_user)):
    try:
        from daily_wecom_job import get_daily_wecom_schedule_status
        status = get_daily_wecom_schedule_status()
        status["source"] = "v2"
        return status
    except Exception:
        return {"enabled": False, "schedule": "30 10 * * *", "schedule_time": "10:30", "source": "v2", "message": "任务状态暂不可读"}
@router.get("/daily/preview")
def preview(report_date: date | None = None, user: dict = Depends(_require_user)):
    return _build_report(report_date or (date.today()-timedelta(days=1)))

@router.post("/daily/send")
def send(req: SendRequest, user: dict = Depends(_require_user)):
    if user.get("role") not in {"master", "admin"}:
        raise HTTPException(status_code=403, detail="仅管理员可发送日报")
    report = _build_report(req.report_date)
    text = "V2运营日报 %s\n" % req.report_date.isoformat()
    for p in report["platforms"]:
        text += "%s：订单%d，GMV %.2f，利润 %.2f\n" % (p["platform"], p["order_count"], p["gmv"], p["profit"])
    try:
        from wecom import send_wecom_report
        result = send_wecom_report(text, req.config)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="企业微信发送失败：%s" % exc) from exc
    return {"report": report, "delivery": result}


@legacy_router.get("/schedule-status")
def legacy_schedule_status(user: dict = Depends(_require_user)):
    return schedule_status(user)

@legacy_router.post("/preview")
def legacy_preview(report_date: date, user: dict = Depends(_require_user)):
    report = _build_report(report_date)
    lines = ["V2运营日报 %s" % report["report_date"]]
    for p in report["platforms"]:
        lines.append("%s：订单%d，GMV %.2f，利润 %.2f" % (p["platform"], p["order_count"], p["gmv"], p["profit"]))
    return {"draft_id": "v2-%s" % report["report_date"], "report_date": report["report_date"], "content": "\n".join(lines), "report": report}

@legacy_router.post("/send")
def legacy_send(req: SendRequest, user: dict = Depends(_require_user)):
    return send(req, user)

@legacy_router.get("/config")
def legacy_config(user: dict = Depends(_require_user)):
    try:
        from wecom import load_wecom_config
        return load_wecom_config()
    except Exception:
        return {}

@legacy_router.post("/config")
def legacy_update_config(config: dict[str, Any], user: dict = Depends(_require_user)):
    if user.get("role") not in {"master", "admin"}:
        raise HTTPException(status_code=403, detail="仅管理员可修改企业微信配置")
    from wecom import save_wecom_config
    save_wecom_config(config)
    return config

@legacy_router.post("/listen")
def legacy_listen(payload: dict[str, Any], user: dict = Depends(_require_user)):
    from wecom import listen_wecom_chatid
    config = payload.get("config") or {}
    timeout = int(payload.get("timeout", 60))
    return listen_wecom_chatid(config, timeout)


