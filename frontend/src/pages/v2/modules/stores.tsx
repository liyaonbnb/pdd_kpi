import { useEffect, useState } from "react"
import { Plus } from "lucide-react"
import { PageHeader } from "@/components/page-kit"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { ReportTable, type ReportColumn } from "../components/report-table"
import { request, fmtDate } from "../api"

interface StoreRow {
  platform: string
  store_name: string
  display_name: string | null
  warehouse_code: string | null
  effective_from: string | null
  is_active: boolean
}

const PLATFORMS = [
  { value: "pdd", label: "拼多多" },
  { value: "douyin", label: "抖音" },
  { value: "tmall", label: "天猫" },
  { value: "wechat", label: "微信" },
]

const today = () => new Date().toISOString().slice(0, 10)

const EMPTY_FORM = { platform: "pdd", store_name: "", display_name: "", warehouse_code: "KUNSHAN", effective_from: today() }

export function StoresModule() {
  const [rows, setRows] = useState<StoreRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [saving, setSaving] = useState(false)

  const load = () => {
    setLoading(true)
    setError("")
    request<StoreRow[]>("/api/v2/stores")
      .then((data) => setRows(Array.isArray(data) ? data : []))
      .catch((e) => setError(e?.message || "加载失败"))
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  const submit = async () => {
    if (!form.store_name.trim()) {
      alert("请填写店铺名称")
      return
    }
    setSaving(true)
    try {
      const storeName = form.store_name.trim()
      await request("/api/v2/stores", {
        method: "POST",
        body: JSON.stringify({ platform: form.platform, store_name: storeName, display_name: form.display_name.trim() || storeName }),
      })
      await request("/api/v2/stores/warehouse", {
        method: "POST",
        body: JSON.stringify({
          platform: form.platform,
          store_name: storeName,
          warehouse_code: form.warehouse_code.trim(),
          effective_from: form.effective_from,
        }),
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

  const columns: ReportColumn<StoreRow>[] = [
    { key: "platform", label: "平台" },
    { key: "store_name", label: "店铺" },
    { key: "display_name", label: "显示名称", render: (r) => r.display_name || r.store_name },
    { key: "warehouse_code", label: "当前仓库", render: (r) => r.warehouse_code || "—" },
    { key: "effective_from", label: "生效日", render: (r) => fmtDate(r.effective_from) },
  ]

  return (
    <div>
      <PageHeader
        title="店铺仓库"
        description="店铺按生效日指派共享仓库，订单按店铺归属仓库扣减库存"
        actions={
          <Button size="sm" onClick={() => setOpen(true)}>
            <Plus className="h-4 w-4" />
            新建店铺
          </Button>
        }
      />
      {error && <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-3.5 py-2.5 text-sm text-destructive">{error}</div>}

      <ReportTable
        columns={columns}
        rows={rows}
        loading={loading}
        rowKey={(r) => `${r.platform}-${r.store_name}`}
        emptyTitle="暂无店铺配置"
      />

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建店铺</DialogTitle>
            <DialogDescription>先创建店铺档案，再写入共享仓库指派</DialogDescription>
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
              <span className="mb-1 block">店铺名称</span>
              <Input value={form.store_name} onChange={(e) => setForm({ ...form, store_name: e.target.value })} />
            </label>
            <label className="block text-xs text-muted-foreground">
              <span className="mb-1 block">显示名称（默认同店铺名）</span>
              <Input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} placeholder={form.store_name || "同店铺名称"} />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block text-xs text-muted-foreground">
                <span className="mb-1 block">默认共享仓库</span>
                <Input value={form.warehouse_code} onChange={(e) => setForm({ ...form, warehouse_code: e.target.value })} placeholder="如 KUNSHAN" />
              </label>
              <label className="block text-xs text-muted-foreground">
                <span className="mb-1 block">配置生效日</span>
                <Input type="date" value={form.effective_from} onChange={(e) => setForm({ ...form, effective_from: e.target.value })} />
              </label>
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="outline" size="sm" onClick={() => setOpen(false)} disabled={saving}>
                取消
              </Button>
              <Button size="sm" onClick={() => void submit()} disabled={saving}>
                {saving ? "保存中…" : "保存店铺"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
