"""
拼多多推广数据 BI 看板 - Streamlit 主入口
新版 UI：左侧功能导航 + 顶部店铺/AI 配置 + 日期范围 + 多店铺管理
"""

import os
import sys
import importlib
import time
import datetime
import streamlit as st
import pandas as pd

# 强制重新加载项目模块，避免 Streamlit 缓存旧版本
_project_modules = [
    "api_client",
    "config_manager",
    "storage",
    "store_manager",
    "data_loader",
    "metrics",
    "data_processor",
    "ai_analyzer",
    "dashboard",
]
for _mod_name in _project_modules:
    if _mod_name in sys.modules:
        importlib.reload(sys.modules[_mod_name])

from data_loader import read_promotion_file, read_order_file, infer_date_from_filename
from data_processor import match_promotion_and_orders
from metrics import (
    compute_product_metrics,
    compute_overall_kpis,
    aggregate_product_metrics,
    aggregate_style_metrics,
    merge_refund_stage_counts,
)
from ai_analyzer import generate_ai_report
from api_client import test_connection, get_ai_log_tail
from storage import (
    save_daily_data,
    load_daily_data,
    load_daily_orders,
    list_available_stores,
    list_available_dates,
    record_exists,
)
from store_manager import add_store, rename_store, delete_store
from wecom import send_wecom_report, save_wecom_config, listen_wecom_chatid
from report_builder import build_daily_report
from cost_manager import (
    apply_costs_to_metrics,
    load_cost_config,
    save_cost_config,
    set_cost,
    append_new_merchant_codes,
    import_costs_from_csv,
)
from dashboard import (
    load_css,
    render_sidebar_nav,
    render_top_header,
    render_store_tab,
    render_ai_tab,
    render_import_module,
    render_recent_imports,
    render_order_detail_module,
    render_store_overview,
    render_history_module,
    render_store_management,
    render_wecom_module,
    render_cost_module,
    render_kpis,
    render_product_table,
    render_charts,
    render_style_table,
    render_trend,
)
from config_manager import load_config, save_config, get_config_defaults

st.set_page_config(
    page_title="拼多多推广数据 BI 看板",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _date_str(d) -> str:
    """统一日期转字符串"""
    if isinstance(d, datetime.date):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, datetime.datetime):
        return d.strftime("%Y-%m-%d")
    return str(d)


def load_analysis_data(store_name: str, start_date, end_date):
    """加载指定店铺、日期范围内的汇总分析数据"""
    dates = list_available_dates(store_name)
    start_s = _date_str(start_date)
    end_s = _date_str(end_date)
    selected_dates = [d for d in dates if start_s <= d <= end_s]

    if not selected_dates:
        return None, None, None

    product_dfs = []
    order_dfs = []
    for d in selected_dates:
        try:
            p, _ = load_daily_data(d, store_name)
            product_dfs.append(p)
        except Exception:
            continue
        try:
            orders = load_daily_orders(d, store_name)
            if not orders.empty:
                order_dfs.append(orders)
        except Exception:
            continue

    if not product_dfs:
        return None, None, None

    metrics = aggregate_product_metrics(product_dfs)
    metrics = merge_refund_stage_counts(metrics, order_dfs)
    metrics = compute_product_metrics(metrics)
    metrics = apply_costs_to_metrics(metrics, store_name)
    style_metrics = aggregate_style_metrics(order_dfs) if order_dfs else pd.DataFrame()
    kpis = compute_overall_kpis(metrics)
    return metrics, style_metrics, kpis


