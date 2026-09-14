import { useEffect, useMemo, useState } from "react"
import { Pencil, Trash2, Download, Upload } from "lucide-react"
import { PageHeader, FilterBar, FilterItem, EmptyState } from "@/components/page-kit"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { ReportTable, type ReportColumn } from "@/pages/v2/components/report-table"
import { request, uploadFile, downloadFile, fmtQty, fmtMoney } from "@/pages/v2/api"

interface BundleCost {
  bundle_code: string
  bundle_name: string
  estimated_shipping_fee: number
  product_cost: number
}

interface BundleComponent {
  item_code: string
  item_name?: string
  quantity: number
}

interface Bundle {
  code: string
  name: string
  estimated_shipping_fee: number
  version_no: number | null
  components: BundleComponent[]
}

interface Balance {
  warehouse_code: string
  warehouse_name: string
  item_code: string
  item_name: string
  sellable_qty: number
  average_unit_cost: number
  total_average_cost: number
  updated_at: string
}

interface ItemAgg {
  qty: number
  amount: number
}

/** 跨仓加权：Σ库存金额 / Σ可售数量（与单品成本同口径） */
function aggregateBalances(balances: Balance[]): Map<string, ItemAgg> {
  const map = new Map<string, ItemAgg>()
  for (const b of balances) {
    const agg = map.get(b.item_code) ?? { qty: 0, amount: 0 }
    agg.qty += Number(b.sellable_qty) || 0
    agg.amount += Number(b.total_average_cost) || 0
    map.set(b.item_code, agg)
  }
  return map
}

