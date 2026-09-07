import { Badge } from "@/components/ui/badge"

type Variant = "default" | "secondary" | "destructive" | "outline" | "success"

/** 全域状态 → Badge 文案与变体映射 */
const MAP: Record<string, { label: string; variant: Variant }> = {
  // 订单库存状态
  legacy: { label: "历史", variant: "secondary" },
  pending: { label: "待扣", variant: "outline" },
  deducted: { label: "已扣", variant: "success" },
  exception: { label: "异常", variant: "destructive" },
  reversed: { label: "已冲销", variant: "secondary" },
  not_applicable: { label: "不适用", variant: "outline" },
  // 库存交易类型
  opening: { label: "期初", variant: "secondary" },
  purchase: { label: "采购入库", variant: "default" },
  sale: { label: "销售出库", variant: "default" },
  sale_reversal: { label: "销售冲销", variant: "secondary" },
  customer_return: { label: "退货入库", variant: "default" },
  other_in: { label: "其它入库", variant: "outline" },
  other_out: { label: "其它出库", variant: "outline" },
  adjustment: { label: "调整", variant: "outline" },
  supplier_return: { label: "供应商退货", variant: "outline" },
  // 批次状态
  sellable: { label: "可售", variant: "success" },
  inspection: { label: "待检", variant: "secondary" },
  defective: { label: "残次", variant: "destructive" },
  scrapped: { label: "报废", variant: "destructive" },
  // 采购单 / 退货单状态
  draft: { label: "草稿", variant: "outline" },
  approved: { label: "已审核", variant: "success" },
  received: { label: "已收货", variant: "default" },
  inspected: { label: "已检验", variant: "default" },
  completed: { label: "已完成", variant: "success" },
  rejected: { label: "已拒绝", variant: "destructive" },
  void: { label: "已作废", variant: "secondary" },
  // 导入批次状态
  processing: { label: "处理中", variant: "default" },
  succeeded: { label: "成功", variant: "success" },
  partial: { label: "部分成功", variant: "secondary" },
  failed: { label: "失败", variant: "destructive" },
  rolled_back: { label: "已回滚", variant: "secondary" },
  imported: { label: "已导入", variant: "success" },
  invalidated: { label: "已失效", variant: "outline" },
  // 异常状态
  open: { label: "待处理", variant: "destructive" },
  resolved: { label: "已解决", variant: "success" },
  cancelled: { label: "已取消", variant: "secondary" },
}

/** 状态徽章：未知值原样显示（outline） */
export function StatusBadge({ value, className }: { value: any; className?: string }) {
  const key = String(value ?? "")
  const hit = MAP[key]
  return (
    <Badge variant={hit?.variant ?? "outline"} className={className}>
      {hit?.label ?? (key || "—")}
    </Badge>
  )
}
