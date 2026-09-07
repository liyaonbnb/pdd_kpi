import { useEffect, useState } from "react"
import { Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { PageHeader, FilterBar, FilterItem, EmptyState } from "@/components/page-kit"
import { getStores, getWechatOrders, type Store } from "@/api/client"

function formatNumber(v: any, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "-"
  if (typeof v === "number") return v.toLocaleString("zh-CN", { maximumFractionDigits: digits })
  return v
}

export function WechatOrdersPage() {
  const [stores, setStores] = useState<Store[]>([])
  const [storeName, setStoreName] = useState("")
  const [date, setDate] = useState(new Date().toISOString().split("T")[0])
  const [orders, setOrders] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState("")

  useEffect(() => {
    getStores("wechat").then((s) => {
      setStores(s)
      if (s.length > 0) setStoreName(s[0].name)
    })
  }, [])

  const handleQuery = async () => {
    if (!storeName) return
    setLoading(true)
    setMessage("")
    try {
      const data = await getWechatOrders(storeName, date)
      setOrders(data)
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <PageHeader title="微信订单" description="按店铺和日期查询微信小店订单明细数据" />

      {message && <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{message}</div>}

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
        <FilterItem label="日期">
          <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </FilterItem>
        <Button onClick={handleQuery} disabled={loading}>
          <Search className="h-4 w-4" /> {loading ? "查询中..." : "查询"}
        </Button>
      </FilterBar>

      <Card>
        <CardHeader>
          <CardTitle>订单明细（{orders.length} 条）</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="max-h-[600px] overflow-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>订单编号</TableHead>
                  <TableHead>商品名称</TableHead>
                  <TableHead>自定义 SKU</TableHead>
                  <TableHead>平台 SKU</TableHead>
                  <TableHead>数量</TableHead>
                  <TableHead>实付金额</TableHead>
                  <TableHead>实际收款</TableHead>
                  <TableHead>退款金额</TableHead>
                  <TableHead>技术服务费</TableHead>
                  <TableHead>带货费用</TableHead>
                  <TableHead>净收入</TableHead>
                  <TableHead>订单状态</TableHead>
                  <TableHead>达人</TableHead>
                  <TableHead>下单时间</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading &&
                  Array.from({ length: 6 }).map((_, i) => (
                    <TableRow key={`sk-${i}`}>
                      <TableCell colSpan={14}>
                        <Skeleton className="h-4 w-full" />
                      </TableCell>
                    </TableRow>
                  ))}
                {!loading &&
                  orders.map((row, idx) => (
                    <TableRow key={idx}>
                      <TableCell className="text-xs whitespace-nowrap">{row.order_id}</TableCell>
                      <TableCell className="text-xs max-w-[200px] truncate">{row.product_name}</TableCell>
                      <TableCell className="text-xs">{row.sku_code}</TableCell>
                      <TableCell className="text-xs">{row.platform_sku_code}</TableCell>
                      <TableCell className="tnum text-xs">{formatNumber(row.quantity, 0)}</TableCell>
                      <TableCell className="tnum text-xs">{formatNumber(row.amount)}</TableCell>
                      <TableCell className="tnum text-xs">{formatNumber(row.actual_revenue)}</TableCell>
                      <TableCell className="tnum text-xs">{formatNumber(row.refund_amount)}</TableCell>
                      <TableCell className="tnum text-xs">{formatNumber(row.tech_fee)}</TableCell>
                      <TableCell className="tnum text-xs">{formatNumber(row.commission)}</TableCell>
                      <TableCell className="tnum text-xs">{formatNumber(row.net_revenue)}</TableCell>
                      <TableCell className="text-xs">
                        <Badge variant={String(row.order_status ?? "").includes("退款") ? "destructive" : "secondary"}>
                          {row.order_status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs">{row.kol_name}</TableCell>
                      <TableCell className="text-xs whitespace-nowrap">{row.order_time}</TableCell>
                    </TableRow>
                  ))}
                {!loading && orders.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={14}>
                      <EmptyState title="暂无数据" hint="请选择店铺和日期后点击查询" />
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
