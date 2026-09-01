"""V2 库存全生命周期本地演练。

不连接旧版线上数据，也不依赖数据库。用于在接 PostgreSQL 前锁定业务结果，
并输出一份可人工核对的 JSON 摘要。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from .inventory_engine import InventoryEngine, PurchaseReceiptLine, allocate_purchase_fees
from .order_engine import OrderInput, OrderLine, process_order, process_orders


INVENTORY_ENABLED_FROM = date(2026, 9, 15)
WAREHOUSES = ("kunshan", "huihuang", "waigaoqiao")


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def run_workflow() -> dict[str, Any]:
    engine = InventoryEngine()
    enabled_at = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)

    # 上线日盘点形成虚拟期初批次；这里仅构造昆山仓，其余仓库保持零库存。
    engine.receive(
        warehouse_id="kunshan", item_id="item-a", batch_id="opening-a", batch_no="LEGACY-OPENING-A",
        qty=100, unit_cost=10, reference_type="opening", reference_id="opening-20260915", received_at=enabled_at,
    )
    engine.receive(
        warehouse_id="kunshan", item_id="item-b", batch_id="opening-b", batch_no="LEGACY-OPENING-B",
        qty=80, unit_cost=5, reference_type="opening", reference_id="opening-20260915", received_at=enabled_at,
    )

    # 采购费用按采购金额分摊进落地成本，审核后入可售库存。
    landed_costs = allocate_purchase_fees(
        [("item-a", 50, 12, 600), ("item-b", 20, 8, 160)],
        fees=76,
    )
    engine.create_purchase_receipt(
        receipt_no="PO-001",
        warehouse_id="kunshan",
        lines=(
            PurchaseReceiptLine("item-a", "purchase-a", "PO-001-A", 50, 12, 600),
            PurchaseReceiptLine("item-b", "purchase-b", "PO-001-B", 20, 8, 160),
        ),
        freight_fee=60,
        other_fee=16,
    )
    engine.approve_purchase_receipt("PO-001", approved_by="buyer")

    def order(order_id: str, paid_at: datetime, quantity: int) -> OrderInput:
        return OrderInput(
            order_id=order_id,
            platform="pdd",
            store_name="本地演练店铺",
            warehouse_id="kunshan",
            payment_time=paid_at,
            status="支付成功",
            lines=(
                OrderLine(
                    bundle_id="bundle-ab-v1",
                    quantity=quantity,
                    expected_shipping_fee=4,
                    bom=(("item-a", 1), ("item-b", 2)),
                ),
            ),
        )

    # 故意倒序传入，验证系统仍按支付时间升序扣库。
    processed = process_orders(
        engine,
        [
            order("order-later", enabled_at + timedelta(hours=4), 2),
            order("order-earlier", enabled_at + timedelta(hours=3), 3),
        ],
        inventory_enabled_from=INVENTORY_ENABLED_FROM,
    )

    # 未发货取消，按原订单实际批次整体冲销。
    engine.reverse_order_group("order-earlier", reference_id="cancel-order-earlier")

    # 已发货退货确认入库后先进入待检，再审核为可售。
    return_batch = engine.receive_customer_return(
        warehouse_id="kunshan", item_id="item-a", batch_id="return-a", batch_no="RETURN-001-A",
        qty=1, unit_cost=engine.average_cost("kunshan", "item-a"), order_id="RETURN-001",
        confirmed_received=True, received_at=enabled_at + timedelta(hours=5),
    )
    available_before_approval = engine.available_qty("kunshan", "item-a")
    engine.approve_inspection(return_batch.batch_id, "sellable")

    # 库存不足的订单照常形成经营结果，但不产生部分扣库或负库存。
    exception_result = process_order(
        engine,
        order("order-insufficient", enabled_at + timedelta(hours=6), 999),
        inventory_enabled_from=INVENTORY_ENABLED_FROM,
    )

    return _json_value({
        "inventory_enabled_from": INVENTORY_ENABLED_FROM,
        "warehouses": WAREHOUSES,
        "purchase_landed_unit_costs": landed_costs,
        "processed_order_sequence": [result.order_id for result in processed],
        "processed_orders": [
            {
                "order_id": result.order_id,
                "inventory_status": result.inventory_status,
                "product_cost": result.product_cost,
                "shipping_fee": result.shipping_fee,
                "total_cost": result.total_cost,
                "allocation_refs": result.allocation_refs,
                "allocations": [asdict(allocation) for allocation in result.allocations],
            }
            for result in processed
        ],
        "cancelled_order_restored": "order-earlier" in engine.reversed_orders,
        "return_available_before_approval": available_before_approval,
        "return_status_after_approval": return_batch.stock_status,
        "exception_order_status": exception_result.inventory_status,
        "exception_count": len(exception_result.exceptions),
        "balances": {
            warehouse: {
                item: {
                    "available_qty": engine.available_qty(warehouse, item),
                    "average_cost": engine.average_cost(warehouse, item),
                }
                for item in ("item-a", "item-b")
            }
            for warehouse in WAREHOUSES
        },
        "ledger_entries": len(engine.ledger),
    })


def main() -> None:
    print(json.dumps(run_workflow(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
