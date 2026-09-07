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
  getGlobalCosts,
  saveGlobalCosts,
  refreshGlobalCostCodes,
  getUnmappedProducts,
  mapProductToMerchantCode,
  exportGlobalCosts,
  importGlobalCosts,
  type Cost,
} from "@/api/client"

interface UnmappedRow {
  product_id: string
  product_name: string
  style_id: string
  style_name: string
  store_name: string
  order_count: number
  first_date: string
}

export function CostsPage() {
  const [costs, setCosts] = useState<Cost[]>([])
  const [unmapped, setUnmapped] = useState<UnmappedRow[]>([])
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState("")
  const [mappingCodes, setMappingCodes] = useState<Record<string, string>>({})
  const fileInputRef = useRef<HTMLInputElement>(null)

  const fetchData = async () => {
    setLoading(true)
    try {
      const [costsData, unmappedData] = await Promise.all([getGlobalCosts(), getUnmappedProducts()])
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

  const updateCost = (idx: number, field: keyof Cost, value: any) => {
    const next = [...costs]
    next[idx] = { ...next[idx], [field]: value }
    setCosts(next)
  }

  const handleSave = async () => {
    try {
      await saveGlobalCosts(costs)
      setMessage("保存成功")
    } catch (err: any) {
      setMessage(err.message)
    }
  }

  const handleRefresh = async () => {
    try {
      const res = await refreshGlobalCostCodes()
      await fetchData()
      setMessage(`已刷新商家编码，新增 ${res.added} 个`)
    } catch (err: any) {
      setMessage(err.message)
    }
  }

  const handleExportPending = async () => {
    try {
      const blob = await exportGlobalCosts(true)
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `待维护商家编码_${new Date().toISOString().split("T")[0]}.csv`
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
      const res = await importGlobalCosts(file)
      await fetchData()
      setMessage(`导入成功，更新 ${res.updated} 条`)
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      e.target.value = ""
    }
  }

  const mappingKey = (row: UnmappedRow) => `${row.product_id}::${row.style_id}`

  const handleMap = async (row: UnmappedRow) => {
    const key = mappingKey(row)
    const merchantCode = mappingCodes[key]
    if (!merchantCode) return
    try {
      await mapProductToMerchantCode(
        row.product_id,
        merchantCode,
        row.style_id === "-" ? undefined : row.style_id,
        row.product_name
      )
      setMappingCodes((prev) => ({ ...prev, [key]: "" }))
      await fetchData()
      setMessage("映射成功")
    } catch (err: any) {
      setMessage(err.message)
    }
  }

  const renderCostTable = (rows: Cost[], title: string, variant: "warning" | "success", icon: React.ReactNode) => {
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
                <TableHead>商家编码</TableHead>
                <TableHead>商品名称</TableHead>
                <TableHead>商品成本/件</TableHead>
                <TableHead>物流成本/件</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((cost) => {
                const idx = costs.findIndex((c) => c.merchant_code === cost.merchant_code)
                return (
                  <TableRow key={cost.merchant_code}>
                    <TableCell className="font-mono text-xs">{cost.merchant_code}</TableCell>
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
                    {variant === "warning" ? "暂无待维护商家编码" : "暂无已维护商家编码"}
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
        title="成本管理"
        description="维护商家编码成本，并处理未映射编码的商品"
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
          <CardTitle className="text-base">商家编码成本（全店铺通用）</CardTitle>
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
                "待维护商家编码",
                "warning",
                <AlertCircle className="h-4 w-4 text-destructive" />
              )}
              {renderCostTable(
                costs.filter((c) => c.product_cost > 0 && c.logistics_cost > 0),
                "已维护商家编码",
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
            未映射商家编码的商品
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
            <EmptyState title="所有商品都有商家编码或已完成映射" />
          ) : (
            <div className="overflow-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>商品ID</TableHead>
                    <TableHead>商品名称</TableHead>
                    <TableHead>样式ID</TableHead>
                    <TableHead>样式/规格</TableHead>
                    <TableHead>出现店铺</TableHead>
                    <TableHead>订单天数</TableHead>
                    <TableHead>映射到商家编码</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {unmapped.map((row) => {
                    const key = mappingKey(row)
                    return (
                      <TableRow key={key}>
                        <TableCell className="font-mono text-xs">{row.product_id}</TableCell>
                        <TableCell>{row.product_name}</TableCell>
                        <TableCell className="font-mono text-xs">{row.style_id}</TableCell>
                        <TableCell>{row.style_name}</TableCell>
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
                                <option key={c.merchant_code} value={c.merchant_code}>
                                  {c.merchant_code} {c.product_name ? `(${c.product_name})` : ""}
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
