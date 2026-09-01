"""订单导入与库存边界。

该模块把平台订单转换成库存动作：先按支付时间升序处理，组合商品展开 BOM，
每个单品独立尝试 FIFO 扣减；某个单品库存不足时保留经营数据并记录异常，不产生负库存。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, List, Optional

from .inventory_engine import BatchAllocation, InsufficientStock, InventoryEngine, expand_bundle, money, quantity


@dataclass(frozen=True)
class OrderLine:
    bundle_id: str
    quantity: Decimal
    expected_shipping_fee: Decimal
    bom: tuple[tuple[str, Decimal], ...]


@dataclass(frozen=True)
class OrderInput:
    order_id: str
    platform: str
    store_name: str
    warehouse_id: str
    payment_time: datetime
    status: str
    lines: tuple[OrderLine, ...]


@dataclass(frozen=True)
class InventoryExceptionRecord:
    order_id: str
    warehouse_id: str
    item_id: str
    requested_qty: Decimal
    available_qty: Decimal
    message: str


@dataclass
class OrderInventoryResult:
    order_id: str
    should_deduct: bool
    product_cost: Decimal = Decimal("0")
    shipping_fee: Decimal = Decimal("0")
    allocations: List[BatchAllocation] | None = None
    exceptions: List[InventoryExceptionRecord] | None = None
    allocation_refs: List[str] | None = None

    def __post_init__(self) -> None:
        self.product_cost = money(self.product_cost)
        self.shipping_fee = money(self.shipping_fee)
        self.allocations = self.allocations or []
        self.exceptions = self.exceptions or []
        self.allocation_refs = self.allocation_refs or []

    @property
    def total_cost(self) -> Decimal:
        return money(self.product_cost + self.shipping_fee)

    @property
    def inventory_status(self) -> str:
        if not self.should_deduct:
            return "not_applicable"
        return "exception" if self.exceptions else "deducted"


def _is_deductible(status: str) -> bool:
    normalized = status.strip().lower()
    if any(token in normalized for token in ("cancel", "closed", "退款", "取消", "关闭")):
        return False
    return normalized in {"paid", "payment_success", "支付成功", "待发货", "待揽收", "待发货/待揽收"}


def process_order(
    engine: InventoryEngine,
    order: OrderInput,
    *,
    inventory_enabled_from: Optional[date] = None,
) -> OrderInventoryResult:
    """处理单笔订单，快递费按订单内组合商品预计快递费之和计算。"""
    shipping_fee = money(sum((quantity(line.quantity) * money(line.expected_shipping_fee) for line in order.lines), Decimal("0")))
    enabled = inventory_enabled_from is None or order.payment_time.date() >= inventory_enabled_from
    should_deduct = enabled and _is_deductible(order.status)
    result = OrderInventoryResult(order_id=order.order_id, should_deduct=should_deduct, shipping_fee=shipping_fee)
    if not should_deduct:
        return result

    requirements: dict[str, Decimal] = {}
    for line in order.lines:
        for item_id, requested_qty in expand_bundle(line.bom, line.quantity).items():
            requirements[item_id] = quantity(requirements.get(item_id, Decimal("0")) + requested_qty)

    # 先整体预检查，避免同一订单出现“部分单品已扣、部分单品异常”的半成功状态。
    for item_id, requested_qty in requirements.items():
        available = engine.available_qty(order.warehouse_id, item_id)
        if available < requested_qty:
            result.exceptions.append(InventoryExceptionRecord(
                order_id=order.order_id,
                warehouse_id=order.warehouse_id,
                item_id=item_id,
                requested_qty=requested_qty,
                available_qty=available,
                message=f"库存不足：仓库={order.warehouse_id}，单品={item_id}，需要={requested_qty}，可用={available}",
            ))
    if result.exceptions:
        return result

    allocation_refs: List[str] = []
    for item_id, requested_qty in requirements.items():
        allocation_ref = f"{order.order_id}:{item_id}"
        cost, allocations = engine.allocate_fifo(
            warehouse_id=order.warehouse_id,
            item_id=item_id,
            qty=requested_qty,
            order_id=allocation_ref,
            occurred_at=order.payment_time,
        )
        result.product_cost = money(result.product_cost + cost)
        result.allocations.extend(allocations)
        allocation_refs.append(allocation_ref)
    engine.register_order_group(order.order_id, allocation_refs)
    result.allocation_refs = allocation_refs
    return result


def process_orders(
    engine: InventoryEngine,
    orders: Iterable[OrderInput],
    *,
    inventory_enabled_from: Optional[date] = None,
) -> List[OrderInventoryResult]:
    """按支付时间升序处理订单；同一时间以订单号保证确定性。"""
    ordered = sorted(orders, key=lambda order: (order.payment_time, order.order_id))
    return [process_order(engine, order, inventory_enabled_from=inventory_enabled_from) for order in ordered]
