import { Fragment, useEffect, useMemo, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import {
  AlertTriangle,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronRight,
  Download,
  Layers3,
  RefreshCw,
  Send,
  Sparkles,
  Store,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  getStores,
  getOperationsDaily,
  previewOperationsDailyWecom,
  sendOperationsDailyWecom,
  type OperationsDailyPlatform,
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

type StoreMultiSelectProps = {
  stores: string[]
  selectedStores: string[]
  onChange: (stores: string[]) => void
  onApply: () => void
  disabled?: boolean
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

const platformAccent: Record<OperationsDailyPlatform["platform"], string> = {
  pdd: "border-l-red-500",
  douyin: "border-l-cyan-500",
  tmall: "border-l-orange-500",
  wechat: "border-l-emerald-500",
}

function StoreMultiSelect({ stores, selectedStores, onChange, onApply, disabled }: StoreMultiSelectProps) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const selectedSet = useMemo(() => new Set(selectedStores), [selectedStores])
  const allSelected = stores.length > 0 && selectedStores.length === stores.length

  useEffect(() => {
    if (!open) return

    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false)
    }

    document.addEventListener("pointerdown", closeOnOutsideClick)
    document.addEventListener("keydown", closeOnEscape)
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick)
      document.removeEventListener("keydown", closeOnEscape)
    }
  }, [open])

  const toggleStore = (storeName: string) => {
    onChange(
      selectedSet.has(storeName)
        ? selectedStores.filter((name) => name !== storeName)
        : [...selectedStores, storeName],
    )
  }

  const buttonLabel = stores.length === 0
    ? "暂无店铺"
    : allSelected
      ? `全部店铺（${stores.length}）`
      : selectedStores.length > 0
        ? `已选 ${selectedStores.length} / ${stores.length} 家`
        : "请选择店铺"

  return (
    <div ref={containerRef} className="relative">
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="w-48 justify-between font-normal"
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled || stores.length === 0}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="truncate">{buttonLabel}</span>
        <ChevronDown className={cn("size-4 shrink-0 transition-transform", open && "rotate-180")} />
      </Button>

      {open ? (
        <div className="absolute left-0 top-full z-50 mt-1 w-72 overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-lg">
          <div className="flex items-center justify-between border-b px-3 py-2">
            <span className="text-xs font-medium">选择参与汇总的店铺</span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                className="rounded px-2 py-1 text-xs text-primary hover:bg-muted"
                onClick={() => onChange(stores)}
              >
                全选
              </button>
              <button
                type="button"
                className="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
                onClick={() => onChange([])}
              >
                清空
              </button>
            </div>
          </div>
          <div role="listbox" aria-multiselectable="true" className="max-h-72 overflow-y-auto p-1.5">
            {stores.map((storeName) => {
              const checked = selectedSet.has(storeName)
              return (
                <button
                  key={storeName}
                  type="button"
                  role="option"
                  aria-selected={checked}
                  className="flex w-full items-center gap-2 rounded-sm px-2 py-2 text-left text-sm hover:bg-muted"
                  onClick={() => toggleStore(storeName)}
                >
                  <span className={cn(
                    "flex size-4 shrink-0 items-center justify-center rounded border",
                    checked ? "border-primary bg-primary text-primary-foreground" : "border-input",
                  )}>
                    {checked ? <Check className="size-3" /> : null}
                  </span>
                  <span className="truncate">{storeName}</span>
                </button>
              )
            })}
          </div>
          <div className="flex items-center justify-between gap-3 border-t bg-muted/30 px-3 py-2">
            <span className="text-[11px] text-muted-foreground">汇总、矩阵和导出将同步更新</span>
            <Button
              type="button"
              size="sm"
              className="h-7 px-3 text-xs"
              disabled={selectedStores.length === 0}
              onClick={() => {
                onApply()
                setOpen(false)
              }}
            >
              应用筛选
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function buildReportSearchParams(startDate: string, endDate: string, selectedStores: string[], storeCount: number) {
  const params = new URLSearchParams({ start: startDate, end: endDate })
  if (selectedStores.length > 0 && selectedStores.length < storeCount) {
    selectedStores.forEach((storeName) => params.append("store", storeName))
  }
  return params
}

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

function PlatformOverview({ platforms }: { platforms: OperationsDailyPlatform[] }) {
  return (
    <section className="space-y-3" aria-labelledby="platform-overview-title">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h3 id="platform-overview-title" className="flex items-center gap-2 text-base font-semibold">
            <Layers3 className="size-4" />
            平台经营概览
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">统一展示有效实收、订单、投放、利润与退款表现。</p>
        </div>
        <Badge variant="outline">{platforms.filter((item) => item.has_data).length} / {platforms.length} 个平台有数据</Badge>
      </div>

      <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-4">
        {platforms.map((platform) => {
          const latest = platform.daily[platform.daily.length - 1]
          return (
            <Card key={platform.platform} className={cn("border-l-4", platformAccent[platform.platform])}>
              <CardHeader className="flex flex-row items-start justify-between gap-3 p-4 pb-3">
                <div>
                  <CardTitle className="text-base">{platform.label}</CardTitle>
                  <CardDescription className="mt-1">{platform.store_count} 家店铺 · {platform.data_days} 个数据日</CardDescription>
                </div>
                <Badge variant={platform.has_data ? "secondary" : "outline"}>
                  {platform.has_data ? "已汇总" : "暂无数据"}
                </Badge>
              </CardHeader>
              <CardContent className="space-y-3 px-4 pb-4">
                {platform.has_data ? (
                  <>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-3">
                      <div>
                        <div className="text-[11px] text-muted-foreground">有效实收</div>
                        <div className="mt-0.5 text-sm font-semibold tabular-nums">{formatValue(platform.totals.income, "money")}</div>
                      </div>
                      <div>
                        <div className="text-[11px] text-muted-foreground">经营利润</div>
                        <div className={cn("mt-0.5 text-sm font-semibold tabular-nums", platform.totals.profit_loss < 0 && "text-destructive")}>
                          {formatValue(platform.totals.profit_loss, "money")}
                        </div>
                      </div>
                      <div>
                        <div className="text-[11px] text-muted-foreground">有效订单</div>
                        <div className="mt-0.5 text-sm font-semibold tabular-nums">{formatValue(platform.totals.order_count, "integer")}</div>
                      </div>
                      <div>
                        <div className="text-[11px] text-muted-foreground">经营利润率</div>
                        <div className={cn("mt-0.5 text-sm font-semibold tabular-nums", platform.totals.profit_loss_rate < 0 && "text-destructive")}>
                          {formatValue(platform.totals.profit_loss_rate, "rate")}
                        </div>
                      </div>
                      <div>
                        <div className="text-[11px] text-muted-foreground">{platform.totals.promo_spend === null ? "退款率" : "推广费"}</div>
                        <div className="mt-0.5 text-sm font-semibold tabular-nums">
                          {platform.totals.promo_spend === null
                            ? formatValue(platform.totals.refund_rate, "rate")
                            : formatValue(platform.totals.promo_spend, "money")}
                        </div>
                      </div>
                      <div>
                        <div className="text-[11px] text-muted-foreground">{platform.totals.roi === null ? "数据日" : "投放 ROI"}</div>
                        <div className="mt-0.5 text-sm font-semibold tabular-nums">
                          {platform.totals.roi === null
                            ? `${platform.data_days} 天`
                            : platform.totals.roi.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}
                        </div>
                      </div>
                    </div>
                    <div className="border-t pt-2 text-[11px] text-muted-foreground">
                      {latest ? `最近数据 ${shortDate(latest.date)} · 实收 ${formatValue(latest.income, "money")}` : "当前范围无每日明细"}
                    </div>
                  </>
                ) : (
                  <div className="flex min-h-32 items-center justify-center text-sm text-muted-foreground">当前日期范围暂无已导入数据</div>
                )}
              </CardContent>
            </Card>
          )
        })}
      </div>
    </section>
  )
}

function downloadReport(report: OperationsDailyReport, visibleMetrics: MetricDefinition[], filtered: boolean) {
  const headers = ["店铺", "指标", "期间合计", ...report.dates.map(shortDate)]
  const total = filtered ? { ...report.total, store_name: "所选店铺汇总" } : report.total
  const groups = [total, ...report.stores]
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
  const storeParams = searchParams.getAll("store")
  const storeParamKey = storeParams.join("\u001f")
  const [startDate, setStartDate] = useState(startParam)
  const [endDate, setEndDate] = useState(endParam)
  const [stores, setStores] = useState<string[]>([])
  const [selectedStores, setSelectedStores] = useState<string[]>(storeParams)
  const [storesLoading, setStoresLoading] = useState(true)
  const [report, setReport] = useState<OperationsDailyReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [showDetails, setShowDetails] = useState(false)
  const [collapsedStores, setCollapsedStores] = useState<Set<string>>(new Set())
  const [wecomPreviewLoading, setWecomPreviewLoading] = useState(false)
  const [wecomSendLoading, setWecomSendLoading] = useState(false)
  const [wecomDraftId, setWecomDraftId] = useState("")
  const [wecomDraftContent, setWecomDraftContent] = useState("")
  const [wecomDraftSent, setWecomDraftSent] = useState(false)
  const [wecomMessage, setWecomMessage] = useState("")
  const [wecomMessageKind, setWecomMessageKind] = useState<"success" | "error">("success")

  const visibleMetrics = useMemo(
    () => metrics.filter((metric) => showDetails || !metric.detail),
    [showDetails],
  )
  const isFiltered = storeParams.length > 0

  useEffect(() => {
    let active = true
    getStores("pdd")
      .then((data) => {
        if (!active) return
        setStores(data.map((store) => store.name))
      })
      .catch((err) => active && setError(err.message || "店铺列表加载失败"))
      .finally(() => active && setStoresLoading(false))
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (stores.length === 0) return
    const requestedStores = storeParamKey ? storeParamKey.split("\u001f") : stores
    const validStores = requestedStores.filter((name) => stores.includes(name))
    setSelectedStores(validStores.length > 0 ? validStores : stores)
  }, [storeParamKey, stores])

  useEffect(() => {
    let active = true
    const requestedStores = storeParamKey ? storeParamKey.split("\u001f") : []
    setLoading(true)
    setError("")
    getOperationsDaily(startParam || undefined, endParam || undefined, requestedStores.length > 0 ? requestedStores : undefined)
      .then((data) => {
        if (!active) return
        setReport(data)
        setStartDate(data.start_date)
        setEndDate(data.end_date)
        if (!startParam || !endParam) {
          const nextParams = new URLSearchParams()
          nextParams.set("start", data.start_date)
          nextParams.set("end", data.end_date)
          requestedStores.forEach((storeName) => nextParams.append("store", storeName))
          setSearchParams(nextParams, { replace: true })
        }
      })
      .catch((err) => active && setError(err.message || "运营日报加载失败"))
      .finally(() => active && setLoading(false))
    return () => {
      active = false
    }
  }, [startParam, endParam, storeParamKey, setSearchParams])

  useEffect(() => {
    setWecomDraftId("")
    setWecomDraftContent("")
    setWecomDraftSent(false)
    setWecomMessage("")
  }, [startParam, endParam])

  const applyRange = () => {
    if (!startDate || !endDate) return
    if (selectedStores.length === 0) {
      setError("请至少选择一个店铺")
      return
    }
    setError("")
    setSearchParams(buildReportSearchParams(startDate, endDate, selectedStores, stores.length))
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
    setSearchParams(buildReportSearchParams(format(start), format(end), selectedStores, stores.length))
  }

  const toggleStore = (storeName: string) => {
    setCollapsedStores((current) => {
      const next = new Set(current)
      if (next.has(storeName)) next.delete(storeName)
      else next.add(storeName)
      return next
    })
  }

  const handleWecomPreview = async () => {
    if (!report || wecomPreviewLoading || wecomSendLoading) return
    setWecomPreviewLoading(true)
    setWecomDraftId("")
    setWecomDraftContent("")
    setWecomDraftSent(false)
    setWecomMessage("")
    try {
      const draft = await previewOperationsDailyWecom(report.start_date, report.end_date)
      setWecomDraftId(draft.draft_id)
      setWecomDraftContent(draft.content)
      setWecomMessageKind("success")
      setWecomMessage("全平台企微日报已生成")
    } catch (err: any) {
      setWecomMessageKind("error")
      setWecomMessage(err.message || "企微日报生成失败")
    } finally {
      setWecomPreviewLoading(false)
    }
  }

  const handleWecomSend = async () => {
    if (!report || !wecomDraftId || wecomSendLoading || wecomPreviewLoading || wecomDraftSent) return
    setWecomSendLoading(true)
    setWecomMessage("")
    try {
      await sendOperationsDailyWecom(report.start_date, report.end_date, wecomDraftId)
      setWecomDraftSent(true)
      setWecomMessageKind("success")
      setWecomMessage("全平台运营日报已发送到企业微信")
    } catch (err: any) {
      setWecomMessageKind("error")
      setWecomMessage(err.message || "企业微信发送失败")
    } finally {
      setWecomSendLoading(false)
    }
  }

  const summaryCards = report
    ? [
        { label: "全平台有效实收", value: formatValue(report.platform_summary.income, "money") },
        { label: "全平台经营利润", value: formatValue(report.platform_summary.profit_loss, "money"), negative: report.platform_summary.profit_loss < 0 },
        { label: "经营利润率", value: formatValue(report.platform_summary.profit_loss_rate, "rate"), negative: report.platform_summary.profit_loss_rate < 0 },
        { label: "全平台推广费", value: formatValue(report.platform_summary.promo_spend, "money") },
        { label: "覆盖店铺", value: `${report.platform_summary.store_count || 0} 家` },
        { label: "数据平台", value: `${report.platform_summary.data_platform_count} / ${report.platform_summary.platform_count} 个`, alert: report.platform_summary.data_platform_count < report.platform_summary.platform_count },
      ]
    : []

  const groups = report
    ? [isFiltered ? { ...report.total, store_name: "所选店铺汇总" } : report.total, ...report.stores]
    : []

  return (
    <div className="mx-auto flex w-full max-w-[1800px] flex-col gap-5">
      <div className="flex flex-col gap-3 2xl:flex-row 2xl:items-end 2xl:justify-between">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
            <Store className="size-3.5" />
            全平台 · 主账号视图
          </div>
          <h2 className="text-2xl font-bold tracking-tight">全平台运营日报</h2>
          <p className="text-sm text-muted-foreground">统一查看各平台收入、订单、投放与利润，并下钻拼多多店铺日数据。</p>
        </div>

        <div className="flex max-w-full flex-wrap items-end gap-2 2xl:justify-end">
          <div className="flex flex-col gap-1 text-xs text-muted-foreground">
            <span>拼多多矩阵店铺</span>
            <StoreMultiSelect
              stores={stores}
              selectedStores={selectedStores}
              onChange={setSelectedStores}
              onApply={applyRange}
              disabled={storesLoading || loading}
            />
          </div>
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
          <Button size="sm" onClick={applyRange} disabled={loading || storesLoading || selectedStores.length === 0}>
            <RefreshCw data-icon="inline-start" className={cn(loading && "animate-spin")} />
            查询
          </Button>
          <Button variant="outline" size="sm" onClick={handleWecomPreview} disabled={!report || loading || wecomPreviewLoading || wecomSendLoading}>
            <Sparkles className={cn("size-4", wecomPreviewLoading && "animate-pulse")} />
            {wecomPreviewLoading ? "生成中" : "生成企微预览"}
          </Button>
          <Button size="sm" onClick={handleWecomSend} disabled={!wecomDraftId || wecomDraftSent || wecomPreviewLoading || wecomSendLoading}>
            <Send className={cn("size-4", wecomSendLoading && "animate-pulse")} />
            {wecomDraftSent ? "已发送" : wecomSendLoading ? "发送中" : "发送到企微"}
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

      {wecomMessage || wecomDraftContent ? (
        <section className="border-y bg-muted/20 px-4 py-3" aria-live="polite">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className={cn("text-sm", wecomMessageKind === "error" ? "text-destructive" : "text-foreground")}>{wecomMessage}</div>
            {wecomDraftContent ? <Badge variant="outline">草稿 30 分钟有效</Badge> : null}
          </div>
          {wecomDraftContent ? (
            <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap border-t pt-3 text-xs leading-5 text-muted-foreground">{wecomDraftContent}</pre>
          ) : null}
        </section>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
        {summaryCards.map((card) => {
          const hasIssues = Boolean(card.alert)
          return (
            <Card key={card.label} className={cn(hasIssues && "border-destructive/40")}>
              <CardHeader className="p-4 pb-2">
                <CardDescription className="text-xs">{card.label}</CardDescription>
                <CardTitle className={cn("text-xl tabular-nums", card.negative && "text-destructive")}>{card.value}</CardTitle>
              </CardHeader>
              {hasIssues && (
                <CardContent className="px-4 pb-4 pt-0 text-xs text-destructive">存在平台暂无当前范围数据</CardContent>
              )}
            </Card>
          )
        })}
      </div>

      {report ? <PlatformOverview platforms={report.platforms} /> : null}

      <Card>
        <CardHeader className="flex flex-col gap-3 border-b p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-col gap-1">
            <CardTitle className="flex items-center gap-2 text-base">
              <CalendarDays className="size-4" />
              拼多多店铺经营矩阵
            </CardTitle>
            <CardDescription>金额按期间求和，比率按汇总金额重新计算；“—”表示当天没有可用数据。</CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => setShowDetails((value) => !value)}>
              {showDetails ? "收起辅助指标" : "展开辅助指标"}
            </Button>
            <Button variant="outline" size="sm" disabled={!report} onClick={() => report && downloadReport(report, visibleMetrics, isFiltered)}>
              <Download data-icon="inline-start" />
              导出 CSV
            </Button>
          </div>
        </CardHeader>

        <CardContent className="p-0">
          {loading && !report ? (
            <div className="flex min-h-64 items-center justify-center gap-2 text-sm text-muted-foreground">
              <RefreshCw className="size-4 animate-spin" />
              正在汇总全平台经营数据…
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