def process_import(config: dict, import_state: dict):
    """处理导入数据逻辑"""
    store_name = config["store_name"]
    import_date = import_state["import_date"]
    promo_file = import_state["promo_file"]
    order_file = import_state["order_file"]

    with st.spinner("正在读取并校验数据..."):
        try:
            promo_df, promo_mapping = read_promotion_file(promo_file)
            order_df, order_mapping = read_order_file(order_file)
        except Exception as e:
            st.error(f"读取文件失败: {e}")
            return

    # 预览
    st.markdown("#### 数据预览")
    c1, c2 = st.columns(2)
    with c1:
        st.write("推广数据")
        st.dataframe(promo_df.head(10), use_container_width=True)
    with c2:
        st.write("订单数据")
        st.dataframe(order_df.head(10), use_container_width=True)

    st.info(
        f"推广数据 {len(promo_df)} 行，订单数据 {len(order_df)} 行。"
        f"即将保存到店铺「{store_name}」日期 {import_date}。"
    )

    with st.spinner("正在匹配并保存数据..."):
        try:
            merged, style_metrics, orders = match_promotion_and_orders(
                promo_df,
                order_df,
                promo_mapping,
                order_mapping,
                date=_date_str(import_date),
            )
            merged["store_name"] = store_name
            style_metrics["store_name"] = store_name
            orders["store_name"] = store_name

            metrics = compute_product_metrics(merged)

            save_daily_data(
                metrics,
                style_metrics,
                orders,
                date=_date_str(import_date),
                store_name=store_name,
                meta={
                    "promo_file": promo_file.name,
                    "order_file": order_file.name,
                },
            )
            st.success(f"✅ {store_name} {import_date} 数据导入成功！")
        except Exception as e:
            st.error(f"数据处理或保存失败: {e}")
            st.exception(e)


def render_ai_analysis(config: dict, metrics, kpis, style_metrics):
    """渲染 AI 洞察内容"""
    st.subheader("🤖 AI 洞察")

    with st.expander("当前 AI 配置", expanded=True):
        key_status = f"已填写 ({len(config['api_key'])} 位字符)" if config["api_key"] else "未填写"
        st.write("- API Key:", key_status)
        st.write("- Base URL:", config["base_url"])
        st.write("- 模型:", config["model"])
        st.write("- Temperature:", config["temperature"])
        st.write("- Reasoning Effort:", config["reasoning_effort"])
        st.write("- 超时:", f"{config['timeout']} 秒")
        st.write("- 单次最大输出 Token:", config.get("max_completion_tokens", 16384))
        if not config["api_key"]:
            st.warning("未填写 API Key，将只能使用规则化洞察。请先在「AI 配置」中填写并保存。")

    if metrics is None or kpis is None:
        st.info("请先导入数据，并确保当前店铺在分析日期范围内有数据。")
        return

    st.markdown("**快速测试**")
    if st.button("🧪 发送一句测试给 AI（10秒超时）", use_container_width=True):
        with st.spinner("正在发送测试请求..."):
            result = test_connection(config["api_key"], config["base_url"], config["model"], timeout=10)
            if result["ok"]:
                st.success(f"AI 响应正常：{result.get('message', '')}")
            else:
                st.error(f"AI 测试失败：{result.get('error', '未知错误')}")

    st.divider()

    gen_col1, gen_col2 = st.columns([3, 1])
    with gen_col1:
        generate_clicked = st.button("🚀 生成 AI 分析报告", use_container_width=True)
    with gen_col2:
        clear_clicked = st.button("🗑️ 清除报告", use_container_width=True)

    if clear_clicked:
        st.session_state.ai_report = None

    if generate_clicked:
        with st.spinner(f"正在调用 AI 模型分析数据（最长等待 {config['timeout']} 秒）..."):
            try:
                start_time = time.time()
                report = generate_ai_report(
                    kpis=kpis,
                    metrics=metrics,
                    api_key=config["api_key"] or None,
                    base_url=config["base_url"],
                    model=config["model"],
                    temperature=config["temperature"],
                    reasoning_effort=config["reasoning_effort"],
                    timeout=config["timeout"],
                    max_completion_tokens=config.get("max_completion_tokens", 16384),
                    date=f"{config['start_date']} ~ {config['end_date']}",
                )
                report["elapsed_seconds"] = round(time.time() - start_time, 2)
                st.session_state.ai_report = report
            except Exception as e:
                st.error(f"生成报告失败: {e}")
                st.exception(e)

    if "ai_report" in st.session_state and st.session_state.ai_report:
        report = st.session_state.ai_report

        if report["source"] == "llm":
            st.success(
                f"✅ 此报告由 AI 模型 **{report['model']}** 生成，耗时 {report.get('elapsed_seconds', '-')} 秒"
            )
        elif report["source"] == "rule_fallback":
            st.warning(
                f"⚠️ AI 调用失败，已降级为内置规则洞察。\n\n错误: {report.get('error', '未知')}"
            )
        else:
            st.info("ℹ️ 当前为内置规则化洞察（未配置 API Key 或 Key 为空）")

        st.divider()
        st.markdown(report["content"])

        with st.expander("🔧 AI 调用调试信息"):
            st.write("- 来源:", report["source"])
            st.write("- 模型:", report.get("model", "-"))
            st.write("- Base URL:", config["base_url"])
            st.write("- Temperature:", config["temperature"])
            st.write("- Reasoning Effort:", config["reasoning_effort"])
            st.write("- 超时设置:", f"{config['timeout']} 秒")
            st.write("- 耗时:", f"{report.get('elapsed_seconds', '-')} 秒")
            if report.get("error"):
                st.error(f"错误详情: {report['error']}")
            st.text_area("Prompt 预览", report.get("prompt", "")[:2000], height=150)
            st.text_area("AI 调用日志", get_ai_log_tail(100), height=200)

        st.download_button(
            label="下载 AI 报告 (Markdown)",
            data=report["content"],
            file_name=f"ai_report_{config['store_name']}_{config['start_date']}_{config['end_date']}.md",
            mime="text/markdown",
            use_container_width=True,
        )
    else:
        st.caption("点击上方按钮生成分析报告。")

    with st.expander("📝 最近的 AI 调用日志"):
        st.text(get_ai_log_tail(200))


