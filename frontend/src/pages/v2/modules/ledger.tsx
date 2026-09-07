import { useCallback, useEffect, useState } from "react"
import { FilterBar, FilterItem, PageHeader } from "@/components/page-kit"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { ReportTable, type ReportColumn } from "../components/report-table"
import { StatusBadge } from "../components/status-badge"
import { cn } from "@/lib/utils"
import { fmtMoney, fmtQty, fmtTime, qs, request } from "../api"

interface Config {
  warehouses: { code: string; name: string }[]
  inventory: { enabled_from: string }
}
interface LedgerRow {
  id: number
  transaction_type: string
  biz_type: string | null
  warehouse_code: string
  item_code: string
  quantity: number
  batch_unit_cost: number
  average_unit_cost: number
  reference_type: string
  reference_id: string
  occurred_at: string
}

const PAGE_SIZE = 200

const TX_TYPES = [
  { value: "", label: "全部类型" },
  { value: "opening", label: "期初" },
  { value: "purchase", label: "采购入库" },
  { value: "sale", label: "销售出库" },
  { value: "sale_reversal", label: "销售冲销" },
  { value: "customer_return", label: "退货入库" },
  { value: "other_in", label: "其它入库" },
  { value: "other_out", label: "其它出库" },
  { value: "adjustment", label: "调整" },
  { value: "supplier_return", label: "供应商退货" },
]

const toDate = (d: Date) => d.toISOString().slice(0, 10)
const defaultRange = () => {
  const end = new Date()
  const start = new Date()
  start.setDate(start.getDate() - 29)
  return { start: toDate(start), end: toDate(end) }
}

export function LedgerModule() {
  const [config, setConfig] = useState<Config | null>(null)
  const [rows, setRows] = useState<LedgerRow[]>([])
  const [{ start, end }, setRange] = useState(defaultRange)
  const [warehouse, setWarehouse] = useState("")
  const [itemCode, setItemCode] = useState("")
  const [txType, setTxType] = useState("")
  const [bizType, setBizType] = useState("")
  const [bizTypes, setBizTypes] = useState<string[]>([])
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  const warehouseName = (code: string) => config?.warehouses?.find((w) => w.code === code)?.name || code

  useEffect(() => {
    request<Config>("/api/v2/config")
      .then(setConfig)
      .catch(() => undefined)
    request<string[]>("/api/v2/inventory/ledger/biz-types")
      .then((data) => setBizTypes(Array.isArray(data) ? data : []))
      .catch(() => undefined)
  }, [])

  const query = useCallback(
    (nextOffset: number) => {
      setLoading(true)
      setError("")
      const queryString = qs({
        limit: PAGE_SIZE,
        offset: nextOffset,
        start_date: start,
        end_date: end,
        warehouse,
        item_code: itemCode.trim(),
        transaction_type: txType,
        biz_type: bizType,
      })
      request<LedgerRow[]>(`/api/v2/inventory/ledger${queryString}`)
        .then((data) => {
          setRows(Array.isArray(data) ? data : [])
          setOffset(nextOffset)
        })
        .catch((e) => {
          setRows([])
          setError(e?.message || "查询失败")
        })
        .finally(() => setLoading(false))
    },
    [start, end, warehouse, itemCode, txType, bizType]
  )

  useEffect(() => {
    query(0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const page = Math.floor(offset / PAGE_SIZE) + 1
  const hasNext = rows.length >= PAGE_SIZE

  const columns: ReportColumn<LedgerRow>[] = [
    { key: "occurred_at", label: "发生时间", render: (r) => fmtTime(r.occurred_at) },
    { key: "transaction_type", label: "类型", render: (r) => <StatusBadge value={r.transaction_type} /> },
    { key: "biz_type", label: "业务类型", render: (r) => r.biz_type || "—" },
    { key: "warehouse_code", label: "仓库", render: (r) => warehouseName(r.warehouse_code) },
    { key: "item_code", label: "单品" },
    {
      key: "quantity",
      label: "数量",
      align: "right",
      render: (r) => (
        <span className={cn((Number(r.quantity) || 0) < 0 && "text-destructive")}>{fmtQty(r.quantity)}</span>
      ),
    },
    { key: "batch_unit_cost", label: "批次成本", align: "right", render: (r) => fmtMoney(r.batch_unit_cost) },
    { key: "average_unit_cost", label: "平均成本", align: "right", render: (r) => fmtMoney(r.average_unit_cost) },
    { key: "reference_type", label: "引用类型", render: (r) => r.reference_type || "—" },
    { key: "reference_id", label: "引用号", render: (r) => r.reference_id || "—" },
  ]

  return (
    <div>
      <PageHeader title="库存流水" description="库存交易明细，数量正数为入库、负数为出库" />
      {error && (
        <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-3.5 py-2.5 text-sm text-destructive">{error}</div>
      )}

      <FilterBar>
        <FilterItem label="开始日期">
          <Input type="date" value={start} onChange={(e) => setRange((r) => ({ ...r, start: e.target.value }))} />
        </FilterItem>
        <FilterItem label="结束日期">
          <Input type="date" value={end} onChange={(e) => setRange((r) => ({ ...r, end: e.target.value }))} />
        </FilterItem>
        <FilterItem label="仓库">
          <Select value={warehouse} onChange={(e) => setWarehouse(e.target.value)}>
            <option value="">全部仓库</option>
            {(config?.warehouses || []).map((w) => (
              <option key={w.code} value={w.code}>
                {w.name}
              </option>
            ))}
          </Select>
        </FilterItem>
        <FilterItem label="单品编码">
          <Input placeholder="精确匹配单品编码" value={itemCode} onChange={(e) => setItemCode(e.target.value)} />
        </FilterItem>
        <FilterItem label="交易类型">
          <Select value={txType} onChange={(e) => setTxType(e.target.value)}>
            {TX_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </Select>
        </FilterItem>
        <FilterItem label="业务类型">
          <Select value={bizType} onChange={(e) => setBizType(e.target.value)}>
            <option value="">全部业务类型</option>
            {bizTypes.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </Select>
        </FilterItem>
        <Button onClick={() => query(0)} disabled={loading}>
          {loading ? "查询中" : "查询"}
        </Button>
      </FilterBar>

      <ReportTable
        columns={columns}
        rows={rows}
        loading={loading}
        rowKey={(r) => r.id}
        emptyTitle="暂无流水记录"
        emptyHint="调整日期区间或筛选条件后重新查询"
        footer={
          <div className="flex items-center justify-between border-t px-3.5 py-2.5">
            <span className="text-xs text-muted-foreground">
              第 {page} 页 · 每页 {PAGE_SIZE} 条
            </span>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" disabled={loading || offset === 0} onClick={() => query(Math.max(offset - PAGE_SIZE, 0))}>
                上一页
              </Button>
              <Button variant="outline" size="sm" disabled={loading || !hasNext} onClick={() => query(offset + PAGE_SIZE)}>
                下一页
              </Button>
            </div>
          </div>
        }
      />
    </div>
  )
}
