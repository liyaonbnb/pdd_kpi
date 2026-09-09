import unittest

from v2.daily_wecom_job import _v2_report_text


class DailyWecomJobTests(unittest.TestCase):
    def test_report_text_formats(self):
        report = {
            "report_date": "2026-09-08",
            "platforms": [
                {"platform": "pdd", "order_count": 3, "gmv": 120.5, "profit": 40.2}
            ],
            "totals": {
                "order_count": 3,
                "gmv": 120.5,
                "product_cost": 60.0,
                "shipping_fee": 20.3,
                "profit": 40.2,
            },
        }
        text = _v2_report_text(report)
        self.assertIn("V2运营日报 2026-09-08", text)
        self.assertIn("pdd：订单3，GMV 120.50，利润 40.20", text)
        self.assertIn("合计：订单3，GMV 120.50，利润 40.20", text)


if __name__ == "__main__":
    unittest.main()