def main():
    load_css()

    # 左侧功能导航
    active_module = render_sidebar_nav()

    # 顶部配置区
    active_top = render_top_header()

    # 基础配置
    config = get_config_defaults()
    config.setdefault("store_name", "默认店铺")

    # 渲染顶部面板
    if active_top == "🏪 店铺切换":
        panel_config = render_store_tab(config.get("store_name"))
    else:
        panel_config = render_ai_tab(config)
    config.update(panel_config)

    # 处理 AI 配置按钮
    if active_top == "⚙️ AI 配置":
        if config.get("ai_save_clicked"):
            save_config({
                "api_key": config["api_key"],
                "base_url": config["base_url"],
                "model": config["model"],
                "temperature": config["temperature"],
                "reasoning_effort": config["reasoning_effort"],
                "timeout": config["timeout"],
                "max_completion_tokens": config["max_completion_tokens"],
            })
            st.success("AI 配置已保存到本地")
        if config.get("ai_test_clicked"):
            with st.spinner("正在测试 AI 连接..."):
                result = test_connection(config["api_key"], config["base_url"], config["model"])
                if result["ok"]:
                    st.success(f"连接成功！模型: {result.get('model', config['model'])}")
                else:
                    st.error(f"连接失败: {result.get('error', '未知错误')}")

    store_name = config.get("store_name", "默认店铺")

    # 页面标题
    st.title("📊 拼多多推广数据 BI 看板")
    st.caption("上传每日「推广数据」和「订单数据」，自动匹配商品ID/样式ID并生成分析。")

    # 根据左侧导航渲染内容
    if active_module == "📥 导入数据":
        import_state = render_import_module(store_name)
        if import_state["import_clicked"]:
            process_import(config, import_state)
            st.rerun()
        render_recent_imports(store_name)

    elif active_module == "📋 订单明细":
        action_state = render_order_detail_module(store_name)
        if action_state.get("action") == "save_product_merchant_mapping":
            from cost_manager import (
                load_cost_config,
                save_cost_config,
                set_product_merchant_mapping,
                set_cost,
            )
            cfg = load_cost_config()
            cfg = set_product_merchant_mapping(
                cfg,
                store_name=store_name,
                product_id=action_state["product_id"],
                merchant_code=action_state["merchant_code"],
            )
            # 同步把该商家编码加入成本表，方便立刻维护成本
            costs = cfg.get("merchant_costs", {}).get(store_name, {})
            if action_state["merchant_code"] not in costs:
                cfg = set_cost(
                    cfg,
                    store_name=store_name,
                    merchant_code=action_state["merchant_code"],
                    product_name="",
                    product_cost=0.0,
                    logistics_cost=0.0,
                )
            save_cost_config(cfg)
            st.success(
                f"✅ 已保存映射：商品 {action_state['product_id']} -> 商家编码 {action_state['merchant_code']}，"
                "请在「成本管理」中维护成本。"
            )
            st.rerun()

    elif active_module == "🏠 店铺总览":
        render_store_overview(config)

    elif active_module in ["📊 核心指标", "🛒 商品分析", "🎨 样式分析", "🤖 AI 洞察", "📤 导出数据"]:
        # 读取分析数据
        start_date = config.get("start_date", datetime.date.today())
        end_date = config.get("end_date", datetime.date.today())

        # 日期范围展示
        st.markdown(
            f"<p style='color:#9ca3af;font-size:13px;margin-bottom:16px;'>"
            f"当前分析：{store_name} · {start_date} ~ {end_date}</p>",
            unsafe_allow_html=True,
        )

        metrics, style_metrics, kpis = load_analysis_data(store_name, start_date, end_date)
        has_result = metrics is not None and kpis is not None

        if active_module == "📊 核心指标":
            if has_result:
                st.subheader("今日核心指标")
                render_kpis(kpis)
                st.divider()
                st.subheader("推广 vs 订单")
                render_charts(metrics, kpis)
            else:
                st.info("该店铺在选定日期范围内暂无数据。请先在「导入数据」中上传。")

        elif active_module == "🛒 商品分析":
            if has_result:
                st.subheader("商品明细")
                render_product_table(metrics)
            else:
                st.info("该店铺在选定日期范围内暂无数据。")

        elif active_module == "🎨 样式分析":
            if has_result:
                st.subheader("样式/规格明细")
                render_style_table(style_metrics)
            else:
                st.info("该店铺在选定日期范围内暂无数据。")

        elif active_module == "🤖 AI 洞察":
            render_ai_analysis(config, metrics, kpis, style_metrics)

        elif active_module == "📤 导出数据":
            if has_result:
                st.subheader("导出数据")
                col_dl1, col_dl2 = st.columns(2)
                with col_dl1:
                    csv_product = metrics.to_csv(index=False, encoding="utf-8-sig")
                    st.download_button(
                        label="下载商品级指标 CSV",
                        data=csv_product,
                        file_name=f"product_metrics_{store_name}_{start_date}_{end_date}.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )
                with col_dl2:
                    csv_style = style_metrics.to_csv(index=False, encoding="utf-8-sig")
                    st.download_button(
                        label="下载样式级指标 CSV",
                        data=csv_style,
                        file_name=f"style_metrics_{store_name}_{start_date}_{end_date}.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )
            else:
                st.info("该店铺在选定日期范围内暂无数据。")

    elif active_module == "📢 企业微信报告":
        wecom_action = render_wecom_module()
        if not wecom_action:
            return

        action = wecom_action.get("action")
        if action == "listen":
            cfg = wecom_action["config"]
            if not cfg.get("bot_id") or not cfg.get("secret"):
                st.error("请先填写 BotID 和 Secret")
            else:
                with st.spinner("正在监听会话，请在群里 @机器人 或向机器人发送消息..."):
                    captured = listen_wecom_chatid(
                        cfg["bot_id"], cfg["secret"], timeout=60
                    )
                if captured:
                    cfg["chatid"] = captured
                    save_wecom_config(cfg)
                    st.success(f"✅ 已捕获会话 ID：{captured}")
                    st.rerun()
                else:
                    st.warning("⏱️ 60 秒内未收到消息，请确认机器人已在群里或被用户单聊后重试")

        elif action == "send_report":
            with st.spinner("正在生成并发送报告..."):
                try:
                    content = build_daily_report(
                        wecom_action["report_date"],
                        ai_config=get_config_defaults(),
                    )
                    result = send_wecom_report(content, wecom_action["config"])
                    st.success("✅ 报告已发送到企业微信")
                    with st.expander("发送结果"):
                        st.json(result)
                except Exception as e:
                    st.error(f"发送失败: {e}")
                    st.exception(e)

    elif active_module == "💰 成本管理":
        cost_action = render_cost_module(store_name)
        if cost_action:
            action = cost_action.get("action")
            if action == "save_costs":
                cfg = load_cost_config()
                raw = cost_action.get("costs", [])
                if isinstance(raw, dict):
                    raw = pd.DataFrame({k: pd.Series(v) for k, v in raw.items()})
                if isinstance(raw, pd.DataFrame):
                    raw = raw.to_dict("records")
                if isinstance(raw, list):
                    for rec in raw:
                        code = str(rec.get("merchant_code", "")).strip()
                        if not code:
                            continue
                        cfg = set_cost(
                            cfg,
                            store_name=store_name,
                            merchant_code=code,
                            product_name=rec.get("product_name", ""),
                            product_cost=rec.get("product_cost", 0),
                            logistics_cost=rec.get("logistics_cost", 0),
                        )
                    save_cost_config(cfg)
                    st.success("✅ 成本配置已保存")
                    st.rerun()
            elif action == "add_cost":
                cfg = load_cost_config()
                cfg = set_cost(
                    cfg,
                    store_name=store_name,
                    merchant_code=cost_action["merchant_code"],
                    product_name=cost_action.get("product_name", ""),
                    product_cost=cost_action.get("product_cost", 0),
                    logistics_cost=cost_action.get("logistics_cost", 0),
                )
                save_cost_config(cfg)
                st.success(f"✅ 已添加 {cost_action['merchant_code']}")
                st.rerun()
            elif action == "refresh_cost_codes":
                with st.spinner("正在从订单中提取新商家编码..."):
                    added = append_new_merchant_codes(store_name)
                if added:
                    st.success(f"✅ 已新增 {added} 个商家编码")
                else:
                    st.info("没有新的商家编码需要追加")
                st.rerun()
            elif action == "import_costs":
                with st.spinner("正在导入成本配置..."):
                    try:
                        count = import_costs_from_csv(store_name, cost_action["file"])
                        st.success(f"✅ 已导入/更新 {count} 条成本记录")
                        st.rerun()
                    except Exception as e:
                        st.error(f"导入失败: {e}")

    elif active_module == "📅 历史数据":
        history_action = render_history_module(store_name)
        if history_action and history_action.get("action") == "delete_record":
            from storage import delete_daily_data
            delete_daily_data(history_action["store_name"], history_action["date"])
            st.success(f"已删除 {history_action['store_name']} {history_action['date']} 的数据")
            st.rerun()

    elif active_module == "⚙️ 店铺管理":
        action = render_store_management()
        if action and action.get("action"):
            if action["action"] == "create":
                store = add_store(action["new_name"])
                st.success(f"店铺「{store['name']}」创建成功")
                st.rerun()
            elif action["action"] == "rename":
                renamed = rename_store(action["store_id"], action["new_name"])
                if renamed:
                    st.success(f"已重命名为「{renamed['name']}」")
                    st.rerun()
            elif action["action"] == "delete":
                # 二次确认用 dialog 不支持时 fallback 到 button
                if st.button(f"确认删除 {action['store_name']}？此操作不可恢复", key="confirm_delete"):
                    if delete_store(action["store_id"]):
                        st.success(f"店铺「{action['store_name']}」已删除")
                        st.rerun()


if __name__ == "__main__":
    main()
