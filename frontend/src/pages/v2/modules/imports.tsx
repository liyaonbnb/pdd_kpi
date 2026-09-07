import { useEffect, useState } from "react"
import { FileUp } from "lucide-react"
import { PageHeader } from "@/components/page-kit"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ReportTable, type ReportColumn } from "../components/report-table"
import { StatusBadge } from "../components/status-badge"
import { request, uploadFile, fmtQty, fmtTime, fmtDate } from "../api"

interface ImportBatch {
  id: string
  platform: string | null
  store_name: string | null
  data_type: string
  metric_date: string | null
  period_from: string | null
  status: string
  row_count: number | null
  error_count: number | null
  created_at: string
}

const TYPE_LABELS: Record<string, string> = {
  orders: "订单",
  promotions: "推广",
  items: "单品",
  bundles: "组合",
  stock_in: "入库明细",
  stock_out: "出库明细",
  inventory: "库存",
  costs: "成本",
}

interface CardConfig {
  key: string
  title: string
  hint: string
  endpoint: string
  /** orders/promotions 需要平台、店铺、数据日期 */
  needsMeta: boolean
  /** 出入库明细支持同单号覆盖重导 */
  supportsOverwrite?: boolean
  buildFields: (meta: { platform: string; store_name: string; metric_date: string }, mode: string, overwrite: boolean) => Record<string, string>
}

const today = () => new Date().toISOString().slice(0, 10)

const CARDS: CardConfig[] = [
  {
    key: "orders",
    title: "订单导入",
    hint: "订单号/商品ID/商品数量(件)/支付时间；历史订单不扣库存",
    endpoint: "/api/v2/imports/file",
    needsMeta: true,
    buildFields: (meta, mode) => ({ ...meta, data_type: "orders", mode }),
  },
  {
    key: "promotions",
    title: "推广导入",
    hint: "成交花费(元)/交易额(元)/曝光量/点击量；需提供数据日期",
    endpoint: "/api/v2/imports/file",
    needsMeta: true,
    buildFields: (meta, mode) => ({ ...meta, data_type: "promotions", mode }),
  },
  {
    key: "items",
    title: "单品导入",
    hint: "单品编码(或货品编号/条码)/单品名称/单位/类别/参考成本",
    endpoint: "/api/v2/imports/catalog",
    needsMeta: false,
    buildFields: (_meta, mode) => ({ import_type: "items", mode }),
  },
  {
    key: "bundles",
    title: "组合商品导入",
    hint: "组合编码/组合名称/单品编码/单品数量/预估快递费；同组合多行各写一个组件",
    endpoint: "/api/v2/imports/catalog",
    needsMeta: false,
    buildFields: (_meta, mode) => ({ import_type: "bundles", mode }),
  },
  {
    key: "stock_in",
    title: "入库明细（网店管家）",
    hint: "入库单号/登记时间/货品货号/数量/单价/仓库/入库原因；直接入库建批次，入库原因记为业务类型",
    endpoint: "/api/v2/imports/stock-io",
    needsMeta: false,
    supportsOverwrite: true,
    buildFields: (_meta, mode, overwrite) => ({ io_type: "in", mode, overwrite: overwrite ? "true" : "false" }),
  },
  {
    key: "stock_out",
    title: "出库明细（网店管家）",
    hint: "出库单号/审核时间/货品编号/数量/仓库/出库原因；FIFO 直接扣库，缺货进异常队列，出库原因记为业务类型",
    endpoint: "/api/v2/imports/stock-io",
    needsMeta: false,
    supportsOverwrite: true,
    buildFields: (_meta, mode, overwrite) => ({ io_type: "out", mode, overwrite: overwrite ? "true" : "false" }),
  },
]

