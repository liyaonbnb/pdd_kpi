import { useEffect, useState } from "react"
import { Calendar } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { MetricLineChart } from "@/components/metric-line-chart"
import { HideableKpiCard, HiddenKpiList } from "@/components/hideable-kpi"
import { PageHeader, FilterBar, FilterItem, EmptyState } from "@/components/page-kit"
import { useHiddenKpis } from "@/hooks/use-hidden-kpis"
import { getStores, getDouyinDashboardSummary, getDouyinAnalysis, type Store } from "@/api/client"

function formatNumber(v: any, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "-"
  if (typeof v === "number") return v.toLocaleString("zh-CN", { maximumFractionDigits: digits })
  return v
}

const productSumKeys = [
  "spend",
  "gmv",
  "valid_gmv",
  "actual_revenue",
  "order_count",
  "valid_order_count",
  "exposure",
  "clicks",
  "refund_orders",
  "refund_amount",
]

function aggregateProductMetrics(storeMetrics: Record<string, any>[][]): Record<string, any>[] {
  const map = new Map<string, Record<string, any>>()
  for (const rows of storeMetrics) {
    for (const row of rows) {
      const id = row.product_id
      if (!id) continue
      if (!map.has(id)) {
        map.set(id, { ...row })
        continue
      }
      const existing = map.get(id)!
      for (const k of productSumKeys) {
        existing[k] = (existing[k] || 0) + (row[k] || 0)
      }
      existing.roi = existing.spend ? existing.gmv / existing.spend : 0
      existing.valid_roi = existing.spend ? existing.valid_gmv / existing.spend : 0
      existing.ctr = existing.exposure ? (existing.clicks / existing.exposure) * 100 : 0
      existing.cvr = existing.clicks ? (existing.order_count / existing.clicks) * 100 : 0
      existing.refund_rate = existing.order_count ? (existing.refund_orders / existing.order_count) * 100 : 0
    }
  }
  return Array.from(map.values())
}

