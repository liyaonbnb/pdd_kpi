import { useCallback, useEffect, useMemo, useState } from "react"
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { PageHeader, StatCard, FilterBar, FilterItem } from "@/components/page-kit"
import { Button } from "@/components/ui/button"
import { Select } from "@/components/ui/select"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ReportTable, type ReportColumn } from "../components/report-table"
import { request, qs, fmtQty, fmtMoney } from "../api"

interface StoreRow {
  store_name: string
  out_qty: string | number
  cost_amount: string | number
}

interface DayRow extends StoreRow {
  period: string
}

interface ItemRow {
  store_name: string
  item_code: string
  item_name: string
  out_qty: string | number
  cost_amount: string | number
}

const toDate = (d: Date) => d.toISOString().slice(0, 10)

/** 店铺出库：实际发货口径（网店管家出库明细的店铺与金额），看出库数量、金额与商品分布 */
export function StoreOutboundModule() {
  const [startDate, setStartDate] = useState(() => toDate(new Date(Date.now() - 29 * 86400000)))
  const [endDate, setEndDate] = useState(() => toDate(new Date()))
  const [store, setStore] = useState("")
  const [storeRows, setStoreRows] = useState<StoreRow[] | null>(null)
  const [dayRows, setDayRows] = useState<DayRow[]>([])
  const [itemRows, setItemRows] = useState<ItemRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  const load = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const base = { start_date: startDate, end_date: endDate, store }
      const [byStore, byDay, byItem] = await Promise.all([
        request<StoreRow[]>(`/api/v2/inventory/sales-by-store${qs({ ...base, group_by: "store" })}`),
        request<DayRow[]>(`/api/v2/inventory/sales-by-store${qs({ ...base, group_by: "day" })}`),
        request<ItemRow[]>(`/api/v2/inventory/sales-by-store${qs({ ...base, group_by: "store_item" })}`),
      ])
      setStoreRows(byStore)
      setDayRows(byDay)
      setItemRows(byItem)
    } catch (e: any) {
      setError(e.message || "查询失败")
      setStoreRows([])
      setItemRows([])
    } finally {
      setLoading(false)
    }
  }, [startDate, endDate, store])

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const totals = useMemo(() => {
    const rows = storeRows || []
    return {
      qty: rows.reduce((n, r) => n + Number(r.out_qty || 0), 0),
      amount: rows.reduce((n, r) => n + Number(r.cost_amount || 0), 0),
    }
  }, [storeRows])

  const trend = useMemo(() => {
    const byPeriod = new Map<string, { period: string; amount: number; qty: number }>()
    for (const r of dayRows) {
      const key = String(r.period).slice(0, 10)
      const cur = byPeriod.get(key) || { period: key, amount: 0, qty: 0 }
      cur.amount += Number(r.cost_amount || 0)
      cur.qty += Number(r.out_qty || 0)
      byPeriod.set(key, cur)
    }
    return [...byPeriod.values()].sort((a, b) => a.period.localeCompare(b.period))
  }, [dayRows])

  const itemTotal = useMemo(() => itemRows.reduce((n, r) => n + Number(r.cost_amount || 0), 0), [itemRows])

  const storeColumns: ReportColumn<StoreRow>[] = [
    { key: "store_name", label: "店铺" },
    { key: "out_qty", label: "出库数量", align: "right", render: (r) => fmtQty(r.out_qty) },
    { key: "cost_amount", label: "出库金额", align: "right", render: (r) => fmtMoney(r.cost_amount) },
    {
      key: "share",
      label: "金额占比",
      align: "right",
      render: (r) => (totals.amount > 0 ? `${((Number(r.cost_amount || 0) / totals.amount) * 100).toFixed(1)}%` : "—"),
    },
  ]

  const itemColumns: ReportColumn<ItemRow>[] = [
    { key: "item_code", label: "单品编码" },
    { key: "item_name", label: "单品名称" },
    { key: "store_name", label: "店铺", render: (r) => r.store_name },
    { key: "out_qty", label: "出库数量", align: "right", render: (r) => fmtQty(r.out_qty) },
    { key: "cost_amount", label: "出库金额", align: "right", render: (r) => fmtMoney(r.cost_amount) },
    {
      key: "share",
      label: "金额占比",
      align: "right",
      render: (r) => (itemTotal > 0 ? `${((Number(r.cost_amount || 0) / itemTotal) * 100).toFixed(1)}%` : "—"),
    },
  ]

  return (
    <div>
      <PageHeader
        title="店铺出库"
        description="实际发货口径：数量与金额来自出库流水，金额 = 出库数量 × FIFO 批次成本；不含未发货订单"
      />
      {error && (
        <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-3.5 py-2.5 text-sm text-destructive">{error}</div>
      )}
      <FilterBar>
        <FilterItem label="开始日期">
          <input type="date" className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </FilterItem>
        <FilterItem label="结束日期">
          <input type="date" className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </FilterItem>
        <FilterItem label="店铺">
          <Select value={store} onChange={(e) => setStore(e.target.value)}>
            <option value="">全部店铺</option>
            {(storeRows || []).map((r) => (
              <option key={r.store_name} value={r.store_name}>
                {r.store_name}
              </option>
            ))}
          </Select>
        </FilterItem>
        <Button onClick={() => void load()} disabled={loading}>
          {loading ? "查询中…" : "查询"}
        </Button>
      </FilterBar>

      <div className="mb-4 grid gap-3 sm:grid-cols-2">
        <StatCard label="总出库数量" value={fmtQty(totals.qty)} hint="件" />
        <StatCard label="总出库金额" value={`¥${fmtMoney(totals.amount)}`} />
      </div>

      <Card className="mb-4">
        <CardHeader>
          <CardTitle className="text-base">出库趋势</CardTitle>
          <CardDescription>{store ? `${store} · ` : "全部店铺 · "}按天汇总出库金额与数量</CardDescription>
        </CardHeader>
        <CardContent>
          {trend.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground">所选区间暂无出库数据</div>
          ) : (
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trend} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
                  <XAxis dataKey="period" tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }} tickLine={false} axisLine={false} tickFormatter={(v: string) => v.slice(5)} />
                  <YAxis yAxisId="amount" tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }} tickLine={false} axisLine={false} width={56} />
                  <YAxis yAxisId="qty" orientation="right" tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }} tickLine={false} axisLine={false} width={40} />
                  <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12, color: "hsl(var(--card-foreground))" }} />
                  <Line yAxisId="amount" type="monotone" dataKey="amount" name="出库金额" stroke="hsl(var(--chart-1))" strokeWidth={2} dot={false} />
                  <Line yAxisId="qty" type="monotone" dataKey="qty" name="出库数量" stroke="hsl(var(--chart-2))" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">店铺汇总</CardTitle>
          </CardHeader>
          <CardContent>
            <ReportTable
              columns={storeColumns}
              rows={storeRows}
              loading={loading}
              rowKey={(r) => r.store_name}
              emptyTitle="暂无出库数据"
              emptyHint="该区间没有出库记录"
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">商品分布</CardTitle>
            <CardDescription>{store ? `${store} 出库的单品构成` : "全部店铺出库的单品构成，按金额降序"}</CardDescription>
          </CardHeader>
          <CardContent>
            <ReportTable
              columns={itemColumns}
              rows={itemRows}
              loading={loading}
              rowKey={(r, i) => `${r.store_name}-${r.item_code}-${i}`}
              emptyTitle="暂无商品出库数据"
            />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
