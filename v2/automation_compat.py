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

class SendRequest(BaseModel):
    report_date: date
    config: dict[str, Any]


def _build_report(report_date: date) -> dict[str, Any]:
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("""select c.platform, count(distinct c.order_id), coalesce(sum(l.line_amount),0), coalesce(sum(c.product_cost),0), coalesce(sum(c.shipping_fee),0) from order_cost_snapshots c left join platform_orders o on o.order_id=c.order_id left join platform_order_lines l on l.order_id=o.id where coalesce(o.payment_time::date,c.average_cost_as_of::date)=%s group by c.platform order by c.platform""", (report_date,))
        rows = cur.fetchall()
    platforms=[{"platform":r[0],"order_count":r[1],"gmv":float(r[2]),"product_cost":float(r[3]),"shipping_fee":float(r[4]),"profit":float(r[2]-r[3]-r[4])} for r in rows]
    return {"report_date":report_date.isoformat(),"platforms":platforms,"totals":{"order_count":sum(x["order_count"] for x in platforms),"gmv":sum(x["gmv"] for x in platforms),"product_cost":sum(x["product_cost"] for x in platforms),"shipping_fee":sum(x["shipping_fee"] for x in platforms),"profit":sum(x["profit"] for x in platforms)}}

@router.get("/schedule-status")
def schedule_status(user: dict = Depends(_require_user)):
    return {"enabled": False, "schedule": "30 10 * * *", "schedule_time": "10:30", "source": "v2", "message": "V2 任务由服务器 cron/systemd 配置后启用"}

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

