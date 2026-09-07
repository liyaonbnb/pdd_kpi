import { useCallback, useEffect, useState } from "react"
import { FilterBar, FilterItem, PageHeader } from "@/components/page-kit"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ReportTable, type ReportColumn } from "../components/report-table"
import { fmtMoney, fmtQty, qs, request, downloadFile } from "../api"

interface Config {
  warehouses: { code: string; name: string }[]
  inventory: { enabled_from: string }
}
interface SummaryRow {
  period: string
  warehouse_code: string
  warehouse_name: string
  item_code: string
  item_name: string
  opening_qty: number
  opening_amount: number
  in_qty: number
  in_amount: number
  out_qty: number
  out_amount: number
  closing_qty: number
  closing_amount: number
}

const toDate = (d: Date) => d.toISOString().slice(0, 10)
const defaultRange = () => {
  const end = new Date()
  const start = new Date()
  start.setDate(start.getDate() - 29)
  return { start: toDate(start), end: toDate(end) }
}

export function LedgerSummaryModule() {
  const [config, setConfig] = useState<Config | null>(null)
  const [rows, setRows] = useState<SummaryRow[]>([])
  const [{ start, end }, setRange] = useState(defaultRange)
  const [warehouse, setWarehouse] = useState("")
  const [itemCode, setItemCode] = useState("")
  const [groupBy, setGroupBy] = useState<"day" | "month">("day")
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState("")

  const exportExcel = async () => {
    setExporting(true)
    setError("")
    try {
      const queryString = qs({
        group_by: groupBy,
        start_date: start,
        end_date: end,
        warehouse,
        item_code: itemCode.trim(),
      })
      await downloadFile(`/api/v2/inventory/ledger/summary/export${queryString}`, `台账汇总_${start}_${end}.xlsx`)
    } catch (e: any) {
      setError(e?.message || "导出失败")
    } finally {
      setExporting(false)
    }
  }

  useEffect(() => {
    request<Config>("/api/v2/config")
      .then(setConfig)
      .catch(() => undefined)
  }, [])

  const query = useCallback(() => {
    setLoading(true)
    setError("")
    const queryString = qs({
      group_by: groupBy,
      start_date: start,
      end_date: end,
      warehouse,
      item_code: itemCode.trim(),
    })
    request<SummaryRow[]>(`/api/v2/inventory/ledger/summary${queryString}`)
      .then((data) => setRows(Array.isArray(data) ? data : []))
      .catch((e) => {
        setRows([])
        setError(e?.message || "查询失败")
      })
      .finally(() => setLoading(false))
  }, [groupBy, start, end, warehouse, itemCode])

  useEffect(() => {
    query()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const columns: ReportColumn<SummaryRow>[] = [
    { key: "period", label: "期间" },
    { key: "warehouse_name", label: "仓库", render: (r) => r.warehouse_name || r.warehouse_code },
    { key: "item_code", label: "单品编码" },
    { key: "item_name", label: "单品名称" },
    { key: "opening_qty", label: "期初数量", align: "right", render: (r) => fmtQty(r.opening_qty) },
    { key: "opening_amount", label: "期初金额", align: "right", render: (r) => fmtMoney(r.opening_amount) },
    { key: "in_qty", label: "入库数量", align: "right", render: (r) => fmtQty(r.in_qty) },
    { key: "in_amount", label: "入库金额", align: "right", render: (r) => fmtMoney(r.in_amount) },
    { key: "out_qty", label: "出库数量", align: "right", render: (r) => fmtQty(r.out_qty) },
    { key: "out_amount", label: "出库金额", align: "right", render: (r) => fmtMoney(r.out_amount) },
    { key: "closing_qty", label: "结存数量", align: "right", render: (r) => fmtQty(r.closing_qty) },
    { key: "closing_amount", label: "结存金额", align: "right", render: (r) => fmtMoney(r.closing_amount) },
  ]

  return (
    <div>
      <PageHeader title="台账汇总" description="按期间汇总期初 / 出入库 / 结存，金额按批次成本口径" />
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
        <FilterItem label="汇总粒度">
          <Tabs value={groupBy} onValueChange={(v) => setGroupBy(v as "day" | "month")}>
            <TabsList>
              <TabsTrigger value="day">按天</TabsTrigger>
              <TabsTrigger value="month">按月</TabsTrigger>
            </TabsList>
          </Tabs>
        </FilterItem>
        <Button onClick={query} disabled={loading}>
          {loading ? "查询中" : "查询"}
        </Button>
        <Button variant="outline" onClick={exportExcel} disabled={exporting || loading}>
          {exporting ? "导出中" : "导出 Excel"}
        </Button>
      </FilterBar>

      <ReportTable
        columns={columns}
        rows={rows}
        loading={loading}
        rowKey={(r, i) => `${r.period}-${r.warehouse_code}-${r.item_code}-${i}`}
        emptyTitle="暂无台账数据"
        emptyHint="调整日期区间或筛选条件后重新查询"
      />
    </div>
  )
}
