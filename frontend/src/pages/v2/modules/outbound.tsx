import { useEffect, useState } from "react"
import { PageHeader, FilterBar, FilterItem } from "@/components/page-kit"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { request, qs, fmtQty, fmtMoney, fmtTime } from "../api"
import { ReportTable, type ReportColumn } from "../components/report-table"
import { StatusBadge } from "../components/status-badge"

interface Warehouse {
  code: string
  name: string
}

interface LedgerRow {
  id: number | string
  transaction_type: string
  biz_type: string | null
  warehouse_code: string
  item_code: string
  quantity: string | number | null
  batch_unit_cost: string | number | null
  average_unit_cost: string | number | null
  reference_type: string | null
  reference_id: string | null
  occurred_at: string | null
}

const TYPE_OPTIONS = [
  { value: "all", label: "全部出库" },
  { value: "sale", label: "销售出库" },
  { value: "other_out", label: "其它出库" },
  { value: "sale_reversal", label: "销售冲销" },
  { value: "supplier_return", label: "供应商退货" },
] as const

const TYPE_VALUES = TYPE_OPTIONS.filter((t) => t.value !== "all").map((t) => t.value)

const dateStr = (d: Date) => d.toISOString().slice(0, 10)

/** 出库流水：库存流水的出库预设视图（销售出库 / 其它出库 / 销售冲销 / 供应商退货） */
export function OutboundModule() {
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [startDate, setStartDate] = useState(() => dateStr(new Date(Date.now() - 29 * 86400000)))
  const [endDate, setEndDate] = useState(() => dateStr(new Date()))
  const [warehouse, setWarehouse] = useState("")
  const [itemCode, setItemCode] = useState("")
  const [type, setType] = useState<string>("all")
  const [bizType, setBizType] = useState("")
  const [bizTypes, setBizTypes] = useState<string[]>([])
  const [rows, setRows] = useState<LedgerRow[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  const load = async () => {
    setLoading(true)
    setError("")
    try {
      const base = { start_date: startDate, end_date: endDate, warehouse, item_code: itemCode.trim(), biz_type: bizType }
      if (type === "all") {
        const results = await Promise.all(
          TYPE_VALUES.map((t) => request<LedgerRow[]>(`/api/v2/inventory/ledger${qs({ ...base, transaction_type: t, limit: 200 })}`))
        )
        const merged = results
          .flat()
          .sort((a, b) => String(b.occurred_at ?? "").localeCompare(String(a.occurred_at ?? "")))
          .slice(0, 200)
        setRows(merged)
      } else {
        const data = await request<LedgerRow[]>(`/api/v2/inventory/ledger${qs({ ...base, transaction_type: type, limit: 200 })}`)
        setRows(data)
      }
    } catch (e: any) {
      setError(e.message || "查询失败")
      setRows([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    request<{ warehouses: Warehouse[] }>("/api/v2/config")
      .then((cfg) => setWarehouses(cfg.warehouses || []))
      .catch(() => {})
    request<string[]>("/api/v2/inventory/ledger/biz-types?direction=out")
      .then((data) => setBizTypes(Array.isArray(data) ? data : []))
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const columns: ReportColumn<LedgerRow>[] = [
    { key: "occurred_at", label: "发生时间", render: (row) => fmtTime(row.occurred_at) },
    { key: "transaction_type", label: "类型", render: (row) => <StatusBadge value={row.transaction_type} /> },
    { key: "biz_type", label: "业务类型", render: (row) => row.biz_type || "—" },
    { key: "warehouse_code", label: "仓库" },
    { key: "item_code", label: "单品" },
    { key: "quantity", label: "数量", align: "right", render: (row) => fmtQty(row.quantity) },
    { key: "batch_unit_cost", label: "批次成本", align: "right", render: (row) => fmtMoney(row.batch_unit_cost) },
    { key: "average_unit_cost", label: "平均成本", align: "right", render: (row) => fmtMoney(row.average_unit_cost) },
    { key: "reference_id", label: "引用号", render: (row) => row.reference_id || "—" },
  ]

  return (
    <div>
      <PageHeader title="出库流水" description="库存流水的出库视图：销售出库 / 其它出库 / 销售冲销 / 供应商退货" />
      <FilterBar>
        <FilterItem label="开始日期">
          <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </FilterItem>
        <FilterItem label="结束日期">
          <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </FilterItem>
        <FilterItem label="仓库">
          <Select value={warehouse} onChange={(e) => setWarehouse(e.target.value)}>
            <option value="">全部仓库</option>
            {warehouses.map((w) => (
              <option key={w.code} value={w.code}>
                {w.name}（{w.code}）
              </option>
            ))}
          </Select>
        </FilterItem>
        <FilterItem label="单品编码">
          <Input value={itemCode} onChange={(e) => setItemCode(e.target.value)} placeholder="精确匹配" />
        </FilterItem>
        <FilterItem label="类型">
          <Select value={type} onChange={(e) => setType(e.target.value)}>
            {TYPE_OPTIONS.map((t) => (
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
        <Button onClick={() => void load()} disabled={loading}>
          {loading ? "查询中…" : "查询"}
        </Button>
      </FilterBar>
      {error && (
        <div className="mb-4 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}
      <ReportTable
        columns={columns}
        rows={rows}
        loading={loading}
        rowKey={(row) => row.id}
        emptyTitle="暂无出库流水"
        emptyHint="调整筛选条件后重新查询"
      />
    </div>
  )
}
