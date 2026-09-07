import { useEffect, useRef, useState } from "react"
import { Save, RefreshCw, Link2, AlertCircle, CheckCircle2, Download, Upload } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { PageHeader, EmptyState } from "@/components/page-kit"
import {
  getWechatCosts,
  saveWechatCosts,
  refreshWechatCostCodes,
  getWechatUnmappedProducts,
  mapWechatProduct,
  exportWechatCosts,
  importWechatCosts,
  type WechatCost,
  type WechatUnmappedRow,
} from "@/api/client"

export function WechatCostsPage() {
  const [costs, setCosts] = useState<WechatCost[]>([])
  const [unmapped, setUnmapped] = useState<WechatUnmappedRow[]>([])
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState("")
  const [mappingCodes, setMappingCodes] = useState<Record<string, string>>({})
  const fileInputRef = useRef<HTMLInputElement>(null)

  const fetchData = async () => {
    setLoading(true)
    try {
      const [costsData, unmappedData] = await Promise.all([getWechatCosts(), getWechatUnmappedProducts()])
      setCosts(costsData)
      setUnmapped(unmappedData)
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  const updateCost = (idx: number, field: keyof WechatCost, value: any) => {
    const next = [...costs]
    next[idx] = { ...next[idx], [field]: value }
    setCosts(next)
  }

  const handleSave = async () => {
    try {
      await saveWechatCosts(costs)
      setMessage("保存成功")
    } catch (err: any) {
      setMessage(err.message)
    }
  }

  const handleRefresh = async () => {
    try {
      const res = await refreshWechatCostCodes()
      await fetchData()
      setMessage(`已刷新 SKU 编码，新增 ${res.added} 个`)
    } catch (err: any) {
      setMessage(err.message)
    }
  }

  const handleExportPending = async () => {
    try {
      const blob = await exportWechatCosts(true)
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `微信待维护SKU编码_${new Date().toISOString().split("T")[0]}.csv`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
      setMessage("导出成功")
    } catch (err: any) {
      setMessage(err.message)
    }
  }

  const handleImportClick = () => {
    fileInputRef.current?.click()
  }

  const handleImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const res = await importWechatCosts(file)
      await fetchData()
      setMessage(`导入成功，更新 ${res.updated} 条`)
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      e.target.value = ""
    }
  }

  const mappingKey = (row: WechatUnmappedRow) => `${row.sku_code}::${row.store_name}`

  const handleMap = async (row: WechatUnmappedRow) => {
    const key = mappingKey(row)
    const skuCode = mappingCodes[key]
    if (!skuCode) return
    try {
      await mapWechatProduct(skuCode, row.product_name)
      setMappingCodes((prev) => ({ ...prev, [key]: "" }))
      await fetchData()
      setMessage("映射成功")
    } catch (err: any) {
      setMessage(err.message)
    }
  }

  const renderCostTable = (rows: WechatCost[], title: string, variant: "warning" | "success", icon: React.ReactNode) => {
    return (
      <div className="space-y-2">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          {icon}
          {title}
          <Badge variant={variant === "warning" ? "destructive" : "success"}>{rows.length}</Badge>
        </h3>
        <div className="overflow-auto rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>SKU 编码</TableHead>
                <TableHead>商品名称</TableHead>
                <TableHead>商品成本/件</TableHead>
                <TableHead>物流成本/件</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((cost) => {
                const idx = costs.findIndex((c) => c.sku_code === cost.sku_code)
                return (
                  <TableRow key={cost.sku_code}>
                    <TableCell className="font-mono text-xs">{cost.sku_code}</TableCell>
                    <TableCell>
                      <Input value={cost.product_name} onChange={(e) => updateCost(idx, "product_name", e.target.value)} />
                    </TableCell>
                    <TableCell>
                      <Input
                        type="number"
                        value={cost.product_cost}
                        onChange={(e) => updateCost(idx, "product_cost", parseFloat(e.target.value) || 0)}
                      />
                    </TableCell>
                    <TableCell>
                      <Input
                        type="number"
                        value={cost.logistics_cost}
                        onChange={(e) => updateCost(idx, "logistics_cost", parseFloat(e.target.value) || 0)}
                      />
                    </TableCell>
                  </TableRow>
                )
              })}
              {rows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-muted-foreground py-4">
                    {variant === "warning" ? "暂无待维护 SKU 编码" : "暂无已维护 SKU 编码"}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </div>
    )
  }

  return (
    <div>
      <PageHeader
        title="微信成本管理"
        description="维护 SKU 编码成本，并处理未映射编码的商品"
        actions={
          <>
            <Button variant="outline" size="sm" onClick={handleExportPending} disabled={loading}>
              <Download className="h-4 w-4 mr-1" /> 导出待维护
            </Button>
            <Button variant="outline" size="sm" onClick={handleImportClick} disabled={loading}>
              <Upload className="h-4 w-4 mr-1" /> 导入成本
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={handleImportFile}
            />
            <Button variant="outline" size="sm" onClick={handleRefresh} disabled={loading}>
              <RefreshCw className="h-4 w-4 mr-1" /> 刷新编码
            </Button>
            <Button size="sm" onClick={handleSave}>
              <Save className="h-4 w-4 mr-1" /> 保存
            </Button>
          </>
        }
      />
      {message && (
        <div
          className={`mb-4 rounded-md border px-3.5 py-2.5 text-[13px] ${
            message.includes("成功") || message.includes("刷新") || message.includes("新增")
              ? "border-success/30 bg-success/10 text-success"
              : "border-destructive/30 bg-destructive/10 text-destructive"
          }`}
        >
          {message}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">SKU 编码成本（全店铺通用）</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {loading && costs.length === 0 ? (
            <div className="space-y-3">
              <Skeleton className="h-6 w-40" />
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-6 w-40" />
              <Skeleton className="h-32 w-full" />
            </div>
          ) : (
            <>
              {renderCostTable(
                costs.filter((c) => c.product_cost <= 0 || c.logistics_cost <= 0),
                "待维护 SKU 编码",
                "warning",
                <AlertCircle className="h-4 w-4 text-destructive" />
              )}
              {renderCostTable(
                costs.filter((c) => c.product_cost > 0 && c.logistics_cost > 0),
                "已维护 SKU 编码",
                "success",
                <CheckCircle2 className="h-4 w-4 text-success" />
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <AlertCircle className="h-4 w-4 text-destructive" />
            未映射 SKU 编码的商品
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading && unmapped.length === 0 ? (
            <div className="space-y-2">
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
            </div>
          ) : unmapped.length === 0 ? (
            <EmptyState title="所有商品都有 SKU 编码或已完成映射" />
          ) : (
            <div className="overflow-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>SKU 编码</TableHead>
                    <TableHead>商品名称</TableHead>
                    <TableHead>平台 SKU</TableHead>
                    <TableHead>出现店铺</TableHead>
                    <TableHead>订单天数</TableHead>
                    <TableHead>映射到 SKU 编码</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {unmapped.map((row) => {
                    const key = mappingKey(row)
                    return (
                      <TableRow key={key}>
                        <TableCell className="font-mono text-xs">{row.sku_code}</TableCell>
                        <TableCell>{row.product_name}</TableCell>
                        <TableCell className="font-mono text-xs">{row.platform_sku_code}</TableCell>
                        <TableCell>{row.store_name}</TableCell>
                        <TableCell>{row.order_count}</TableCell>
                        <TableCell>
                          <div className="flex gap-2">
                            <Select
                              value={mappingCodes[key] || ""}
                              onChange={(e) => setMappingCodes((prev) => ({ ...prev, [key]: e.target.value }))}
                            >
                              <option value="">选择或输入</option>
                              {costs.map((c) => (
                                <option key={c.sku_code} value={c.sku_code}>
                                  {c.sku_code} {c.product_name ? `(${c.product_name})` : ""}
                                </option>
                              ))}
                            </Select>
                            <Input
                              placeholder="新编码"
                              className="w-24"
                              value={mappingCodes[key] || ""}
                              onChange={(e) => setMappingCodes((prev) => ({ ...prev, [key]: e.target.value }))}
                            />
                          </div>
                        </TableCell>
                        <TableCell className="text-right">
                          <Button size="sm" onClick={() => handleMap(row)} disabled={!mappingCodes[key]}>
                            <Link2 className="h-4 w-4 mr-1" /> 映射
                          </Button>
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
