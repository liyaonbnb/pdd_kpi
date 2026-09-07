import { useEffect, useState } from "react"
import { AlertTriangle, CheckCircle2, Loader2, Upload, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { FileDropzone } from "@/components/ui/file-dropzone"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { EmptyState, PageHeader } from "@/components/page-kit"
import {
  getStores,
  importDouyinData,
  getDouyinRecords,
  deleteDouyinRecord,
  type Store,
  type DouyinImportRecord,
} from "@/api/client"

export function DouyinImportPage() {
  const [stores, setStores] = useState<Store[]>([])
  const [records, setRecords] = useState<DouyinImportRecord[]>([])
  const [storeName, setStoreName] = useState("")
  const [importDate, setImportDate] = useState("")
  const [promoFile, setPromoFile] = useState<File | null>(null)
  const [orderFile, setOrderFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState("")

  useEffect(() => {
    getStores("douyin").then((s) => {
      setStores(s)
      if (s.length > 0 && !storeName) {
        setStoreName(s[0].name)
      }
    })
    fetchRecords()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchRecords = async () => {
    const data = await getDouyinRecords()
    setRecords(data)
  }

  const handleImport = async () => {
    if (!storeName) {
      setMessage("请选择店铺")
      return
    }
    if (!promoFile && !orderFile) {
      setMessage("请至少上传推广数据或订单数据中的一个")
      return
    }
    setLoading(true)
    setMessage("")
    try {
      const formData = new FormData()
      formData.append("store_name", storeName)
      if (importDate) formData.append("import_date", importDate)
      if (promoFile) formData.append("promo_file", promoFile)
      if (orderFile) formData.append("order_file", orderFile)

      const res = await importDouyinData(formData)
      if (res.error) {
        setMessage(res.error)
        return
      }
      const dates = res.processed_dates || [res.date]
      setMessage(
        `导入成功。店铺：${res.store_name}，处理日期：${dates.join(", ")}；商品 ${res.product_rows || 0} 行，订单 ${res.order_rows || 0} 行`
      )
      setPromoFile(null)
      setOrderFile(null)
      fetchRecords()
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (storeName: string, date: string) => {
    if (!confirm("确定删除该日数据？")) return
    try {
      await deleteDouyinRecord(storeName, date)
      fetchRecords()
    } catch (err: any) {
      setMessage(err.message)
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader title="抖音导入" />
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
          <CardTitle className="flex items-center gap-2">
            <Upload className="h-4 w-4" />
            导入抖音数据
          </CardTitle>
          <CardDescription>支持 乘方推广/全域推广 Excel 以及抖音订单 CSV</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
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
              <Label>日期（留空则自动识别文件内所有日期）</Label>
              <Input type="date" value={importDate} onChange={(e) => setImportDate(e.target.value)} />
            </div>
            <div className="flex items-end">
              <Button onClick={handleImport} disabled={loading} className="w-full">
                {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                {loading ? "导入中..." : "开始导入"}
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>推广数据 Excel</Label>
              <FileDropzone
                accept=".xls,.xlsx"
                label="点击或拖拽上传推广 Excel"
                description="支持 .xls / .xlsx"
                value={promoFile}
                onChange={setPromoFile}
              />
            </div>
            <div className="space-y-2">
              <Label>订单数据 CSV</Label>
              <FileDropzone
                accept=".csv"
                label="点击或拖拽上传订单 CSV"
                description="支持 .csv"
                value={orderFile}
                onChange={setOrderFile}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>导入历史</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>日期</TableHead>
                <TableHead>店铺</TableHead>
                <TableHead>商品 / 订单</TableHead>
                <TableHead>文件名</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {records.map((r) => (
                <TableRow key={`${r.store_name}-${r.date}`}>
                  <TableCell>{r.date}</TableCell>
                  <TableCell>{r.store_name}</TableCell>
                  <TableCell>
                    {r.product_rows || 0} / {r.order_rows || 0}
                  </TableCell>
                  <TableCell className="text-xs max-w-xs truncate">
                    {r.promo_file} / {r.order_file}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="sm" onClick={() => handleDelete(r.store_name, r.date)}>
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {records.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="p-0">
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
