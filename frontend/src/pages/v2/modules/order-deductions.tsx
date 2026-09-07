import { Fragment, useEffect, useState } from "react"
import { Loader2 } from "lucide-react"
import { PageHeader, FilterItem, EmptyState } from "@/components/page-kit"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { request, fmtQty, fmtMoney, fmtTime } from "../api"
import { StatusBadge } from "../components/status-badge"

interface Warehouse {
  code: string
  name: string
}

interface OrderRow {
  order_id: string
  platform: string | null
  store_name: string | null
  payment_time: string | null
  order_status: string | null
  inventory_status: string
  created_at: string | null
}

interface CostSnapshot {
  order_id: string
  platform: string | null
  store_name: string | null
  warehouse_code: string | null
  bundle_code: string | null
  bom_version_id: string | number | null
  product_cost: string | number | null
  shipping_fee: string | number | null
  total_cost: string | number | null
  average_cost_as_of: string | null
}

interface CostLine {
  item_code: string
  item_name: string | null
  bundle_code: string | null
  quantity: string | number | null
  average_unit_cost: string | number | null
  product_cost: string | number | null
  shipping_fee: string | number | null
}

interface CostState {
  loading: boolean
  snapshot?: CostSnapshot
  lines?: CostLine[]
  error?: string
}

const EMPTY_FORM = {
  order_id: "",
  store_name: "",
  warehouse_code: "",
  bundle_code: "",
  quantity: "1",
  payment_time: new Date().toISOString().slice(0, 16),
}

const HEADERS = ["订单号", "平台", "店铺", "支付时间", "订单状态", "库存状态", "操作"]

