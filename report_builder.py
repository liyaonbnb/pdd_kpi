"""
企业微信汇总报告生成器
"""

import datetime
from typing import Dict, List, Optional

import pandas as pd

from ai_analyzer import generate_ai_report
from storage import list_available_stores, list_available_dates, load_daily_data
from store_manager import list_store_names
from metrics import compute_overall_kpis, aggregate_product_metrics


def _date_str(d) -> str:
    if isinstance(d, datetime.date):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, datetime.datetime):
        return d.strftime("%Y-%m-%d")
    return str(d)


def _load_store_metrics_for_range(store_name: str, start_date, end_date) -> Optional[pd.DataFrame]:
    """加载店铺在日期范围内的汇总商品指标"""
    dates = list_available_dates(store_name)
    start_s = _date_str(start_date)
    end_s = _date_str(end_date)
    selected = [d for d in dates if start_s <= d <= end_s]
    if not selected:
        return None

    dfs = []
    for d in selected:
        try:
            df, _ = load_daily_data(d, store_name)
            if df is not None and not df.empty:
                dfs.append(df)
        except Exception:
            continue
    if not dfs:
        return None
    aggregated = aggregate_product_metrics(dfs)
    return aggregated if aggregated is not None and not aggregated.empty else None


def _build_store_summary(store_name: str, report_date: datetime.date) -> Dict:
    """构建单个店铺昨日 + 本月累计摘要"""
    yesterday = report_date - datetime.timedelta(days=1)
    month_start = yesterday.replace(day=1)

    # 昨日
    yesterday_metrics = _load_store_metrics_for_range(store_name, yesterday, yesterday)
    yesterday_kpis = compute_overall_kpis(yesterday_metrics) if yesterday_metrics is not None else {}

    # 本月累计（1号到昨天）
    month_metrics = _load_store_metrics_for_range(store_name, month_start, yesterday)
    month_kpis = compute_overall_kpis(month_metrics) if month_metrics is not None else {}

    return {
        "store_name": store_name,
        "yesterday": yesterday,
        "month_start": month_start,
        "yesterday_kpis": yesterday_kpis if yesterday_metrics is not None else {},
        "month_kpis": month_kpis if month_metrics is not None else {},
        "has_yesterday_data": yesterday_metrics is not None,
        "has_month_data": month_metrics is not None,
    }


def _format_money(value: float) -> str:
    return f"{value:,.2f}"


def _format_percent(value: float) -> str:
    return f"{value:.2f}%"


def _build_ai_analysis(
    report_date: datetime.date,
    stores: List[str],
    ai_config: Dict,
) -> str:
    """基于所有拼多多店铺昨日数据生成 AI 分析，失败时返回可读提示。"""
    yesterday = report_date - datetime.timedelta(days=1)
    metrics_frames = []
    for store in stores:
        metrics = _load_store_metrics_for_range(store, yesterday, yesterday)
        if metrics is None or metrics.empty:
            continue
        metrics = metrics.copy()
        if "product_name" in metrics.columns:
            metrics["product_name"] = f"[{store}] " + metrics["product_name"].astype(str)
        metrics_frames.append(metrics)

    if not metrics_frames:
        return "暂无昨日数据，无法生成 AI 分析。"

    combined = pd.concat(metrics_frames, ignore_index=True)
    kpis = compute_overall_kpis(combined)
    result = generate_ai_report(
        kpis=kpis,
        metrics=combined,
        api_key=ai_config.get("api_key") or None,
        base_url=ai_config.get("base_url", "https://api.kimi.com/coding/v1"),
        model=ai_config.get("model", "kimi-coding"),
        temperature=ai_config.get("temperature", 1.0),
        reasoning_effort=ai_config.get("reasoning_effort", "low"),
        timeout=ai_config.get("timeout", 60),
        max_completion_tokens=ai_config.get("max_completion_tokens", 16384),
        date=f"{yesterday.strftime('%Y-%m-%d')}（全店铺）",
    )
    content = str(result.get("content") or "").strip()
    source = result.get("source") or "unknown"
    if not content:
        return "AI 分析未返回内容。"
    prefix = "（规则化兜底分析）" if source in {"rule", "rule_fallback"} else ""
    return f"{prefix}\n{content}".strip()


