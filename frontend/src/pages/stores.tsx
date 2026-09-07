import { useEffect, useState } from "react"
import { Plus, Trash2, Edit2, Check, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { PageHeader, FilterBar, FilterItem, EmptyState } from "@/components/page-kit"
import { getStores, createStore, renameStore, updateStorePlatform, deleteStore, type Store } from "@/api/client"

export function StoresPage() {
  const [stores, setStores] = useState<Store[]>([])
  const [newName, setNewName] = useState("")
  const [newPlatform, setNewPlatform] = useState("pdd")
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState("")
  const [editPlatform, setEditPlatform] = useState("pdd")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const fetchStores = async () => {
    try {
      setLoading(true)
      const data = await getStores()
      setStores(data)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStores()
  }, [])

  const handleCreate = async () => {
    if (!newName.trim()) return
    try {
      await createStore(newName.trim(), newPlatform)
      setNewName("")
      fetchStores()
    } catch (err: any) {
      setError(err.message)
    }
  }

  const handleRename = async (id: string) => {
    if (!editName.trim()) return
    try {
      await renameStore(id, editName.trim())
      setEditingId(null)
      fetchStores()
    } catch (err: any) {
      setError(err.message)
    }
  }

  const handlePlatformChange = async (id: string, platform: string) => {
    try {
      await updateStorePlatform(id, platform)
      fetchStores()
    } catch (err: any) {
      setError(err.message)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm("确定删除该店铺？")) return
    try {
      await deleteStore(id)
      fetchStores()
    } catch (err: any) {
      setError(err.message)
    }
  }

  return (
    <div>
      <PageHeader title="店铺管理" description="维护店铺列表与所属平台" />
      {error && (
        <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-3.5 py-2.5 text-[13px] text-destructive">
          {error}
        </div>
      )}

      <FilterBar>
        <FilterItem label="店铺名称">
          <Input
            placeholder="店铺名称"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          />
        </FilterItem>
        <FilterItem label="平台">
          <Select value={newPlatform} onChange={(e) => setNewPlatform(e.target.value)}>
            <option value="pdd">拼多多</option>
            <option value="douyin">抖音</option>
            <option value="tmall">天猫</option>
            <option value="wechat">微信小店</option>
          </Select>
        </FilterItem>
        <Button size="sm" onClick={handleCreate} disabled={loading}>
          <Plus className="h-4 w-4 mr-1" /> 新增
        </Button>
      </FilterBar>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>名称</TableHead>
                <TableHead>平台</TableHead>
                <TableHead>创建时间</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {stores.map((store) => (
                <TableRow key={store.id}>
                  <TableCell className="font-mono text-xs">{store.id}</TableCell>
                  <TableCell>
                    {editingId === store.id ? (
                      <Input
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        className="h-8"
                        autoFocus
                      />
                    ) : (
                      store.name
                    )}
                  </TableCell>
                  <TableCell>
                    {editingId === store.id ? (
                      <Select
                        className="h-8 w-auto"
                        value={editPlatform}
                        onChange={(e) => {
                          setEditPlatform(e.target.value)
                          handlePlatformChange(store.id, e.target.value)
                        }}
                      >
                        <option value="pdd">拼多多</option>
                        <option value="douyin">抖音</option>
                        <option value="tmall">天猫</option>
                        <option value="wechat">微信小店</option>
                      </Select>
                    ) : (
                      <Badge variant="secondary">
                        {store.platform === "douyin" ? "抖音" : store.platform === "tmall" ? "天猫" : store.platform === "wechat" ? "微信小店" : "拼多多"}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>{new Date(store.created_at).toLocaleString()}</TableCell>
                  <TableCell className="text-right">
                    {editingId === store.id ? (
                      <>
                        <Button variant="ghost" size="sm" onClick={() => handleRename(store.id)}>
                          <Check className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setEditingId(null)}>
                          <X className="h-4 w-4" />
                        </Button>
                      </>
                    ) : (
                      <>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setEditingId(store.id)
                            setEditName(store.name)
                            setEditPlatform(store.platform || "pdd")
                          }}
                        >
                          <Edit2 className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => handleDelete(store.id)}>
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {loading && stores.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="p-4">
                    <div className="space-y-2">
                      <Skeleton className="h-8 w-full" />
                      <Skeleton className="h-8 w-full" />
                    </div>
                  </TableCell>
                </TableRow>
              )}
              {!loading && stores.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5}>
                    <EmptyState title="暂无店铺" hint="使用上方表单新增店铺" />
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
