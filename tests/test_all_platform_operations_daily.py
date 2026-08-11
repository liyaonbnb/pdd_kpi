import datetime
import unittest
from unittest.mock import patch

import services


def _platform_summary(income, orders, spend, profit, platform="other"):
    trend = [{
        "date": "2026-08-07",
        "valid_merchant_income" if platform == "pdd" else "actual_revenue": income,
        "valid_order_count": orders,
        "promo_spend" if platform == "pdd" else "spend": spend,
        "profit_loss": profit,
    }]
    if platform == "pdd":
        return {
            "kpis": {
                "valid_merchant_income": income,
                "valid_order_count": orders,
                "promo_spend": spend,
                "profit_loss": profit,
                "profit_loss_rate": profit / income * 100 if income else 0,
                "refund_rate": 1,
                "real_roi": income / spend if spend else 0,
            },
            "trend": trend,
        }
    return {
        "kpis": {
            "actual_revenue": income,
            "valid_order_count": orders,
            "spend": spend,
            "refund_rate": 2,
            "valid_roi": income / spend if spend else 0,
        },
        "cost_kpis": {
            "profit_loss": profit,
            "profit_loss_rate": profit / income * 100 if income else 0,
        },
        "trend": trend,
    }


class AllPlatformOperationsDailyTests(unittest.TestCase):
    @patch("wechat_services.get_wechat_dashboard_summary")
    @patch("tmall_services.get_tmall_dashboard_summary")
    @patch("douyin_services.get_douyin_dashboard_summary")
    @patch("services.get_dashboard_summary")
    @patch("services.get_operations_daily_report")
    @patch("store_manager.list_store_names")
    def test_report_contains_every_platform_and_combined_summary(
        self,
        list_stores,
        pdd_matrix,
        pdd_summary,
        douyin_summary,
        tmall_summary,
        wechat_summary,
    ):
        stores = {
            "pdd": ["拼店1", "拼店2"],
            "douyin": ["抖店"],
            "tmall": ["天猫店"],
            "wechat": ["微信店"],
        }
        list_stores.side_effect = lambda platform: stores[platform]
        pdd_matrix.return_value = {
            "start_date": "2026-08-01",
            "end_date": "2026-08-07",
            "dates": [],
            "summary": {},
            "total": {},
            "stores": [],
        }
        pdd_summary.return_value = _platform_summary(100, 10, 20, 15, "pdd")
        douyin_summary.return_value = _platform_summary(200, 20, 40, 30)
        tmall_summary.return_value = _platform_summary(300, 30, 60, 45)
        wechat_summary.return_value = {
            "kpis": {"net_revenue": 400, "valid_order_count": 40, "refund_rate": 3},
            "cost_kpis": {"profit_loss": 60, "profit_loss_rate": 15},
            "trend": [{
                "date": "2026-08-07",
                "net_revenue": 400,
                "valid_order_count": 40,
                "profit_loss": 60,
            }],
        }

        report = services.get_all_platform_operations_daily(
            datetime.date(2026, 8, 1),
            datetime.date(2026, 8, 7),
            stores["pdd"],
        )

        self.assertEqual([item["platform"] for item in report["platforms"]], ["pdd", "douyin", "tmall", "wechat"])
        self.assertEqual(report["platform_summary"]["income"], 1000)
        self.assertEqual(report["platform_summary"]["profit_loss"], 150)
        self.assertEqual(report["platform_summary"]["store_count"], 5)
        self.assertEqual(report["platform_summary"]["data_platform_count"], 4)
        self.assertIsNone(report["platforms"][3]["totals"]["promo_spend"])

    def test_platform_without_daily_rows_is_marked_as_no_data(self):
        platform = services._normalize_operations_platform(
            "pdd",
            "拼多多",
            1,
            {"valid_merchant_income": 0, "valid_order_count": 0},
            {},
            [],
        )

        self.assertFalse(platform["has_data"])
        self.assertEqual(platform["data_days"], 0)

    @patch("wechat_storage.list_available_dates", return_value=["2026-08-10"])
    @patch("tmall_storage.list_available_dates", return_value=[])
    @patch("douyin_storage.list_available_dates", return_value=["2026-08-09"])
    @patch("services.list_available_dates", return_value=["2026-08-01"])
    def test_default_range_uses_latest_date_from_every_platform(
        self,
        _pdd_dates,
        _douyin_dates,
        _tmall_dates,
        _wechat_dates,
    ):
        start_date, end_date = services._resolve_all_platform_operations_range(
            None,
            None,
            {
                "pdd": ["拼店"],
                "douyin": ["抖店"],
                "tmall": ["天猫店"],
                "wechat": ["微信店"],
            },
        )

        self.assertEqual(end_date, datetime.date(2026, 8, 10))
        self.assertEqual(start_date, datetime.date(2026, 8, 4))

    def test_wecom_report_includes_all_platform_labels(self):
        report = {
            "start_date": "2026-08-01",
            "end_date": "2026-08-07",
            "platform_summary": {
                "data_platform_count": 4,
                "platform_count": 4,
                "store_count": 5,
                "income": 1000,
                "order_count": 100,
                "promo_spend": 120,
                "profit_loss": 150,
                "profit_loss_rate": 15,
            },
            "platforms": [
                {
                    "label": label,
                    "store_count": 1,
                    "has_data": True,
                    "totals": {
                        "income": 250,
                        "order_count": 25,
                        "promo_spend": None if label == "微信小店" else 30,
                        "profit_loss": 40,
                        "profit_loss_rate": 16,
                        "refund_rate": 1,
                        "roi": None if label == "微信小店" else 2,
                    },
                    "daily": [],
                }
                for label in ("拼多多", "抖音", "天猫", "微信小店")
            ],
        }
        with patch("services.get_all_platform_operations_daily", return_value=report), patch(
            "store_manager.list_store_names", return_value=["店铺"]
        ):
            content = services.build_all_platform_operations_wecom_report(
                datetime.date(2026, 8, 1),
                datetime.date(2026, 8, 7),
            )

        for label in ("拼多多", "抖音", "天猫", "微信小店"):
            self.assertIn(f"### {label}", content)

    @patch("services.mark_report_draft_sent")
    @patch("services.send_wecom_report", return_value={"errcode": 0})
    @patch("services.get_wecom_config", return_value={"chat_id": "group"})
    @patch("services.get_report_draft")
    def test_wecom_send_uses_operations_draft(self, get_draft, _config, send, mark_sent):
        get_draft.return_value = {"draft_id": "draft-1", "content": "全平台日报"}

        result = services.send_all_platform_operations_wecom_report(
            datetime.date(2026, 8, 1),
            datetime.date(2026, 8, 7),
            "draft-1",
        )

        self.assertEqual(result["errcode"], 0)
        get_draft.assert_called_once_with("draft-1", "2026-08-01:2026-08-07", platform="operations")
        send.assert_called_once_with("全平台日报", {"chat_id": "group"})
        mark_sent.assert_called_once_with("draft-1")


if __name__ == "__main__":
    unittest.main()