export function BundleCostsModule() {
  const [costs, setCosts] = useState<BundleCost[] | null>(null)
  const [bundles, setBundles] = useState<Bundle[] | null>(null)
  const [balances, setBalances] = useState<Balance[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [keyword, setKeyword] = useState("")
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([
      request<BundleCost[]>("/api/v2/costs/bundles"),
      request<Bundle[]>("/api/v2/bundles"),
      request<Balance[]>("/api/v2/inventory/balances"),
    ])
      .then(([costList, bundleList, balanceList]) => {
        if (cancelled) return
        setCosts(costList)
        setBundles(bundleList)
        setBalances(balanceList)
        setError("")
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "加载失败"))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [])

  const balanceMap = useMemo(() => aggregateBalances(balances ?? []), [balances])
  const bundleMap = useMemo(() => new Map((bundles ?? []).map((b) => [b.code, b])), [bundles])

  const rows = useMemo(() => {
    const list = costs ?? []
    const kw = keyword.trim().toLowerCase()
    if (!kw) return list
    return list.filter(
      (row) => row.bundle_code.toLowerCase().includes(kw) || (row.bundle_name ?? "").toLowerCase().includes(kw)
    )
  }, [costs, keyword])

  const maintainBundle = async (row: BundleCost) => {
    const bundle = bundleMap.get(row.bundle_code)
    if (!bundle) return
    const name = window.prompt("组合名称", bundle.name)
    if (name === null || !name.trim()) return
    const feeText = window.prompt("预估快递费", String(bundle.estimated_shipping_fee ?? row.estimated_shipping_fee ?? 0))
    if (feeText === null) return
    const fee = Number(feeText)
    if (!Number.isFinite(fee) || fee < 0) { alert("快递费必须是非负数字"); return }
    try {
      await request(`/api/v2/bundles/${encodeURIComponent(row.bundle_code)}`, { method: "PATCH", body: JSON.stringify({ name: name.trim(), estimated_shipping_fee: fee }) })
      setBundles((current) => current?.map((item) => item.code === row.bundle_code ? { ...item, name: name.trim(), estimated_shipping_fee: fee } : item) ?? null)
      setCosts((current) => current?.map((item) => item.bundle_code === row.bundle_code ? { ...item, bundle_name: name.trim(), estimated_shipping_fee: fee } : item) ?? null)
    } catch (e: any) { alert(e?.message || "保存失败") }
  }

  const deactivateBundle = async (row: BundleCost) => {
    if (!window.confirm(`确定停用组合「${row.bundle_code}」吗？历史订单不会删除。`)) return
    try { await request(`/api/v2/bundles/${encodeURIComponent(row.bundle_code)}`, { method: "DELETE" }); setCosts((current) => current?.filter((item) => item.bundle_code !== row.bundle_code) ?? null); setBundles((current) => current?.filter((item) => item.code !== row.bundle_code) ?? null) }
    catch (e: any) { alert(e?.message || "停用失败") }
  }

  const columns: ReportColumn<BundleCost>[] = [
    { key: "bundle_code", label: "组合编码" },
    { key: "bundle_name", label: "组合名称" },
    { key: "product_cost", label: "产品成本", align: "right", render: (row) => fmtMoney(row.product_cost) },
    {
      key: "estimated_shipping_fee",
      label: "预估快递费",
      align: "right",
      render: (row) => fmtMoney(row.estimated_shipping_fee),
    },
    {
      key: "total_cost",
      label: "总成本",
      align: "right",
      render: (row) => fmtMoney((Number(row.product_cost) || 0) + (Number(row.estimated_shipping_fee) || 0)),
    },
    {
      key: "version_no",
      label: "版本号",
      align: "center",
      render: (row) => bundleMap.get(row.bundle_code)?.version_no ?? "—",
    },
    { key: "_actions", label: "操作", align: "center", render: (row) => <div className="flex justify-center gap-1"><Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); void maintainBundle(row) }}><Pencil className="h-3.5 w-3.5" />编辑</Button><Button variant="ghost" size="sm" className="text-destructive" onClick={(e) => { e.stopPropagation(); void deactivateBundle(row) }}><Trash2 className="h-3.5 w-3.5" />停用</Button></div> },
  ]

  const selectedBundle = selected ? bundleMap.get(selected) : undefined
  const bomColumns: ReportColumn<BundleComponent>[] = [
    { key: "item_code", label: "单品编码" },
    { key: "item_name", label: "名称", render: (c) => c.item_name || "—" },
    { key: "quantity", label: "用量", align: "right", render: (c) => fmtQty(c.quantity) },
    {
      key: "avg_cost",
      label: "当前均价",
      align: "right",
      render: (c) => {
        const agg = balanceMap.get(c.item_code)
        if (!agg || agg.qty <= 0) return <span className="text-chart-3">无库存</span>
        return fmtMoney(agg.amount / agg.qty)
      },
    },
    {
      key: "subtotal",
      label: "小计",
      align: "right",
      render: (c) => {
        const agg = balanceMap.get(c.item_code)
        if (!agg || agg.qty <= 0) return "—"
        return fmtMoney((Number(c.quantity) || 0) * (agg.amount / agg.qty))
      },
    },
  ]

  return (
    <div>
      <PageHeader
        title="组合成本"
        description="产品成本 = Σ 组件用量 × 库存加权均价（无库存回退最新成本版本）"
        actions={<div className="flex gap-2"><Button variant="outline" size="sm" onClick={() => void downloadFile("/api/costs/global/export", "组合成本.csv")}><Download className="h-4 w-4" />导出 CSV</Button><label><span className="inline-flex h-9 cursor-pointer items-center gap-2 rounded-md border px-3 text-sm font-medium hover:bg-muted"><Upload className="h-4 w-4" />导入 CSV</span><input type="file" accept=".csv" className="hidden" onChange={async (e) => { const file = e.target.files?.[0]; if (!file) return; try { const r = await uploadFile<{ updated: number }>("/api/costs/global/import", {}, file); alert(`已导入 ${r.updated} 条组合成本`); window.location.reload() } catch (err: any) { alert(err?.message || "导入失败") } e.target.value = "" }} /></label></div>}
      />

      {error && (
        <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-3.5 py-2.5 text-[13px] text-destructive">
          {error}
        </div>
      )}

      <FilterBar>
        <FilterItem label="编码 / 名称">
          <Input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="搜索组合编码或名称" />
        </FilterItem>
      </FilterBar>

      <ReportTable
        columns={columns}
        rows={rows}
        loading={loading}
        rowKey={(row) => row.bundle_code}
        emptyTitle="暂无组合"
        emptyHint="请先在组合管理中维护组合与 BOM"
        onRowClick={(row) => setSelected(selected === row.bundle_code ? null : row.bundle_code)}
        rowClassName={(row) => (selected === row.bundle_code ? "bg-muted/40" : undefined)}
      />

      {selected && (
        <Card className="mt-4">
          <CardContent className="p-4">
            <div className="mb-3 text-sm font-medium">
              BOM 组件：{selected} {selectedBundle?.name ?? ""}
            </div>
            {selectedBundle && selectedBundle.components.length > 0 ? (
              <ReportTable
                columns={bomColumns}
                rows={selectedBundle.components}
                loading={loading}
                rowKey={(c) => c.item_code}
              />
            ) : (
              <EmptyState title="该组合暂无 BOM 组件" className="py-6" />
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
