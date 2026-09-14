import { useCallback, useEffect, useState } from "react"
import { PageHeader, StatCard } from "@/components/page-kit"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { ReportTable, type ReportColumn } from "@/pages/v2/components/report-table"
import { request, fmtQty, fmtDate } from "@/pages/v2/api"

interface UnmappedRow {
  platform: string
  store_name: string
  product_id: string
  product_name: string | null
  style_id: string | null
  style_name: string | null
  order_count: number
  first_date: string | null
}

interface UnmappedResponse {
  rows: UnmappedRow[]
  total: number
}

export function UnmappedModule() {
  const [data, setData] = useState<UnmappedResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  // 映射对话框
  const [mapping, setMapping] = useState<UnmappedRow | null>(null)
  const [bundleCode, setBundleCode] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [dialogError, setDialogError] = useState("")
  const [bundles, setBundles] = useState<{ code: string; name: string }[]>([])
  const [choices, setChoices] = useState<Record<string, string>>({})
  const [bulkSaving, setBulkSaving] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    request<UnmappedResponse>("/api/v2/costs/unmapped")
      .then((res) => {
        setData(res)
        setError("")
      })
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
    request<{ code: string; name: string }[]>("/api/v2/bundles").then((list) => setBundles(list.filter((b) => b))).catch(() => undefined)
  }, [load])

  const openDialog = (row: UnmappedRow) => {
    setMapping(row)
    setBundleCode("")
    setDialogError("")
  }

  const submitMapping = async () => {
    if (!mapping) return
    const code = bundleCode.trim()
    if (!code) {
      setDialogError("请输入目标组合编码")
      return
    }
    setSubmitting(true)
    setDialogError("")
    try {
      await request("/api/v2/listings", {
        method: "POST",
        body: JSON.stringify({
          platform: mapping.platform,
          store_name: mapping.store_name,
          product_id: mapping.product_id,
          style_id: mapping.style_id,
          bundle_code: code,
        }),
      })
      setMapping(null)
      setNotice(`映射成功：${mapping.product_id} → ${code}`)
      load()
    } catch (err) {
      const message = err instanceof Error ? err.message : "映射失败"
      setDialogError(message.includes("已存在") ? "该链接映射已存在，请勿重复提交" : message)
    } finally {
      setSubmitting(false)
    }
  }

  const rowKey = (row: UnmappedRow) => `${row.platform}|${row.store_name}|${row.product_id}|${row.style_id ?? ""}`
  const recommended = (row: UnmappedRow) => {
    const text = `${row.product_id} ${row.product_name || ""}`.toLowerCase()
    return bundles.find((bundle) => text.includes(bundle.code.toLowerCase()) || text.includes(bundle.name.toLowerCase()))?.code || ""
  }
  const setChoice = (row: UnmappedRow, code: string) => setChoices((current) => ({ ...current, [rowKey(row)]: code }))
  const applyRecommendations = () => {
    const next = { ...choices }
    for (const row of data?.rows || []) if (!next[rowKey(row)]) next[rowKey(row)] = recommended(row)
    setChoices(next)
  }
  const saveBulk = async () => {
    const mappings = (data?.rows || []).filter((row) => choices[rowKey(row)]).map((row) => ({ platform: row.platform, store_name: row.store_name, product_id: row.product_id, style_id: row.style_id, bundle_code: choices[rowKey(row)], effective_from: new Date().toISOString().slice(0, 10) }))
    if (!mappings.length) { alert("请先为至少一条商品选择组合"); return }
    setBulkSaving(true)
    try { await request("/api/v2/listings/bulk", { method: "POST", body: JSON.stringify({ mappings }) }); setNotice(`已批量保存 ${mappings.length} 条映射`); setChoices({}); load() }
    catch (err) { alert(err instanceof Error ? err.message : "批量保存失败") }
    finally { setBulkSaving(false) }
  }

  const columns: ReportColumn<UnmappedRow>[] = [
    { key: "platform", label: "平台" },
    { key: "store_name", label: "店铺" },
    { key: "product_id", label: "商品ID" },
    { key: "product_name", label: "商品名称", render: (row) => row.product_name || "—" },
    { key: "style_id", label: "规格ID", render: (row) => row.style_id || "—" },
    { key: "order_count", label: "订单数", align: "right", render: (row) => fmtQty(row.order_count) },
    { key: "first_date", label: "首次出现日期", render: (row) => fmtDate(row.first_date) },
    {
      key: "action",
      label: "操作",
      align: "center",
      render: (row) => (
        <div className="flex items-center justify-center gap-2"><Select className="w-44" value={choices[rowKey(row)] || ""} onChange={(e) => setChoice(row, e.target.value)}><option value="">选择组合</option>{bundles.map((bundle) => <option key={bundle.code} value={bundle.code}>{bundle.code} · {bundle.name}</option>)}</Select><Button size="sm" variant="ghost" onClick={() => openDialog(row)}>手工</Button></div>
      ),
    },
  ]

  return (
    <div>
      <PageHeader
        title="未映射治理"
        description="订单中出现但尚未映射到组合的链接；可自动推荐后批量保存映射"
        actions={<div className="flex gap-2"><Button variant="outline" size="sm" onClick={applyRecommendations}>自动推荐</Button><Button size="sm" onClick={() => void saveBulk()} disabled={bulkSaving}>{bulkSaving ? "保存中…" : "批量保存映射"}</Button></div>}
      />

      {error && (
        <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-3.5 py-2.5 text-[13px] text-destructive">
          {error}
        </div>
      )}
      {notice && (
        <div className="mb-4 rounded-md border border-success/30 bg-success/10 px-3.5 py-2.5 text-[13px] text-success">
          {notice}
        </div>
      )}

      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="未映射链接总数" value={loading ? "…" : fmtQty(data?.total ?? 0)} hint="需要维护映射后才能正常扣减库存" />
      </div>

      <ReportTable
        columns={columns}
        rows={data?.rows ?? []}
        loading={loading}
        rowKey={(row) => `${row.platform}|${row.store_name}|${row.product_id}|${row.style_id ?? ""}`}
        emptyTitle="没有未映射链接"
        emptyHint="所有订单链接均已映射到组合"
      />

      <Dialog open={mapping !== null} onOpenChange={(open) => !open && setMapping(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>映射到组合</DialogTitle>
            <DialogDescription>
              {mapping
                ? `${mapping.platform} / ${mapping.store_name} / 商品 ${mapping.product_id}${
                    mapping.style_id ? ` / 规格 ${mapping.style_id}` : ""
                  }`
                : ""}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            {dialogError && (
              <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3.5 py-2.5 text-[13px] text-destructive">
                {dialogError}
              </div>
            )}
            <label className="block text-xs text-muted-foreground">
              <span className="mb-1 block">目标组合编码</span>
              <Input
                value={bundleCode}
                onChange={(e) => setBundleCode(e.target.value)}
                placeholder="输入组合编码，如 BUNDLE-001"
                autoFocus
              />
            </label>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setMapping(null)} disabled={submitting}>
                取消
              </Button>
              <Button onClick={submitMapping} disabled={submitting}>
                {submitting ? "提交中…" : "确认映射"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
