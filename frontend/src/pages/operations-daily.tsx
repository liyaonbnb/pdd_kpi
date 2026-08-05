import { Fragment, useEffect, useMemo, useState } from "react"
import { useSearchParams } from "react-router-dom"
import {
  AlertTriangle,
  CalendarDays,
  ChevronDown,
  ChevronRight,
  Download,
  RefreshCw,
  Store,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  getOperationsDaily,
  type OperationsDailyQuality,
  type OperationsDailyReport,
  type OperationsDailyStore,
} from "@/api/client"
import { cn } from "@/lib/utils"

type MetricDefinition = {
  key: string
  label: string
  format: "money" | "integer" | "rate"
  detail?: boolean
  profit?: boolean
}

const metrics: MetricDefinition[] = [
  { key: "valid_merchant_income", label: "有效实收", format: "money" },
  { key: "valid_order_count", label: "有效订单数", format: "integer", detail: true },
  { key: "avg_valid_order_income", label: "有效客单价", format: "money", detail: true },
  { key: "total_product_cost", label: "商品成本", format: "money" },
  { key: "total_logistics_cost", label: "物流辅材费", format: "money" },
  { key: "platform_fee", label: "平台服务费", format: "money", detail: true },
  { key: "promo_spend", label: "推广费", format: "money" },
  { key: "link_gross_profit", label: "链接毛利", format: "money", detail: true, profit: true },
  { key: "profit_loss", label: "经营利润", format: "money", profit: true },
  { key: "promo_cost_ratio", label: "推广费率", format: "rate" },
  { key: "gross_margin_rate", label: "链接毛利率", format: "rate", detail: true, profit: true },
  { key: "profit_loss_rate", label: "经营利润率", format: "rate", profit: true },
  { key: "product_cost_ratio", label: "商品成本率", format: "rate" },
  { key: "logistics_cost_ratio", label: "物流辅材费率", format: "rate" },
  { key: "refund_rate", label: "退款率", format: "rate" },
]

