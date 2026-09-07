import { useEffect, useMemo, useState } from "react"
import { FilterBar, FilterItem, PageHeader } from "@/components/page-kit"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { ReportTable, type ReportColumn } from "../components/report-table"
import { cn } from "@/lib/utils"
import { fmtMoney, fmtQty, fmtTime, request } from "../api"

interface Config {
  warehouses: { code: string; name: string }[]
  inventory: { enabled_from: string }
}
interface Balance {
  warehouse_code: string
  warehouse_name: string
  item_code: string
  item_name: string
  sellable_qty: number
  average_unit_cost: number
  total_average_cost: number
  updated_at: string
  avg_daily_out: number | null
  threshold_qty: number | null
}

export function BalancesModule() {
  const [config, setConfig] = useState<Config | null>(null)
  const [balances, setBalances] = useState<Balance[]>([])
  const [warehouse, setWarehouse] = useState("")
  const [keyword, setKeyword] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  useEffect(() => {
    setLoading(true)
    setError("")
    Promise.all([request<Config>("/api/v2/config"), request<Balance[]>("/api/v2/inventory/balances")])
      .then(([cfg, bal]) => {
        setConfig(cfg)
        setBalances(Array.isArray(bal) ? bal : [])
      })
      .catch((e) => setError(e?.message || "加载失败"))
      .finally(() => setLoading(false))
  }, [])

  // 预警口径：可售 < 近7天日均出库量 × 3天（阈值由后端 balances 接口统一下发）
  const isLow = (r: Balance) => {
    const threshold = Number(r.threshold_qty) || 0
    return threshold > 0 && (Number(r.sellable_qty) || 0) < threshold
  }

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    return balances.filter((r) => {
      if (warehouse && r.warehouse_code !== warehouse) return false
      if (kw && !`${r.item_code} ${r.item_name}`.toLowerCase().includes(kw)) return false
      return true
    })
  }, [balances, warehouse, keyword])

  const totals = useMemo(
    () =>
      filtered.reduce(
        (acc, r) => {
          acc.qty += Number(r.sellable_qty) || 0
          acc.amount += Number(r.total_average_cost) || 0
          return acc
        },
        { qty: 0, amount: 0 }
      ),
    [filtered]
  )

  const columns: ReportColumn<Balance>[] = [
    { key: "warehouse_name", label: "仓库", render: (r) => r.warehouse_name || r.warehouse_code },
    { key: "item_code", label: "单品编码" },
    { key: "item_name", label: "单品名称" },
    {
      key: "sellable_qty",
      label: "可售数量",
      align: "right",
      render: (r) => <span className={cn(isLow(r) && "font-medium text-destructive")}>{fmtQty(r.sellable_qty)}</span>,
    },
    { key: "average_unit_cost", label: "加权均价", align: "right", render: (r) => fmtMoney(r.average_unit_cost) },
    {
      key: "avg_daily_out",
      label: "近7天日均出库",
      align: "right",
      render: (r) => (Number(r.avg_daily_out) ? fmtQty(r.avg_daily_out) : <span className="text-muted-foreground">—</span>),
    },
    {
      key: "days_of_stock",
      label: "可售天数",
      align: "right",
      render: (r) => {
        const avg = Number(r.avg_daily_out) || 0
        if (avg <= 0) return <span className="text-muted-foreground">—</span>
        const days = (Number(r.sellable_qty) || 0) / avg
        return (
          <span className={cn("tnum", days < 3 ? "font-medium text-destructive" : days < 7 ? "text-amber-500" : "text-muted-foreground")}>
            {days.toFixed(1)} 天
          </span>
        )
      },
    },
    { key: "total_average_cost", label: "库存金额", align: "right", render: (r) => fmtMoney(r.total_average_cost) },
    { key: "updated_at", label: "更新时间", render: (r) => fmtTime(r.updated_at) },
    {
      key: "flag",
      label: "预警",
      align: "center",
      render: (r) => (isLow(r) ? <Badge variant="destructive">低库存</Badge> : <span className="text-muted-foreground">—</span>),
    },
  ]

  return (
    <div>
      <PageHeader title="库存余额" description="各仓库单品的实时可售数量与加权平均成本" />
      {error && (
        <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-3.5 py-2.5 text-sm text-destructive">{error}</div>
      )}

      <FilterBar>
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
        <FilterItem label="单品编码 / 名称">
          <Input placeholder="搜索单品编码或名称" value={keyword} onChange={(e) => setKeyword(e.target.value)} />
        </FilterItem>
      </FilterBar>

      <ReportTable
        columns={columns}
        rows={filtered}
        loading={loading}
        rowKey={(r) => `${r.warehouse_code}-${r.item_code}`}
        emptyTitle="暂无库存余额"
        emptyHint="调整筛选条件或确认库存已启用"
        footer={
          <div className="border-t px-3.5 py-2.5 text-xs text-muted-foreground">
            共 {fmtQty(filtered.length)} 个单品 · 总件数 {fmtQty(totals.qty)} · 总金额 ¥ {fmtMoney(totals.amount)}
          </div>
        }
      />
    </div>
  )
}
