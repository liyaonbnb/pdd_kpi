import { useEffect, useMemo, useState } from "react"
import { Plus } from "lucide-react"
import { PageHeader, FilterBar, FilterItem } from "@/components/page-kit"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { ReportTable, type ReportColumn } from "../components/report-table"
import { request, fmtQty, fmtDate } from "../api"

interface ItemRow {
  id: string
  code: string
  name: string
  base_unit: string
  category: string | null
  safety_stock: number | null
  is_active: boolean
  created_at: string
}

const EMPTY_FORM = { code: "", name: "", base_unit: "件", category: "" }

export function ItemsModule() {
  const [rows, setRows] = useState<ItemRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [keyword, setKeyword] = useState("")
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [saving, setSaving] = useState(false)

  const load = () => {
    setLoading(true)
    setError("")
    request<ItemRow[]>("/api/v2/items")
      .then((data) => setRows(Array.isArray(data) ? data : []))
      .catch((e) => setError(e?.message || "加载失败"))
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    if (!kw) return rows
    return rows.filter((r) => r.code?.toLowerCase().includes(kw) || r.name?.toLowerCase().includes(kw))
  }, [rows, keyword])

  const submit = async () => {
    if (!form.code.trim() || !form.name.trim()) {
      alert("请填写单品编码与名称")
      return
    }
    setSaving(true)
    try {
      await request("/api/v2/items", {
        method: "POST",
        body: JSON.stringify({ code: form.code.trim(), name: form.name.trim(), base_unit: form.base_unit.trim() || "件", category: form.category.trim() }),
      })
      setOpen(false)
      setForm(EMPTY_FORM)
      load()
    } catch (e: any) {
      alert(e.message)
    } finally {
      setSaving(false)
    }
  }

  const columns: ReportColumn<ItemRow>[] = [
    { key: "code", label: "编码" },
    { key: "name", label: "名称" },
    { key: "base_unit", label: "单位" },
    { key: "category", label: "分类", render: (r) => r.category || "—" },
    { key: "safety_stock", label: "安全库存", align: "right", render: (r) => fmtQty(r.safety_stock) },
    {
      key: "is_active",
      label: "状态",
      render: (r) => (r.is_active ? <Badge variant="success">启用</Badge> : <Badge variant="secondary">停用</Badge>),
    },
    { key: "created_at", label: "创建时间", render: (r) => fmtDate(r.created_at) },
  ]

  return (
    <div>
      <PageHeader
        title="单品档案"
        description="库存单品主数据：编码、单位、分类与安全库存"
        actions={
          <Button size="sm" onClick={() => setOpen(true)}>
            <Plus className="h-4 w-4" />
            新建单品
          </Button>
        }
      />
      {error && <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-3.5 py-2.5 text-sm text-destructive">{error}</div>}

      <FilterBar>
        <FilterItem label="编码 / 名称">
          <Input placeholder="输入编码或名称搜索" value={keyword} onChange={(e) => setKeyword(e.target.value)} />
        </FilterItem>
      </FilterBar>

      <ReportTable columns={columns} rows={filtered} loading={loading} rowKey={(r) => r.id ?? r.code} emptyTitle="暂无单品档案" />

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建单品</DialogTitle>
            <DialogDescription>编码保存后不可修改，请确认无误</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <label className="block text-xs text-muted-foreground">
              <span className="mb-1 block">单品编码</span>
              <Input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="如 ITEM-001" />
            </label>
            <label className="block text-xs text-muted-foreground">
              <span className="mb-1 block">单品名称</span>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <label className="block text-xs text-muted-foreground">
              <span className="mb-1 block">基础单位</span>
              <Input value={form.base_unit} onChange={(e) => setForm({ ...form, base_unit: e.target.value })} placeholder="件" />
            </label>
            <label className="block text-xs text-muted-foreground">
              <span className="mb-1 block">分类</span>
              <Input value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} placeholder="可空" />
            </label>
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="outline" size="sm" onClick={() => setOpen(false)} disabled={saving}>
                取消
              </Button>
              <Button size="sm" onClick={() => void submit()} disabled={saving}>
                {saving ? "保存中…" : "保存单品"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
