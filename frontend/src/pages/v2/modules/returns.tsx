import { useEffect, useState } from "react"
import { PageHeader, FilterItem } from "@/components/page-kit"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { request, fmtTime } from "../api"
import { ReportTable, type ReportColumn } from "../components/report-table"
import { StatusBadge } from "../components/status-badge"

interface Warehouse {
  code: string
  name: string
}

interface ReturnRow {
  return_no: string
  order_id: string | null
  warehouse_code: string
  status: string
  received_at: string | null
}

const EMPTY_FORM = {
  return_no: "",
  order_id: "",
  warehouse_code: "",
  item_code: "",
  quantity: "",
  unit_cost: "",
}

/** 退货检验：退货收货进入待检批次，检验为可售才回补库存 */
export function ReturnsModule() {
  const [rows, setRows] = useState<ReturnRow[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [dialogOpen, setDialogOpen] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [busy, setBusy] = useState(false)

  const reload = async () => {
    setLoading(true)
    setError("")
    try {
      const data = await request<ReturnRow[]>("/api/v2/returns")
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
    if (!form.return_no.trim()) return alert("请填写退货单号")
    if (!form.order_id.trim()) return alert("请填写原订单号")
    if (!form.warehouse_code) return alert("请选择仓库")
    if (!form.item_code.trim()) return alert("请填写单品编码")
    const quantity = Number(form.quantity)
    if (!Number.isFinite(quantity) || quantity <= 0) return alert("数量必须大于 0")
    const unitCost = Number(form.unit_cost)
    if (!Number.isFinite(unitCost) || unitCost < 0) return alert("成本必须是不小于 0 的数字")
    setBusy(true)
    try {
      await request("/api/v2/returns", {
        method: "POST",
        body: JSON.stringify({
          return_no: form.return_no.trim(),
          order_id: form.order_id.trim(),
          warehouse_code: form.warehouse_code,
          item_code: form.item_code.trim(),
          quantity,
          unit_cost: unitCost,
        }),
      })
      setDialogOpen(false)
      setForm(EMPTY_FORM)
      await reload()
    } catch (e: any) {
      alert(e.message)
    } finally {
      setBusy(false)
    }
  }

  const inspect = async (returnNo: string, targetStatus: "sellable" | "defective" | "scrapped") => {
    try {
      await request(`/api/v2/returns/${encodeURIComponent(returnNo)}/inspect`, {
        method: "POST",
        body: JSON.stringify({ target_status: targetStatus }),
      })
      await reload()
    } catch (e: any) {
      alert(e.message)
    }
  }

  const columns: ReportColumn<ReturnRow>[] = [
    { key: "return_no", label: "退货单号" },
    { key: "order_id", label: "原订单", render: (row) => row.order_id || "—" },
    { key: "warehouse_code", label: "仓库" },
    { key: "status", label: "状态", render: (row) => <StatusBadge value={row.status} /> },
    { key: "received_at", label: "收货时间", render: (row) => fmtTime(row.received_at) },
    {
      key: "actions",
      label: "操作",
      render: (row) =>
        row.status !== "completed" && row.status !== "void" ? (
          <div className="flex gap-1.5">
            <Button size="sm" variant="outline" onClick={() => void inspect(row.return_no, "sellable")}>
              可售
            </Button>
            <Button size="sm" variant="outline" onClick={() => void inspect(row.return_no, "defective")}>
              残次
            </Button>
            <Button size="sm" variant="outline" onClick={() => void inspect(row.return_no, "scrapped")}>
              报废
            </Button>
          </div>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
  ]

  return (
    <div>
      <PageHeader
        title="退货检验"
        description="退货收货进入待检批次，检验为可售才回补库存"
        actions={<Button onClick={() => setDialogOpen(true)}>退货收货</Button>}
      />
      {error && (
        <div className="mb-4 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}
      <ReportTable
        columns={columns}
        rows={rows}
        loading={loading}
        rowKey={(row) => row.return_no}
        emptyTitle="暂无退货单"
        emptyHint="点击右上角「退货收货」登记退货入库"
      />

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>退货收货</DialogTitle>
            <DialogDescription>确认收货后进入待检批次，检验结论决定库存去向</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <FilterItem label="退货单号">
              <Input value={form.return_no} onChange={(e) => setField("return_no", e.target.value)} />
            </FilterItem>
            <FilterItem label="原订单号">
              <Input value={form.order_id} onChange={(e) => setField("order_id", e.target.value)} />
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
            <FilterItem label="单品编码">
              <Input value={form.item_code} onChange={(e) => setField("item_code", e.target.value)} />
            </FilterItem>
            <FilterItem label="数量">
              <Input type="number" min="1" value={form.quantity} onChange={(e) => setField("quantity", e.target.value)} />
            </FilterItem>
            <FilterItem label="成本">
              <Input type="number" min="0" step="0.01" value={form.unit_cost} onChange={(e) => setField("unit_cost", e.target.value)} />
            </FilterItem>
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="outline" onClick={() => setDialogOpen(false)} disabled={busy}>
              取消
            </Button>
            <Button onClick={() => void submit()} disabled={busy}>
              {busy ? "提交中…" : "确认收货并进入待检"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
