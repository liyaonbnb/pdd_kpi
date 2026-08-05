import datetime
import unittest
from unittest.mock import patch

import pandas as pd

import services


def _row(store, date, income, orders, product, logistics, promo, refunds=0):
    platform_fee = income * 0.006
    link_profit = income - product - logistics - platform_fee
    return {
        "store_name": store,
        "date": date,
        "valid_merchant_income": income,
        "valid_order_count": orders,
        "order_count": orders,
        "refund_count": refunds,
        "total_product_cost": product,
        "total_logistics_cost": logistics,
        "platform_fee": platform_fee,
        "promo_spend": promo,
        "link_gross_profit": link_profit,
        "profit_loss": link_profit - promo,
    }


class OperationsDailyTests(unittest.TestCase):
    @patch("services.load_daily_promo")
    @patch("services.load_daily_orders")
    @patch("services.load_daily_data")
    @patch("services.load_trend_data")
    @patch("services.list_available_dates")
    def test_report_recomputes_rates_and_marks_missing_days(
        self, available_dates, trend_data, daily_data, daily_orders, daily_promo
    ):
        available_dates.return_value = ["2026-08-01", "2026-08-02"]
        trend_data.return_value = [
            _row("店铺A", "2026-08-01", 100, 10, 30, 10, 20, 1),
            _row("店铺A", "2026-08-02", 200, 20, 60, 20, 40, 1),
            _row("店铺B", "2026-08-01", 50, 5, 15, 5, 10, 0),
        ]

        def has_data(date, store):
            if store == "店铺B" and date == "2026-08-02":
                raise FileNotFoundError
            return pd.DataFrame([{"value": 1}])

        daily_data.side_effect = lambda date, store: (has_data(date, store), pd.DataFrame())
        daily_orders.side_effect = has_data
        daily_promo.side_effect = has_data

        report = services.get_operations_daily_report(
            datetime.date(2026, 8, 1),
            datetime.date(2026, 8, 2),
            ["店铺A", "店铺B"],
        )

        self.assertEqual(report["dates"], ["2026-08-01", "2026-08-02"])
        self.assertAlmostEqual(report["summary"]["valid_merchant_income"], 350)
        self.assertAlmostEqual(report["summary"]["promo_cost_ratio"], 20)
        self.assertAlmostEqual(report["summary"]["product_cost_ratio"], 30)
        self.assertAlmostEqual(report["summary"]["logistics_cost_ratio"], 10)
        self.assertEqual(report["summary"]["data_issue_store_count"], 1)
        self.assertEqual(report["stores"][1]["quality_counts"]["missing"], 1)
        self.assertIsNone(report["stores"][1]["daily"]["2026-08-02"])


if __name__ == "__main__":
    unittest.main()