/** 订单扣减：手工录入订单（BOM 展开 → FIFO 扣批次 → 订单级成本快照），支持取消冲销与成本快照展开 */
export function OrderDeductionsModule() {
  const [rows, setRows] = useState<OrderRow[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [dialogOpen, setDialogOpen] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [busy, setBusy] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [costs, setCosts] = useState<Record<string, CostState>>({})

  const reload = async () => {
    setLoading(true)
    setError("")
    try {
      const data = await request<OrderRow[]>("/api/v2/orders")
      setRows(data)
    } catch (e: any) {
      setError(e.message || "加载失败")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void reload()
    request<{ warehouses: Warehouse[] }>("/api/v2/config")
      .then((cfg) => setWarehouses(cfg.warehouses || []))
      .catch(() => {})
  }, [])

  const setField = (key: keyof typeof EMPTY_FORM, value: string) => setForm((current) => ({ ...current, [key]: value }))

  const submit = async () => {
    if (!form.order_id.trim()) return alert("请填写订单号")
    if (!form.store_name.trim()) return alert("请填写店铺")
    if (!form.warehouse_code) return alert("请选择仓库")
    if (!form.bundle_code.trim()) return alert("请填写组合编码")
    const quantity = Number(form.quantity)
    if (!Number.isFinite(quantity) || quantity <= 0) return alert("数量必须大于 0")
    if (!form.payment_time) return alert("请选择支付时间")
    const paymentDate = new Date(form.payment_time)
    if (Number.isNaN(paymentDate.getTime())) return alert("支付时间格式不正确")
    setBusy(true)
    try {
      await request("/api/v2/orders", {
        method: "POST",
        body: JSON.stringify({
          order_id: form.order_id.trim(),
          store_name: form.store_name.trim(),
          warehouse_code: form.warehouse_code,
          payment_time: paymentDate.toISOString(),
          lines: [{ bundle_code: form.bundle_code.trim(), quantity }],
        }),
      })
      setDialogOpen(false)
      setForm(EMPTY_FORM)
      setCosts({})
      setExpandedId(null)
      await reload()
    } catch (e: any) {
      alert(e.message)
    } finally {
      setBusy(false)
    }
  }

  const cancel = async (order: OrderRow) => {
    if (!window.confirm(`确认取消冲销订单 ${order.order_id}？将按原批次回补库存`)) return
    try {
      await request(`/api/v2/orders/${encodeURIComponent(order.order_id)}/cancel`, { method: "POST" })
      await reload()
    } catch (e: any) {
      alert(e.message)
    }
  }

  const toggleExpand = async (order: OrderRow) => {
    if (expandedId === order.order_id) {
      setExpandedId(null)
      return
    }
    setExpandedId(order.order_id)
    if (costs[order.order_id]) return
    setCosts((current) => ({ ...current, [order.order_id]: { loading: true } }))
    try {
      const data = await request<{ snapshot: CostSnapshot; lines: CostLine[] }>(
        `/api/v2/orders/${encodeURIComponent(order.order_id)}/cost`
      )
      setCosts((current) => ({ ...current, [order.order_id]: { loading: false, snapshot: data.snapshot, lines: data.lines } }))
    } catch (e: any) {
      const message = String(e?.message || "")
      setCosts((current) => ({
        ...current,
        [order.order_id]: {
          loading: false,
          error: message.includes("快照") ? "该订单无成本快照（历史订单或未扣库）" : message || "加载失败",
        },
      }))
    }
  }

  const renderCostPanel = (orderId: string) => {
    const state = costs[orderId]
    if (!state || state.loading) {
      return (
        <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          成本快照加载中…
        </div>
      )
    }
    if (state.error || !state.snapshot) {
      return <div className="py-6 text-sm text-muted-foreground">{state.error || "该订单无成本快照（历史订单或未扣库）"}</div>
    }
    const snapshot = state.snapshot
    const lines = state.lines || []
    return (
      <div className="space-y-4 py-1">
        <div className="grid gap-3 sm:grid-cols-4">
          {[
            { label: "产品成本", value: fmtMoney(snapshot.product_cost) },
            { label: "快递费", value: fmtMoney(snapshot.shipping_fee) },
            { label: "总成本", value: fmtMoney(snapshot.total_cost) },
            { label: "成本时点", value: fmtTime(snapshot.average_cost_as_of) },
          ].map((item) => (
            <div key={item.label} className="rounded-md border bg-card p-3">
              <div className="text-xs text-muted-foreground">{item.label}</div>
              <div className="tnum mt-1 text-lg font-semibold">{item.value}</div>
            </div>
          ))}
        </div>
        <div className="overflow-auto rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/50 hover:bg-muted/50">
                {["单品", "名称", "数量", "时点均价", "产品成本"].map((h) => (
                  <TableHead key={h} className="whitespace-nowrap text-xs font-medium text-muted-foreground">
                    {h}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {lines.length === 0 ? (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={5}>
                    <EmptyState title="快照无明细行" />
                  </TableCell>
                </TableRow>
              ) : (
                lines.map((line, i) => (
                  <TableRow key={`${line.item_code}-${i}`} className="hover:bg-muted/40">
                    <TableCell className="whitespace-nowrap">{line.item_code}</TableCell>
                    <TableCell className="whitespace-nowrap">{line.item_name || "—"}</TableCell>
                    <TableCell className="tnum whitespace-nowrap">{fmtQty(line.quantity)}</TableCell>
                    <TableCell className="tnum whitespace-nowrap">{fmtMoney(line.average_unit_cost)}</TableCell>
                    <TableCell className="tnum whitespace-nowrap">{fmtMoney(line.product_cost)}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </div>
    )
  }

  return (
    <div>
      <PageHeader
        title="订单扣减"
        description="BOM 展开 → FIFO 扣批次 → 订单级成本快照"
        actions={<Button onClick={() => setDialogOpen(true)}>手工录入订单</Button>}
      />
      {error && (
        <div className="mb-4 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="overflow-auto rounded-md border">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/50 hover:bg-muted/50">
              {HEADERS.map((h) => (
                <TableHead key={h} className="whitespace-nowrap text-xs font-medium text-muted-foreground">
                  {h}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              Array.from({ length: 6 }).map((_, i) => (
                <TableRow key={i}>
                  {HEADERS.map((h) => (
                    <TableCell key={h}>
                      <Skeleton className="h-4 w-full max-w-24" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : !rows || rows.length === 0 ? (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={HEADERS.length}>
                  <EmptyState title="暂无订单" hint="点击右上角「手工录入订单」录入支付成功订单" />
                </TableCell>
              </TableRow>
            ) : (
              rows.map((order) => (
                <Fragment key={order.order_id}>
                  <TableRow
                    className="cursor-pointer hover:bg-muted/40"
                    onClick={() => void toggleExpand(order)}
                  >
                    <TableCell className="whitespace-nowrap">{order.order_id}</TableCell>
                    <TableCell className="whitespace-nowrap">{order.platform || "—"}</TableCell>
                    <TableCell className="whitespace-nowrap">{order.store_name || "—"}</TableCell>
                    <TableCell className="tnum whitespace-nowrap">{fmtTime(order.payment_time)}</TableCell>
                    <TableCell className="whitespace-nowrap">{order.order_status || "—"}</TableCell>
                    <TableCell className="whitespace-nowrap">
                      <StatusBadge value={order.inventory_status} />
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      {order.inventory_status === "deducted" ? (
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={(e) => {
                            e.stopPropagation()
                            void cancel(order)
                          }}
                        >
                          取消冲销
                        </Button>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                  </TableRow>
                  {expandedId === order.order_id && (
                    <TableRow className="hover:bg-transparent">
                      <TableCell colSpan={HEADERS.length} className="bg-muted/30 px-4 py-3">
                        {renderCostPanel(order.order_id)}
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>手工录入订单</DialogTitle>
            <DialogDescription>按支付成功订单录入，提交后立即 BOM 展开并按 FIFO 扣减库存</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <FilterItem label="订单号">
              <Input value={form.order_id} onChange={(e) => setField("order_id", e.target.value)} />
            </FilterItem>
            <FilterItem label="店铺">
              <Input value={form.store_name} onChange={(e) => setField("store_name", e.target.value)} />
            </FilterItem>
            <FilterItem label="仓库">
              <Select value={form.warehouse_code} onChange={(e) => setField("warehouse_code", e.target.value)}>
                <option value="">请选择仓库</option>
                {warehouses.map((w) => (
                  <option key={w.code} value={w.code}>
                    {w.name}（{w.code}）
                  </option>
                ))}
              </Select>
            </FilterItem>
            <FilterItem label="组合编码">
              <Input value={form.bundle_code} onChange={(e) => setField("bundle_code", e.target.value)} />
            </FilterItem>
            <FilterItem label="数量">
              <Input type="number" min="1" value={form.quantity} onChange={(e) => setField("quantity", e.target.value)} />
            </FilterItem>
            <FilterItem label="支付时间">
              <Input type="datetime-local" value={form.payment_time} onChange={(e) => setField("payment_time", e.target.value)} />
            </FilterItem>
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="outline" onClick={() => setDialogOpen(false)} disabled={busy}>
              取消
            </Button>
            <Button onClick={() => void submit()} disabled={busy}>
              {busy ? "提交中…" : "提交并扣减库存"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
