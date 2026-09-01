import unittest
from datetime import datetime, timezone
from datetime import date
from decimal import Decimal

from v2.inventory_engine import (
    InsufficientStock,
    InventoryEngine,
    PurchaseReceiptLine,
    allocate_purchase_fees,
    expand_bundle,
)
from v2.order_engine import OrderInput, OrderLine, process_order, process_orders
from v2.import_contract import ImportValidationError, validate_order_frame


class InventoryEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = InventoryEngine()
        self.t1 = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.t2 = datetime(2026, 9, 2, tzinfo=timezone.utc)

    def test_weighted_average_is_per_warehouse_and_item(self):
        self.engine.receive(
            warehouse_id="kunshan", item_id="item-a", batch_id="b1", batch_no="B1",
            qty=100, unit_cost=10, reference_type="opening", reference_id="open-1", received_at=self.t1,
        )
        self.engine.receive(
            warehouse_id="kunshan", item_id="item-a", batch_id="b2", batch_no="B2",
            qty=200, unit_cost=12, reference_type="purchase", reference_id="p-1", received_at=self.t2,
        )
        self.engine.receive(
            warehouse_id="huihuang", item_id="item-a", batch_id="b3", batch_no="B3",
            qty=10, unit_cost=99, reference_type="opening", reference_id="open-2", received_at=self.t1,
        )
        self.assertEqual(self.engine.average_cost("kunshan", "item-a"), Decimal("11.333333"))
        self.assertEqual(self.engine.average_cost("huihuang", "item-a"), Decimal("99.000000"))

    def test_fifo_allocation_keeps_actual_batches_and_average_cost(self):
        self.engine.receive(
            warehouse_id="kunshan", item_id="item-a", batch_id="b1", batch_no="B1",
            qty=5, unit_cost=10, reference_type="opening", reference_id="open-1", received_at=self.t1,
        )
        self.engine.receive(
            warehouse_id="kunshan", item_id="item-a", batch_id="b2", batch_no="B2",
            qty=10, unit_cost=20, reference_type="purchase", reference_id="p-1", received_at=self.t2,
        )
        cost, allocations = self.engine.allocate_fifo(
            warehouse_id="kunshan", item_id="item-a", qty=7, order_id="o-1",
        )
        self.assertEqual([(a.batch_no, a.quantity) for a in allocations], [("B1", Decimal("5.0000")), ("B2", Decimal("2.0000"))])
        # 订单利润按扣减前的永续加权平均成本核算，实际 FIFO 批次留在 allocations 中追溯。
        self.assertEqual(cost, Decimal("116.666669"))
        self.assertEqual(self.engine.batches["b1"].remaining_qty, Decimal("0.0000"))
        self.assertEqual(self.engine.batches["b2"].remaining_qty, Decimal("8.0000"))
        self.assertEqual(self.engine.average_cost("kunshan", "item-a"), Decimal("16.666666"))

    def test_insufficient_stock_does_not_partially_consume_batches(self):
        self.engine.receive(
            warehouse_id="kunshan", item_id="item-a", batch_id="b1", batch_no="B1",
            qty=5, unit_cost=10, reference_type="opening", reference_id="open-1", received_at=self.t1,
        )
        with self.assertRaises(InsufficientStock):
            self.engine.allocate_fifo(warehouse_id="kunshan", item_id="item-a", qty=6, order_id="o-1")
        self.assertEqual(self.engine.batches["b1"].remaining_qty, Decimal("5.0000"))
        self.assertEqual(self.engine.available_qty("kunshan", "item-a"), Decimal("5.0000"))

    def test_reverse_order_restores_original_batches(self):
        self.engine.receive(
            warehouse_id="kunshan", item_id="item-a", batch_id="b1", batch_no="B1",
            qty=5, unit_cost=10, reference_type="opening", reference_id="open-1", received_at=self.t1,
        )
        self.engine.receive(
            warehouse_id="kunshan", item_id="item-a", batch_id="b2", batch_no="B2",
            qty=10, unit_cost=20, reference_type="purchase", reference_id="p-1", received_at=self.t2,
        )
        self.engine.allocate_fifo(warehouse_id="kunshan", item_id="item-a", qty=7, order_id="o-1")
        self.engine.reverse_order("o-1")
        self.assertEqual(self.engine.batches["b1"].remaining_qty, Decimal("5.0000"))
        self.assertEqual(self.engine.batches["b2"].remaining_qty, Decimal("10.0000"))
        self.assertEqual(self.engine.average_cost("kunshan", "item-a"), Decimal("16.666667"))

    def test_multi_item_order_can_be_reversed_as_one_order(self):
        self.engine.receive(
            warehouse_id="kunshan", item_id="item-a", batch_id="ba", batch_no="BA",
            qty=5, unit_cost=10, reference_type="opening", reference_id="open-a", received_at=self.t1,
        )
        self.engine.receive(
            warehouse_id="kunshan", item_id="item-b", batch_id="bb", batch_no="BB",
            qty=5, unit_cost=20, reference_type="opening", reference_id="open-b", received_at=self.t1,
        )
        order = OrderInput(
            order_id="o-bundle", platform="pdd", store_name="店铺 A", warehouse_id="kunshan",
            payment_time=self.t1, status="paid",
            lines=(OrderLine("bundle-1", 1, 4, (("item-a", 1), ("item-b", 2))),),
        )
        result = process_order(self.engine, order)
        self.assertEqual(result.inventory_status, "deducted")
        self.assertEqual(result.allocation_refs, ["o-bundle:item-a", "o-bundle:item-b"])
        self.engine.reverse_order_group("o-bundle")
        self.assertEqual(self.engine.available_qty("kunshan", "item-a"), Decimal("5.0000"))
        self.assertEqual(self.engine.available_qty("kunshan", "item-b"), Decimal("5.0000"))

    def test_bundle_expands_and_merges_components(self):
        result = expand_bundle([("item-a", 2), ("item-b", 1), ("item-a", 1)], 3)
        self.assertEqual(result, {"item-a": Decimal("9.0000"), "item-b": Decimal("3.0000")})

    def test_inspection_batch_only_enters_cost_pool_after_approval(self):
        self.engine.receive(
            warehouse_id="kunshan", item_id="item-a", batch_id="r1", batch_no="R1",
            qty=10, unit_cost=8, reference_type="customer_return", reference_id="return-1",
            received_at=self.t1, stock_status="inspection",
        )
        self.assertEqual(self.engine.available_qty("kunshan", "item-a"), Decimal("0.0000"))
        self.assertEqual(self.engine.average_cost("kunshan", "item-a"), Decimal("0.000000"))
        self.engine.approve_inspection("r1", "sellable")
        self.assertEqual(self.engine.available_qty("kunshan", "item-a"), Decimal("10.0000"))
        self.assertEqual(self.engine.average_cost("kunshan", "item-a"), Decimal("8.000000"))

    def test_purchase_fees_are_allocated_by_amount(self):
        costs = allocate_purchase_fees(
            [("item-a", 10, 10, 100), ("item-b", 5, 20, 100)],
            fees=15,
        )
        self.assertEqual(costs["item-a"], Decimal("10.750000"))
        self.assertEqual(costs["item-b"], Decimal("21.500000"))

    def test_purchase_receipt_only_updates_inventory_after_approval(self):
        receipt = self.engine.create_purchase_receipt(
            receipt_no="PO-DRAFT",
            warehouse_id="kunshan",
            lines=(PurchaseReceiptLine("item-a", "po-batch", "PO-BATCH", 10, 10, 100),),
            freight_fee=20,
        )
        self.assertEqual(receipt.status, "draft")
        self.assertEqual(self.engine.available_qty("kunshan", "item-a"), Decimal("0.0000"))
        self.engine.approve_purchase_receipt("PO-DRAFT", approved_by="buyer")
        self.assertEqual(receipt.status, "approved")
        self.assertEqual(self.engine.available_qty("kunshan", "item-a"), Decimal("10.0000"))
        self.assertEqual(self.engine.average_cost("kunshan", "item-a"), Decimal("12.000000"))

    def test_unconfirmed_return_cannot_restore_inventory(self):
        with self.assertRaisesRegex(Exception, "尚未确认收货"):
            self.engine.receive_customer_return(
                warehouse_id="kunshan",
                item_id="item-a",
                batch_id="return-unconfirmed",
                batch_no="RETURN-UNCONFIRMED",
                qty=1,
                unit_cost=10,
                order_id="o-1",
                confirmed_received=False,
            )

    def test_order_uses_payment_time_and_bundle_shipping_fee(self):
        self.engine.receive(
            warehouse_id="kunshan", item_id="item-a", batch_id="b1", batch_no="B1",
            qty=10, unit_cost=10, reference_type="opening", reference_id="open-1", received_at=self.t1,
        )
        order = OrderInput(
            order_id="o-1", platform="pdd", store_name="店铺 A", warehouse_id="kunshan",
            payment_time=self.t1, status="支付成功",
            lines=(OrderLine(bundle_id="bundle-1", quantity=2, expected_shipping_fee=3, bom=(("item-a", 1),)),),
        )
        result = process_order(self.engine, order)
        self.assertEqual(result.inventory_status, "deducted")
        self.assertEqual(result.product_cost, Decimal("20.000000"))
        self.assertEqual(result.shipping_fee, Decimal("6.000000"))
        self.assertEqual(result.total_cost, Decimal("26.000000"))

    def test_insufficient_order_is_atomic_and_keeps_business_result(self):
        self.engine.receive(
            warehouse_id="kunshan", item_id="item-a", batch_id="b1", batch_no="B1",
            qty=10, unit_cost=10, reference_type="opening", reference_id="open-1", received_at=self.t1,
        )
        order = OrderInput(
            order_id="o-2", platform="pdd", store_name="店铺 A", warehouse_id="kunshan",
            payment_time=self.t1, status="paid",
            lines=(OrderLine(bundle_id="bundle-1", quantity=2, expected_shipping_fee=0, bom=(("item-a", 1), ("item-b", 1))),),
        )
        result = process_order(self.engine, order)
        self.assertEqual(result.inventory_status, "exception")
        self.assertEqual(result.product_cost, Decimal("0.000000"))
        self.assertEqual(self.engine.available_qty("kunshan", "item-a"), Decimal("10.0000"))

    def test_cancelled_order_and_pre_enable_order_do_not_deduct(self):
        self.engine.receive(
            warehouse_id="kunshan", item_id="item-a", batch_id="b1", batch_no="B1",
            qty=10, unit_cost=10, reference_type="opening", reference_id="open-1", received_at=self.t1,
        )
        cancelled = OrderInput(
            order_id="o-cancel", platform="pdd", store_name="店铺 A", warehouse_id="kunshan",
            payment_time=self.t2, status="已取消", lines=(),
        )
        before_enable = OrderInput(
            order_id="o-before", platform="pdd", store_name="店铺 A", warehouse_id="kunshan",
            payment_time=self.t1, status="paid", lines=(),
        )
        self.assertEqual(process_order(self.engine, cancelled).inventory_status, "not_applicable")
        self.assertEqual(process_order(self.engine, before_enable, inventory_enabled_from=date(2026, 9, 2)).inventory_status, "not_applicable")
        self.assertEqual(self.engine.available_qty("kunshan", "item-a"), Decimal("10.0000"))

    def test_orders_are_sorted_by_payment_time_then_id(self):
        orders = [
            OrderInput("o-2", "pdd", "店铺", "kunshan", self.t2, "已取消", ()),
            OrderInput("o-1", "pdd", "店铺", "kunshan", self.t1, "已取消", ()),
        ]
        self.assertEqual([r.order_id for r in process_orders(self.engine, orders)], ["o-1", "o-2"])

    def test_process_orders_deducts_earlier_payment_first(self):
        self.engine.receive(
            warehouse_id="kunshan", item_id="item-a", batch_id="b1", batch_no="B1",
            qty=1, unit_cost=10, reference_type="opening", reference_id="open-1", received_at=self.t1,
        )
        def make_order(order_id, paid_at):
            return OrderInput(
                order_id=order_id, platform="pdd", store_name="店铺 A", warehouse_id="kunshan",
                payment_time=paid_at, status="paid",
                lines=(OrderLine("bundle-1", 1, 0, (("item-a", 1),)),),
            )
        results = process_orders(self.engine, [make_order("late", self.t2), make_order("early", self.t1)])
        self.assertEqual([r.order_id for r in results], ["early", "late"])
        self.assertEqual(results[0].inventory_status, "deducted")
        self.assertEqual(results[1].inventory_status, "exception")

    def test_import_contract_detects_missing_fields_and_duplicates(self):
        frame = __import__("pandas").DataFrame([
            {"order_id": "o-1", "product_id": "p-1", "style_id": "s-1", "quantity": 1, "pay_time": "2026-09-01"},
            {"order_id": "o-1", "product_id": "p-1", "style_id": "s-1", "quantity": 1, "pay_time": "2026-09-01"},
            {"order_id": "o-2", "product_id": "p-2", "style_id": "s-2", "quantity": 0, "pay_time": ""},
        ])
        check = validate_order_frame(frame)
        self.assertEqual(check.rows, 3)
        self.assertEqual(check.unique_order_ids, 2)
        self.assertEqual(check.duplicate_order_lines, 1)
        self.assertEqual(check.missing_payment_times, 1)
        self.assertEqual(check.status, "partial")
        with self.assertRaises(ImportValidationError):
            validate_order_frame(frame.drop(columns=["product_id"]))


if __name__ == "__main__":
    unittest.main()