function downloadCsv(filename: string, rows: Record<string, any>[], headers: { key: string; label: string }[]) {
  if (rows.length === 0) return
  const escape = (v: any) => {
    const s = v === null || v === undefined ? "" : String(v)
    if (s.includes(",") || s.includes("\n") || s.includes('"')) {
      return `"${s.replace(/"/g, '""')}"`
    }
    return s
  }
  const lines = [headers.map((h) => h.label).join(","), ...rows.map((r) => headers.map((h) => escape(r[h.key])).join(","))]
  const blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

const overviewKpis = [
  { key: "selected_stores", label: "已选店铺" },
  { key: "spend", label: "总消耗", unit: "元" },
  { key: "gmv", label: "成交金额", unit: "元" },
  { key: "valid_gmv", label: "净成交金额", unit: "元" },
  { key: "actual_revenue", label: "实际收入", unit: "元" },
  { key: "order_count", label: "订单数" },
  { key: "valid_order_count", label: "净订单数" },
  { key: "roi", label: "ROI" },
  { key: "ctr", label: "点击率", unit: "%" },
  { key: "total_cost", label: "总成本", unit: "元" },
  { key: "gross_profit", label: "毛利润", unit: "元" },
  { key: "profit_loss", label: "盈亏", unit: "元" },
  { key: "gross_margin_rate", label: "毛利率", unit: "%" },
  { key: "profit_loss_rate", label: "盈亏率", unit: "%" },
]

const trendCharts = [
  {
    title: "成交与消耗",
    description: "消耗、成交金额、净成交金额",
    metrics: [
      { key: "spend", name: "消耗", color: "hsl(var(--chart-1))", unit: "元" },
      { key: "gmv", name: "成交金额", color: "hsl(var(--chart-2))", unit: "元" },
      { key: "valid_gmv", name: "净成交金额", color: "hsl(var(--chart-3))", unit: "元" },
      { key: "actual_revenue", name: "实际收入", color: "hsl(var(--chart-4))", unit: "元" },
    ],
  },
  {
    title: "订单与流量",
    description: "订单数、点击、曝光",
    metrics: [
      { key: "order_count", name: "订单数", color: "hsl(var(--chart-1))" },
      { key: "valid_order_count", name: "净订单数", color: "hsl(var(--chart-2))" },
      { key: "clicks", name: "点击", color: "hsl(var(--chart-3))" },
      { key: "exposure", name: "曝光", color: "hsl(var(--chart-4))" },
    ],
  },
]

export function DouyinDashboardPage() {
  const [stores, setStores] = useState<Store[]>([])
  const [selectedStores, setSelectedStores] = useState<string[]>([])
  const [startDate, setStartDate] = useState(() => {
    const d = new Date()
    d.setDate(d.getDate() - 14)
    return d.toISOString().split("T")[0]
  })
  const [endDate, setEndDate] = useState(() => new Date().toISOString().split("T")[0])
  const [kpis, setKpis] = useState<Record<string, number | null>>({})
  const [costKpis, setCostKpis] = useState<Record<string, number | null>>({})
  const [trend, setTrend] = useState<any[]>([])
  const [productMetrics, setProductMetrics] = useState<Record<string, any>[]>([])
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState("")
  const { hiddenKpis, toggleKpi } = useHiddenKpis("douyin_hidden_kpis")

  useEffect(() => {
    getStores("douyin").then((s) => {
      setStores(s)
      if (s.length > 0) {
        setSelectedStores(s.map((x) => x.name))
      }
    })
  }, [])

  useEffect(() => {
    if (selectedStores.length > 0) {
      fetchSummary()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedStores.length])

  const fetchSummary = async () => {
    if (selectedStores.length === 0) {
      setMessage("请至少选择一个店铺")
      return
    }
    setLoading(true)
    setMessage("")
    try {
      const summary = await getDouyinDashboardSummary(startDate, endDate, selectedStores)
      setKpis(summary.kpis)
      setCostKpis(summary.cost_kpis || {})
      setTrend(summary.trend)

      const analyses = await Promise.all(selectedStores.map((store) => getDouyinAnalysis(store, startDate, endDate)))
      const merged = aggregateProductMetrics(analyses.map((a) => a.product_metrics))
      setProductMetrics(merged)
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setLoading(false)
    }
  }

  const toggleStore = (name: string) => {
    setSelectedStores((prev) => (prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]))
  }

  const overviewKpiValues: Record<string, number | null> = {
    ...kpis,
    ...costKpis,
    selected_stores: selectedStores.length,
  }
  const visibleOverviewKpis = overviewKpis.filter((item) => !hiddenKpis.has(item.key))
  const hiddenOverviewKpis = overviewKpis.filter((item) => hiddenKpis.has(item.key))

  return (
    <div className="space-y-4">
      <PageHeader
        title="抖音总览"
        description="抖音店铺经营数据总览"
        actions={
          <Button onClick={fetchSummary} disabled={loading}>
            <Calendar className="mr-1 h-4 w-4" /> {loading ? "加载中..." : "查询"}
          </Button>
        }
      />

      {message && <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{message}</div>}

      <FilterBar>
        <FilterItem label="开始日期">
          <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </FilterItem>
        <FilterItem label="结束日期">
          <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </FilterItem>
        <FilterItem label="店铺筛选">
          <div className="flex min-h-9 min-w-[280px] flex-wrap items-center gap-2 rounded-md border border-input bg-background px-3 py-1.5">
            {stores.length === 0 ? (
              <span className="text-sm text-muted-foreground">暂无抖音店铺，请先去店铺页创建</span>
            ) : (
              stores.map((s) => (
                <label key={s.id} className="flex items-center gap-1.5 text-sm">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-input"
                    checked={selectedStores.includes(s.name)}
                    onChange={() => toggleStore(s.name)}
                  />
                  <span className="text-muted-foreground">{s.name}</span>
                </label>
              ))
            )}
          </div>
        </FilterItem>
      </FilterBar>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5 xl:grid-cols-6">
        {visibleOverviewKpis.map((item) => (
          <HideableKpiCard
            key={item.key}
            label={item.label}
            value={overviewKpiValues[item.key]}
            unit={item.unit}
            onHide={() => toggleKpi(item.key)}
          />
        ))}
      </div>
      <HiddenKpiList items={hiddenOverviewKpis} onRestore={toggleKpi} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {trendCharts.map((chart) => (
          <Card key={chart.title}>
            <CardHeader className="pb-3">
              <CardTitle>{chart.title}</CardTitle>
              <CardDescription>{chart.description}</CardDescription>
            </CardHeader>
            <CardContent>
              <MetricLineChart
                hideHeader
                title={chart.title}
                description={chart.description}
                data={trend}
                metrics={chart.metrics}
              />
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle>商品明细（共 {selectedStores.length} 个店铺）</CardTitle>
          <Button
              variant="outline"
              size="sm"
              onClick={() =>
                downloadCsv(
                  `抖音商品明细_${startDate}_${endDate}.csv`,
                  productMetrics,
                  [
                    { key: "product_id", label: "商品ID" },
                    { key: "product_name", label: "商品名称" },
                    { key: "spend", label: "消耗" },
                    { key: "gmv", label: "成交金额" },
                    { key: "valid_gmv", label: "净成交金额" },
                    { key: "actual_revenue", label: "实际收入" },
                    { key: "order_count", label: "订单数" },
                    { key: "valid_order_count", label: "净订单数" },
                    { key: "roi", label: "ROI" },
                    { key: "ctr", label: "点击率" },
                    { key: "cvr", label: "转化率" },
                  ]
                )
              }
              disabled={productMetrics.length === 0}
            >
              导出商品明细
          </Button>
        </CardHeader>
        <CardContent>
          <div className="overflow-auto max-h-96 rounded-md border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                <tr>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">商品</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">消耗</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">成交金额</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">净成交</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">实际收入</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">ROI</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">点击率</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">成本</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">毛利润</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">盈亏</th>
                </tr>
              </thead>
              <tbody>
                {productMetrics.map((row) => (
                  <tr key={row.product_id} className="border-b transition-colors hover:bg-muted/40">
                    <td className="px-3 py-2">{row.product_name || row.product_id}</td>
                    <td className="px-3 py-2 text-right">{formatNumber(row.spend)}</td>
                    <td className="px-3 py-2 text-right">{formatNumber(row.gmv)}</td>
                    <td className="px-3 py-2 text-right">{formatNumber(row.valid_gmv)}</td>
                    <td className="px-3 py-2 text-right">{formatNumber(row.actual_revenue)}</td>
                    <td className="px-3 py-2 text-right">{formatNumber(row.roi)}</td>
                    <td className="px-3 py-2 text-right">{formatNumber(row.ctr)}%</td>
                    <td className="px-3 py-2 text-right">{formatNumber(row.total_cost)}</td>
                    <td className="px-3 py-2 text-right">{formatNumber(row.gross_profit)}</td>
                    <td className="px-3 py-2 text-right">{formatNumber(row.profit_loss)}</td>
                  </tr>
                ))}
                {productMetrics.length === 0 && (
                  <tr>
                    <td colSpan={10} className="p-0">
                      <EmptyState />
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
