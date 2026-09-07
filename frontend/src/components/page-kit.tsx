import * as React from "react"
import { cn } from "@/lib/utils"
import { Card, CardContent } from "@/components/ui/card"
import { TrendingUp, TrendingDown, Minus } from "lucide-react"

/** 页面头部：标题 + 副标题 + 右侧操作区 */
function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: React.ReactNode
  description?: React.ReactNode
  actions?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn("mb-5 flex flex-wrap items-end justify-between gap-3", className)}>
      <div className="space-y-1">
        <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
        {description && <p className="text-[13px] text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

/** KPI 指标卡：标签 + 大数字 + 可选环比 */
function StatCard({
  label,
  value,
  hint,
  delta,
  className,
}: {
  label: React.ReactNode
  value: React.ReactNode
  hint?: React.ReactNode
  delta?: number | null
  className?: string
}) {
  const deltaIcon =
    delta == null ? null : delta > 0 ? (
      <TrendingUp className="h-3.5 w-3.5 text-success" />
    ) : delta < 0 ? (
      <TrendingDown className="h-3.5 w-3.5 text-destructive" />
    ) : (
      <Minus className="h-3.5 w-3.5 text-muted-foreground" />
    )
  return (
    <Card className={cn("transition-shadow hover:shadow-md", className)}>
      <CardContent className="p-4">
        <div className="text-[13px] text-muted-foreground">{label}</div>
        <div className="tnum mt-1.5 flex items-baseline gap-2 text-2xl font-semibold tracking-tight">
          {value}
          {deltaIcon}
        </div>
        {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
      </CardContent>
    </Card>
  )
}

/** 筛选条：横向内联排布筛选项 */
function FilterBar({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <Card className={cn("mb-4", className)}>
      <CardContent className="flex flex-wrap items-end gap-3 p-3.5">{children}</CardContent>
    </Card>
  )
}

function FilterItem({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <label className="min-w-[140px] flex-1 text-xs text-muted-foreground sm:flex-none">
      <span className="mb-1 block">{label}</span>
      {children}
    </label>
  )
}

/** 空态 */
function EmptyState({
  title = "暂无数据",
  hint,
  className,
}: {
  title?: React.ReactNode
  hint?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-1 py-12 text-center", className)}>
      <div className="text-sm font-medium text-muted-foreground">{title}</div>
      {hint && <div className="text-xs text-muted-foreground/70">{hint}</div>}
    </div>
  )
}

export { PageHeader, StatCard, FilterBar, FilterItem, EmptyState }
