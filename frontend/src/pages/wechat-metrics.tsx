import { useEffect, useState } from "react"
import { Search, BarChart3 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { PageHeader, StatCard, FilterBar, FilterItem, EmptyState } from "@/components/page-kit"
import { MetricLineChart } from "@/components/metric-line-chart"
import { getStores, getWechatAnalysis, getWechatTrend, type Store } from "@/api/client"

function formatNumber(v: any, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "-"
  if (typeof v === "number") return v.toLocaleString("zh-CN", { maximumFractionDigits: digits })
  return v
}

const CHART_COLORS = [
  "hsl(var(--chart-1))",
  "hsl(var(--chart-2))",
  "hsl(var(--chart-3))",
  "hsl(var(--chart-4))",
  "hsl(var(--chart-5))",
]
const chartColor = (i: number) => CHART_COLORS[i % CHART_COLORS.length]

const kpiGroups = [
  {
    title: "成交与收入",
    items: [
      { key: "gmv", label: "成交金额", unit: "元" },
      { key: "actual_revenue", label: "实际收款", unit: "元" },
      { key: "valid_gmv", label: "净成交金额", unit: "元" },
      { key: "net_revenue", label: "净收入", unit: "元" },
      { key: "order_count", label: "订单数" },
      { key: "valid_order_count", label: "净订单数" },
      { key: "quantity", label: "商品件数" },
      { key: "valid_quantity", label: "有效件数" },
    ],
  },
  {
    title: "退款与费用",
    items: [
      { key: "refund_orders", label: "退款订单数" },
      { key: "refund_amount", label: "退款金额", unit: "元" },
      { key: "refund_rate", label: "退款率", unit: "%" },
      { key: "refund_amount_rate", label: "退款金额率", unit: "%" },
      { key: "tech_fee", label: "技术服务费", unit: "元" },
      { key: "commission", label: "带货费用", unit: "元" },
      { key: "commission_rate", label: "佣金率", unit: "%" },
    ],
  },
  {
    title: "成本与利润",
    items: [
      { key: "total_cost", label: "总成本", unit: "元" },
      { key: "gross_profit", label: "毛利润", unit: "元" },
      { key: "profit_loss", label: "盈亏", unit: "元" },
      { key: "gross_margin_rate", label: "毛利率", unit: "%" },
      { key: "profit_loss_rate", label: "盈亏率", unit: "%" },
    ],
  },
]

const productColumns = [
  { key: "product_id", label: "商品/SKU" },
  { key: "product_name", label: "商品名称" },
  { key: "sku_code", label: "自定义 SKU" },
  { key: "platform_sku_code", label: "平台 SKU" },
  { key: "gmv", label: "成交金额" },
  { key: "actual_revenue", label: "实际收款" },
  { key: "valid_gmv", label: "净成交金额" },
  { key: "order_count", label: "订单数" },
  { key: "valid_order_count", label: "净订单数" },
  { key: "quantity", label: "商品件数" },
  { key: "valid_quantity", label: "有效件数" },
  { key: "refund_orders", label: "退款订单" },
  { key: "refund_amount", label: "退款金额" },
  { key: "refund_rate", label: "退款率%" },
  { key: "refund_amount_rate", label: "退款金额率%" },
  { key: "tech_fee", label: "技术服务费" },
  { key: "commission", label: "带货费用" },
  { key: "commission_rate", label: "佣金率%" },
  { key: "net_revenue", label: "净收入" },
  { key: "total_cost", label: "总成本" },
  { key: "gross_profit", label: "毛利润" },
  { key: "profit_loss", label: "盈亏" },
  { key: "gross_margin_rate", label: "毛利率%" },
  { key: "profit_loss_rate", label: "盈亏率%" },
]

export function WechatMetricsPage() {
  const [stores, setStores] = useState<Store[]>([])
  const [storeName, setStoreName] = useState("")
  const [startDate, setStartDate] = useState(new Date().toISOString().split("T")[0])
  const [endDate, setEndDate] = useState(new Date().toISOString().split("T")[0])
  const [data, setData] = useState<any>(null)
  const [trend, setTrend] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState("overview")

  useEffect(() => {
    getStores("wechat").then(setStores)
  }, [])

  const handleAnalyze = async () => {
    if (!storeName) return
    setLoading(true)
    try {
      const [analysis, trendData] = await Promise.all([
        getWechatAnalysis(storeName, startDate, endDate),
        getWechatTrend(storeName, startDate, endDate),
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

  return (
    <div>
      <PageHeader title="微信指标" description="按店铺和日期范围分析微信小店经营指标" />

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
            <TabsTrigger value="trend">趋势图</TabsTrigger>
            <TabsTrigger value="products">商品/SKU 明细</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="space-y-4">
            {kpiGroups.map((group) => {
              const items = group.items.filter((item) => kpis[item.key] !== undefined && kpis[item.key] !== null)
              if (items.length === 0) return null
              return (
                <Card key={group.title}>
                  <CardHeader>
                    <CardTitle>{group.title}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
                      {items.map((item) => (
                        <StatCard
                          key={item.key}
                          label={item.label}
                          value={
                            <>
                              {formatNumber(kpis[item.key])}
                              {item.unit && <span className="text-sm font-normal text-muted-foreground"> {item.unit}</span>}
                            </>
                          }
                        />
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </TabsContent>

          <TabsContent value="trend" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <BarChart3 className="h-4 w-4" />
                  趋势细分
                </CardTitle>
                <CardDescription>按主题拆分的多维度走势</CardDescription>
              </CardHeader>
              <CardContent className="grid grid-cols-1 xl:grid-cols-2 gap-6">
                {[
                  {
                    title: "成交与收入",
                    description: "成交金额、实际收款、净成交金额",
                    metrics: [
                      { key: "gmv", name: "成交金额", unit: "元" },
                      { key: "actual_revenue", name: "实际收款", unit: "元" },
                      { key: "valid_gmv", name: "净成交金额", unit: "元" },
                      { key: "net_revenue", name: "净收入", unit: "元" },
                    ],
                  },
                  {
                    title: "订单与售后",
                    description: "订单数、净订单数、退款订单",
                    metrics: [
                      { key: "order_count", name: "订单数" },
                      { key: "valid_order_count", name: "净订单数" },
                      { key: "refund_orders", name: "退款订单" },
                      { key: "quantity", name: "商品件数" },
                    ],
                  },
                  {
                    title: "退款与费用",
                    description: "退款金额、技术服务费、带货费用",
                    metrics: [
                      { key: "refund_amount", name: "退款金额", unit: "元" },
                      { key: "tech_fee", name: "技术服务费", unit: "元" },
                      { key: "commission", name: "带货费用", unit: "元" },
                    ],
                  },
                  {
                    title: "成本与利润",
                    description: "成本、毛利润、盈亏",
                    metrics: [
                      { key: "total_cost", name: "总成本", unit: "元" },
                      { key: "gross_profit", name: "毛利润", unit: "元" },
                      { key: "profit_loss", name: "盈亏", unit: "元" },
                    ],
                  },
                ].map((chart) => (
                  <MetricLineChart
                    key={chart.title}
                    title={chart.title}
                    description={chart.description}
                    data={trend}
                    metrics={chart.metrics.map((m, i) => ({ ...m, color: chartColor(i) }))}
                  />
                ))}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="products">
            <Card>
              <CardHeader>
                <CardTitle>商品/SKU 指标（{data.product_metrics.length} 条）</CardTitle>
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
                      {data.product_metrics.map((row: any, idx: number) => (
                        <TableRow key={idx}>
                          {productColumns.map((col) => {
                            const v = row[col.key]
                            const isRate = col.label.includes("%") || col.key.includes("rate")
                            const isMoney = [
                              "gmv",
                              "actual_revenue",
                              "valid_gmv",
                              "net_revenue",
                              "refund_amount",
                              "tech_fee",
                              "commission",
                              "total_cost",
                              "gross_profit",
                              "profit_loss",
                            ].includes(col.key)
                            return (
                              <TableCell key={col.key} className="text-xs whitespace-nowrap">
                                {col.key === "product_name" ? (
                                  <span className="max-w-[200px] truncate inline-block">{String(v ?? "")}</span>
                                ) : isRate ? (
                                  <Badge variant={(v > 30 && col.key.includes("refund")) ? "destructive" : "default"}>
                                    {formatNumber(v)}
                                  </Badge>
                                ) : (
                                  formatNumber(v, isMoney ? 2 : 0)
                                )}
                              </TableCell>
                            )
                          })}
                        </TableRow>
                      ))}
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
