/**
 * 供应链中心（/v2）：集中 API 封装与展示格式化工具。
 * 所有模块自取自渲，统一走这里的 request/uploadFile/downloadFile。
 * 认证：与主站共用登录态（localStorage 的 pdd_token），同源 /api 代理到 V2 API。
 */

import { getToken } from "@/api/auth"

// 默认同源（由 test_web / nginx 把 /api 代理到 V2 API）；本地联调可用 VITE_V2_API_URL 指向测试机
const API = import.meta.env.VITE_V2_API_URL || ""

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function request<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...authHeaders(), ...(options.headers || {}) },
  })
  if (response.status === 401) {
    window.location.href = "/login"
    throw new Error("登录已失效")
  }
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error((body as any).detail || "请求失败")
  return body as T
}

/** 文件上传（导入类接口：multipart/form-data） */
export async function uploadFile<T = any>(path: string, fields: Record<string, string>, file: File): Promise<T> {
  const body = new FormData()
  Object.entries(fields).forEach(([key, value]) => body.append(key, value))
  body.append("file", file)
  const response = await fetch(`${API}${path}`, { method: "POST", headers: authHeaders(), body })
  if (response.status === 401) {
    window.location.href = "/login"
    throw new Error("登录已失效")
  }
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error((payload as any).detail || "文件导入失败")
  return payload as T
}

/** 文件下载（导出类接口：携带登录态，按 Content-Disposition 文件名保存） */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const response = await fetch(`${API}${path}`, { headers: authHeaders() })
  if (response.status === 401) {
    window.location.href = "/login"
    throw new Error("登录已失效")
  }
  if (!response.ok) throw new Error("导出失败")
  const blob = await response.blob()
  const disposition = response.headers.get("Content-Disposition") || ""
  const match = disposition.match(/filename\*=UTF-8''([^;]+)/)
  const name = match ? decodeURIComponent(match[1]) : fallbackName
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}

/** 把可选筛选参数拼成 query string（空值自动丢弃） */
export function qs(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value) !== "") search.set(key, String(value))
  })
  const text = search.toString()
  return text ? `?${text}` : ""
}

// ---------- 数字与时间的展示规则：数量整数、金额两位小数、空值 "—" ----------

const NULL_TEXT = "—"

export const num2 = (v: any): string => {
  const n = Number(v)
  return Number.isFinite(n) && String(v ?? "").trim() !== "" ? n.toFixed(2) : String(v ?? NULL_TEXT)
}

export const fmtQty = (v: any): string => {
  const n = Number(v)
  return Number.isFinite(n) && /^-?\d+(\.\d+)?$/.test(String(v ?? "").trim()) ? String(Math.round(n)) : String(v ?? NULL_TEXT)
}

export const fmtMoney = num2

/** 按列名自动套用数量/金额规则（通用表用） */
const QTY_RE = /数量|需要|可用|缺口/
const MONEY_RE = /金额|费用|成本|均价|单价|快递费/
export const fmtCell = (v: any, header: string): string => {
  if (v === null || v === undefined) return NULL_TEXT
  if (typeof v === "object") return JSON.stringify(v)
  if (QTY_RE.test(header)) return fmtQty(v)
  if (MONEY_RE.test(header)) return fmtMoney(v)
  return String(v ?? NULL_TEXT)
}

export const fmtTime = (v: any): string => {
  if (!v) return NULL_TEXT
  const text = String(v)
  return text.length >= 16 ? text.replace("T", " ").slice(0, 16) : text
}

export const fmtDate = (v: any): string => (v ? String(v).slice(0, 10) : NULL_TEXT)
