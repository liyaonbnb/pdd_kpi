import { useEffect, useMemo, useState } from "react"
import { Key, Plus, Trash2, Users } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { getStores } from "@/api/client"
import { createUser, deleteUser, getUsers, updateUser, type User } from "@/api/users"

const pageGroups = [
  {
    label: "拼多多",
    options: [
      { id: "overview", label: "总览" },
      { id: "stores", label: "店铺" },
      { id: "import", label: "导入" },
      { id: "metrics", label: "指标" },
      { id: "orders", label: "订单" },
      { id: "costs", label: "成本" },
      { id: "knowledge_assistant", label: "知识助手" },
    ],
  },
  {
    label: "抖音",
    options: [
      { id: "douyin_overview", label: "总览" },
      { id: "douyin_import", label: "导入" },
      { id: "douyin_metrics", label: "指标" },
      { id: "douyin_orders", label: "订单" },
      { id: "douyin_costs", label: "成本" },
    ],
  },
  {
    label: "天猫",
    options: [
      { id: "tmall_overview", label: "总览" },
      { id: "tmall_import", label: "导入" },
      { id: "tmall_metrics", label: "指标" },
      { id: "tmall_orders", label: "订单" },
      { id: "tmall_costs", label: "成本" },
    ],
  },
  {
    label: "微信小店",
    options: [
      { id: "wechat_overview", label: "总览" },
      { id: "wechat_import", label: "导入" },
      { id: "wechat_metrics", label: "指标" },
      { id: "wechat_orders", label: "订单" },
      { id: "wechat_costs", label: "成本" },
    ],
  },
  {
    label: "通用",
    options: [{ id: "ai_wecom", label: "AI & 企微" }],
  },
]

const flatPageOptions = pageGroups.flatMap((g) => g.options)
const allPageIds = flatPageOptions.map((p) => p.id)

