import { useEffect, useState } from "react"
import { AlertTriangle, CheckCircle2, Loader2, Upload, Search, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { FileDropzone } from "@/components/ui/file-dropzone"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { EmptyState, PageHeader } from "@/components/page-kit"
import { getStores, importWechat, getWechatRecords, deleteWechatRecord, type Store } from "@/api/client"

export function WechatImportPage() {
  const [stores, setStores] = useState<Store[]>([])
  const [storeName, setStoreName] = useState("")
  const [importDate, setImportDate] = useState("")
  const [orderFile, setOrderFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState("")
  const [records, setRecords] = useState<any[]>([])

  useEffect(() => {
    getStores("wechat").then((s) => {
      setStores(s)
      if (s.length > 0) setStoreName(s[0].name)
    })
    loadRecords()
  }, [])

  const loadRecords = async () => {
    try {
      const data = await getWechatRecords()
      setRecords(data)
    } catch (err: any) {
      setMessage(err.message)
    }
  }

  const handleImport = async () => {
    if (!storeName) {
      setMessage("请选择店铺")
      return
    }
    if (!orderFile) {
      setMessage("请上传订单 Excel")
      return
    }
    setLoading(true)
    setMessage("")
    try {
      const formData = new FormData()
      formData.append("store_name", storeName)
      if (importDate) formData.append("import_date", importDate)
      formData.append("order_file", orderFile)
      const res = await importWechat(formData)
      setMessage(`导入成功：处理日期 ${res.processed_dates.join(", ")}，商品/SKU 行 ${res.product_rows}，订单行 ${res.order_rows}`)
      setOrderFile(null)
      await loadRecords()
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (store: string, date: string) => {
    if (!confirm(`确定删除 ${store} ${date} 的数据？`)) return
    try {
      await deleteWechatRecord(store, date)
      await loadRecords()
    } catch (err: any) {
      setMessage(err.message)
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader title="微信导入" />

      {message && (
        <div
          className={`flex items-center gap-2 rounded-lg border px-3 py-2.5 text-sm ${
            message.includes("成功") ? "border-success/30 bg-success/10 text-success" : "border-destructive/30 bg-destructive/10 text-destructive"
          }`}
        >
          {message.includes("成功") ? <CheckCircle2 className="h-4 w-4 shrink-0" /> : <AlertTriangle className="h-4 w-4 shrink-0" />}
          {message}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>上传数据</CardTitle>
          <CardDescription>支持微信小店订单明细 Excel，日期留空时自动按订单日期拆分</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 items-end">
            <div className="space-y-2">
              <Label>店铺</Label>
              <Select value={storeName} onChange={(e) => setStoreName(e.target.value)}>
                <option value="">选择店铺</option>
                {stores.map((s) => (
                  <option key={s.id} value={s.name}>
                    {s.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label>指定日期（可选）</Label>
              <Input type="date" value={importDate} onChange={(e) => setImportDate(e.target.value)} />
            </div>
          </div>

          <FileDropzone
            accept=".xlsx,.xls"
            label="微信小店订单明细 Excel"
            value={orderFile}
            onChange={setOrderFile}
          />

          <Button onClick={handleImport} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} {loading ? "导入中..." : "开始导入"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Search className="h-4 w-4" />
            导入历史
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>日期</TableHead>
                <TableHead>店铺</TableHead>
                <TableHead>订单文件</TableHead>
                <TableHead>商品/SKU 行</TableHead>
                <TableHead>订单行</TableHead>
                <TableHead>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {records.map((r, idx) => (
                <TableRow key={idx}>
                  <TableCell>{r.date}</TableCell>
                  <TableCell>{r.store_name}</TableCell>
                  <TableCell className="text-xs max-w-[300px] truncate">{r.order_file || "-"}</TableCell>
                  <TableCell>{r.product_rows}</TableCell>
                  <TableCell>{r.order_rows}</TableCell>
                  <TableCell>
                    <Button variant="ghost" size="icon" onClick={() => handleDelete(r.store_name, r.date)}>
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {records.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="p-0">
                    <EmptyState title="暂无导入记录" />
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