function ImportCard({ config, onImported }: { config: CardConfig; onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [meta, setMeta] = useState({ platform: "pdd", store_name: "", metric_date: today() })
  const [overwrite, setOverwrite] = useState(false)

  const upload = async (mode: "preview" | "import") => {
    if (!file) {
      alert("请先选择 CSV、XLS 或 XLSX 文件")
      return
    }
    if (config.needsMeta && (!meta.store_name.trim() || !meta.metric_date)) {
      alert("请填写店铺与数据日期")
      return
    }
    setBusy(true)
    try {
      const fields = config.buildFields({ ...meta, store_name: meta.store_name.trim() }, mode, overwrite)
      const payload = await uploadFile(config.endpoint, fields, file)
      setResult(payload)
      if (mode === "import") onImported()
    } catch (e: any) {
      alert(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <FileUp className="h-4 w-4 text-muted-foreground" />
          {config.title}
        </CardTitle>
        <p className="text-xs leading-relaxed text-muted-foreground">{config.hint}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        {config.needsMeta && (
          <div className="grid grid-cols-3 gap-2">
            <label className="block text-xs text-muted-foreground">
              <span className="mb-1 block">平台</span>
              <Select value={meta.platform} onChange={(e) => setMeta({ ...meta, platform: e.target.value })}>
                <option value="pdd">拼多多</option>
                <option value="douyin">抖音</option>
                <option value="tmall">天猫</option>
                <option value="wechat">微信</option>
              </Select>
            </label>
            <label className="block text-xs text-muted-foreground">
              <span className="mb-1 block">店铺</span>
              <Input value={meta.store_name} onChange={(e) => setMeta({ ...meta, store_name: e.target.value })} />
            </label>
            <label className="block text-xs text-muted-foreground">
              <span className="mb-1 block">数据日期</span>
              <Input type="date" value={meta.metric_date} onChange={(e) => setMeta({ ...meta, metric_date: e.target.value })} />
            </label>
          </div>
        )}
        <label className="block text-xs text-muted-foreground">
          <span className="mb-1 block">选择文件</span>
          <Input type="file" accept=".csv,.xls,.xlsx" onChange={(e) => setFile(e.target.files?.[0] || null)} />
        </label>
        {config.supportsOverwrite && (
          <label className="flex items-start gap-2 text-xs text-muted-foreground">
            <input type="checkbox" className="mt-0.5" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} />
            <span>
              同单号自动覆盖：重新导入时撤销该单旧流水按新文件重记；
              已被消耗的入库单会拒绝覆盖并在结果中提示冲突
            </span>
          </label>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" disabled={busy} onClick={() => void upload("preview")}>
            预览校验
          </Button>
          <Button size="sm" disabled={busy} onClick={() => void upload("import")}>
            {busy ? "处理中…" : "正式导入"}
          </Button>
        </div>
        {result && (
          <pre className="max-h-72 overflow-auto rounded-md border bg-muted/60 p-3 text-xs">{JSON.stringify(result, null, 2)}</pre>
        )}
      </CardContent>
    </Card>
  )
}

export function ImportsModule() {
  const [batches, setBatches] = useState<ImportBatch[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [rollingBack, setRollingBack] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError("")
    request<ImportBatch[]>("/api/v2/imports/batches")
      .then((data) => setBatches(Array.isArray(data) ? data : []))
      .catch((e) => setError(e?.message || "加载失败"))
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  const rollback = async (batch: ImportBatch) => {
    if (!window.confirm(`确认回滚批次 ${batch.id}（${TYPE_LABELS[batch.data_type] || batch.data_type}）？有库存动作的批次会被拒绝。`)) return
    setRollingBack(batch.id)
    try {
      await request(`/api/v2/imports/batches/${batch.id}/rollback`, { method: "POST" })
      load()
    } catch (e: any) {
      alert(e.message)
    } finally {
      setRollingBack(null)
    }
  }

  const columns: ReportColumn<ImportBatch>[] = [
    { key: "id", label: "ID", render: (r) => <span title={r.id}>{String(r.id).slice(0, 8)}</span> },
    { key: "platform", label: "平台", render: (r) => r.platform || "—" },
    { key: "store_name", label: "店铺", render: (r) => r.store_name || "—" },
    { key: "data_type", label: "类型", render: (r) => TYPE_LABELS[r.data_type] || r.data_type },
    { key: "metric_date", label: "日期", render: (r) => fmtDate(r.metric_date || r.period_from) },
    { key: "status", label: "状态", render: (r) => <StatusBadge value={r.status} /> },
    { key: "row_count", label: "行数", align: "right", render: (r) => fmtQty(r.row_count) },
    {
      key: "error_count",
      label: "错误数",
      align: "right",
      render: (r) => (
        <span className={Number(r.error_count) > 0 ? "text-destructive" : undefined}>{fmtQty(r.error_count)}</span>
      ),
    },
    { key: "created_at", label: "创建时间", render: (r) => fmtTime(r.created_at) },
    {
      key: "actions",
      label: "操作",
      render: (r) => (
        <Button
          variant="destructive"
          size="sm"
          disabled={rollingBack === r.id || r.status === "rolled_back"}
          onClick={() => void rollback(r)}
        >
          {rollingBack === r.id ? "回滚中…" : "回滚"}
        </Button>
      ),
    },
  ]

  return (
    <div>
      <PageHeader title="导入中心" description="自动识别编码与字段别名；同文件指纹幂等，重复导入自动跳过" />
      {error && <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-3.5 py-2.5 text-sm text-destructive">{error}</div>}

      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-3">
        {CARDS.map((config) => (
          <ImportCard key={config.key} config={config} onImported={load} />
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>最近导入批次</CardTitle>
        </CardHeader>
        <CardContent>
          <ReportTable columns={columns} rows={batches} loading={loading} rowKey={(r) => r.id} emptyTitle="暂无导入批次" />
        </CardContent>
      </Card>
    </div>
  )
}
