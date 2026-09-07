import * as React from "react"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/page-kit"
import { cn } from "@/lib/utils"

/** 报表列定义：render 优先，否则按 label 自动套数量/金额格式 */
export interface ReportColumn<T = any> {
  key: string
  label: string
  align?: "left" | "right" | "center"
  render?: (row: T) => React.ReactNode
  className?: string
}

interface ReportTableProps<T = any> {
  columns: ReportColumn<T>[]
  rows: T[] | null | undefined
  loading?: boolean
  rowKey?: (row: T, index: number) => React.Key
  emptyTitle?: string
  emptyHint?: string
  footer?: React.ReactNode
  /** 行点击（如展开明细） */
  onRowClick?: (row: T) => void
  rowClassName?: (row: T) => string | undefined
}

/** 通用报表表：紧凑行高 + tabular-nums + 加载骨架 + 空态 */
export function ReportTable<T = any>({
  columns,
  rows,
  loading = false,
  rowKey,
  emptyTitle = "暂无数据",
  emptyHint,
  footer,
  onRowClick,
  rowClassName,
}: ReportTableProps<T>) {
  return (
    <div className="overflow-auto rounded-md border">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/50 hover:bg-muted/50">
            {columns.map((col) => (
              <TableHead
                key={col.key}
                className={cn(
                  "whitespace-nowrap text-xs font-medium text-muted-foreground",
                  col.align === "right" && "text-right",
                  col.align === "center" && "text-center",
                  col.className
                )}
              >
                {col.label}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading ? (
            Array.from({ length: 6 }).map((_, i) => (
              <TableRow key={i}>
                {columns.map((col) => (
                  <TableCell key={col.key}>
                    <Skeleton className="h-4 w-full max-w-24" />
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : !rows || rows.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={columns.length}>
                <EmptyState title={emptyTitle} hint={emptyHint} />
              </TableCell>
            </TableRow>
          ) : (
            rows.map((row, i) => (
              <TableRow
                key={rowKey ? rowKey(row, i) : i}
                className={cn("hover:bg-muted/40", onRowClick && "cursor-pointer", rowClassName?.(row))}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {columns.map((col) => (
                  <TableCell
                    key={col.key}
                    className={cn(
                      "tnum whitespace-nowrap",
                      col.align === "right" && "text-right",
                      col.align === "center" && "text-center",
                      col.className
                    )}
                  >
                    {col.render ? col.render(row) : String((row as any)[col.key] ?? "—")}
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
      {footer}
    </div>
  )
}
