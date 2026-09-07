import { useEffect, useState } from "react"
import { PageHeader, StatCard } from "@/components/page-kit"
import { request, fmtQty, fmtTime } from "../api"
import { ReportTable, type ReportColumn } from "../components/report-table"
import { StatusBadge } from "../components/status-badge"

interface ExceptionRow {
  id: number | string
  order_id: string
  warehouse_code: string
  item_code: string
  requested_qty: string | number | null
  available_qty: string | number | null
  status: string
  created_at: string | null
}

/** 异常队列：缺货订单的缺料明细（纯报表，补货后由人工处理） */
export function ExceptionsModule() {
  const [rows, setRows] = useState<ExceptionRow[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  const reload = async () => {
    setLoading(true)
    setError("")
    try {
      const data = await request<ExceptionRow[]>("/api/v2/exceptions")
      setRows(data)
    } catch (e: any) {
      setError(e.message || "加载失败")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void reload()
  }, [])

  const countBy = (status: string) => (rows || []).filter((row) => row.status === status).length

  const columns: ReportColumn<ExceptionRow>[] = [
    { key: "order_id", label: "订单号" },
    { key: "warehouse_code", label: "仓库" },
    { key: "item_code", label: "单品" },
    { key: "requested_qty", label: "需求数量", align: "right", render: (row) => fmtQty(row.requested_qty) },
    { key: "available_qty", label: "可用数量", align: "right", render: (row) => fmtQty(row.available_qty) },
    {
      key: "gap",
      label: "缺口",
      align: "right",
      render: (row) => {
        const gap = Number(row.requested_qty) - Number(row.available_qty)
        return <span className="text-destructive">{fmtQty(Number.isFinite(gap) ? gap : null)}</span>
      },
    },
    { key: "status", label: "状态", render: (row) => <StatusBadge value={row.status} /> },
    { key: "created_at", label: "时间", render: (row) => fmtTime(row.created_at) },
  ]

  return (
    <div>
      <PageHeader
        title="异常队列"
        description="缺货订单正常入账不产生负库存；补货后由人工处理（重试闭环后续版本提供）"
      />
      <div className="mb-4 grid gap-4 sm:grid-cols-3">
        <StatCard label="待处理" value={countBy("open")} />
        <StatCard label="已解决" value={countBy("resolved")} />
        <StatCard label="已取消" value={countBy("cancelled")} />
      </div>
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
        emptyTitle="暂无异常"
        emptyHint="缺货订单扣减失败时会自动生成异常记录"
      />
    </div>
  )
}
