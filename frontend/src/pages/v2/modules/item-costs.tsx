import { useEffect, useMemo, useState } from "react"
import { PageHeader, FilterBar, FilterItem, EmptyState } from "@/components/page-kit"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { ReportTable, type ReportColumn } from "@/pages/v2/components/report-table"
import { StatusBadge } from "@/pages/v2/components/status-badge"
import { request, fmtQty, fmtMoney, fmtDate } from "@/pages/v2/api"

interface Item {
  code: string
  name: string
  base_unit: string
  category: string | null
  safety_stock: number | null
  is_active: boolean
  created_at: string
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

interface CostVersion {
  id: string
  warehouse_code: string | null
  unit_cost: number
  effective_from: string
  effective_to: string | null
  source_type: string
  source_id: string | null
  created_at: string
}

interface ItemAgg {
  qty: number
  amount: number
}

/** 跨仓加权：Σ库存金额 / Σ可售数量 */
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

export function ItemCostsModule() {
  const [items, setItems] = useState<Item[] | null>(null)
  const [balances, setBalances] = useState<Balance[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [keyword, setKeyword] = useState("")
  // 行点击展开的单品：成本版本历史（懒加载 + 缓存）
  const [selected, setSelected] = useState<Item | null>(null)
  const [versions, setVersions] = useState<CostVersion[] | null>(null)
  const [versionsLoading, setVersionsLoading] = useState(false)
  const [versionsError, setVersionsError] = useState("")

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([request<Item[]>("/api/v2/items"), request<Balance[]>("/api/v2/inventory/balances")])
      .then(([itemList, balanceList]) => {
        if (cancelled) return
        setItems(itemList)
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

  const rows = useMemo(() => {
    const list = items ?? []
    const kw = keyword.trim().toLowerCase()
    if (!kw) return list
    return list.filter((item) => item.code.toLowerCase().includes(kw) || (item.name ?? "").toLowerCase().includes(kw))
  }, [items, keyword])

  const openDetail = (item: Item) => {
    if (selected?.code === item.code) {
      setSelected(null)
      return
    }
    setSelected(item)
    setVersions(null)
    setVersionsError("")
    setVersionsLoading(true)
    request<CostVersion[]>(`/api/v2/items/${encodeURIComponent(item.code)}/cost-versions`)
      .then((list) => setVersions(list))
      .catch((err) => setVersionsError(err instanceof Error ? err.message : "加载失败"))
      .finally(() => setVersionsLoading(false))
  }

  const columns: ReportColumn<Item>[] = [
    { key: "code", label: "单品编码" },
    { key: "name", label: "名称" },
    { key: "base_unit", label: "单位" },
    { key: "category", label: "分类" },
    {
      key: "avg_cost",
      label: "当前加权均价",
      align: "right",
      render: (item) => {
        const agg = balanceMap.get(item.code)
        return agg && agg.qty > 0 ? fmtMoney(agg.amount / agg.qty) : "—"
      },
    },
    {
      key: "qty",
      label: "库存总量",
      align: "right",
      render: (item) => fmtQty(balanceMap.get(item.code)?.qty ?? 0),
    },
    {
      key: "amount",
      label: "库存金额",
      align: "right",
      render: (item) => fmtMoney(balanceMap.get(item.code)?.amount ?? 0),
    },
    { key: "safety_stock", label: "安全库存", align: "right", render: (item) => fmtQty(item.safety_stock) },
  ]

  const versionColumns: ReportColumn<CostVersion>[] = [
    { key: "warehouse_code", label: "仓库", render: (v) => v.warehouse_code || "全部仓库" },
    { key: "unit_cost", label: "单位成本", align: "right", render: (v) => fmtMoney(v.unit_cost) },
    { key: "effective_from", label: "生效起", render: (v) => fmtDate(v.effective_from) },
    { key: "effective_to", label: "生效止", render: (v) => (v.effective_to ? fmtDate(v.effective_to) : "至今") },
    { key: "source_type", label: "来源类型", render: (v) => <StatusBadge value={v.source_type} /> },
    { key: "source_id", label: "来源单号", render: (v) => v.source_id || "—" },
  ]

  return (
    <div>
      <PageHeader
        title="单品成本"
        description="移动加权平均 =（期初金额+Σ入库金额）/（期初数量+Σ入库数量），出库不改均价"
      />

      {error && (
        <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-3.5 py-2.5 text-[13px] text-destructive">
          {error}
        </div>
      )}

      <FilterBar>
        <FilterItem label="编码 / 名称">
          <Input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="搜索单品编码或名称" />
        </FilterItem>
      </FilterBar>

      <ReportTable
        columns={columns}
        rows={rows}
        loading={loading}
        rowKey={(item) => item.code}
        emptyTitle="暂无单品"
        emptyHint="请先在单品管理中维护单品"
        onRowClick={openDetail}
        rowClassName={(item) => (selected?.code === item.code ? "bg-muted/40" : undefined)}
      />

      {selected && (
        <Card className="mt-4">
          <CardContent className="p-4">
            <div className="mb-3 text-sm font-medium">
              成本版本历史：{selected.code} {selected.name}
            </div>
            {versionsError && (
              <div className="mb-3 rounded-md border border-destructive/30 bg-destructive/10 px-3.5 py-2.5 text-[13px] text-destructive">
                {versionsError}
              </div>
            )}
            {versionsLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-4 w-full" />
                ))}
              </div>
            ) : versions && versions.length > 0 ? (
              <ReportTable columns={versionColumns} rows={versions} rowKey={(v) => v.id} />
            ) : (
              <EmptyState title="无成本版本记录" className="py-6" />
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
