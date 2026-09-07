import { useEffect, useState } from "react"
import { Plus } from "lucide-react"
import { PageHeader } from "@/components/page-kit"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { ReportTable, type ReportColumn } from "../components/report-table"
import { request } from "../api"

interface AllowedStore {
  platform: string
  store_name: string
}

interface UserRow {
  username: string
  role: string
  allowed_stores: AllowedStore[] | null
  allowed_pages: string[] | null
  is_active: boolean
}

type BadgeVariant = "default" | "secondary" | "destructive" | "outline" | "success"

const ROLE_MAP: Record<string, { label: string; variant: BadgeVariant }> = {
  master: { label: "主账号", variant: "default" },
  admin: { label: "管理员", variant: "secondary" },
  sub: { label: "子账号", variant: "outline" },
  viewer: { label: "只读", variant: "outline" },
}

const EMPTY_FORM = { username: "", password: "", role: "sub", allowed_stores: "", allowed_pages: "overview,stores,imports,orders" }

export function UsersModule() {
  const [rows, setRows] = useState<UserRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [saving, setSaving] = useState(false)

  const load = () => {
    setLoading(true)
    setError("")
    request<UserRow[]>("/api/v2/users")
      .then((data) => setRows(Array.isArray(data) ? data : []))
      .catch((e) => setError(e?.message || "加载失败"))
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  const submit = async () => {
    if (!form.username.trim() || !form.password) {
      alert("请填写账号与初始密码")
      return
    }
    setSaving(true)
    try {
      await request("/api/v2/users", {
        method: "POST",
        body: JSON.stringify({
          username: form.username.trim(),
          password: form.password,
          role: form.role,
          display_name: form.username.trim(),
          allowed_stores: form.allowed_stores.split(",").map((x) => x.trim()).filter(Boolean),
          allowed_pages: form.allowed_pages.split(",").map((x) => x.trim()).filter(Boolean),
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

  const columns: ReportColumn<UserRow>[] = [
    { key: "username", label: "账号" },
    {
      key: "role",
      label: "角色",
      render: (r) => {
        const hit = ROLE_MAP[r.role] || { label: r.role || "—", variant: "outline" as BadgeVariant }
        return <Badge variant={hit.variant}>{hit.label}</Badge>
      },
    },
    {
      key: "allowed_stores",
      label: "店铺授权",
      render: (r) =>
        r.allowed_stores && r.allowed_stores.length > 0
          ? r.allowed_stores.map((s) => `${s.platform}:${s.store_name}`).join("、")
          : "全部/未限制",
    },
    {
      key: "allowed_pages",
      label: "页面授权",
      render: (r) => (r.allowed_pages && r.allowed_pages.length > 0 ? r.allowed_pages.join("、") : "全部"),
    },
    {
      key: "is_active",
      label: "状态",
      render: (r) => (r.is_active ? <Badge variant="success">启用</Badge> : <Badge variant="secondary">停用</Badge>),
    },
  ]

  return (
    <div>
      <PageHeader
        title="账号权限"
        description="V2 工作台账号、角色与店铺/页面授权范围"
        actions={
          <Button size="sm" onClick={() => setOpen(true)}>
            <Plus className="h-4 w-4" />
            新建账号
          </Button>
        }
      />
      {error && <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-3.5 py-2.5 text-sm text-destructive">{error}</div>}

      <ReportTable columns={columns} rows={rows} loading={loading} rowKey={(r) => r.username} emptyTitle="暂无账号" />

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建账号</DialogTitle>
            <DialogDescription>店铺授权与页面授权留空表示不限制</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <label className="block text-xs text-muted-foreground">
                <span className="mb-1 block">账号</span>
                <Input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
              </label>
              <label className="block text-xs text-muted-foreground">
                <span className="mb-1 block">初始密码</span>
                <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
              </label>
            </div>
            <label className="block text-xs text-muted-foreground">
              <span className="mb-1 block">角色</span>
              <Select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                <option value="sub">子账号</option>
                <option value="master">主账号</option>
                <option value="admin">管理员</option>
                <option value="viewer">只读</option>
              </Select>
            </label>
            <label className="block text-xs text-muted-foreground">
              <span className="mb-1 block">店铺授权（逗号分隔）</span>
              <Input value={form.allowed_stores} onChange={(e) => setForm({ ...form, allowed_stores: e.target.value })} placeholder="如 测试店A,测试店B；留空为全部" />
            </label>
            <label className="block text-xs text-muted-foreground">
              <span className="mb-1 block">页面授权（逗号分隔）</span>
              <Input value={form.allowed_pages} onChange={(e) => setForm({ ...form, allowed_pages: e.target.value })} placeholder="如 overview,stores,imports,orders" />
            </label>
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="outline" size="sm" onClick={() => setOpen(false)} disabled={saving}>
                取消
              </Button>
              <Button size="sm" onClick={() => void submit()} disabled={saving}>
                {saving ? "保存中…" : "保存账号"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
