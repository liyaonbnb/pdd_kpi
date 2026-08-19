import { useEffect, useState } from "react"
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock3,
  FileCheck2,
  History,
  Loader2,
  RotateCcw,
  ShieldAlert,
  Trash2,
  Upload,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { FileDropzone } from "@/components/ui/file-dropzone"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { isMaster } from "@/api/auth"
import {
  deleteRecord,
  cleanupData,
  getImportBatches,
  getRecords,
  getStores,
  importData,
  previewImport,
  previewCleanup,
  rollbackImportBatch,
  type ImportBatch,
  type ImportPreview,
  type CleanupPreview,
  type Store,
} from "@/api/client"

function getYesterday() {
  const d = new Date()
  d.setDate(d.getDate() - 1)
  return d.toISOString().split("T")[0]
}

type PlatformRecord = {
  date: string
  store_name: string
  product_rows: number
  order_rows: number
  style_rows?: number
}

type BatchFilter = "all" | "imported" | "rolled_back" | "failed"

const statusMeta: Record<ImportBatch["status"], { label: string; className: string }> = {
  importing: { label: "导入中", className: "bg-blue-50 text-blue-700 ring-blue-200" },
  imported: { label: "已导入", className: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  rolled_back: { label: "已撤销", className: "bg-zinc-100 text-zinc-600 ring-zinc-200" },
  failed: { label: "失败", className: "bg-red-50 text-red-700 ring-red-200" },
  invalidated: { label: "已失效", className: "bg-amber-50 text-amber-700 ring-amber-200" },
}

const batchFilters: Array<{ value: BatchFilter; label: string }> = [
  { value: "all", label: "全部" },
  { value: "imported", label: "已导入" },
  { value: "rolled_back", label: "已撤销" },
  { value: "failed", label: "异常" },
]

function formatTime(value: string) {
  if (!value) return "-"
  return value.replace("T", " ").slice(0, 16)
}

function StatusPill({ status }: { status: ImportBatch["status"] }) {
  const meta = statusMeta[status] || statusMeta.invalidated
  return (
    <span className={`inline-flex items-center rounded px-2 py-1 text-xs font-medium ring-1 ring-inset ${meta.className}`}>
      {meta.label}
    </span>
  )
}

export function ImportPage() {
  const [stores, setStores] = useState<Store[]>([])
  const [batches, setBatches] = useState<ImportBatch[]>([])
  const [records, setRecords] = useState<PlatformRecord[]>([])
  const [storeName, setStoreName] = useState("")
  const [importDate, setImportDate] = useState(getYesterday())
  const [promoFile, setPromoFile] = useState<File | null>(null)
  const [orderFile, setOrderFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [batchFilter, setBatchFilter] = useState<BatchFilter>("all")
  const [loading, setLoading] = useState(false)
  const [busyBatch, setBusyBatch] = useState("")
  const [message, setMessage] = useState("")
  const [cleanupOpen, setCleanupOpen] = useState(false)
  const [cleanupStore, setCleanupStore] = useState("")
  const [cleanupDate, setCleanupDate] = useState("")
  const [cleanupType, setCleanupType] = useState<"orders" | "promo" | "all">("orders")
  const [cleanupPreviewData, setCleanupPreviewData] = useState<CleanupPreview | null>(null)
  const [cleanupLoading, setCleanupLoading] = useState(false)
  const master = isMaster()

  useEffect(() => {
    getStores("pdd").then(setStores)
    void fetchHistory()
  }, [])

  useEffect(() => {
    if (stores.length > 0 && !storeName) setStoreName(stores[0].name)
    if (stores.length > 0 && !cleanupStore) setCleanupStore(stores[0].name)
  }, [stores, storeName])

  const fetchHistory = async () => {
    const [batchRows, dailyRows] = await Promise.all([
      getImportBatches(),
      master ? getRecords() : Promise.resolve([]),
    ])
    setBatches(batchRows)
    setRecords(dailyRows)
  }

  const resetPreview = () => {
    setPreview(null)
    setMessage("")
  }

  const buildFormData = () => {
    const formData = new FormData()
    formData.append("store_name", storeName)
    formData.append("import_date", importDate)
    if (promoFile) formData.append("promo_file", promoFile)
    if (orderFile) formData.append("order_file", orderFile)
    return formData
  }

  const validateSelection = () => {
    if (!storeName) {
      setMessage("请选择店铺")
      return false
    }
    if (!promoFile && !orderFile) {
      setMessage("请至少上传一个数据文件")
      return false
    }
    return true
  }

  const handlePreview = async () => {
    if (!validateSelection()) return
    setLoading(true)
    setMessage("")
    try {
      setPreview(await previewImport(buildFormData()))
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleImport = async () => {
    if (!preview?.can_import || !validateSelection()) return
    setLoading(true)
    setMessage("")
    try {
      const res = await importData(buildFormData())
      setMessage(`导入成功 · 批次 ${String(res.batch_id).slice(0, 8)}`)
      setPromoFile(null)
      setOrderFile(null)
      setPreview(null)
      await fetchHistory()
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleRollback = async (batch: ImportBatch) => {
    const dates = batch.affected_dates.join("、") || batch.import_date
    if (!confirm(`撤销批次 ${batch.batch_id.slice(0, 8)}？\n将恢复 ${batch.store_name} 在 ${dates} 导入前的数据。`)) return
    setBusyBatch(batch.batch_id)
    setMessage("")
    try {
      await rollbackImportBatch(batch.batch_id)
      setMessage(`已撤销批次 ${batch.batch_id.slice(0, 8)}`)
      await fetchHistory()
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setBusyBatch("")
    }
  }

  const handleDeleteDay = async (record: PlatformRecord) => {
    const expected = `${record.store_name} ${record.date}`
    const input = prompt(`此操作不可撤销。请输入“${expected}”确认：`)
    if (input !== expected) return
    setMessage("")
    try {
      await deleteRecord(record.store_name, record.date)
      setMessage(`已删除 ${record.store_name} ${record.date} 的整日数据`)
      await fetchHistory()
    } catch (err: any) {
      setMessage(err.message)
    }
  }

  const openCleanup = () => {
    setCleanupStore(stores[0]?.name || storeName)
    setCleanupDate("")
    setCleanupType("orders")
    setCleanupPreviewData(null)
    setCleanupOpen(true)
  }

  const handleCleanupPreview = async () => {
    if (!cleanupStore || !cleanupDate) {
      setMessage("请选择店铺和日期")
      return
    }
    setCleanupLoading(true)
    try {
      setCleanupPreviewData(await previewCleanup(cleanupStore, cleanupDate))
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setCleanupLoading(false)
    }
  }

  const handleCleanup = async () => {
    if (!cleanupPreviewData) return
    const expected = `${cleanupStore} ${cleanupDate}`
    const input = prompt(`此操作会删除选定范围并重算指标。请输入“${expected}”确认：`)
    if (input !== expected) return
    setCleanupLoading(true)
    try {
      await cleanupData(cleanupStore, cleanupDate, cleanupType, input)
      setMessage(`已清理 ${cleanupStore} ${cleanupDate} 的${cleanupType === "orders" ? "订单" : cleanupType === "promo" ? "推广数据" : "整日数据"}`)
      setCleanupOpen(false)
      setCleanupPreviewData(null)
      await fetchHistory()
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setCleanupLoading(false)
    }
  }

  const filteredBatches = batches.filter((batch) => {
    if (batchFilter === "all") return true
    if (batchFilter === "failed") return batch.status === "failed" || batch.status === "invalidated"
    return batch.status === batchFilter
  })
  const stats = preview?.orders
  const hasFiles = Boolean(promoFile || orderFile)
  const messageIsSuccess = message.includes("成功") || message.includes("已撤销") || message.includes("已删除")

  return (
    <div className="space-y-6 pb-8">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="mb-1 flex items-center gap-2 text-xs font-medium text-muted-foreground">
            <span>拼多多</span><span className="text-zinc-300">/</span><span>数据中心</span>
          </div>
          <h2 className="text-2xl font-semibold text-zinc-950">数据导入</h2>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Clock3 className="h-3.5 w-3.5" />
          最近导入 {batches[0] ? formatTime(batches[0].created_at) : "暂无"}
        </div>
      </div>

      {message && (
        <div className={`flex items-center gap-2 rounded-lg border px-3 py-2.5 text-sm ${messageIsSuccess ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-red-200 bg-red-50 text-red-800"}`}>
          {messageIsSuccess ? <CheckCircle2 className="h-4 w-4 shrink-0" /> : <AlertTriangle className="h-4 w-4 shrink-0" />}
          {message}
        </div>
      )}

      <section className="overflow-hidden rounded-lg border border-zinc-200 bg-white shadow-sm">
        <div className="grid lg:grid-cols-[minmax(0,1.55fr)_minmax(320px,0.85fr)]">
          <div className="p-5 sm:p-6">
            <div className="mb-5 flex items-center gap-3">
              <span className="flex h-8 w-8 items-center justify-center rounded-md bg-zinc-950 text-white">
                <Upload className="h-4 w-4" />
              </span>
              <div>
                <h3 className="text-sm font-semibold text-zinc-950">新建导入</h3>
                <p className="text-xs text-muted-foreground">{storeName || "未选择店铺"} · {importDate}</p>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label className="text-xs font-medium text-zinc-700">店铺</Label>
                <Select value={storeName} onChange={(e) => { setStoreName(e.target.value); resetPreview() }}>
                  <option value="">选择店铺</option>
                  {stores.map((store) => <option key={store.id} value={store.name}>{store.name}</option>)}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs font-medium text-zinc-700">推广数据日期</Label>
                <Input type="date" value={importDate} onChange={(e) => { setImportDate(e.target.value); resetPreview() }} />
              </div>
            </div>

            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label className="text-xs font-medium text-zinc-700">推广数据</Label>
                <FileDropzone
                  compact accept=".xls,.xlsx" label="选择推广 Excel" description="XLS / XLSX"
                  value={promoFile} onChange={(file) => { setPromoFile(file); resetPreview() }}
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs font-medium text-zinc-700">订单数据</Label>
                <FileDropzone
                  compact accept=".csv" label="选择订单 CSV" description="CSV"
                  value={orderFile} onChange={(file) => { setOrderFile(file); resetPreview() }}
                />
              </div>
            </div>

            <div className="mt-5 flex items-center justify-between border-t border-zinc-100 pt-4">
              <div className="text-xs text-muted-foreground">{hasFiles ? `${Number(Boolean(promoFile)) + Number(Boolean(orderFile))} 个文件待检查` : "尚未选择文件"}</div>
              <Button onClick={handlePreview} disabled={loading || !hasFiles} className="min-w-[118px]">
                {loading && !preview ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileCheck2 className="h-4 w-4" />}
                检查数据
              </Button>
            </div>
          </div>

          <aside className="border-t border-zinc-200 bg-zinc-50/70 p-5 sm:p-6 lg:border-l lg:border-t-0">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-zinc-950">检查摘要</h3>
              {preview && (
                <span className={`inline-flex items-center gap-1 text-xs font-medium ${preview.can_import ? "text-emerald-700" : "text-red-700"}`}>
                  {preview.can_import ? <Check className="h-3.5 w-3.5" /> : <ShieldAlert className="h-3.5 w-3.5" />}
                  {preview.can_import ? "校验通过" : "需要处理"}
                </span>
              )}
            </div>

            {!preview ? (
              <div className="flex min-h-[238px] flex-col items-center justify-center border-y border-dashed border-zinc-200 text-center">
                <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-white text-zinc-400 ring-1 ring-zinc-200">
                  <FileCheck2 className="h-4 w-4" />
                </span>
                <p className="text-sm font-medium text-zinc-700">尚未生成检查结果</p>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-zinc-200 bg-zinc-200">
                  {[
                    ["有效订单", stats?.valid_orders || 0, "text-zinc-950"],
                    ["新增订单", stats?.new_orders || 0, "text-emerald-700"],
                    ["覆盖已有", stats?.existing_orders || 0, "text-amber-700"],
                    ["迁移日期", stats?.migrated_orders || 0, "text-blue-700"],
                  ].map(([label, value, color]) => (
                    <div key={String(label)} className="bg-white px-3 py-3">
                      <div className="text-[11px] text-muted-foreground">{label}</div>
                      <div className={`mt-0.5 text-xl font-semibold tabular-nums ${color}`}>{value}</div>
                    </div>
                  ))}
                </div>

                <div className="space-y-2 text-xs">
                  <div className="flex justify-between gap-3"><span className="text-muted-foreground">原始行数</span><span className="font-medium tabular-nums">{stats?.total_rows || 0}</span></div>
                  <div className="flex justify-between gap-3"><span className="text-muted-foreground">影响日期</span><span className="text-right font-medium">{preview.affected_dates.join("、") || "无"}</span></div>
                </div>

                {(preview.blockers.length > 0 || preview.warnings.length > 0) && (
                  <div className="space-y-2 border-t border-zinc-200 pt-3">
                    {preview.blockers.map((item) => <div key={item} className="flex gap-2 text-xs leading-5 text-red-700"><ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />{item}</div>)}
                    {preview.warnings.map((item) => <div key={item} className="flex gap-2 text-xs leading-5 text-amber-700"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{item}</div>)}
                  </div>
                )}

                <Button onClick={handleImport} disabled={loading || !preview.can_import} className="w-full">
                  {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                  确认导入
                </Button>
              </div>
            )}
          </aside>
        </div>
      </section>

      <section className="overflow-hidden rounded-lg border border-zinc-200 bg-white shadow-sm">
        <div className="flex flex-col gap-3 border-b border-zinc-200 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <span className="flex h-8 w-8 items-center justify-center rounded-md bg-zinc-100 text-zinc-700"><History className="h-4 w-4" /></span>
            <div>
              <h3 className="text-sm font-semibold text-zinc-950">导入批次</h3>
              <p className="text-xs text-muted-foreground">共 {batches.length} 条记录</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {master && (
              <Button variant="outline" size="sm" onClick={openCleanup} className="gap-1.5">
                <Trash2 className="h-3.5 w-3.5" />数据清理
              </Button>
            )}
            <div className="inline-flex w-fit rounded-md bg-zinc-100 p-0.5">
              {batchFilters.map((filter) => (
              <button
                key={filter.value}
                type="button"
                onClick={() => setBatchFilter(filter.value)}
                className={`h-7 rounded px-2.5 text-xs font-medium transition-colors ${batchFilter === filter.value ? "bg-white text-zinc-950 shadow-sm" : "text-zinc-500 hover:text-zinc-800"}`}
              >
                {filter.label}
              </button>
              ))}
            </div>
          </div>
        </div>

        <Table className="min-w-[850px]">
          <TableHeader className="bg-zinc-50/80"><TableRow>
            <TableHead className="pl-5">批次</TableHead><TableHead>店铺 / 文件</TableHead>
            <TableHead className="text-right">新增</TableHead><TableHead className="text-right">覆盖</TableHead>
            <TableHead>导入人</TableHead><TableHead>状态</TableHead><TableHead className="pr-5 text-right">操作</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {filteredBatches.map((batch) => (
              <TableRow key={batch.batch_id} className="hover:bg-zinc-50/70">
                <TableCell className="pl-5">
                  <div className="font-mono text-xs font-medium text-zinc-800">{batch.batch_id.slice(0, 8)}</div>
                  <div className="mt-0.5 whitespace-nowrap text-[11px] text-muted-foreground">{formatTime(batch.created_at)}</div>
                </TableCell>
                <TableCell>
                  <div className="text-sm font-medium text-zinc-900">{batch.store_name}</div>
                  <div className="mt-0.5 max-w-[260px] truncate text-xs text-muted-foreground">{batch.order_filename || batch.promo_filename}</div>
                </TableCell>
                <TableCell className="text-right font-medium tabular-nums text-emerald-700">{batch.stats?.new_orders || 0}</TableCell>
                <TableCell className="text-right font-medium tabular-nums text-amber-700">{batch.stats?.existing_orders || 0}</TableCell>
                <TableCell className="text-xs text-zinc-600">{batch.imported_by || "-"}</TableCell>
                <TableCell><StatusPill status={batch.status} /></TableCell>
                <TableCell className="pr-5 text-right">
                  <Button
                    variant="ghost" size="sm" title={batch.can_rollback ? "撤销本次导入" : batch.rollback_reason}
                    disabled={!batch.can_rollback || busyBatch === batch.batch_id}
                    onClick={() => handleRollback(batch)}
                    className="text-zinc-600 hover:text-zinc-950"
                  >
                    {busyBatch === batch.batch_id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
                    撤销
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {filteredBatches.length === 0 && (
              <TableRow><TableCell colSpan={7} className="h-28 text-center text-sm text-muted-foreground">暂无匹配的批次记录</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </section>

      {master && cleanupOpen && (
        <section className="overflow-hidden rounded-lg border border-zinc-200 bg-white shadow-sm">
          <div className="flex items-center justify-between border-b border-zinc-200 px-5 py-4">
            <div>
              <h3 className="text-sm font-semibold text-zinc-950">数据清理中心</h3>
              <p className="mt-0.5 text-xs text-muted-foreground">仅处理指定店铺指定日期，不影响其他日期。</p>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setCleanupOpen(false)}>关闭</Button>
          </div>
          <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.8fr)]">
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label className="text-xs font-medium text-zinc-700">店铺</Label>
                  <Select value={cleanupStore} onChange={(e) => { setCleanupStore(e.target.value); setCleanupPreviewData(null) }}>
                    <option value="">选择店铺</option>
                    {stores.map((store) => <option key={store.id} value={store.name}>{store.name}</option>)}
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs font-medium text-zinc-700">日期</Label>
                  <Input type="date" value={cleanupDate} onChange={(e) => { setCleanupDate(e.target.value); setCleanupPreviewData(null) }} />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs font-medium text-zinc-700">清理范围</Label>
                <div className="grid gap-2 sm:grid-cols-3">
                  {[
                    ["orders", "仅订单", "保留推广数据"],
                    ["promo", "仅推广", "保留订单数据"],
                    ["all", "整日数据", "订单、推广、指标全部删除"],
                  ].map(([value, label, desc]) => (
                    <button key={value} type="button" onClick={() => { setCleanupType(value as typeof cleanupType); setCleanupPreviewData(null) }} className={`rounded-md border p-3 text-left transition-colors ${cleanupType === value ? "border-zinc-950 bg-zinc-950 text-white" : "border-zinc-200 hover:border-zinc-400"}`}>
                      <div className="text-sm font-medium">{label}</div>
                      <div className={`mt-1 text-[11px] ${cleanupType === value ? "text-zinc-300" : "text-muted-foreground"}`}>{desc}</div>
                    </button>
                  ))}
                </div>
              </div>
              <Button onClick={handleCleanupPreview} disabled={cleanupLoading || !cleanupStore || !cleanupDate} className="gap-1.5">
                <FileCheck2 className="h-4 w-4" />检查影响范围
              </Button>
            </div>
            <div className="rounded-lg border border-zinc-200 bg-zinc-50/70 p-4">
              <h4 className="text-sm font-semibold text-zinc-900">删除前预览</h4>
              {!cleanupPreviewData ? (
                <p className="mt-8 text-center text-xs text-muted-foreground">选择店铺和日期后检查</p>
              ) : (
                <div className="mt-4 space-y-3">
                  <div className="grid grid-cols-2 gap-2">
                    <div className="rounded border border-zinc-200 bg-white p-3"><div className="text-[11px] text-muted-foreground">订单行</div><div className="mt-1 text-xl font-semibold text-zinc-950">{cleanupPreviewData.order_rows}</div></div>
                    <div className="rounded border border-zinc-200 bg-white p-3"><div className="text-[11px] text-muted-foreground">推广行</div><div className="mt-1 text-xl font-semibold text-zinc-950">{cleanupPreviewData.promo_rows}</div></div>
                    <div className="rounded border border-zinc-200 bg-white p-3"><div className="text-[11px] text-muted-foreground">商品指标</div><div className="mt-1 text-xl font-semibold text-zinc-950">{cleanupPreviewData.product_rows}</div></div>
                    <div className="rounded border border-zinc-200 bg-white p-3"><div className="text-[11px] text-muted-foreground">样式指标</div><div className="mt-1 text-xl font-semibold text-zinc-950">{cleanupPreviewData.style_rows}</div></div>
                  </div>
                  <p className="text-xs leading-5 text-amber-700">确认后会写入操作日志，并将相关导入批次标记为已失效。</p>
                  <Button variant="destructive" onClick={handleCleanup} disabled={cleanupLoading || (!cleanupPreviewData.has_orders && !cleanupPreviewData.has_promo)} className="w-full gap-1.5">
                    <Trash2 className="h-4 w-4" />确认清理
                  </Button>
                </div>
              )}
            </div>
          </div>
        </section>
      )}

      {master && (
        <details className="group overflow-hidden rounded-lg border border-zinc-200 bg-white">
          <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-4 text-sm font-medium text-zinc-700 hover:bg-zinc-50">
            <span className="flex items-center gap-2"><Trash2 className="h-4 w-4 text-zinc-400" />整日数据管理</span>
            <ChevronDown className="h-4 w-4 text-zinc-400 transition-transform group-open:rotate-180" />
          </summary>
          <div className="border-t border-zinc-200">
            <Table className="min-w-[620px]">
              <TableHeader className="bg-zinc-50/80"><TableRow>
                <TableHead className="pl-5">日期</TableHead><TableHead>店铺</TableHead><TableHead>商品 / 样式 / 订单</TableHead><TableHead className="pr-5 text-right">操作</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {records.map((record) => (
                  <TableRow key={`${record.store_name}-${record.date}`}>
                    <TableCell className="pl-5 font-mono text-xs">{record.date}</TableCell><TableCell>{record.store_name}</TableCell>
                    <TableCell className="tabular-nums text-zinc-600">{record.product_rows} / {record.style_rows || 0} / {record.order_rows}</TableCell>
                    <TableCell className="pr-5 text-right">
                      <Button variant="ghost" size="sm" title="删除整日数据" className="text-red-600 hover:bg-red-50 hover:text-red-700" onClick={() => handleDeleteDay(record)}>
                        <Trash2 className="h-3.5 w-3.5" />删除整日
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {records.length === 0 && <TableRow><TableCell colSpan={4} className="h-24 text-center text-muted-foreground">暂无每日数据</TableCell></TableRow>}
              </TableBody>
            </Table>
          </div>
        </details>
      )}
    </div>
  )
}