export function UsersPage() {
  const [users, setUsers] = useState<User[]>([])
  const [stores, setStores] = useState<{ id: string; name: string }[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const [newUsername, setNewUsername] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [newRole, setNewRole] = useState<"sub" | "master">("sub")
  const [newStores, setNewStores] = useState<string[]>([])
  const [newPages, setNewPages] = useState<string[]>(allPageIds)

  const [editingUser, setEditingUser] = useState<string | null>(null)
  const [editStores, setEditStores] = useState<string[]>([])
  const [editPages, setEditPages] = useState<string[]>([])
  const [editPassword, setEditPassword] = useState("")

  const storeNames = useMemo(() => stores.map((s) => s.name), [stores])

  const fetchData = async () => {
    setLoading(true)
    try {
      const [u, s] = await Promise.all([getUsers(), getStores()])
      setUsers(u)
      setStores(s)
    } catch (err: any) {
      setError(err.message || "加载失败")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    try {
      await createUser({
        username: newUsername.trim(),
        password: newPassword,
        role: newRole,
        allowed_stores: newRole === "master" ? [] : newStores,
        allowed_pages: newRole === "master" ? [] : newPages,
      })
      setNewUsername("")
      setNewPassword("")
      setNewRole("sub")
      setNewStores([])
      setNewPages(allPageIds)
      await fetchData()
    } catch (err: any) {
      setError(err.message || "创建失败")
    }
  }

  const handleDelete = async (username: string) => {
    if (!confirm(`确定删除用户 ${username} 吗？`)) return
    try {
      await deleteUser(username)
      await fetchData()
    } catch (err: any) {
      setError(err.message || "删除失败")
    }
  }

  const startEdit = (user: User) => {
    setEditingUser(user.username)
    setEditStores(user.allowed_stores || [])
    setEditPages(user.allowed_pages || allPageIds)
    setEditPassword("")
  }

  const cancelEdit = () => {
    setEditingUser(null)
    setEditStores([])
    setEditPages([])
    setEditPassword("")
  }

  const saveEdit = async (username: string) => {
    try {
      const payload: {
        allowed_stores?: string[]
        allowed_pages?: string[]
        password?: string
      } = {
        allowed_stores: editStores,
        allowed_pages: editPages,
      }
      if (editPassword.trim()) {
        payload.password = editPassword.trim()
      }
      await updateUser(username, payload)
      setEditingUser(null)
      await fetchData()
    } catch (err: any) {
      setError(err.message || "保存失败")
    }
  }

  const toggleItem = (id: string, selected: string[], setter: (v: string[]) => void) => {
    if (selected.includes(id)) {
      setter(selected.filter((s) => s !== id))
    } else {
      setter([...selected, id])
    }
  }

  const Checkboxes = ({
    selected,
    onChange,
  }: {
    selected: string[]
    onChange: (v: string[]) => void
  }) => (
    <div className="space-y-4 mt-2">
      {pageGroups.map((group) => {
        const groupIds = group.options.map((o) => o.id)
        const allChecked = groupIds.every((id) => selected.includes(id))
        const someChecked = groupIds.some((id) => selected.includes(id)) && !allChecked
        return (
          <div key={group.label} className="rounded-md border p-3">
            <label className="flex items-center gap-2 font-medium text-sm mb-2">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-input"
                checked={allChecked}
                ref={(el) => {
                  if (el) el.indeterminate = someChecked
                }}
                onChange={() => {
                  if (allChecked) {
                    onChange(selected.filter((id) => !groupIds.includes(id)))
                  } else {
                    onChange(Array.from(new Set([...selected, ...groupIds])))
                  }
                }}
              />
              {group.label}
            </label>
            <div className="flex flex-wrap gap-3 pl-6">
              {group.options.map((opt) => (
                <label key={opt.id} className="flex items-center gap-1.5 text-sm">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-input"
                    checked={selected.includes(opt.id)}
                    onChange={() => toggleItem(opt.id, selected, onChange)}
                  />
                  <span className="text-muted-foreground">{opt.label}</span>
                </label>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )

  const StoreCheckboxes = ({
    selected,
    onChange,
  }: {
    selected: string[]
    onChange: (v: string[]) => void
  }) => (
    <div className="flex flex-wrap gap-3 mt-2">
      {storeNames.map((name) => (
        <label key={name} className="flex items-center gap-1.5 text-sm">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-input"
            checked={selected.includes(name)}
            onChange={() => toggleItem(name, selected, onChange)}
          />
          <span className="text-muted-foreground">{name}</span>
        </label>
      ))}
    </div>
  )

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Users className="h-5 w-5" />
        <h1 className="text-2xl font-bold">用户管理</h1>
      </div>

      {error && (
        <div className="rounded-md bg-destructive/10 px-4 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">开通子账号</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleCreate} className="space-y-4">
            <div className="grid gap-4 md:grid-cols-3">
              <div className="space-y-2">
                <Label>用户名</Label>
                <Input
                  value={newUsername}
                  onChange={(e) => setNewUsername(e.target.value)}
                  placeholder="请输入用户名"
                  required
                />
              </div>
              <div className="space-y-2">
                <Label>密码</Label>
                <Input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="请输入初始密码"
                  required
                />
              </div>
              <div className="space-y-2">
                <Label>角色</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value as "sub" | "master")}
                >
                  <option value="sub">子账号</option>
                  <option value="master">主账号</option>
                </select>
              </div>
            </div>
            {newRole === "sub" && (
              <>
                <div>
                  <Label className="mb-2 block">店铺权限</Label>
                  <StoreCheckboxes selected={newStores} onChange={setNewStores} />
                </div>
                <div>
                  <Label className="mb-2 block">功能权限</Label>
                  <Checkboxes selected={newPages} onChange={setNewPages} />
                </div>
              </>
            )}
            <Button type="submit" disabled={loading}>
              <Plus className="mr-1 h-4 w-4" />
              创建用户
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">用户列表</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>用户名</TableHead>
                <TableHead>角色</TableHead>
                <TableHead>店铺权限</TableHead>
                <TableHead>功能权限</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((user) => (
                <TableRow key={user.username}>
                  <TableCell className="font-medium">{user.username}</TableCell>
                  <TableCell>
                    {user.role === "master" ? (
                      <span className="rounded bg-primary/10 px-2 py-1 text-xs text-primary">主账号</span>
                    ) : (
                      <span className="rounded bg-muted px-2 py-1 text-xs text-muted-foreground">子账号</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {user.role === "master" ? (
                      <span className="text-sm text-muted-foreground">全部店铺</span>
                    ) : editingUser === user.username ? (
                      <StoreCheckboxes selected={editStores} onChange={setEditStores} />
                    ) : user.allowed_stores.length > 0 ? (
                      <span className="text-sm">{user.allowed_stores.join(", ")}</span>
                    ) : (
                      <span className="text-sm text-muted-foreground">未分配店铺</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {user.role === "master" ? (
                      <span className="text-sm text-muted-foreground">全部功能</span>
                    ) : editingUser === user.username ? (
                      <Checkboxes selected={editPages} onChange={setEditPages} />
                    ) : user.allowed_pages.length > 0 ? (
                      <span className="text-sm">
                        {user.allowed_pages
                          .map((id) => flatPageOptions.find((p) => p.id === id)?.label || id)
                          .join(", ")}
                      </span>
                    ) : (
                      <span className="text-sm text-muted-foreground">未分配功能</span>
                    )}
                    {editingUser === user.username && (
                      <div className="mt-3 flex items-center gap-2">
                        <Key className="h-4 w-4 text-muted-foreground" />
                        <Input
                          type="password"
                          placeholder="重置密码（留空则不修改）"
                          value={editPassword}
                          onChange={(e) => setEditPassword(e.target.value)}
                          className="w-64"
                        />
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    {editingUser === user.username ? (
                      <div className="flex justify-end gap-2">
                        <Button size="sm" variant="ghost" onClick={cancelEdit}>
                          取消
                        </Button>
                        <Button size="sm" onClick={() => saveEdit(user.username)} disabled={loading}>
                          保存
                        </Button>
                      </div>
                    ) : (
                      <div className="flex justify-end gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => startEdit(user)}
                          disabled={user.role === "master"}
                        >
                          编辑权限
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => handleDelete(user.username)}
                          disabled={user.role === "master"}
                        >
                          <Trash2 className="mr-1 h-4 w-4" />
                          删除
                        </Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {users.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                    暂无用户
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
