import { useEffect, useState } from "react"
import { Calendar } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { MetricLineChart } from "@/components/metric-line-chart"
import { HideableKpiCard, HiddenKpiList } from "@/components/hideable-kpi"
import { PageHeader, StatCard, FilterBar, FilterItem, EmptyState } from "@/components/page-kit"
import { useHiddenKpis } from "@/hooks/use-hidden-kpis"
import { getStores, getDashboardSummary, type Kpis } from "@/api/client"

const kpiGroups = [
  {
    title: "成交与收入",
    items: [
      { key: "promo_spend", label: "推广花费", unit: "元" },
      { key: "promo_gmv", label: "推广 GMV", unit: "元" },
      { key: "order_gmv", label: "订单 GMV", unit: "元" },
      { key: "valid_order_gmv", label: "有效订单 GMV", unit: "元" },
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
      { key: "ctr", label: "点击率 CTR", unit: "%" },
      { key: "cpc", label: "CPC", unit: "元" },
      { key: "cpm", label: "CPM", unit: "元" },
    ],
  },
  {
    title: "退款与取消",
    items: [
      { key: "problem_rate", label: "问题订单率", unit: "%" },
      { key: "refund_rate", label: "退款率", unit: "%" },
      { key: "cancel_rate", label: "取消率", unit: "%" },
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

const trendCharts = [
  {
    title: "成交与收入",
    description: "推广花费、GMV、有效 GMV",
    metrics: [
      { key: "promo_spend", name: "推广花费", color: "hsl(var(--chart-1))", unit: "元" },
      { key: "promo_gmv", name: "推广 GMV", color: "hsl(var(--chart-2))", unit: "元" },
      { key: "order_gmv", name: "订单 GMV", color: "hsl(var(--chart-3))", unit: "元" },
      { key: "valid_order_gmv", name: "有效 GMV", color: "hsl(var(--chart-4))", unit: "元" },
    ],
  },
  {
    title: "ROI 与效率",
    description: "推广 ROI、真实 ROI、CTR",
    metrics: [
      { key: "promo_roi", name: "推广 ROI", color: "hsl(var(--chart-1))" },
      { key: "real_roi", name: "真实 ROI", color: "hsl(var(--chart-2))" },
      { key: "ctr", name: "CTR", color: "hsl(var(--chart-3))", unit: "%" },
    ],
  },
  {
    title: "流量与点击成本",
    description: "曝光量、点击量、CPC、CPM",
    metrics: [
      { key: "exposure", name: "曝光量", color: "hsl(var(--chart-1))", unit: "次" },
      { key: "clicks", name: "点击量", color: "hsl(var(--chart-2))", unit: "次" },
      { key: "cpc", name: "CPC", color: "hsl(var(--chart-3))", unit: "元" },
      { key: "cpm", name: "CPM", color: "hsl(var(--chart-4))", unit: "元" },
    ],
  },
  {
    title: "退款与取消",
    description: "问题订单率、退款率、取消率",
    metrics: [
      { key: "problem_rate", name: "问题订单率", color: "hsl(var(--chart-1))", unit: "%" },
      { key: "refund_rate", name: "退款率", color: "hsl(var(--chart-2))", unit: "%" },
      { key: "cancel_rate", name: "取消率", color: "hsl(var(--chart-3))", unit: "%" },
    ],
  },
  {
    title: "成本与利润",
    description: "商品成本、物流成本、毛利、盈亏、毛利率、盈亏率",
    metrics: [
      { key: "total_product_cost", name: "商品成本", color: "hsl(var(--chart-1))", unit: "元" },
      { key: "total_logistics_cost", name: "物流成本", color: "hsl(var(--chart-2))", unit: "元" },
      { key: "total_cost", name: "总成本", color: "hsl(var(--chart-3))", unit: "元" },
      { key: "link_gross_profit", name: "链接毛利", color: "hsl(var(--chart-4))", unit: "元" },
      { key: "profit_loss", name: "盈亏", color: "hsl(var(--chart-5))", unit: "元" },
      { key: "gross_margin_rate", name: "毛利率", color: "hsl(var(--chart-1))", unit: "%" },
      { key: "profit_loss_rate", name: "盈亏率", color: "hsl(var(--chart-2))", unit: "%" },
    ],
  },
]

export function DashboardPage() {
  const [stores, setStores] = useState<{ id: string; name: string }[]>([])
  const [selectedStores, setSelectedStores] = useState<string[]>([])
  const [startDate, setStartDate] = useState(() => {
    const d = new Date()
    d.setDate(d.getDate() - 30)
    return d.toISOString().split("T")[0]
  })
  const [endDate, setEndDate] = useState(() => new Date().toISOString().split("T")[0])
  const [kpis, setKpis] = useState<Kpis>({})
  const [trend, setTrend] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState("")
  const [activeTab, setActiveTab] = useState("overview")
  const { hiddenKpis, toggleKpi } = useHiddenKpis("pdd_hidden_kpis")

  useEffect(() => {
    getStores("pdd").then((s) => {
      setStores(s)
      setSelectedStores(s.map((x) => x.name))
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
      const data = await getDashboardSummary(startDate, endDate, selectedStores)
      setKpis(data.kpis)
      setTrend(data.trend)
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setLoading(false)
    }
  }

  const toggleStore = (name: string) => {
    setSelectedStores((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]
    )
  }

  const hasKpis = kpis && Object.keys(kpis).length > 0

  return (
    <div className="space-y-4">
      <PageHeader
        title="总览"
        description="拼多多店铺经营数据总览"
        actions={
          <Button onClick={fetchSummary} disabled={loading}>
            <Calendar className="mr-1 h-4 w-4" /> {loading ? "加载中..." : "查询"}
          </Button>
        }
      />

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
              <span className="text-sm text-muted-foreground">暂无店铺</span>
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

      {message && (
        <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{message}</div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="已选店铺" value={selectedStores.length} />
        <StatCard
          label="数据区间"
          value={<span className="text-sm font-medium">{startDate} ~ {endDate}</span>}
        />
        <StatCard label="功能模块" value={8} />
      </div>

      {loading && !hasKpis && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          {Array.from({ length: 10 }).map((_, i) => (
            <Skeleton key={i} className="h-[86px]" />
          ))}
        </div>
      )}

      {!loading && !hasKpis && !message && (
        <Card>
          <CardContent className="p-0">
            <EmptyState hint="选择店铺与日期后点击查询" />
          </CardContent>
        </Card>
      )}

      {hasKpis && (
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="flex-wrap h-auto">
            <TabsTrigger value="overview">总览 KPI</TabsTrigger>
            <TabsTrigger value="trend">趋势</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="space-y-4">
            {kpiGroups.map((group) => {
              const allItems = group.items.filter((item) => kpis[item.key] !== undefined && kpis[item.key] !== null)
              const visibleItems = allItems.filter((item) => !hiddenKpis.has(item.key))
              const hiddenItems = allItems.filter((item) => hiddenKpis.has(item.key))
              if (allItems.length === 0) return null
              return (
                <Card key={group.title}>
                  <CardHeader className="pb-3">
                    <CardTitle>{group.title}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
                      {visibleItems.map((item) => (
                        <HideableKpiCard
                          key={item.key}
                          label={item.label}
                          value={kpis[item.key]}
                          unit={item.unit}
                          onHide={() => toggleKpi(item.key)}
                        />
                      ))}
                    </div>
                    <HiddenKpiList items={hiddenItems} onRestore={toggleKpi} />
                  </CardContent>
                </Card>
              )
            })}
          </TabsContent>

          <TabsContent value="trend" className="space-y-4">
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
          </TabsContent>
        </Tabs>
      )}
    </div>
  )
}
