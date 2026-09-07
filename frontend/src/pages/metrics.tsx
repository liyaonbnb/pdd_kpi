import { Fragment, useEffect, useState } from "react"
import { Search, Eye, EyeOff, ChevronDown, ChevronRight, Download } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { PageHeader, FilterBar, FilterItem, EmptyState } from "@/components/page-kit"
import { MetricLineChart } from "@/components/metric-line-chart"
import { getStores, getAnalysis, getTrend, type Store } from "@/api/client"

function formatNumber(v: any, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "-"
  if (typeof v === "number") return v.toLocaleString("zh-CN", { maximumFractionDigits: digits })
  return v
}

/** 统一 ID 为文本形式（去掉浮点 .0 后缀） */
function normId(v: any): string {
  return String(v ?? "").replace(/\.0$/, "")
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

const CHART_COLORS = [
  "hsl(var(--chart-1))",
  "hsl(var(--chart-2))",
  "hsl(var(--chart-3))",
  "hsl(var(--chart-4))",
  "hsl(var(--chart-5))",
]
const chartColor = (i: number) => CHART_COLORS[i % CHART_COLORS.length]

const MONEY_COLS = ["promo_spend", "promo_gmv", "valid_order_gmv", "valid_merchant_income", "order_gmv", "merchant_income", "total_product_cost", "total_logistics_cost", "platform_fee", "total_cost", "link_gross_profit", "profit_loss", "cpc", "avg_order_gmv", "avg_valid_order_income"]

/** 商品/规格明细单元格渲染 */
function renderMetricCell(
  row: any,
  col: { key: string; label: string },
  opts: { isExpander?: boolean; isOpen?: boolean; onToggle?: () => void } = {},
) {
  const v = row[col.key]
  const isRate = col.label.includes("%") || col.key.includes("rate") || col.key.includes("roi")
  const isMoney = MONEY_COLS.includes(col.key)
  return (
    <TableCell key={col.key} className="text-xs whitespace-nowrap">
      {col.key === "product_name" || col.key === "style_name" ? (
        <span className="max-w-[200px] truncate inline-block">{String(v ?? "")}</span>
      ) : opts.isExpander ? (
        <button onClick={opts.onToggle} className="inline-flex items-center gap-1 hover:text-primary">
          {opts.isOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          {String(v ?? "")}
        </button>
      ) : isRate ? (
        <Badge variant={(v > 30 && col.key.includes("refund")) || (v < 1 && col.key.includes("roi")) ? "destructive" : "default"}>
          {formatNumber(v)}
        </Badge>
      ) : (
        formatNumber(v, isMoney ? 2 : 0)
      )}
    </TableCell>
  )
}

function KpiCard({
  label,
  value,
  unit = "",
  indent = false,
  onClick,
}: {
  label: string
  value: any
  unit?: string
  indent?: boolean
  onClick?: () => void
}) {
  return (
    <Card
      onClick={onClick}
      className={`relative cursor-pointer transition-colors hover:bg-muted/50 ${indent ? "border-l-4 border-l-primary/30" : ""}`}
      title="点击隐藏"
    >
      <CardHeader className="pb-2">
        <CardDescription className={`text-xs ${indent ? "pl-2" : ""}`}>{label}</CardDescription>
        <CardTitle className={`text-xl ${indent ? "pl-2" : ""}`}>
          {formatNumber(value)} {unit && <span className="text-sm font-normal text-muted-foreground">{unit}</span>}
        </CardTitle>
      </CardHeader>
      <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
        <EyeOff className="h-3 w-3 text-muted-foreground" />
      </div>
    </Card>
  )
}

const kpiGroups = [
  {
    title: "成交与收入",
    items: [
      { key: "promo_spend", label: "推广花费", unit: "元" },
      { key: "promo_gmv", label: "推广 GMV", unit: "元" },
      { key: "promo_gmv_ratio", label: "推广 GMV 占比", unit: "%" },
      { key: "promo_orders", label: "推广订单数" },
      { key: "promo_order_ratio", label: "推广订单占比", unit: "%" },
      { key: "order_gmv", label: "订单 GMV", unit: "元" },
      { key: "valid_order_gmv", label: "有效订单 GMV", unit: "元" },
      { key: "valid_order_gmv_ratio", label: "有效 GMV 占比", unit: "%" },
      { key: "merchant_income", label: "商家实收", unit: "元" },
      { key: "valid_merchant_income", label: "有效商家实收", unit: "元" },
      { key: "promo_cost_ratio", label: "推广费比", unit: "%" },
      { key: "order_count", label: "订单数" },
      { key: "valid_order_count", label: "有效订单数" },
    ],
  },
  {
    title: "ROI 与效率",
    items: [
      { key: "promo_roi", label: "推广 ROI" },
      { key: "real_roi", label: "真实 ROI" },
      { key: "valid_order_gmv_roi", label: "有效 GMV ROI" },
      { key: "exposure", label: "曝光量" },
      { key: "clicks", label: "点击量" },
      { key: "ctr", label: "点击率 CTR", unit: "%" },
      { key: "cpc", label: "CPC", unit: "元" },
      { key: "cpm", label: "CPM", unit: "元" },
      { key: "click_to_order_rate", label: "点击转化率", unit: "%" },
      { key: "exposure_to_order_rate", label: "曝光到订单转化率", unit: "%" },
      { key: "promo_cost_per_order", label: "推广单均成本", unit: "元" },
    ],
  },
  {
    title: "退款与取消",
    items: [
      { key: "problem_rate", label: "问题订单率", unit: "%" },
      { key: "refund_rate", label: "退款率", unit: "%" },
      { key: "refund_unshipped_rate", label: "└ 未发货退款率", unit: "%", indent: true },
      { key: "refund_shipped_rate", label: "└ 已发货退款率", unit: "%", indent: true },
      { key: "refund_received_rate", label: "└ 已收货退款率", unit: "%", indent: true },
      { key: "cancel_rate", label: "取消率", unit: "%" },
      { key: "refund_count", label: "退款数" },
      { key: "refund_unshipped_count", label: "└ 未发货退款数", indent: true },
      { key: "refund_shipped_count", label: "└ 已发货退款数", indent: true },
      { key: "refund_received_count", label: "└ 已收货退款数", indent: true },
      { key: "cancel_count", label: "取消数" },
    ],
  },
  {
    title: "自然流量",
    items: [
      { key: "organic_orders", label: "自然订单数" },
      { key: "organic_valid_order_count", label: "自然有效订单数" },
      { key: "organic_gmv", label: "自然 GMV", unit: "元" },
      { key: "organic_merchant_income", label: "自然有效商家实收", unit: "元" },
      { key: "organic_ratio_orders", label: "自然订单占比", unit: "%" },
      { key: "organic_ratio_valid_orders", label: "自然有效订单占比", unit: "%" },
      { key: "organic_ratio_gmv", label: "自然 GMV 占比", unit: "%" },
      { key: "organic_ratio_income", label: "自然有效收入占比", unit: "%" },
    ],
  },
  {
    title: "成本与利润",
    items: [
      { key: "total_product_cost", label: "商品成本", unit: "元" },
      { key: "total_logistics_cost", label: "物流成本", unit: "元" },
      { key: "platform_fee", label: "平台技术费", unit: "元" },
      { key: "total_cost", label: "总成本", unit: "元" },
      { key: "link_gross_profit", label: "链接毛利", unit: "元" },
      { key: "profit_loss", label: "盈亏", unit: "元" },
      { key: "gross_margin_rate", label: "毛利率", unit: "%" },
      { key: "profit_loss_rate", label: "盈亏率", unit: "%" },
    ],
  },
]

// 导出 CSV 时的附加列（样式明细专属字段，商品行大多也有）
const exportExtraColumns = [
  { key: "order_gmv", label: "订单GMV" },
  { key: "merchant_income", label: "商家实收" },
  { key: "quantity", label: "件数" },
  { key: "valid_quantity", label: "有效件数" },
  { key: "refund_count", label: "退款数" },
  { key: "cancel_count", label: "取消数" },
  { key: "refund_unshipped_count", label: "未发货退款" },
  { key: "refund_shipped_count", label: "已发货退款" },
  { key: "refund_received_count", label: "已收货退款" },
]

const productColumns = [
  { key: "product_id", label: "商品ID" },
  { key: "product_name", label: "商品名称" },
  { key: "promo_spend", label: "推广花费" },
  { key: "promo_gmv", label: "推广GMV" },
  { key: "promo_orders", label: "推广订单" },
  { key: "exposure", label: "曝光量" },
  { key: "clicks", label: "点击量" },
  { key: "ctr", label: "CTR%" },
  { key: "cpc", label: "CPC" },
  { key: "cpm", label: "CPM" },
  { key: "order_count", label: "订单数" },
  { key: "valid_order_count", label: "有效订单" },
  { key: "valid_order_gmv", label: "有效GMV" },
  { key: "valid_merchant_income", label: "有效收入" },
  { key: "promo_roi", label: "推广ROI" },
  { key: "real_roi_merchant_income", label: "真实ROI" },
  { key: "refund_rate", label: "退款率%" },
  { key: "cancel_rate", label: "取消率%" },
  { key: "problem_rate", label: "问题率%" },
  { key: "organic_ratio_gmv", label: "自然GMV%" },
  { key: "organic_ratio_orders", label: "自然订单%" },
  { key: "organic_merchant_income", label: "自然有效收入" },
  { key: "organic_valid_order_count", label: "自然有效订单" },
  { key: "organic_ratio_income", label: "自然收入%" },
  { key: "organic_ratio_valid_orders", label: "自然有效订单%" },
  { key: "avg_order_gmv", label: "客单价" },
  { key: "avg_valid_order_income", label: "单均收入" },
  { key: "total_product_cost", label: "商品成本" },
  { key: "total_logistics_cost", label: "物流成本" },
  { key: "platform_fee", label: "平台技术费" },
  { key: "total_cost", label: "总成本" },
  { key: "link_gross_profit", label: "毛利" },
  { key: "profit_loss", label: "盈亏" },
  { key: "gross_margin_rate", label: "毛利率%" },
  { key: "profit_loss_rate", label: "盈亏率%" },
]

export function MetricsPage() {
  const [stores, setStores] = useState<Store[]>([])
  const [storeName, setStoreName] = useState("")
  const [startDate, setStartDate] = useState(new Date().toISOString().split("T")[0])
  const [endDate, setEndDate] = useState(new Date().toISOString().split("T")[0])
  const [data, setData] = useState<any>(null)
  const [trend, setTrend] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState("overview")
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const toggleExpand = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }
  const [hiddenKpis, setHiddenKpis] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem("pdd_hidden_kpis") || "[]"))
    } catch {
      return new Set()
    }
  })

  useEffect(() => {
    getStores("pdd").then(setStores)
  }, [])

  const toggleKpi = (key: string) => {
    setHiddenKpis((prev) => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      localStorage.setItem("pdd_hidden_kpis", JSON.stringify(Array.from(next)))
      return next
    })
  }

  const handleAnalyze = async () => {
    if (!storeName) return
    setLoading(true)
    try {
      const [analysis, trendData] = await Promise.all([
        getAnalysis(storeName, startDate, endDate),
        getTrend([storeName], startDate, endDate),
      ])
      setData(analysis)
      setTrend(trendData)
    } catch (err: any) {
      alert(err.message)
    } finally {
      setLoading(false)
    }
  }

  const kpis = data?.kpis || {}

  // 规格明细按商品ID分组，用于商品明细的展开子行
  const stylesByProduct: Record<string, any[]> = {}
  ;(data?.style_metrics || []).forEach((s: any) => {
    const k = normId(s.product_id)
    ;(stylesByProduct[k] = stylesByProduct[k] || []).push(s)
  })

  return (
    <div>
      <PageHeader title="指标分析" description="按店铺和日期范围分析拼多多经营指标" />

      <FilterBar>
        <FilterItem label="店铺">
          <Select value={storeName} onChange={(e) => setStoreName(e.target.value)}>
            <option value="">选择店铺</option>
            {stores.map((s) => (
              <option key={s.id} value={s.name}>
                {s.name}
              </option>
            ))}
          </Select>
        </FilterItem>
        <FilterItem label="开始日期">
          <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </FilterItem>
        <FilterItem label="结束日期">
          <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </FilterItem>
        <Button onClick={handleAnalyze} disabled={loading}>
          <Search className="h-4 w-4" /> {loading ? "分析中..." : "分析"}
        </Button>
      </FilterBar>

      {data && (
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="flex-wrap h-auto">
            <TabsTrigger value="overview">总览 KPI</TabsTrigger>
            <TabsTrigger value="trend">趋势</TabsTrigger>
            <TabsTrigger value="products">商品明细</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="space-y-4">
            {kpiGroups.map((group) => {
              const allItems = group.items.filter((item) => kpis[item.key] !== undefined && kpis[item.key] !== null)
              const visibleItems = allItems.filter((item) => !hiddenKpis.has(item.key))
              const hiddenItems = allItems.filter((item) => hiddenKpis.has(item.key))
              if (allItems.length === 0) return null
              return (
                <Card key={group.title}>
                  <CardHeader>
                    <CardTitle>{group.title}</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                      {visibleItems.map((item) => (
                        <KpiCard
                          key={item.key}
                          label={item.label}
                          value={kpis[item.key]}
                          unit={item.unit}
                          indent={(item as any).indent}
                          onClick={() => toggleKpi(item.key)}
                        />
                      ))}
                    </div>
                    {hiddenItems.length > 0 && (
                      <div className="flex flex-wrap items-center gap-2 pt-2 border-t">
                        <span className="text-xs text-muted-foreground">已隐藏：</span>
                        {hiddenItems.map((item) => (
                          <button
                            key={item.key}
                            onClick={() => toggleKpi(item.key)}
                            className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-muted hover:bg-muted/80"
                            title="点击显示"
                          >
                            <Eye className="h-3 w-3" />
                            {item.label}
                          </button>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              )
            })}
          </TabsContent>

          <TabsContent value="trend" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>趋势细分</CardTitle>
                <CardDescription>按主题拆分的多维度走势（点击上方标签可单独显示/隐藏折线）</CardDescription>
              </CardHeader>
              <CardContent className="grid grid-cols-1 xl:grid-cols-2 gap-6">
                {[
                  {
                    title: "成交与收入",
                    description: "推广花费、推广 GMV、订单 GMV、有效 GMV",
                    metrics: [
                      { key: "promo_spend", name: "推广花费", unit: "元" },
                      { key: "promo_gmv", name: "推广 GMV", unit: "元" },
                      { key: "order_gmv", name: "订单 GMV", unit: "元" },
                      { key: "valid_order_gmv", name: "有效 GMV", unit: "元" },
                      { key: "promo_cost_ratio", name: "推广费比", unit: "%" },
                    ],
                  },
                  {
                    title: "ROI 与效率",
                    description: "推广 ROI、真实 ROI、有效 GMV ROI",
                    metrics: [
                      { key: "promo_roi", name: "推广 ROI" },
                      { key: "real_roi", name: "真实 ROI" },
                      { key: "valid_order_gmv_roi", name: "有效 GMV ROI" },
                    ],
                  },
                  {
                    title: "流量与点击成本",
                    description: "曝光量、点击量、CTR、CPC、CPM",
                    metrics: [
                      { key: "exposure", name: "曝光量", unit: "次" },
                      { key: "clicks", name: "点击量", unit: "次" },
                      { key: "ctr", name: "CTR", unit: "%" },
                      { key: "cpc", name: "CPC", unit: "元" },
                      { key: "cpm", name: "CPM", unit: "元" },
                    ],
                  },
                  {
                    title: "退款与取消",
                    description: "退款率、取消率、问题订单率及三阶段退款率",
                    metrics: [
                      { key: "refund_rate", name: "退款率", unit: "%" },
                      { key: "cancel_rate", name: "取消率", unit: "%" },
                      { key: "problem_rate", name: "问题订单率", unit: "%" },
                      { key: "refund_unshipped_rate", name: "未发货退款率", unit: "%" },
                      { key: "refund_shipped_rate", name: "已发货退款率", unit: "%" },
                      { key: "refund_received_rate", name: "已收货退款率", unit: "%" },
                    ],
                  },
                  {
                    title: "自然流量（有效）",
                    description: "自然有效订单、自然有效收入及占比",
                    metrics: [
                      { key: "organic_valid_order_count", name: "自然有效订单", unit: "单" },
                      { key: "organic_merchant_income", name: "自然有效收入", unit: "元" },
                      { key: "organic_ratio_valid_orders", name: "自然有效订单占比", unit: "%" },
                      { key: "organic_ratio_income", name: "自然有效收入占比", unit: "%" },
                    ],
                  },
                  {
                    title: "成本与利润",
                    description: "商品成本、物流成本、毛利、盈亏、毛利率、盈亏率",
                    metrics: [
                      { key: "total_product_cost", name: "商品成本", unit: "元" },
                      { key: "total_logistics_cost", name: "物流成本", unit: "元" },
                      { key: "link_gross_profit", name: "链接毛利", unit: "元" },
                      { key: "profit_loss", name: "盈亏", unit: "元" },
                      { key: "gross_margin_rate", name: "毛利率", unit: "%" },
                      { key: "profit_loss_rate", name: "盈亏率", unit: "%" },
                    ],
                  },
                ].map((chart) => (
                  <MetricLineChart
                    key={chart.title}
                    title={chart.title}
                    description={chart.description}
                    data={trend}
                    metrics={chart.metrics.map((m, i) => ({ ...m, color: chartColor(i) }))}
                    hiddenKeys={hiddenKpis}
                  />
                ))}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="products">
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>
                    商品指标（{data.product_metrics.length} 个商品 / {data.style_metrics.length} 个规格）
                  </CardTitle>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      const rows: any[] = []
                      data.product_metrics.forEach((row: any) => {
                        rows.push(row)
                        const pid = normId(row.product_id)
                        ;(stylesByProduct[pid] || []).forEach((s: any) => {
                          rows.push({
                            ...s,
                            product_id: normId(s.style_id),
                            product_name: `↳ ${s.style_name || s.style_id || "未命名规格"}`,
                          })
                        })
                      })
                      downloadCsv(`商品明细_${storeName}_${startDate}_${endDate}.csv`, rows, [...productColumns, ...exportExtraColumns])
                    }}
                    disabled={data.product_metrics.length === 0}
                  >
                    <Download className="h-4 w-4 mr-1" /> 导出 CSV
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                <div className="overflow-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        {productColumns.map((col) => (
                          <TableHead key={col.key} className="whitespace-nowrap text-xs">
                            {col.label}
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.product_metrics.map((row: any, idx: number) => {
                        const pid = normId(row.product_id)
                        const styles = stylesByProduct[pid] || []
                        const isOpen = expanded.has(pid)
                        return (
                          <Fragment key={idx}>
                            <TableRow>
                              {productColumns.map((col) => renderMetricCell(row, col, {
                                isExpander: col.key === "product_id" && styles.length > 0,
                                isOpen,
                                onToggle: () => toggleExpand(pid),
                              }))}
                            </TableRow>
                            {isOpen &&
                              styles.map((s: any, si: number) => {
                                const srow = {
                                  ...s,
                                  product_id: normId(s.style_id),
                                  product_name: `↳ ${s.style_name || s.style_id || "未命名规格"}`,
                                }
                                return (
                                  <TableRow key={`s-${si}`} className="bg-muted/40">
                                    {productColumns.map((col) => renderMetricCell(srow, col, {}))}
                                  </TableRow>
                                )
                              })}
                          </Fragment>
                        )
                      })}
                      {data.product_metrics.length === 0 && (
                        <TableRow>
                          <TableCell colSpan={productColumns.length}>
                            <EmptyState title="无数据" hint="当前筛选条件下没有商品指标" />
                          </TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      )}
    </div>
  )
}
