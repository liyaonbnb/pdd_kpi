import { useCallback, useEffect, useMemo, useState } from "react"
import { FilterBar, FilterItem, PageHeader } from "@/components/page-kit"
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
interface Batch {
  id: number
  batch_no: string
  warehouse_code: string
  warehouse_name?: string
  item_code: string
  received_qty: number
  remaining_qty: number
  unit_cost: number
  stock_status: string
  received_at: string
}

interface BatchUsageTx {
  transaction_type: string
  biz_type: string | null
  quantity: number
  batch_unit_cost: number | null
  reference_type: string | null
  reference_id: string | null
  store_name: string | null
  sale_amount: number | null
  occurred_at: string
}
interface BatchUsage {
  batch: Batch
  transactions: BatchUsageTx[]
}

const STATUS_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "sellable", label: "可售" },
  { value: "inspection", label: "待检" },
  { value: "defective", label: "残次" },
  { value: "scrapped", label: "报废" },
]

const ageDays = (receivedAt: string) => {
  const t = new Date(receivedAt).getTime()
  if (!Number.isFinite(t)) return null
  return Math.max(0, Math.floor((Date.now() - t) / 86400000))
}

export function BatchesModule() {
  const [config, setConfig] = useState<Config | null>(null)
  const [rows, setRows] = useState<Batch[]>([])
  const [status, setStatus] = useState("")
  const [warehouse, setWarehouse] = useState("")
  const [keyword, setKeyword] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [usage, setUsage] = useState<BatchUsage | null>(null)
  const [usageLoading, setUsageLoading] = useState(false)

  const openUsage = (batch: Batch) => {
    setUsageLoading(true)
    request<BatchUsage>(`/api/v2/inventory/batches/${batch.id}/usage`)
      .then(setUsage)
      .catch((e) => alert(e?.message || "加载批次明细失败"))
      .finally(() => setUsageLoading(false))
  }

  const warehouseName = (code: string) => config?.warehouses?.find((w) => w.code === code)?.name || code

  useEffect(() => {
    request<Config>("/api/v2/config")
      .then(setConfig)
      .catch(() => undefined)
  }, [])

  const query = useCallback((nextStatus: string) => {
    setLoading(true)
    setError("")
    request<Batch[]>(`/api/v2/inventory/batches${qs({ status: nextStatus })}`)
      .then((data) => setRows(Array.isArray(data) ? data : []))
      .catch((e) => {
        setRows([])
        setError(e?.message || "查询失败")
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    query(status)
  }, [status, query])

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    return rows.filter((r) => {
      if (warehouse && r.warehouse_code !== warehouse) return false
      if (kw && !`${r.item_code} ${r.batch_no}`.toLowerCase().includes(kw)) return false
      return true
    })
  }, [rows, warehouse, keyword])

  const totalRemaining = useMemo(
    () => filtered.reduce((acc, r) => acc + (Number(r.remaining_qty) || 0), 0),
    [filtered]
  )

  const columns: ReportColumn<Batch>[] = [
    { key: "batch_no", label: "批次号" },
    { key: "warehouse_code", label: "仓库", render: (r) => warehouseName(r.warehouse_code) },
    { key: "item_code", label: "单品" },
    { key: "received_qty", label: "入库数量", align: "right", render: (r) => fmtQty(r.received_qty) },
    {
      key: "out_qty",
      label: "已出库数量",
      align: "right",
      render: (r) => {
        const out = (Number(r.received_qty) || 0) - (Number(r.remaining_qty) || 0)
        return <span className={cn(out > 0 && "text-chart-1")}>{fmtQty(out)}</span>
      },
    },
    {
      key: "out_progress",
      label: "出库进度",
      align: "right",
      render: (r) => {
        const received = Number(r.received_qty) || 0
        if (received <= 0) return "—"
        const pct = Math.round(((received - (Number(r.remaining_qty) || 0)) / received) * 100)
        return <span className={cn(pct >= 100 ? "text-muted-foreground" : "text-chart-1")}>{pct}%</span>
      },
    },
    { key: "remaining_qty", label: "剩余数量", align: "right", render: (r) => fmtQty(r.remaining_qty) },
    { key: "unit_cost", label: "批次成本", align: "right", render: (r) => fmtMoney(r.unit_cost) },
    { key: "stock_status", label: "状态", align: "center", render: (r) => <StatusBadge value={r.stock_status} /> },
    { key: "received_at", label: "入库时间", render: (r) => fmtTime(r.received_at) },
    {
      key: "age",
      label: "库龄（天）",
      align: "right",
      render: (r) => {
        const days = ageDays(r.received_at)
        if (days === null) return "—"
        return (
          <span className={cn(days >= 90 && "font-medium text-chart-3")} title={days >= 90 ? "呆滞库存" : undefined}>
            {days}
          </span>
        )
      },
    },
  ]

  const usageColumns: ReportColumn<BatchUsageTx>[] = [
    { key: "occurred_at", label: "时间", render: (t) => fmtTime(t.occurred_at) },
    { key: "transaction_type", label: "类型", render: (t) => <StatusBadge value={t.transaction_type} /> },
    { key: "biz_type", label: "业务类型", render: (t) => t.biz_type || "—" },
    { key: "reference_id", label: "引用单号", render: (t) => t.reference_id || "—" },
    { key: "store_name", label: "店铺", render: (t) => t.store_name || "—" },
    {
      key: "quantity",
      label: "数量",
      align: "right",
      render: (t) => (
        <span className={cn(Number(t.quantity) < 0 ? "text-chart-1" : "text-chart-2")}>
          {Number(t.quantity) > 0 ? `+${fmtQty(t.quantity)}` : fmtQty(t.quantity)}
        </span>
      ),
    },
    {
      key: "batch_unit_cost",
      label: "批次成本",
      align: "right",
      render: (t) => fmtMoney(t.batch_unit_cost),
    },
    {
      key: "amount",
      label: "金额（成本）",
      align: "right",
      render: (t) => {
        const qty = Math.abs(Number(t.quantity) || 0)
        const cost = Number(t.batch_unit_cost) || 0
        return fmtMoney(qty * cost)
      },
    },
  ]

  return (
    <div>
      <PageHeader title="批次台账" description="批次维度的入库与剩余情况，库龄 ≥ 90 天提示呆滞" />
      {error && (
        <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-3.5 py-2.5 text-sm text-destructive">{error}</div>
      )}

      <FilterBar>
        <FilterItem label="状态">
          <Select value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUS_OPTIONS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </Select>
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
        <FilterItem label="单品编码 / 批次号">
          <Input placeholder="搜索单品编码或批次号" value={keyword} onChange={(e) => setKeyword(e.target.value)} />
        </FilterItem>
      </FilterBar>

      <ReportTable
        columns={columns}
        rows={filtered}
        loading={loading}
        rowKey={(r) => r.id}
        onRowClick={openUsage}
        emptyTitle="暂无批次数据"
        emptyHint="调整筛选条件后重试"
        footer={
          <div className="border-t px-3.5 py-2.5 text-xs text-muted-foreground">
            共 {fmtQty(filtered.length)} 个批次 · 总剩余量 {fmtQty(totalRemaining)} · 点击行查看该批次出库明细
          </div>
        }
      />

      {usage && (
        <div className="mt-4 rounded-md border p-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold">
                批次 {usage.batch.batch_no} 出入库明细
              </h3>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {usage.batch.item_code} · {usage.batch.warehouse_name || usage.batch.warehouse_code} · 入库 {fmtQty(usage.batch.received_qty)} · 已出库 {fmtQty((Number(usage.batch.received_qty) || 0) - (Number(usage.batch.remaining_qty) || 0))} · 剩余 {fmtQty(usage.batch.remaining_qty)} · 批次成本 ¥{fmtMoney(usage.batch.unit_cost)}
              </p>
            </div>
            <button className="text-xs text-muted-foreground hover:text-foreground" onClick={() => setUsage(null)}>
              关闭
            </button>
          </div>
          <div className="mt-3">
            <ReportTable
              columns={usageColumns}
              rows={usage.transactions}
              loading={usageLoading}
              rowKey={(t, i) => `${t.occurred_at}-${i}`}
              emptyTitle="该批次暂无流水"
            />
          </div>
        </div>
      )}
    </div>
  )
}
