import datetime
import unittest
from unittest.mock import patch

import report_builder


class ReportBuilderTests(unittest.TestCase):
    @patch("report_builder.aggregate_product_metrics")
    @patch("report_builder.load_daily_data")
    @patch("report_builder.list_available_dates", return_value=["2026-08-11"])
    def test_empty_daily_metrics_are_treated_as_missing_data(
        self,
        _available_dates,
        load_daily_data,
        aggregate_product_metrics,
    ):
        import pandas as pd

        load_daily_data.return_value = (pd.DataFrame(), pd.DataFrame())

        result = report_builder._load_store_metrics_for_range(
            "空数据店铺",
            datetime.date(2026, 8, 11),
            datetime.date(2026, 8, 11),
        )

        self.assertIsNone(result)
        aggregate_product_metrics.assert_not_called()

    @patch("report_builder.list_available_stores", return_value=["旧数据店铺"])
    @patch("report_builder.list_store_names", return_value=["店铺A", "店铺B"])
    @patch("report_builder._build_store_summary")
    def test_report_keeps_registered_stores_without_yesterday_data(
        self, build_summary, list_store_names, list_available_stores
    ):
        build_summary.side_effect = [
            {"yesterday_kpis": {"promo_spend": 10, "promo_gmv": 20, "valid_merchant_income": 18, "real_roi": 2, "problem_rate": 1}, "month_kpis": {}},
            {"yesterday_kpis": {}, "month_kpis": {}},
        ]

        content = report_builder.build_daily_report(datetime.date(2026, 8, 11))

        self.assertIn("店铺范围：拼多多已注册店铺共 2 家", content)
        self.assertIn("### 店铺A", content)
        self.assertIn("### 店铺B", content)
        self.assertIn("店铺B\n\n**昨日数据**\n- 暂无昨日已导入数据", content)
        list_store_names.assert_called_once_with("pdd")
        list_available_stores.assert_not_called()

    @patch("report_builder.generate_ai_report")
    @patch("report_builder._load_store_metrics_for_range")
    def test_report_can_append_all_store_ai_analysis(self, load_metrics, generate_ai):
        import pandas as pd

        load_metrics.return_value = pd.DataFrame({
            "product_name": ["商品"],
            "promo_spend": [10],
            "promo_gmv": [20],
            "promo_orders": [1],
            "exposure": [100],
            "clicks": [10],
            "order_count": [1],
            "valid_order_count": [1],
            "order_gmv": [20],
            "valid_order_gmv": [20],
            "merchant_income": [18],
            "valid_merchant_income": [18],
            "refund_count": [0],
            "cancel_count": [0],
            "organic_orders": [0],
            "organic_gmv": [0],
            "organic_merchant_income": [0],
            "organic_valid_order_count": [0],
            "platform_fee": [0],
        })
        generate_ai.return_value = {"source": "rule", "content": "### 全店 AI 结论\n建议关注投放效率。"}

        content = report_builder.build_daily_report(
            datetime.date(2026, 8, 11),
            ai_config={"api_key": ""},
        )

        self.assertIn("## 🤖 AI 经营分析", content)
        self.assertIn("全店 AI 结论", content)
        self.assertEqual(generate_ai.call_args.kwargs["date"], "2026-08-10（全店铺）")


if __name__ == "__main__":
    unittest.main()