def build_daily_report(report_date: datetime.date = None, ai_config: Optional[Dict] = None) -> str:
    """
    构建所有店铺昨日销售汇总报告（Markdown 格式）
    """
    if report_date is None:
        report_date = datetime.date.today()

    yesterday = report_date - datetime.timedelta(days=1)
    # 日报按已注册的拼多多店铺遍历，不能因为某店铺当天没数据就从日报中消失。
    stores = list_store_names("pdd") or list_available_stores()

    lines = []
    lines.append(f"## 📊 拼多多推广日报 ({yesterday.strftime('%Y-%m-%d')})")
    lines.append("")
    lines.append(f"> 统计范围：昨日 {yesterday.strftime('%Y-%m-%d')} + 本月累计 {yesterday.replace(day=1).strftime('%Y-%m-%d')} ~ {yesterday.strftime('%Y-%m-%d')}")
    lines.append(f"> 店铺范围：拼多多已注册店铺共 {len(stores)} 家（无数据店铺保留并标注）")
    lines.append("")

    has_data = False
    for store in stores:
        summary = _build_store_summary(store, report_date)
        y = summary["yesterday_kpis"]
        m = summary["month_kpis"]
        has_data = has_data or bool(y or m)

        lines.append(f"### {store}")
        lines.append("")
        lines.append("**昨日数据**")
        if y:
            roi_status = "🟢" if y.get("real_roi", 0) >= 2.5 else ("🟡" if y.get("real_roi", 0) >= 1.5 else "🔴")
            problem_status = "🟢" if y.get("problem_rate", 0) < 20 else "🔴"
            lines.append(f"- 推广花费：¥{_format_money(y.get('promo_spend', 0))}")
            lines.append(f"- 推广 GMV：¥{_format_money(y.get('promo_gmv', 0))}")
            lines.append(f"- 有效商家实收：¥{_format_money(y.get('valid_merchant_income', 0))}")
            lines.append(f"- 真实 ROI：{y.get('real_roi', 0):.2f} {roi_status}")
            lines.append(f"- 退款+取消率：{_format_percent(y.get('problem_rate', 0))} {problem_status}")
        else:
            lines.append("- 暂无昨日已导入数据")
        lines.append("")

        if m:
            lines.append("**本月累计**")
            lines.append(f"- 推广花费：¥{_format_money(m.get('promo_spend', 0))}")
            lines.append(f"- 推广 GMV：¥{_format_money(m.get('promo_gmv', 0))}")
            lines.append(f"- 有效商家实收：¥{_format_money(m.get('valid_merchant_income', 0))}")
            lines.append(f"- 真实 ROI：{m.get('real_roi', 0):.2f}")
            lines.append(f"- 订单数：{m.get('order_count', 0):.0f}")
            lines.append("")
        elif not y:
            lines.append("**本月累计**")
            lines.append("- 暂无本月已导入数据")
            lines.append("")

    if ai_config is not None:
        lines.append("## 🤖 AI 经营分析")
        lines.append("")
        try:
            lines.append(_build_ai_analysis(report_date, stores, ai_config))
        except Exception:
            lines.append("AI 分析生成失败，本次仅发送基础日报。")
        lines.append("")

    if not has_data:
        lines.append("暂无店铺数据，请先导入数据。")

    lines.append("---")
    lines.append("来自 拼多多推广 BI 看板")
    return "\n".join(lines)


def preview_report(report_date: datetime.date = None) -> str:
    """预览报告内容"""
    return build_daily_report(report_date)
