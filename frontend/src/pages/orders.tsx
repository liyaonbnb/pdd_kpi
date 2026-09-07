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
import { getStores, getOrders, type Store } from "@/api/client"

export function OrdersPage() {
  const [stores, setStores] = useState<Store[]>([])
  const [storeName, setStoreName] = useState("")
  const [date, setDate] = useState(new Date().toISOString().split("T")[0])
  const [orders, setOrders] = useState<any[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    getStores("pdd").then(setStores)
  }, [])

  const handleSearch = async () => {
    if (!storeName) return
    setLoading(true)
    try {
      const res = await getOrders(storeName, date)
      setOrders(res)
    } catch (err: any) {
      alert(err.message)
    } finally {
      setLoading(false)
    }
  }

  const columns = orders.length > 0 ? Object.keys(orders[0]) : []
  const colSpan = Math.max(columns.length, 1)

  return (
    <div>
      <PageHeader title="订单明细" description="按店铺和日期查询拼多多订单明细数据" />

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
        <Button onClick={handleSearch} disabled={loading}>
          <Search className="h-4 w-4" /> {loading ? "查询中..." : "查询"}
        </Button>
      </FilterBar>

      <Card>
        <CardHeader>
          <CardTitle>订单列表（共 {orders.length} 条）</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                {columns.slice(0, 10).map((col) => (
                  <TableHead key={col}>{col}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading &&
                Array.from({ length: 6 }).map((_, i) => (
                  <TableRow key={`sk-${i}`}>
                    <TableCell colSpan={colSpan}>
                      <Skeleton className="h-4 w-full" />
                    </TableCell>
                  </TableRow>
                ))}
              {!loading &&
                orders.slice(0, 100).map((row, idx) => (
                  <TableRow key={idx}>
                    {columns.slice(0, 10).map((col) => (
                      <TableCell key={col} className="text-xs max-w-[200px] truncate">
                        {col.includes("状态") ? (
                          <Badge variant="secondary">{String(row[col] ?? "")}</Badge>
                        ) : (
                          String(row[col] ?? "")
                        )}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              {!loading && orders.length === 0 && (
                <TableRow>
                  <TableCell colSpan={colSpan}>
                    <EmptyState title="无订单数据" hint="请选择店铺和日期后点击查询" />
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
