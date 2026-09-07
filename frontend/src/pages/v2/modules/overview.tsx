import { useEffect, useMemo, useState } from "react"
import { Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { PageHeader, StatCard } from "@/components/page-kit"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { ReportTable, type ReportColumn } from "../components/report-table"
import { cn } from "@/lib/utils"
import { fmtMoney, fmtQty, qs, request } from "../api"

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
interface SummaryRow {
  period: string
  in_qty: number
  out_qty: number
}
interface LowStockRow {
  warehouse_code: string
  warehouse_name: string
  item_code: string
  item_name: string
  base_unit: string
  sellable_qty: number
  avg_daily_out: number
  threshold_qty: number
  days_of_stock: number
  gap_qty: number
  average_unit_cost: number
  total_average_cost: number
}
interface StagnantRow {
  warehouse_code: string
  warehouse_name: string
  item_code: string
  item_name: string
  base_unit: string
  sellable_qty: number
  avg_daily_out: number
  days_of_stock: number | null
  average_unit_cost: number
  total_average_cost: number
}
interface Alerts {
  low_stock: LowStockRow[]
  stagnant: StagnantRow[]
  stagnant_days: number
  open_exceptions: number
}

const toDate = (d: Date) => d.toISOString().slice(0, 10)

const axisTick = { fontSize: 12, fill: "hsl(var(--muted-foreground))" }
const tooltipStyle = {
  backgroundColor: "hsl(var(--card))",
  borderColor: "hsl(var(--border))",
  borderRadius: "0.5rem",
  color: "hsl(var(--card-foreground))",
  fontSize: 12,
}

const CHART_COLORS = ["hsl(var(--chart-1))", "hsl(var(--chart-2))", "hsl(var(--chart-3))"]

export function OverviewModule() {
  const [config, setConfig] = useState<Config | null>(null)
  const [balances, setBalances] = useState<Balance[]>([])
  const [itemCount, setItemCount] = useState(0)
  const [bundleCount, setBundleCount] = useState(0)
  const [exceptionCount, setExceptionCount] = useState(0)
  const [alerts, setAlerts] = useState<Alerts | null>(null)
  const [summary, setSummary] = useState<SummaryRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  useEffect(() => {
    const end = new Date()
    const start = new Date()
    start.setDate(start.getDate() - 29)
    const summaryQuery = qs({ group_by: "day", start_date: toDate(start), end_date: toDate(end) })
    setLoading(true)
    setError("")
    Promise.all([
      request<Config>("/api/v2/config"),
      request<Balance[]>("/api/v2/inventory/balances"),
      request<any[]>("/api/v2/items"),
      request<any[]>("/api/v2/bundles"),
      request<Alerts>("/api/v2/inventory/alerts"),
      request<any[]>("/api/v2/exceptions"),
      request<SummaryRow[]>(`/api/v2/inventory/ledger/summary${summaryQuery}`),
    ])
      .then(([cfg, bal, items, bundles, al, exceptions, sum]) => {
        setConfig(cfg)
        setBalances(Array.isArray(bal) ? bal : [])
        setItemCount(Array.isArray(items) ? items.length : 0)
        setBundleCount(Array.isArray(bundles) ? bundles.length : 0)
        setExceptionCount(Array.isArray(exceptions) ? exceptions.length : 0)
        setAlerts(al)
        setSummary(Array.isArray(sum) ? sum : [])
      })
      .catch((e) => setError(e?.message || "加载失败"))
      .finally(() => setLoading(false))
  }, [])

  const totalAmount = useMemo(() => balances.reduce((acc, r) => acc + (Number(r.total_average_cost) || 0), 0), [balances])
  const totalQty = useMemo(() => balances.reduce((acc, r) => acc + (Number(r.sellable_qty) || 0), 0), [balances])

  const trend = useMemo(() => {
    const map = new Map<string, { period: string; in_qty: number; out_qty: number }>()
    summary.forEach((r) => {
      const cur = map.get(r.period) || { period: r.period, in_qty: 0, out_qty: 0 }
      cur.in_qty += Number(r.in_qty) || 0
      cur.out_qty += Number(r.out_qty) || 0
      map.set(r.period, cur)
    })
    return Array.from(map.values()).sort((a, b) => a.period.localeCompare(b.period))
  }, [summary])

  const warehouseDist = useMemo(() => {
    const map = new Map<string, number>()
    balances.forEach((r) => {
      const name = r.warehouse_name || r.warehouse_code || "未知仓库"
      map.set(name, (map.get(name) || 0) + (Number(r.total_average_cost) || 0))
    })
    const list = Array.from(map.entries()).map(([name, amount]) => ({ name, amount })).sort((a, b) => b.amount - a.amount)
    const max = list.length ? list[0].amount : 0
    return { list, max }
  }, [balances])

  const lowStockTop = useMemo(() => (alerts?.low_stock || []).slice(0, 8), [alerts])
  const lowStockCount = alerts?.low_stock?.length ?? 0
  const stagnantCount = alerts?.stagnant?.length ?? 0
  const stagnantAmount = useMemo(() => (alerts?.stagnant || []).reduce((acc, r) => acc + (Number(r.total_average_cost) || 0), 0), [alerts])
  const openExceptions = alerts?.open_exceptions ?? 0

  // 库存周转：按可售天数（可售 ÷ 近7天日均出库）分桶 + 全部单品周转表
  const turnover = useMemo(() => {
    const buckets = [
      { label: "不足 3 天", count: 0, cls: "text-destructive" },
      { label: "3 - 7 天", count: 0, cls: "text-amber-500" },
      { label: "7 - 30 天", count: 0, cls: "" },
      { label: "30 天以上", count: 0, cls: "text-muted-foreground" },
      { label: "近7天无出库", count: 0, cls: "text-muted-foreground" },
    ]
    const rows: (Balance & { days: number | null })[] = []
    balances.forEach((r) => {
      const avg = Number(r.avg_daily_out) || 0
      if (avg <= 0) {
        buckets[4].count += 1
        rows.push({ ...r, days: null })
        return
      }
      const days = (Number(r.sellable_qty) || 0) / avg
      rows.push({ ...r, days })
      if (days < 3) buckets[0].count += 1
      else if (days < 7) buckets[1].count += 1
      else if (days < 30) buckets[2].count += 1
      else buckets[3].count += 1
    })
    // 有出库的按可售天数升序（越紧缺越靠前），无出库的排最后
    rows.sort((a, b) => (a.days ?? Infinity) - (b.days ?? Infinity))
    return { buckets, rows }
  }, [balances])

  const lowColumns: ReportColumn<LowStockRow>[] = [
    { key: "warehouse_name", label: "仓库", render: (r) => r.warehouse_name || r.warehouse_code },
    { key: "item_code", label: "单品编码" },
    { key: "item_name", label: "单品名称" },
    { key: "sellable_qty", label: "可售", align: "right", render: (r) => <span className="text-destructive">{fmtQty(r.sellable_qty)}</span> },
    { key: "avg_daily_out", label: "近7天日均出库", align: "right", render: (r) => fmtQty(r.avg_daily_out) },
    {
      key: "days_of_stock",
      label: "可售天数",
      align: "right",
      render: (r) => <span className="font-medium text-destructive">{fmtQty(r.days_of_stock)} 天</span>,
    },
    {
      key: "gap_qty",
      label: "缺口",
      align: "right",
      render: (r) => <span className="font-medium text-destructive">{fmtQty(r.gap_qty)}</span>,
    },
  ]

  type TurnoverRow = Balance & { days: number | null }
  const turnoverColumns: ReportColumn<TurnoverRow>[] = [
    { key: "warehouse_name", label: "仓库", render: (r) => r.warehouse_name || r.warehouse_code },
    { key: "item_code", label: "单品编码" },
    { key: "item_name", label: "单品名称" },
    { key: "sellable_qty", label: "可售", align: "right", render: (r) => fmtQty(r.sellable_qty) },
    { key: "avg_daily_out", label: "近7天日均出库", align: "right", render: (r) => (Number(r.avg_daily_out) ? fmtQty(r.avg_daily_out) : <span className="text-muted-foreground">—</span>) },
    {
      key: "days",
      label: "可售天数",
      align: "right",
      render: (r) =>
        r.days === null ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          <span className={cn("tnum", r.days < 3 ? "font-medium text-destructive" : r.days < 7 ? "text-amber-500" : r.days >= 30 ? "text-muted-foreground" : "")}>{r.days.toFixed(1)} 天</span>
        ),
    },
    { key: "total_average_cost", label: "占用资金", align: "right", render: (r) => fmtMoney(r.total_average_cost) },
    {
      key: "status",
      label: "状态",
      align: "center",
      render: (r) => {
        if (r.days === null) return <Badge variant="secondary">呆滞·无出库</Badge>
        if (r.days < 3) return <Badge variant="destructive">紧缺</Badge>
        if (r.days < 7) return <Badge variant="secondary">偏紧</Badge>
        if (r.days >= 30) return <Badge variant="secondary">呆滞</Badge>
        return <span className="text-muted-foreground">正常</span>
      },
    },
  ]

  return (
    <div>
      <PageHeader
        title="运营总览"
        description={config ? `库存启用日：${config.inventory?.enabled_from || "—"} · 数据实时取自供应链台账` : "供应链报表中心 landing"}
      />
      {error && (
        <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-3.5 py-2.5 text-sm text-destructive">{error}</div>
      )}

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {loading ? (
          Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-[104px] w-full rounded-lg" />)
        ) : (
          <>
            <StatCard label="库存总金额" value={`¥ ${fmtMoney(totalAmount)}`} hint="按加权平均成本口径" />
            <StatCard label="可售总件数" value={fmtQty(totalQty)} hint="全部仓库可售合计" />
            <StatCard label="库存单品数" value={fmtQty(itemCount)} hint="单品档案总数" />
            <StatCard label="组合商品数" value={fmtQty(bundleCount)} hint="组合档案总数" />
            <StatCard
              label="低库存预警数"
              value={<span className={cn(lowStockCount > 0 && "text-destructive")}>{fmtQty(lowStockCount)}</span>}
              hint={`可售不足3天出库量 · 呆滞 ${fmtQty(stagnantCount)} 个`}
            />
            <StatCard
              label="开放异常数"
              value={<span className={cn(openExceptions > 0 && "text-destructive")}>{fmtQty(openExceptions)}</span>}
              hint={`异常记录共 ${fmtQty(exceptionCount)} 条`}
            />
          </>
        )}
      </div>

      <div className="mb-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>近 30 天出入库趋势</CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-[280px] w-full" />
            ) : trend.length === 0 ? (
              <div className="flex h-[280px] items-center justify-center text-sm text-muted-foreground">近 30 天暂无出入库记录</div>
            ) : (
              <div className="h-[280px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={trend} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                    <XAxis dataKey="period" tick={axisTick} tickLine={false} axisLine={{ stroke: "hsl(var(--border))" }} tickFormatter={(v) => String(v).slice(5)} />
                    <YAxis tick={axisTick} tickLine={false} axisLine={false} width={48} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Legend />
                    <Area type="monotone" dataKey="in_qty" name="入库数量" stroke="hsl(var(--chart-2))" fill="hsl(var(--chart-2))" fillOpacity={0.15} strokeWidth={2} />
                    <Area type="monotone" dataKey="out_qty" name="出库数量" stroke="hsl(var(--chart-4))" fill="hsl(var(--chart-4))" fillOpacity={0.15} strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>仓库库存金额分布</CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-3">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              </div>
            ) : warehouseDist.list.length === 0 ? (
              <div className="flex h-[280px] items-center justify-center text-sm text-muted-foreground">暂无库存余额数据</div>
            ) : (
              <div className="space-y-3">
                {warehouseDist.list.map((w, i) => (
                  <div key={w.name}>
                    <div className="mb-1 flex items-baseline justify-between text-sm">
                      <span className="font-medium">{w.name}</span>
                      <span className="tnum text-xs text-muted-foreground">¥ {fmtMoney(w.amount)}</span>
                    </div>
                    <div className="h-2.5 w-full rounded-full bg-muted">
                      <div
                        className="h-2.5 rounded-full"
                        style={{
                          width: `${warehouseDist.max > 0 ? Math.max((w.amount / warehouseDist.max) * 100, 2) : 0}%`,
                          backgroundColor: CHART_COLORS[i % CHART_COLORS.length],
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mb-4">
        <CardHeader>
          <CardTitle>
            库存周转（全部单品）
            <span className="ml-2 text-sm font-normal text-muted-foreground">
              按近7天日均出库推算可售天数{stagnantCount > 0 && ` · 呆滞 ${stagnantCount} 个 · 占用 ¥ ${fmtMoney(stagnantAmount)}`}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="mb-3 flex flex-wrap gap-2">
            {turnover.buckets.map((b) => (
              <span key={b.label} className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs">
                <span className="text-muted-foreground">{b.label}</span>
                <span className={cn("tnum font-medium", b.cls)}>{fmtQty(b.count)}</span>
              </span>
            ))}
          </div>
          <ReportTable
            columns={turnoverColumns}
            rows={turnover.rows}
            loading={loading}
            rowKey={(r) => `${r.warehouse_code}-${r.item_code}`}
            emptyTitle="暂无库存数据"
            emptyHint="确认库存已启用并有余额"
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>低库存预警 Top（可售 &lt; 近7天日均出库 × 3天）</CardTitle>
        </CardHeader>
        <CardContent>
          <ReportTable
            columns={lowColumns}
            rows={lowStockTop}
            loading={loading}
            rowKey={(r) => `${r.warehouse_code}-${r.item_code}`}
            emptyTitle="暂无低库存预警"
            emptyHint="所有单品均在安全库存之上"
          />
        </CardContent>
      </Card>
    </div>
  )
}
