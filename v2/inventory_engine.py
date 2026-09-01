"""库存与成本领域引擎。

这个模块故意不依赖 Web 框架或数据库，便于先用确定性测试锁定业务规则。
数据库适配层只需要把这些事件持久化到 inventory_transactions 和相关表。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Iterable, List, Optional, Sequence


MONEY_SCALE = Decimal("0.000001")
QTY_SCALE = Decimal("0.0001")


def dec(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value))


def money(value: Decimal | int | float | str) -> Decimal:
    return dec(value).quantize(MONEY_SCALE, rounding=ROUND_HALF_UP)


def quantity(value: Decimal | int | float | str) -> Decimal:
    return dec(value).quantize(QTY_SCALE, rounding=ROUND_HALF_UP)


class InventoryError(Exception):
    """领域规则错误。"""


class InsufficientStock(InventoryError):
    def __init__(self, warehouse_id: str, item_id: str, requested: Decimal, available: Decimal):
        self.warehouse_id = warehouse_id
        self.item_id = item_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"库存不足：仓库={warehouse_id}，单品={item_id}，需要={requested}，可用={available}"
        )


@dataclass
class Batch:
    batch_id: str
    warehouse_id: str
    item_id: str
    batch_no: str
    received_at: datetime
    received_qty: Decimal
    remaining_qty: Decimal
    unit_cost: Decimal
    stock_status: str = "sellable"

    def __post_init__(self) -> None:
        self.received_qty = quantity(self.received_qty)
        self.remaining_qty = quantity(self.remaining_qty)
        self.unit_cost = money(self.unit_cost)
        if self.stock_status not in {"sellable", "inspection", "defective", "scrapped"}:
            raise InventoryError(f"库存状态无效：{self.stock_status}")

    @property
    def sellable(self) -> bool:
        return self.stock_status == "sellable"


@dataclass
class CostBalance:
    warehouse_id: str
    item_id: str
    quantity: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")

    @property
    def average_cost(self) -> Decimal:
        if self.quantity <= 0:
            return money(0)
        return money(self.total_cost / self.quantity)


@dataclass(frozen=True)
class BatchAllocation:
    batch_id: str
    batch_no: str
    quantity: Decimal
    batch_unit_cost: Decimal


@dataclass(frozen=True)
class LedgerEntry:
    transaction_type: str
    warehouse_id: str
    item_id: str
    quantity: Decimal
    unit_cost: Decimal
    reference_type: str
    reference_id: str
    batch_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class PurchaseReceiptLine:
    item_id: str
    batch_id: str
    batch_no: str
    quantity: Decimal
    base_unit_cost: Decimal
    line_amount: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", quantity(self.quantity))
        object.__setattr__(self, "base_unit_cost", money(self.base_unit_cost))
        object.__setattr__(self, "line_amount", money(self.line_amount))
        if self.quantity <= 0:
            raise InventoryError("采购数量必须大于 0")
        if self.base_unit_cost < 0 or self.line_amount < 0:
            raise InventoryError("采购成本不能为负数")


@dataclass
class PurchaseReceipt:
    receipt_no: str
    warehouse_id: str
    lines: tuple[PurchaseReceiptLine, ...]
    freight_fee: Decimal = Decimal("0")
    other_fee: Decimal = Decimal("0")
    status: str = "draft"
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        self.freight_fee = money(self.freight_fee)
        self.other_fee = money(self.other_fee)
        if self.freight_fee < 0 or self.other_fee < 0:
            raise InventoryError("采购费用不能为负数")
        if self.status not in {"draft", "approved", "rejected", "void"}:
            raise InventoryError(f"采购单状态无效：{self.status}")


class InventoryEngine:
    """内存中的库存账本，作为数据库事务的参考实现。

    重要保证：
    1. 扣库前先做总量预检查，库存不足不会发生部分扣减。
    2. 扣库只改变批次剩余数量，不改变加权平均成本余额。
    3. 入库同时更新批次和加权平均成本。
    4. 销售出库保存实际批次分配，便于未发货取消按原批次冲销。
    """

    def __init__(self) -> None:
        self.batches: Dict[str, Batch] = {}
        self.costs: Dict[tuple[str, str], CostBalance] = {}
        self.ledger: List[LedgerEntry] = []
        self.order_allocations: Dict[str, List[BatchAllocation]] = {}
        self.order_average_cost: Dict[str, Decimal] = {}
        # 一个组合订单可能展开成多个单品扣库引用，保留订单级索引才能完整冲销。
        self.order_groups: Dict[str, List[str]] = {}
        self.reversed_orders: set[str] = set()
        self.purchase_receipts: Dict[str, PurchaseReceipt] = {}

    def _balance(self, warehouse_id: str, item_id: str) -> CostBalance:
        key = (warehouse_id, item_id)
        if key not in self.costs:
            self.costs[key] = CostBalance(warehouse_id, item_id)
        return self.costs[key]

    def available_qty(self, warehouse_id: str, item_id: str) -> Decimal:
        return quantity(
            sum(
                (b.remaining_qty for b in self.batches.values()
                 if b.warehouse_id == warehouse_id and b.item_id == item_id and b.sellable),
                Decimal("0"),
            )
        )

    def average_cost(self, warehouse_id: str, item_id: str) -> Decimal:
        return self._balance(warehouse_id, item_id).average_cost

    def receive(
        self,
        *,
        warehouse_id: str,
        item_id: str,
        batch_id: str,
        batch_no: str,
        qty: Decimal | int | float | str,
        unit_cost: Decimal | int | float | str,
        reference_type: str,
        reference_id: str,
        received_at: Optional[datetime] = None,
        sellable: bool = True,
        stock_status: Optional[str] = None,
    ) -> Batch:
        qty_d = quantity(qty)
        if qty_d <= 0:
            raise InventoryError("入库数量必须大于 0")
        cost_d = money(unit_cost)
        if cost_d < 0:
            raise InventoryError("入库成本不能为负数")
        if batch_id in self.batches:
            raise InventoryError(f"批次已存在：{batch_id}")

        resolved_status = stock_status or ("sellable" if sellable else "inspection")
        batch = Batch(
            batch_id=batch_id,
            warehouse_id=warehouse_id,
            item_id=item_id,
            batch_no=batch_no,
            received_at=received_at or datetime.now(timezone.utc),
            received_qty=qty_d,
            remaining_qty=qty_d,
            unit_cost=cost_d,
            stock_status=resolved_status,
        )
        self.batches[batch_id] = batch

        # 加权平均余额只统计可售库存；待检/残次/报废不进入可售成本池。
        if batch.sellable:
            balance = self._balance(warehouse_id, item_id)
            balance.quantity = quantity(balance.quantity + qty_d)
            balance.total_cost = money(balance.total_cost + qty_d * cost_d)

        self.ledger.append(LedgerEntry(
            transaction_type="receipt",
            warehouse_id=warehouse_id,
            item_id=item_id,
            quantity=qty_d,
            unit_cost=cost_d,
            reference_type=reference_type,
            reference_id=reference_id,
            batch_id=batch_id,
        ))
        return batch

    def create_purchase_receipt(
        self,
        *,
        receipt_no: str,
        warehouse_id: str,
        lines: Sequence[PurchaseReceiptLine],
        freight_fee: Decimal | int | float | str = 0,
        other_fee: Decimal | int | float | str = 0,
    ) -> PurchaseReceipt:
        """创建采购入库单；创建阶段只落单，不改变库存和成本。"""
        if not receipt_no.strip():
            raise InventoryError("采购单号不能为空")
        if receipt_no in self.purchase_receipts:
            raise InventoryError(f"采购单已存在：{receipt_no}")
        normalized = tuple(lines)
        if not normalized:
            raise InventoryError("采购单至少需要一行商品")
        batch_ids = [line.batch_id for line in normalized]
        if len(batch_ids) != len(set(batch_ids)) or any(batch_id in self.batches for batch_id in batch_ids):
            raise InventoryError("采购单包含重复或已存在的批次")
        receipt = PurchaseReceipt(
            receipt_no=receipt_no,
            warehouse_id=warehouse_id,
            lines=normalized,
            freight_fee=freight_fee,
            other_fee=other_fee,
        )
        self.purchase_receipts[receipt_no] = receipt
        return receipt

    def approve_purchase_receipt(self, receipt_no: str, *, approved_by: str) -> PurchaseReceipt:
        """审核采购入库单，审核成功后才写入批次、库存余额和成本池。"""
        receipt = self.purchase_receipts.get(receipt_no)
        if receipt is None:
            raise InventoryError(f"找不到采购单：{receipt_no}")
        if receipt.status != "draft":
            raise InventoryError(f"只有草稿采购单可以审核：{receipt_no}")
        landed_costs = allocate_purchase_fees(
            [
                (line.item_id, line.quantity, line.base_unit_cost, line.line_amount)
                for line in receipt.lines
            ],
            receipt.freight_fee + receipt.other_fee,
        )
        occurred_at = datetime.now(timezone.utc)
        for line in receipt.lines:
            self.receive(
                warehouse_id=receipt.warehouse_id,
                item_id=line.item_id,
                batch_id=line.batch_id,
                batch_no=line.batch_no,
                qty=line.quantity,
                unit_cost=landed_costs[line.item_id],
                reference_type="purchase",
                reference_id=receipt.receipt_no,
                received_at=occurred_at,
            )
        receipt.status = "approved"
        receipt.approved_by = approved_by
        receipt.approved_at = occurred_at
        return receipt

    def receive_customer_return(
        self,
        *,
        warehouse_id: str,
        item_id: str,
        batch_id: str,
        batch_no: str,
        qty: Decimal | int | float | str,
        unit_cost: Decimal | int | float | str,
        order_id: str,
        confirmed_received: bool,
        received_at: Optional[datetime] = None,
    ) -> Batch:
        """已发货退货确认收货后进入待检；未确认不得恢复库存。"""
        if not confirmed_received:
            raise InventoryError("退货尚未确认收货，不能入库")
        return self.receive(
            warehouse_id=warehouse_id,
            item_id=item_id,
            batch_id=batch_id,
            batch_no=batch_no,
            qty=qty,
            unit_cost=unit_cost,
            reference_type="customer_return",
            reference_id=order_id,
            received_at=received_at,
            stock_status="inspection",
        )

    def approve_inspection(self, batch_id: str, target_status: str) -> Batch:
        """将待检批次审核为可售、残次或报废。"""
        if target_status not in {"sellable", "defective", "scrapped"}:
            raise InventoryError(f"待检审核状态无效：{target_status}")
        batch = self.batches.get(batch_id)
        if batch is None:
            raise InventoryError(f"找不到批次：{batch_id}")
        if batch.stock_status != "inspection":
            raise InventoryError(f"只有待检批次可以审核：{batch_id}")
        batch.stock_status = target_status
        if target_status == "sellable" and batch.remaining_qty > 0:
            balance = self._balance(batch.warehouse_id, batch.item_id)
            balance.quantity = quantity(balance.quantity + batch.remaining_qty)
            balance.total_cost = money(balance.total_cost + batch.remaining_qty * batch.unit_cost)
        return batch

    def allocate_fifo(
        self,
        *,
        warehouse_id: str,
        item_id: str,
        qty: Decimal | int | float | str,
        order_id: str,
        occurred_at: Optional[datetime] = None,
    ) -> tuple[Decimal, List[BatchAllocation]]:
        qty_d = quantity(qty)
        if qty_d <= 0:
            raise InventoryError("出库数量必须大于 0")
        if order_id in self.order_allocations:
            raise InventoryError(f"订单已经扣过库存：{order_id}")

        available = self.available_qty(warehouse_id, item_id)
        if available < qty_d:
            raise InsufficientStock(warehouse_id, item_id, qty_d, available)

        candidates = sorted(
            (b for b in self.batches.values()
             if b.warehouse_id == warehouse_id and b.item_id == item_id
             and b.sellable and b.remaining_qty > 0),
            key=lambda b: (b.received_at, b.batch_id),
        )

        remaining = qty_d
        allocations: List[BatchAllocation] = []
        for batch in candidates:
            if remaining <= 0:
                break
            taken = min(batch.remaining_qty, remaining)
            batch.remaining_qty = quantity(batch.remaining_qty - taken)
            remaining = quantity(remaining - taken)
            allocations.append(BatchAllocation(batch.batch_id, batch.batch_no, taken, batch.unit_cost))
            self.ledger.append(LedgerEntry(
                transaction_type="sale",
                warehouse_id=warehouse_id,
                item_id=item_id,
                quantity=-taken,
                unit_cost=batch.unit_cost,
                reference_type="order",
                reference_id=order_id,
                batch_id=batch.batch_id,
                created_at=occurred_at or datetime.now(timezone.utc),
            ))

        # total_cost 按订单发生前的加权平均成本核算，实际批次成本通过 allocations 追溯。
        balance = self._balance(warehouse_id, item_id)
        average_before_sale = balance.average_cost
        balance.quantity = quantity(balance.quantity - qty_d)
        balance.total_cost = money(balance.total_cost - qty_d * average_before_sale)
        self.order_allocations[order_id] = allocations
        self.order_average_cost[order_id] = average_before_sale
        return money(qty_d * average_before_sale), allocations

    def reverse_order(self, order_id: str, *, reference_id: Optional[str] = None) -> List[BatchAllocation]:
        allocations = self.order_allocations.get(order_id)
        if not allocations:
            raise InventoryError(f"找不到订单扣库记录：{order_id}")
        if order_id in self.reversed_orders:
            raise InventoryError(f"订单已经冲销：{order_id}")

        total_qty = Decimal("0")
        for allocation in allocations:
            batch = self.batches[allocation.batch_id]
            batch.remaining_qty = quantity(batch.remaining_qty + allocation.quantity)
            total_qty += allocation.quantity
        average_cost = self.order_average_cost.get(order_id)
        if average_cost is None:
            raise InventoryError(f"找不到订单成本快照：{order_id}")
        total_cost = total_qty * average_cost
        for allocation in allocations:
            batch = self.batches[allocation.batch_id]
            self.ledger.append(LedgerEntry(
                transaction_type="sale_reversal",
                warehouse_id=batch.warehouse_id,
                item_id=batch.item_id,
                quantity=allocation.quantity,
                unit_cost=allocation.batch_unit_cost,
                reference_type="reversal",
                reference_id=reference_id or order_id,
                batch_id=batch.batch_id,
            ))

        # 冲销恢复的是原来的成本池，不重新按当前成本计算。
        first_batch = self.batches[allocations[0].batch_id]
        balance = self._balance(first_batch.warehouse_id, first_batch.item_id)
        balance.quantity = quantity(balance.quantity + total_qty)
        balance.total_cost = money(balance.total_cost + total_cost)
        self.reversed_orders.add(order_id)
        return allocations

    def register_order_group(self, order_id: str, allocation_refs: Sequence[str]) -> None:
        """登记一个订单展开后的所有单品扣库引用，供取消时整体冲销。"""
        refs = [str(ref) for ref in allocation_refs if str(ref)]
        if not refs:
            return
        if order_id in self.order_groups:
            raise InventoryError(f"订单已经登记扣库分组：{order_id}")
        self.order_groups[order_id] = refs

    def reverse_order_group(self, order_id: str, *, reference_id: Optional[str] = None) -> List[BatchAllocation]:
        """按原批次整体冲销订单，支持多单品组合订单。"""
        if order_id in self.reversed_orders:
            raise InventoryError(f"订单已经冲销：{order_id}")
        refs = self.order_groups.get(order_id)
        if not refs:
            # 兼容单品订单直接以原订单号扣库的旧调用方式。
            return self.reverse_order(order_id, reference_id=reference_id)
        restored: List[BatchAllocation] = []
        for ref in refs:
            restored.extend(self.reverse_order(ref, reference_id=reference_id or order_id))
        self.reversed_orders.add(order_id)
        return restored


def expand_bundle(bom: Iterable[tuple[str, Decimal | int | float | str]], bundle_qty: Decimal | int | float | str) -> Dict[str, Decimal]:
    """将组合商品数量展开成单品需求。"""
    multiplier = quantity(bundle_qty)
    if multiplier <= 0:
        raise InventoryError("组合商品购买数量必须大于 0")
    result: Dict[str, Decimal] = {}
    for item_id, component_qty in bom:
        component = quantity(component_qty)
        if component <= 0:
            raise InventoryError(f"BOM 用量必须大于 0：{item_id}")
        result[item_id] = quantity(result.get(item_id, Decimal("0")) + component * multiplier)
    return result


def allocate_purchase_fees(
    lines: Sequence[tuple[str, Decimal | int | float | str, Decimal | int | float | str, Decimal | int | float | str]],
    fees: Decimal | int | float | str,
) -> Dict[str, Decimal]:
    """按采购行金额分摊费用，返回每个单品的落地单位成本。

    lines 为 (item_id, quantity, base_unit_cost, line_amount)。金额全部为零时，
    自动退化为按数量分摊，避免采购单无法入账。
    """
    fee_d = money(fees)
    if fee_d < 0:
        raise InventoryError("采购费用不能为负数")
    normalized = [(item_id, quantity(qty), money(unit_cost), money(amount)) for item_id, qty, unit_cost, amount in lines]
    if any(qty <= 0 for _, qty, _, _ in normalized):
        raise InventoryError("采购数量必须大于 0")
    total_amount = sum((amount for _, _, _, amount in normalized), Decimal("0"))
    total_qty = sum((qty for _, qty, _, _ in normalized), Decimal("0"))
    result: Dict[str, Decimal] = {}
    for item_id, qty, unit_cost, amount in normalized:
        ratio = (amount / total_amount) if total_amount > 0 else (qty / total_qty)
        result[item_id] = money(unit_cost + fee_d * ratio / qty)
    return result
