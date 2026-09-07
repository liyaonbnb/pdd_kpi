import { useEffect, useState } from "react"
import { PageHeader, FilterBar, FilterItem } from "@/components/page-kit"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { request, fmtDate, fmtMoney, fmtQty, fmtTime, qs } from "../api"
import { ReportTable, type ReportColumn } from "../components/report-table"
import { StatusBadge } from "../components/status-badge"

interface Warehouse {
  code: string
  name: string
}

interface PurchaseRow {
  receipt_no: string
  warehouse_code: string
  supplier_name: string | null
  purchase_amount: string | number | null
  freight_fee: string | number | null
  other_fee: string | number | null
  status: string
  created_at: string | null
}

interface InboundDoc {
  doc_no: string
  biz_type: string
  warehouse_code: string
  warehouse_name: string
  doc_date: string | null
  line_count: number
  total_qty: number
  total_amount: number
}

const EMPTY_FORM = {
  receipt_no: "",
  warehouse_code: "",
  supplier_name: "",
  item_code: "",
  batch_no: "",
  quantity: "",
  base_unit_cost: "",
  line_amount: "",
  freight_fee: "",
  other_fee: "",
}

/** 采购入库单：创建待审核采购单，审核后按金额分摊费用计算落地成本并更新加权均价 */
export function PurchasesModule() {
  const [rows, setRows] = useState<PurchaseRow[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [dialogOpen, setDialogOpen] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [busy, setBusy] = useState(false)

  const [inboundDocs, setInboundDocs] = useState<InboundDoc[] | null>(null)
  const [inboundLoading, setInboundLoading] = useState(true)
  const [inboundError, setInboundError] = useState("")
  const [bizType, setBizType] = useState("采购入库")
  const [bizTypes, setBizTypes] = useState<string[]>([])
  const [startDate, setStartDate] = useState("")
  const [endDate, setEndDate] = useState("")

  const reload = async () => {
    setLoading(true)
    setError("")
    try {
      const data = await request<PurchaseRow[]>("/api/v2/purchases")
      setRows(data)
    } catch (e: any) {
      setError(e.message || "加载失败")
    } finally {
      setLoading(false)
    }
  }

  const loadInboundDocs = async () => {
    setInboundLoading(true)
    setInboundError("")
    try {
      const data = await request<InboundDoc[]>(`/api/v2/inventory/inbound-docs${qs({ biz_type: bizType, start_date: startDate, end_date: endDate })}`)
      setInboundDocs(data)
    } catch (e: any) {
      setInboundError(e.message || "加载失败")
    } finally {
      setInboundLoading(false)
    }
  }

  useEffect(() => {
    void reload()
    request<{ warehouses: Warehouse[] }>("/api/v2/config")
      .then((cfg) => setWarehouses(cfg.warehouses || []))
      .catch(() => {})
    request<string[]>("/api/v2/inventory/ledger/biz-types?direction=in")
      .then((list) => setBizTypes(Array.isArray(list) ? list : []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    void loadInboundDocs()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bizType, startDate, endDate])

  const setField = (key: keyof typeof EMPTY_FORM, value: string) => {
    setForm((current) => {
      const next = { ...current, [key]: value }
      // 数量或单价变化时自动带出行金额（仍可在提交前手工调整）
      if (key === "quantity" || key === "base_unit_cost") {
        const qty = Number(next.quantity)
        const cost = Number(next.base_unit_cost)
        if (Number.isFinite(qty) && Number.isFinite(cost) && next.quantity !== "" && next.base_unit_cost !== "") {
          next.line_amount = (qty * cost).toFixed(2)
        }
      }
      return next
    })
  }

  const submit = async () => {
    if (!form.receipt_no.trim()) return alert("请填写采购单号")
    if (!form.warehouse_code) return alert("请选择仓库")
    if (!form.item_code.trim()) return alert("请填写单品编码")
    if (!form.batch_no.trim()) return alert("请填写批次号")
    const quantity = Number(form.quantity)
    if (!Number.isFinite(quantity) || quantity <= 0) return alert("数量必须大于 0")
    const baseUnitCost = Number(form.base_unit_cost)
    if (!Number.isFinite(baseUnitCost) || baseUnitCost < 0) return alert("采购单价必须是不小于 0 的数字")
    const lineAmount = form.line_amount === "" ? quantity * baseUnitCost : Number(form.line_amount)
    if (!Number.isFinite(lineAmount) || lineAmount < 0) return alert("行金额必须是不小于 0 的数字")
    const freightFee = Number(form.freight_fee || 0)
    const otherFee = Number(form.other_fee || 0)
    if (!Number.isFinite(freightFee) || freightFee < 0) return alert("采购运费必须是不小于 0 的数字")
    if (!Number.isFinite(otherFee) || otherFee < 0) return alert("其它费用必须是不小于 0 的数字")
    setBusy(true)
    try {
      await request("/api/v2/purchases", {
        method: "POST",
        body: JSON.stringify({
          receipt_no: form.receipt_no.trim(),
          warehouse_code: form.warehouse_code,
          supplier_name: form.supplier_name.trim(),
          freight_fee: freightFee,
          other_fee: otherFee,
          lines: [
            {
              item_code: form.item_code.trim(),
              batch_no: form.batch_no.trim(),
              quantity,
              base_unit_cost: baseUnitCost,
              line_amount: lineAmount,
            },
          ],
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

  const approve = async (receiptNo: string) => {
    try {
      await request(`/api/v2/purchases/${encodeURIComponent(receiptNo)}/approve`, { method: "POST" })
      await reload()
    } catch (e: any) {
      alert(e.message)
    }
  }

  const columns: ReportColumn<PurchaseRow>[] = [
    { key: "receipt_no", label: "采购单号" },
    { key: "warehouse_code", label: "仓库" },
    { key: "supplier_name", label: "供应商", render: (row) => row.supplier_name || "—" },
    { key: "purchase_amount", label: "采购金额", align: "right", render: (row) => fmtMoney(row.purchase_amount) },
    { key: "freight_fee", label: "运费", align: "right", render: (row) => fmtMoney(row.freight_fee) },
    { key: "other_fee", label: "其它费用", align: "right", render: (row) => fmtMoney(row.other_fee) },
    { key: "status", label: "状态", render: (row) => <StatusBadge value={row.status} /> },
    { key: "created_at", label: "创建时间", render: (row) => fmtTime(row.created_at) },
    {
      key: "actions",
      label: "操作",
      render: (row) =>
        row.status !== "approved" ? (
          <Button size="sm" variant="outline" onClick={() => void approve(row.receipt_no)}>
            审核
          </Button>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
  ]

  const inboundColumns: ReportColumn<InboundDoc>[] = [
    { key: "doc_no", label: "入库单号" },
    { key: "biz_type", label: "入库类型", render: (row) => <StatusBadge value={row.biz_type} /> },
    { key: "warehouse_name", label: "仓库", render: (row) => row.warehouse_name || row.warehouse_code },
    { key: "doc_date", label: "入库日期", render: (row) => fmtDate(row.doc_date) },
    { key: "line_count", label: "单品数", align: "right", render: (row) => fmtQty(row.line_count) },
    { key: "total_qty", label: "入库数量", align: "right", render: (row) => fmtQty(row.total_qty) },
    { key: "total_amount", label: "入库金额（成本）", align: "right", render: (row) => fmtMoney(row.total_amount) },
  ]

  return (
    <div>
      <PageHeader
        title="采购入库单"
        description="系统内创建的采购单（审核后建立批次）+ 网店管家导入的入库单（按入库类型分类）"
        actions={
          <Button onClick={() => setDialogOpen(true)}>
            新建采购单
          </Button>
        }
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
        rowKey={(row) => row.receipt_no}
        emptyTitle="暂无采购单"
        emptyHint="点击右上角「新建采购单」创建第一张采购入库单"
      />

      <div className="mt-8">
        <h3 className="text-base font-semibold">导入入库单（网店管家）</h3>
        <p className="mt-1 text-sm text-muted-foreground">从网店管家入库明细账导入的入库单，按入库类型分类，金额 = 数量 × 批次成本</p>
        <div className="mt-3">
          <FilterBar>
            <FilterItem label="入库类型">
              <Select value={bizType} onChange={(e) => setBizType(e.target.value)}>
                <option value="">全部类型</option>
                {bizTypes.map((t) => (
                  <option key={t} value={t}>
                    {t}
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
          </FilterBar>
        </div>
        {inboundError && (
          <div className="mb-4 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {inboundError}
          </div>
        )}
        <ReportTable
          columns={inboundColumns}
          rows={inboundDocs}
          loading={inboundLoading}
          rowKey={(row) => `${row.doc_no}-${row.warehouse_code}`}
          emptyTitle="暂无导入入库单"
          emptyHint="调整筛选条件或通过数据导入上传入库明细账"
          footer={
            inboundDocs && inboundDocs.length > 0 ? (
              <div className="border-t px-3.5 py-2.5 text-xs text-muted-foreground">
                共 {inboundDocs.length} 张入库单 · 总入库数量 {fmtQty(inboundDocs.reduce((s, r) => s + (Number(r.total_qty) || 0), 0))} · 总金额 ¥{fmtMoney(inboundDocs.reduce((s, r) => s + (Number(r.total_amount) || 0), 0))}
              </div>
            ) : undefined
          }
        />
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>新建采购单</DialogTitle>
            <DialogDescription>保存后为待审核状态，审核后才建立批次并更新库存</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <FilterItem label="采购单号">
              <Input value={form.receipt_no} onChange={(e) => setField("receipt_no", e.target.value)} placeholder="如 PO-20260902-001" />
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
            <FilterItem label="供应商">
              <Input value={form.supplier_name} onChange={(e) => setField("supplier_name", e.target.value)} />
            </FilterItem>
            <FilterItem label="单品编码">
              <Input value={form.item_code} onChange={(e) => setField("item_code", e.target.value)} />
            </FilterItem>
            <FilterItem label="批次号">
              <Input value={form.batch_no} onChange={(e) => setField("batch_no", e.target.value)} />
            </FilterItem>
            <FilterItem label="数量">
              <Input type="number" min="0" value={form.quantity} onChange={(e) => setField("quantity", e.target.value)} />
            </FilterItem>
            <FilterItem label="采购单价">
              <Input type="number" min="0" step="0.01" value={form.base_unit_cost} onChange={(e) => setField("base_unit_cost", e.target.value)} />
            </FilterItem>
            <FilterItem label="行金额">
              <Input type="number" min="0" step="0.01" value={form.line_amount} onChange={(e) => setField("line_amount", e.target.value)} placeholder="留空按数量×单价计算" />
            </FilterItem>
            <FilterItem label="采购运费">
              <Input type="number" min="0" step="0.01" value={form.freight_fee} onChange={(e) => setField("freight_fee", e.target.value)} placeholder="0.00" />
            </FilterItem>
            <FilterItem label="其它费用">
              <Input type="number" min="0" step="0.01" value={form.other_fee} onChange={(e) => setField("other_fee", e.target.value)} placeholder="0.00" />
            </FilterItem>
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="outline" onClick={() => setDialogOpen(false)} disabled={busy}>
              取消
            </Button>
            <Button onClick={() => void submit()} disabled={busy}>
              {busy ? "保存中…" : "保存待审核采购单"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
