-- 生产事务模板（PostgreSQL 15+）
-- 应用层在一个短事务中执行：外部文件解析和平台 API 调用不得放在事务内。

-- 1) 订单扣库前锁定所有相关余额行，顺序固定为 warehouse_id + item_id，降低死锁概率。
begin;
set local statement_timeout = '10s';

select warehouse_id, item_id
from inventory_balances
where warehouse_id = :warehouse_id
  and item_id = any(:item_ids)
order by warehouse_id, item_id
for update;

-- 2) FIFO 候选批次必须按 received_at + id 排序并加行锁；库存不足时由应用层回滚本事务，
--    订单本身仍写入 platform_orders，inventory_status='exception'。
select id, item_id, remaining_qty, unit_cost
from inventory_batches
where warehouse_id = :warehouse_id
  and item_id = :item_id
  and stock_status = 'sellable'
  and remaining_qty > 0
order by received_at, id
for update;

-- 3) 所有库存交易使用幂等键；重复导入直接冲突转为已处理，不允许重复扣库。
insert into inventory_transactions (
    warehouse_id, item_id, batch_id, transaction_type, quantity,
    batch_unit_cost, average_unit_cost, reference_type, reference_id,
    idempotency_key, occurred_at
) values (
    :warehouse_id, :item_id, :batch_id, 'sale', :negative_qty,
    :batch_unit_cost, :average_unit_cost, 'order', :order_id,
    :idempotency_key, :payment_time
)
on conflict (idempotency_key) do nothing;

commit;

-- 生产实现说明：
-- * 订单按 payment_time, order_id 升序批处理。
-- * 一笔订单的所有 BOM 展开单品先做总量预检查，再统一扣减，防止部分扣减。
-- * 取消订单仅在“未发货”状态调用 reversal，并使用 order_batch_allocations 原批次恢复。
-- * 已发货退货先进入 inspection，人工审核后才生成 customer_return 入库交易。
