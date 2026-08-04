import { useCallback, useState } from "react"
import { Upload, FileCheck2 } from "lucide-react"
import { cn } from "@/lib/utils"

interface FileDropzoneProps {
  accept?: string
  label: string
  description?: string
  value?: File | null
  onChange: (file: File | null) => void
  className?: string
  compact?: boolean
}

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function FileDropzone({ accept, label, description, value, onChange, className, compact = false }: FileDropzoneProps) {
  const [isDragging, setIsDragging] = useState(false)

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragging(false)
      const droppedFile = e.dataTransfer.files?.[0]
      if (droppedFile) {
        onChange(droppedFile)
      }
    },
    [onChange]
  )

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selectedFile = e.target.files?.[0]
      if (selectedFile) {
        onChange(selectedFile)
      }
    },
    [onChange]
  )

  return (
    <label
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={cn(
        "group flex cursor-pointer items-center rounded-lg border border-dashed transition-colors hover:border-foreground/30 hover:bg-zinc-50",
        compact ? "min-h-[82px] gap-3 px-4 py-3" : "min-h-[132px] flex-col justify-center gap-2 p-6 text-center",
        isDragging ? "border-foreground/40 bg-zinc-50" : "border-zinc-300 bg-white",
        className
      )}
    >
      <input
        type="file"
        accept={accept}
        onChange={handleInputChange}
        className="sr-only"
      />
      {value ? (
        <>
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-emerald-50 text-emerald-700">
            <FileCheck2 className="h-4 w-4" />
          </span>
          <span className={cn("min-w-0", !compact && "text-center")}>
            <span className="block truncate text-sm font-medium text-foreground">{value.name}</span>
            <span className="block text-xs text-muted-foreground">{formatFileSize(value.size)} · 点击替换</span>
          </span>
        </>
      ) : (
        <>
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-zinc-100 text-zinc-600 transition-colors group-hover:bg-zinc-200">
            <Upload className="h-4 w-4" />
          </span>
          <span className={cn("min-w-0", !compact && "text-center")}>
            <span className="block text-sm font-medium">{label}</span>
            {description && <span className="block text-xs text-muted-foreground">{description}</span>}
          </span>
        </>
      )}
    </label>
  )
}