function formatValue(value: number | null | undefined, format: MetricDefinition["format"]) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  if (format === "rate") return `${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}%`
  if (format === "integer") return Math.round(value).toLocaleString("zh-CN")
  return `¥${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function shortDate(value: string) {
  const date = new Date(`${value}T00:00:00`)
  return `${date.getMonth() + 1}月${date.getDate()}日`
}

function weekday(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { weekday: "short" }).format(new Date(`${value}T00:00:00`))
}

function metricCellClass(metric: MetricDefinition, value: number | null | undefined) {
  return cn(
    "whitespace-nowrap px-3 py-2.5 text-right font-mono text-xs tabular-nums",
    metric.profit && typeof value === "number" && value < 0 && "bg-destructive/5 font-semibold text-destructive",
    value === null || value === undefined ? "text-muted-foreground" : "text-foreground",
  )
}

function qualityBadge(counts?: OperationsDailyStore["quality_counts"]) {
  if (!counts) return null
  if (counts.missing > 0) return <Badge variant="destructive">缺失 {counts.missing} 天</Badge>
  if (counts.partial > 0) return <Badge variant="outline">部分数据 {counts.partial} 天</Badge>
  return <Badge variant="secondary">数据完整</Badge>
}

function qualityLabel(quality?: OperationsDailyQuality) {
  if (!quality || quality.status === "complete") return ""
  if (quality.status === "missing") return "当日未导入数据"
  const missing = [
    !quality.orders && "订单",
    !quality.promotion && "推广",
    !quality.metrics && "指标",
  ].filter(Boolean)
  return `缺少${missing.join("、")}数据`
}

function downloadReport(report: OperationsDailyReport, visibleMetrics: MetricDefinition[]) {
  const headers = ["店铺", "指标", "期间合计", ...report.dates.map(shortDate)]
  const groups = [report.total, ...report.stores]
  const rows = groups.flatMap((group) =>
    visibleMetrics.map((metric) => [
      group.store_name,
      metric.label,
      formatValue(group.totals[metric.key], metric.format),
      ...report.dates.map((date) => formatValue(group.daily[date]?.[metric.key], metric.format)),
    ]),
  )
  const escape = (value: string) => `"${String(value).replace(/"/g, '""')}"`
  const csv = [headers, ...rows].map((row) => row.map(escape).join(",")).join("\n")
  const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = `运营日报_${report.start_date}_${report.end_date}.csv`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export function OperationsDailyPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const startParam = searchParams.get("start") || ""
  const endParam = searchParams.get("end") || ""
  const [startDate, setStartDate] = useState(startParam)
  const [endDate, setEndDate] = useState(endParam)
  const [report, setReport] = useState<OperationsDailyReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [showDetails, setShowDetails] = useState(false)
  const [collapsedStores, setCollapsedStores] = useState<Set<string>>(new Set())

  const visibleMetrics = useMemo(
    () => metrics.filter((metric) => showDetails || !metric.detail),
    [showDetails],
  )

  useEffect(() => {
    let active = true
    setLoading(true)
    setError("")
    getOperationsDaily(startParam || undefined, endParam || undefined)
      .then((data) => {
        if (!active) return
        setReport(data)
        setStartDate(data.start_date)
        setEndDate(data.end_date)
        if (!startParam || !endParam) {
          setSearchParams({ start: data.start_date, end: data.end_date }, { replace: true })
        }
      })
      .catch((err) => active && setError(err.message || "运营日报加载失败"))
      .finally(() => active && setLoading(false))
    return () => {
      active = false
    }
  }, [startParam, endParam, setSearchParams])

  const applyRange = () => {
    if (!startDate || !endDate) return
    setSearchParams({ start: startDate, end: endDate })
  }

  const showRecentDays = (days: number) => {
    const base = report?.end_date || endDate
    if (!base) return
    const end = new Date(`${base}T00:00:00`)
    const start = new Date(end)
    start.setDate(end.getDate() - days + 1)
    const format = (date: Date) => [
      date.getFullYear(),
      String(date.getMonth() + 1).padStart(2, "0"),
      String(date.getDate()).padStart(2, "0"),
    ].join("-")
    setStartDate(format(start))
    setEndDate(format(end))
    setSearchParams({ start: format(start), end: format(end) })
  }

  const toggleStore = (storeName: string) => {
    setCollapsedStores((current) => {
      const next = new Set(current)
      if (next.has(storeName)) next.delete(storeName)
      else next.add(storeName)
      return next
    })
  }

  const summaryCards = report
    ? [
        { label: "全店有效实收", value: formatValue(report.summary.valid_merchant_income, "money") },
        { label: "全店经营利润", value: formatValue(report.summary.profit_loss, "money"), profit: true },
        { label: "经营利润率", value: formatValue(report.summary.profit_loss_rate, "rate"), profit: true },
        { label: "推广费率", value: formatValue(report.summary.promo_cost_ratio, "rate") },
        { label: "日均有效实收", value: formatValue(report.summary.daily_income, "money") },
        { label: "数据异常店铺", value: `${report.summary.data_issue_store_count || 0} 家`, alert: true },
      ]
    : []

  const groups = report ? [report.total, ...report.stores] : []

  return (
    <div className="mx-auto flex w-full max-w-[1800px] flex-col gap-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
            <Store className="size-3.5" />
            拼多多 · 主账号视图
          </div>
          <h2 className="text-2xl font-bold tracking-tight">全店运营日报</h2>
          <p className="text-sm text-muted-foreground">按店铺对比收入、成本、投放与利润，快速定位异常经营日。</p>
        </div>

        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            开始日期
            <Input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} className="w-40" />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            结束日期
            <Input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} className="w-40" />
          </label>
          <Button variant="outline" size="sm" onClick={() => showRecentDays(7)}>近 7 天</Button>
          <Button variant="outline" size="sm" onClick={() => showRecentDays(14)}>近 14 天</Button>
          <Button size="sm" onClick={applyRange} disabled={loading}>
            <RefreshCw data-icon="inline-start" className={cn(loading && "animate-spin")} />
            查询
          </Button>
        </div>
      </div>

      {error && (
        <Card className="border-destructive/40">
          <CardContent className="flex items-center gap-2 p-4 text-sm text-destructive">
            <AlertTriangle className="size-4" />
            {error}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
        {summaryCards.map((card) => {
          const profit = Number(report?.summary.profit_loss || 0)
          const profitRate = Number(report?.summary.profit_loss_rate || 0)
          const negative = card.profit && (card.label.includes("率") ? profitRate < 0 : profit < 0)
          const hasIssues = card.alert && Number(report?.summary.data_issue_store_count || 0) > 0
          return (
            <Card key={card.label} className={cn(hasIssues && "border-destructive/40")}>
              <CardHeader className="p-4 pb-2">
                <CardDescription className="text-xs">{card.label}</CardDescription>
                <CardTitle className={cn("text-xl tabular-nums", negative && "text-destructive")}>{card.value}</CardTitle>
              </CardHeader>
              {hasIssues && (
                <CardContent className="px-4 pb-4 pt-0 text-xs text-destructive">存在缺失或部分导入数据</CardContent>
              )}
            </Card>
          )
        })}
      </div>

      <Card>
        <CardHeader className="flex flex-col gap-3 border-b p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-col gap-1">
            <CardTitle className="flex items-center gap-2 text-base">
              <CalendarDays className="size-4" />
              店铺经营矩阵
            </CardTitle>
            <CardDescription>金额按期间求和，比率按汇总金额重新计算；“—”表示当天没有可用数据。</CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => setShowDetails((value) => !value)}>
              {showDetails ? "收起辅助指标" : "展开辅助指标"}
            </Button>
            <Button variant="outline" size="sm" disabled={!report} onClick={() => report && downloadReport(report, visibleMetrics)}>
              <Download data-icon="inline-start" />
              导出 CSV
            </Button>
          </div>
        </CardHeader>

        <CardContent className="p-0">
          {loading && !report ? (
            <div className="flex min-h-64 items-center justify-center gap-2 text-sm text-muted-foreground">
              <RefreshCw className="size-4 animate-spin" />
              正在汇总全部店铺数据…
            </div>
          ) : report && groups.length > 0 ? (
            <div className="max-h-[calc(100vh-280px)] overflow-auto">
              <table className="w-full min-w-[980px] border-collapse text-sm">
                <thead className="sticky top-0 bg-card shadow-sm">
                  <tr>
                    <th className="sticky left-0 min-w-44 border-b bg-card px-3 py-3 text-left font-semibold">店铺 / 指标</th>
                    <th className="sticky left-44 min-w-32 border-b border-l bg-card px-3 py-3 text-right font-semibold">期间合计</th>
                    {report.dates.map((date) => (
                      <th key={date} className="min-w-28 border-b border-l bg-card px-3 py-2 text-right font-semibold">
                        <div>{shortDate(date)}</div>
                        <div className="text-[11px] font-normal text-muted-foreground">{weekday(date)}</div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {groups.map((group, groupIndex) => {
                    const collapsed = collapsedStores.has(group.store_name)
                    return (
                      <Fragment key={group.store_name}>
                        <tr className={cn(groupIndex === 0 ? "bg-muted/80" : "bg-muted/35")}>
                          <th colSpan={report.dates.length + 2} className="border-y px-3 py-2 text-left">
                            <button
                              type="button"
                              className="flex w-full items-center gap-2 text-left"
                              onClick={() => toggleStore(group.store_name)}
                              aria-expanded={!collapsed}
                            >
                              {collapsed ? <ChevronRight className="size-4" /> : <ChevronDown className="size-4" />}
                              <span className="font-semibold">{group.store_name}</span>
                              {groupIndex === 0 ? <Badge variant="outline">汇总</Badge> : qualityBadge(group.quality_counts)}
                            </button>
                          </th>
                        </tr>
                        {!collapsed && visibleMetrics.map((metric) => (
                          <tr key={`${group.store_name}-${metric.key}`} className="hover:bg-muted/25">
                            <th className="sticky left-0 border-b bg-card px-3 py-2.5 text-left text-xs font-medium">{metric.label}</th>
                            <td className={cn(metricCellClass(metric, group.totals[metric.key]), "sticky left-44 border-b border-l bg-card font-semibold")}>
                              {formatValue(group.totals[metric.key], metric.format)}
                            </td>
                            {report.dates.map((date) => {
                              const value = group.daily[date]?.[metric.key]
                              const quality = group.quality?.[date]
                              return (
                                <td
                                  key={date}
                                  title={qualityLabel(quality)}
                                  className={cn(
                                    metricCellClass(metric, value),
                                    "border-b border-l",
                                    quality?.status === "partial" && "bg-muted/40",
                                    quality?.status === "missing" && "bg-destructive/5",
                                  )}
                                >
                                  {formatValue(value, metric.format)}
                                </td>
                              )
                            })}
                          </tr>
                        ))}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="flex min-h-64 flex-col items-center justify-center gap-2 text-center text-sm text-muted-foreground">
              <CalendarDays className="size-8" />
              当前日期范围暂无可展示的店铺数据
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-3 text-xs text-muted-foreground md:grid-cols-2">
        <div className="rounded-lg border bg-card p-3">
          <span className="font-medium text-foreground">利润口径：</span>
          链接毛利 = 有效实收 − 商品成本 − 物流辅材费 − 平台服务费；经营利润 = 链接毛利 − 推广费。
        </div>
        <div className="rounded-lg border bg-card p-3">
          <span className="font-medium text-foreground">数据提示：</span>
          红色为负利润或缺失数据；部分数据不会按 0 参与展示，避免误判店铺经营情况。
        </div>
      </div>
    </div>
  )
}
