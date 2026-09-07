import { type KeyboardEvent } from "react"
import { Eye } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"

interface KpiItem {
  key: string
  label: string
}

function formatNumber(value: any, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-"
  if (typeof value === "number") {
    return value.toLocaleString("zh-CN", { maximumFractionDigits: digits })
  }
  return value
}

export function HideableKpiCard({
  label,
  value,
  unit = "",
  onHide,
}: {
  label: string
  value: any
  unit?: string
  onHide: () => void
}) {
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      onHide()
    }
  }

  return (
    <Card
      role="button"
      tabIndex={0}
      aria-label={`隐藏${label}`}
      onClick={onHide}
      onKeyDown={handleKeyDown}
      className="cursor-pointer transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      title="点击隐藏"
    >
      <CardContent className="p-4">
        <div className="text-[13px] text-muted-foreground">{label}</div>
        <div className="tnum mt-1.5 text-xl font-semibold tracking-tight">
          {formatNumber(value)}
          {unit && <span className="ml-1 text-xs font-normal text-muted-foreground">{unit}</span>}
        </div>
      </CardContent>
    </Card>
  )
}

export function HiddenKpiList({
  items,
  onRestore,
}: {
  items: KpiItem[]
  onRestore: (key: string) => void
}) {
  if (items.length === 0) return null

  return (
    <div className="flex flex-wrap items-center gap-2 border-t pt-3">
      <span className="text-xs text-muted-foreground">已隐藏：</span>
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          onClick={() => onRestore(item.key)}
          className="inline-flex items-center gap-1 rounded-full border border-border bg-muted px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          title="点击显示"
        >
          <Eye className="h-3 w-3" />
          {item.label}
        </button>
      ))}
    </div>
  )
}
