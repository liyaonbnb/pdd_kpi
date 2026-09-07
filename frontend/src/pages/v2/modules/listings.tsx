import { useEffect, useMemo, useState } from "react"
import { Plus } from "lucide-react"
import { PageHeader, FilterBar, FilterItem } from "@/components/page-kit"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { ReportTable, type ReportColumn } from "../components/report-table"
import { request, fmtDate } from "../api"

interface ListingRow {
  id: string
  platform: string
  store_name: string
  product_id: string
  style_id: string | null
  bundle_code: string
  effective_from: string | null
  effective_to: string | null
}

const PLATFORMS = [
  { value: "pdd", label: "拼多多" },
  { value: "douyin", label: "抖音" },
  { value: "tmall", label: "天猫" },
  { value: "wechat", label: "微信" },
]

const today = () => new Date().toISOString().slice(0, 10)

const EMPTY_FORM = { platform: "pdd", store_name: "", product_id: "", style_id: "", bundle_code: "", effective_from: today() }

export function ListingsModule() {
  const [rows, setRows] = useState<ListingRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [platform, setPlatform] = useState("")
  const [keyword, setKeyword] = useState("")
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [saving, setSaving] = useState(false)

  const load = () => {
    setLoading(true)
    setError("")
    request<ListingRow[]>("/api/v2/listings")
      .then((data) => setRows(Array.isArray(data) ? data : []))
      .catch((e) => setError(e?.message || "加载失败"))
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    return rows.filter((r) => {
      if (platform && r.platform !== platform) return false
      if (kw && !r.product_id?.toLowerCase().includes(kw) && !r.bundle_code?.toLowerCase().includes(kw)) return false
      return true
    })
  }, [rows, platform, keyword])

  const submit = async () => {
    if (!form.store_name.trim() || !form.product_id.trim() || !form.bundle_code.trim()) {
      alert("请填写店铺、商品ID 与组合编码")
      return
    }
    setSaving(true)
    try {
      await request("/api/v2/listings", {
        method: "POST",
        body: JSON.stringify({
          platform: form.platform,
          store_name: form.store_name.trim(),
          product_id: form.product_id.trim(),
          style_id: form.style_id.trim() || null,
          bundle_code: form.bundle_code.trim(),
          effective_from: form.effective_from || undefined,
        }),
      })
      setOpen(false)
      setForm(EMPTY_FORM)
      load()
    } catch (e: any) {
      if (/409|已存在|存在/.test(e?.message || "")) alert("该链接映射已存在")
      else alert(e.message)
    } finally {
      setSaving(false)
    }
  }

  const columns: ReportColumn<ListingRow>[] = [
    { key: "platform", label: "平台" },
    { key: "store_name", label: "店铺" },
    { key: "product_id", label: "商品ID" },
    { key: "style_id", label: "规格ID", render: (r) => r.style_id || "—" },
    { key: "bundle_code", label: "组合编码" },
    { key: "effective_from", label: "生效起", render: (r) => fmtDate(r.effective_from) },
    { key: "effective_to", label: "生效止", render: (r) => fmtDate(r.effective_to) },
  ]

  return (
    <div>
      <PageHeader
        title="链接映射"
        description="平台商品链接（商品ID/规格ID）与组合 BOM 的对应关系"
        actions={
          <Button size="sm" onClick={() => setOpen(true)}>
            <Plus className="h-4 w-4" />
            新建映射
          </Button>
        }
      />
      {error && <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-3.5 py-2.5 text-sm text-destructive">{error}</div>}

      <FilterBar>
        <FilterItem label="平台">
          <Select value={platform} onChange={(e) => setPlatform(e.target.value)}>
            <option value="">全部平台</option>
            {PLATFORMS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}（{p.value}）
              </option>
            ))}
          </Select>
        </FilterItem>
        <FilterItem label="商品ID / 组合编码">
          <Input placeholder="输入商品ID或组合编码搜索" value={keyword} onChange={(e) => setKeyword(e.target.value)} />
        </FilterItem>
      </FilterBar>

      <ReportTable columns={columns} rows={filtered} loading={loading} rowKey={(r) => r.id} emptyTitle="暂无链接映射" />

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建映射</DialogTitle>
            <DialogDescription>同一链接重复创建会被拒绝（409）</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <label className="block text-xs text-muted-foreground">
              <span className="mb-1 block">平台</span>
              <Select value={form.platform} onChange={(e) => setForm({ ...form, platform: e.target.value })}>
                {PLATFORMS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}（{p.value}）
                  </option>
                ))}
              </Select>
            </label>
            <label className="block text-xs text-muted-foreground">
              <span className="mb-1 block">店铺</span>
              <Input value={form.store_name} onChange={(e) => setForm({ ...form, store_name: e.target.value })} />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block text-xs text-muted-foreground">
                <span className="mb-1 block">商品ID</span>
                <Input value={form.product_id} onChange={(e) => setForm({ ...form, product_id: e.target.value })} />
              </label>
              <label className="block text-xs text-muted-foreground">
                <span className="mb-1 block">规格ID（可空）</span>
                <Input value={form.style_id} onChange={(e) => setForm({ ...form, style_id: e.target.value })} />
              </label>
            </div>
            <label className="block text-xs text-muted-foreground">
              <span className="mb-1 block">组合编码</span>
              <Input value={form.bundle_code} onChange={(e) => setForm({ ...form, bundle_code: e.target.value })} />
            </label>
            <label className="block text-xs text-muted-foreground">
              <span className="mb-1 block">生效起</span>
              <Input type="date" value={form.effective_from} onChange={(e) => setForm({ ...form, effective_from: e.target.value })} />
            </label>
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="outline" size="sm" onClick={() => setOpen(false)} disabled={saving}>
                取消
              </Button>
              <Button size="sm" onClick={() => void submit()} disabled={saving}>
                {saving ? "保存中…" : "保存映射"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
