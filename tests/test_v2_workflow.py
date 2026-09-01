import unittest

from v2.local_workflow import run_workflow


class V2WorkflowTests(unittest.TestCase):
    def test_full_inventory_lifecycle(self):
        result = run_workflow()

        self.assertEqual(result["processed_order_sequence"], ["order-earlier", "order-later"])
        self.assertTrue(result["cancelled_order_restored"])
        self.assertEqual(result["return_status_after_approval"], "sellable")
        self.assertEqual(result["exception_order_status"], "exception")
        self.assertGreater(result["exception_count"], 0)
        self.assertEqual(result["balances"]["huihuang"]["item-a"]["available_qty"], "0.0000")
        self.assertEqual(result["balances"]["waigaoqiao"]["item-b"]["available_qty"], "0.0000")
        self.assertGreater(float(result["balances"]["kunshan"]["item-a"]["available_qty"]), 0)


if __name__ == "__main__":
    unittest.main()
