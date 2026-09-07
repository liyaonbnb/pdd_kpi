import { useEffect, useState } from "react"
import { Pencil, Plus, X } from "lucide-react"
import { PageHeader } from "@/components/page-kit"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { ReportTable, type ReportColumn } from "../components/report-table"
import { request, fmtMoney, fmtQty, fmtDate } from "../api"

interface BundleComponent {
  item_code: string
  item_name?: string
  quantity: number
}

interface BundleRow {
  code: string
  name: string
  estimated_shipping_fee: number | string | null
  version_no: number | null
  effective_from: string | null
  components: BundleComponent[]
}

const today = () => new Date().toISOString().slice(0, 10)

const emptyComponents = () => [
  { item_code: "", quantity: "1" },
  { item_code: "", quantity: "1" },
  { item_code: "", quantity: "1" },
]

const EMPTY_FORM = { code: "", name: "", estimated_shipping_fee: "", effective_from: today() }

export function BundlesModule() {
  const [rows, setRows] = useState<BundleRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [selected, setSelected] = useState<BundleRow | null>(null)
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [components, setComponents] = useState(emptyComponents())
  const [saving, setSaving] = useState(false)
  const [editing, setEditing] = useState<BundleRow | null>(null)
  const [editForm, setEditForm] = useState({ name: "", estimated_shipping_fee: "" })
  const [editSaving, setEditSaving] = useState(false)

  const load = () => {
    setLoading(true)
    setError("")
    request<BundleRow[]>("/api/v2/bundles")
      .then((data) => setRows(Array.isArray(data) ? data : []))
      .catch((e) => setError(e?.message || "加载失败"))
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  const setComponent = (index: number, patch: Partial<{ item_code: string; quantity: string }>) => {
    setComponents((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  }

  const submit = async () => {
    if (!form.code.trim() || !form.name.trim()) {
      alert("请填写组合编码与名称")
      return
    }
    const validComponents = components
      .filter((c) => c.item_code.trim())
      .map((c) => ({ item_code: c.item_code.trim(), quantity: Number(c.quantity) || 1 }))
    if (validComponents.length === 0) {
      alert("请至少填写一行组件（单品编码 + 数量）")
      return
    }
    setSaving(true)
    try {
      await request("/api/v2/bundles", {
        method: "POST",
        body: JSON.stringify({
          code: form.code.trim(),
          name: form.name.trim(),
          estimated_shipping_fee: Number(form.estimated_shipping_fee) || 0,
          effective_from: form.effective_from,
          components: validComponents,
        }),
      })
      setOpen(false)
      setForm(EMPTY_FORM)
      setComponents(emptyComponents())
      setSelected(null)
      load()
    } catch (e: any) {
      alert(e.message)
    } finally {
      setSaving(false)
    }
  }

  const openEdit = (row: BundleRow) => {
    setEditing(row)
    setEditForm({ name: row.name, estimated_shipping_fee: String(row.estimated_shipping_fee ?? "") })
  }

  const submitEdit = async () => {
    if (!editing) return
    const fee = Number(editForm.estimated_shipping_fee)
    if (!Number.isFinite(fee) || fee < 0) {
      alert("快递费必须是不小于 0 的数字")
      return
    }
    setEditSaving(true)
    try {
      await request(`/api/v2/bundles/${encodeURIComponent(editing.code)}`, {
        method: "PATCH",
        body: JSON.stringify({ name: editForm.name.trim() || undefined, estimated_shipping_fee: fee }),
      })
      setEditing(null)
      setSelected(null)
      load()
    } catch (e: any) {
      alert(e.message)
    } finally {
      setEditSaving(false)
    }
  }

  const columns: ReportColumn<BundleRow>[] = [
    { key: "code", label: "组合编码" },
    { key: "name", label: "名称" },
    { key: "estimated_shipping_fee", label: "预估快递费", align: "right", render: (r) => fmtMoney(r.estimated_shipping_fee) },
    { key: "version_no", label: "当前版本", align: "center", render: (r) => (r.version_no ? `V${r.version_no}` : "—") },
    { key: "component_count", label: "组件数", align: "right", render: (r) => fmtQty(r.components?.length ?? 0) },
    { key: "effective_from", label: "生效日", render: (r) => fmtDate(r.effective_from) },
    {
      key: "_actions",
      label: "操作",
      align: "center",
      render: (r) => (
        <Button
          variant="ghost"
          size="sm"
          onClick={(e) => {
            e.stopPropagation()
            openEdit(r)
          }}
        >
          <Pencil className="h-3.5 w-3.5" />
          编辑
        </Button>
      ),
    },
  ]

  const componentColumns: ReportColumn<BundleComponent>[] = [
    { key: "item_code", label: "单品编码" },
    { key: "item_name", label: "单品名称", render: (r) => r.item_name || "—" },
    { key: "quantity", label: "用量", align: "right", render: (r) => fmtQty(r.quantity) },
  ]

  return (
    <div>
      <PageHeader
        title="组合 BOM"
        description="同编码重复导入会自动产生新 BOM 版本，旧版本退休"
        actions={
          <Button size="sm" onClick={() => setOpen(true)}>
            <Plus className="h-4 w-4" />
            新建组合
          </Button>
        }
      />
      {error && <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-3.5 py-2.5 text-sm text-destructive">{error}</div>}

      <ReportTable
        columns={columns}
        rows={rows}
        loading={loading}
        rowKey={(r) => r.code}
        emptyTitle="暂无组合档案"
        onRowClick={(row) => setSelected((current) => (current?.code === row.code ? null : row))}
      />

      {selected && (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle className="text-sm">
              组件明细 — {selected.code} {selected.name}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ReportTable
              columns={componentColumns}
              rows={selected.components || []}
              rowKey={(r, i) => `${r.item_code}-${i}`}
              emptyTitle="当前版本暂无组件"
            />
          </CardContent>
        </Card>
      )}

      <Dialog open={!!editing} onOpenChange={(v) => !v && setEditing(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>编辑组合</DialogTitle>
            <DialogDescription>{editing?.code} · 仅修改名称与预估快递费，不影响 BOM 版本；历史成本快照不受影响</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <label className="block text-xs text-muted-foreground">
              <span className="mb-1 block">组合名称</span>
              <Input value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} />
            </label>
            <label className="block text-xs text-muted-foreground">
              <span className="mb-1 block">预估快递费（元）</span>
              <Input type="number" value={editForm.estimated_shipping_fee} onChange={(e) => setEditForm({ ...editForm, estimated_shipping_fee: e.target.value })} />
            </label>
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="outline" size="sm" onClick={() => setEditing(null)} disabled={editSaving}>
                取消
              </Button>
              <Button size="sm" onClick={() => void submitEdit()} disabled={editSaving}>
                {editSaving ? "保存中…" : "保存修改"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>新建组合</DialogTitle>
            <DialogDescription>创建组合及首个 BOM 版本，组件至少一行</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <label className="block text-xs text-muted-foreground">
                <span className="mb-1 block">组合编码</span>
                <Input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="如 BUNDLE-001" />
              </label>
              <label className="block text-xs text-muted-foreground">
                <span className="mb-1 block">组合名称</span>
                <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </label>
              <label className="block text-xs text-muted-foreground">
                <span className="mb-1 block">预估快递费（元）</span>
                <Input type="number" value={form.estimated_shipping_fee} onChange={(e) => setForm({ ...form, estimated_shipping_fee: e.target.value })} placeholder="0" />
              </label>
              <label className="block text-xs text-muted-foreground">
                <span className="mb-1 block">生效日</span>
                <Input type="date" value={form.effective_from} onChange={(e) => setForm({ ...form, effective_from: e.target.value })} />
              </label>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">组件（单品编码 + 数量）</span>
                <Button variant="outline" size="sm" onClick={() => setComponents((current) => [...current, { item_code: "", quantity: "1" }])}>
                  <Plus className="h-3.5 w-3.5" />
                  添加组件行
                </Button>
              </div>
              {components.map((c, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Input value={c.item_code} onChange={(e) => setComponent(i, { item_code: e.target.value })} placeholder="单品编码" />
                  <Input type="number" className="w-28" value={c.quantity} onChange={(e) => setComponent(i, { quantity: e.target.value })} placeholder="数量" />
                  <Button
                    variant="ghost"
                    size="icon"
                    className="shrink-0"
                    disabled={components.length <= 1}
                    onClick={() => setComponents((current) => current.filter((_, index) => index !== i))}
                    aria-label="删除组件行"
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="outline" size="sm" onClick={() => setOpen(false)} disabled={saving}>
                取消
              </Button>
              <Button size="sm" onClick={() => void submit()} disabled={saving}>
                {saving ? "保存中…" : "保存组合"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
