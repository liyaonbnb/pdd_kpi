import { useEffect, useRef, useState } from "react"
import { BrowserRouter, Routes, Route, NavLink, useLocation, useNavigate } from "react-router-dom"
import {
  LayoutDashboard,
  Store,
  Upload,
  BarChart3,
  ShoppingCart,
  Coins,
  Bot,
  Menu,
  X,
  LogOut,
  Users,
  Settings,
  RefreshCw,
  User,
  ChevronUp,
  Sun,
  Moon,
  XCircle,
  CheckCircle2,
  BookOpenCheck,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Select } from "@/components/ui/select"
import { useTheme } from "@/components/theme-provider"
import { AuthGuard } from "@/components/auth-guard"
import { canAccessPage, getCurrentUser, isMaster, logout } from "@/api/auth"
import {
  updateFromGithub,
  getGlobalUnmappedCount,
  getDouyinUnmappedCount,
  getTmallUnmappedCount,
  getWechatUnmappedCount,
} from "@/api/client"
import { LoginPage } from "@/pages/login"
import { DashboardPage } from "@/pages/dashboard"
import { StoresPage } from "@/pages/stores"
import { ImportPage } from "@/pages/import"
import { MetricsPage } from "@/pages/metrics"
import { OrdersPage } from "@/pages/orders"
import { CostsPage } from "@/pages/costs"
import { AiWecomPage } from "@/pages/ai-wecom"
import { UsersPage } from "@/pages/users"
import { DouyinDashboardPage } from "@/pages/douyin-dashboard"
import { DouyinImportPage } from "@/pages/douyin-import"
import { DouyinMetricsPage } from "@/pages/douyin-metrics"
import { DouyinOrdersPage } from "@/pages/douyin-orders"
import { DouyinCostsPage } from "@/pages/douyin-costs"
import { TmallDashboardPage } from "@/pages/tmall-dashboard"
import { TmallImportPage } from "@/pages/tmall-import"
import { TmallMetricsPage } from "@/pages/tmall-metrics"
import { TmallOrdersPage } from "@/pages/tmall-orders"
import { TmallCostsPage } from "@/pages/tmall-costs"
import { WechatDashboardPage } from "@/pages/wechat-dashboard"
import { WechatImportPage } from "@/pages/wechat-import"
import { WechatMetricsPage } from "@/pages/wechat-metrics"
import { WechatOrdersPage } from "@/pages/wechat-orders"
import { WechatCostsPage } from "@/pages/wechat-costs"
import { ChangePasswordPage } from "@/pages/change-password"
import { KnowledgeAssistantPage } from "@/pages/knowledge-assistant"

type Platform = "pdd" | "douyin" | "tmall" | "wechat"

interface NavItem {
  id: string
  to: string
  label: string
  icon: React.ComponentType<{ className?: string }>
}

const pddNavItems: NavItem[] = [
  { id: "overview", to: "/", label: "总览", icon: LayoutDashboard },
  { id: "import", to: "/import", label: "导入", icon: Upload },
  { id: "metrics", to: "/metrics", label: "指标", icon: BarChart3 },
  { id: "orders", to: "/orders", label: "订单", icon: ShoppingCart },
  { id: "costs", to: "/costs", label: "成本", icon: Coins },
  { id: "knowledge_assistant", to: "/knowledge", label: "知识助手", icon: BookOpenCheck },
  { id: "ai_wecom", to: "/ai-wecom", label: "AI & 企微", icon: Bot },
]

const douyinNavItems: NavItem[] = [
  { id: "douyin_overview", to: "/douyin", label: "抖音总览", icon: LayoutDashboard },
  { id: "douyin_import", to: "/douyin/import", label: "抖音导入", icon: Upload },
  { id: "douyin_metrics", to: "/douyin/metrics", label: "抖音指标", icon: BarChart3 },
  { id: "douyin_orders", to: "/douyin/orders", label: "抖音订单", icon: ShoppingCart },
  { id: "douyin_costs", to: "/douyin/costs", label: "抖音成本", icon: Coins },
  { id: "ai_wecom", to: "/ai-wecom", label: "AI & 企微", icon: Bot },
]

const tmallNavItems: NavItem[] = [
  { id: "tmall_overview", to: "/tmall", label: "天猫总览", icon: LayoutDashboard },
  { id: "tmall_import", to: "/tmall/import", label: "天猫导入", icon: Upload },
  { id: "tmall_metrics", to: "/tmall/metrics", label: "天猫指标", icon: BarChart3 },
  { id: "tmall_orders", to: "/tmall/orders", label: "天猫订单", icon: ShoppingCart },
  { id: "tmall_costs", to: "/tmall/costs", label: "天猫成本", icon: Coins },
  { id: "ai_wecom", to: "/ai-wecom", label: "AI & 企微", icon: Bot },
]

const wechatNavItems: NavItem[] = [
  { id: "wechat_overview", to: "/wechat", label: "微信总览", icon: LayoutDashboard },
  { id: "wechat_import", to: "/wechat/import", label: "微信导入", icon: Upload },
  { id: "wechat_metrics", to: "/wechat/metrics", label: "微信指标", icon: BarChart3 },
  { id: "wechat_orders", to: "/wechat/orders", label: "微信订单", icon: ShoppingCart },
  { id: "wechat_costs", to: "/wechat/costs", label: "微信成本", icon: Coins },
  { id: "ai_wecom", to: "/ai-wecom", label: "AI & 企微", icon: Bot },
]

const platformTabs: { key: Platform; label: string; defaultTo: string }[] = [
  { key: "pdd", label: "拼多多", defaultTo: "/" },
  { key: "douyin", label: "抖音", defaultTo: "/douyin" },
  { key: "tmall", label: "天猫", defaultTo: "/tmall" },
  { key: "wechat", label: "微信小店", defaultTo: "/wechat" },
]

const routePageMap: { path: string; id: string }[] = [
  { path: "/", id: "overview" },
  { path: "/stores", id: "stores" },
  { path: "/import", id: "import" },
  { path: "/metrics", id: "metrics" },
  { path: "/orders", id: "orders" },
  { path: "/costs", id: "costs" },
  { path: "/knowledge", id: "knowledge_assistant" },
  { path: "/douyin", id: "douyin_overview" },
  { path: "/douyin/import", id: "douyin_import" },
  { path: "/douyin/metrics", id: "douyin_metrics" },
  { path: "/douyin/orders", id: "douyin_orders" },
  { path: "/douyin/costs", id: "douyin_costs" },
  { path: "/tmall", id: "tmall_overview" },
  { path: "/tmall/import", id: "tmall_import" },
  { path: "/tmall/metrics", id: "tmall_metrics" },
  { path: "/tmall/orders", id: "tmall_orders" },
  { path: "/tmall/costs", id: "tmall_costs" },
  { path: "/wechat", id: "wechat_overview" },
  { path: "/wechat/import", id: "wechat_import" },
  { path: "/wechat/metrics", id: "wechat_metrics" },
  { path: "/wechat/orders", id: "wechat_orders" },
  { path: "/wechat/costs", id: "wechat_costs" },
  { path: "/ai-wecom", id: "ai_wecom" },
  { path: "/users", id: "users" },
]

function getPageIdByPath(pathname: string): string | null {
  if (pathname === "/change-password") return null
  const exact = routePageMap.find((r) => r.path === pathname)
  if (exact) return exact.id
  const prefix = routePageMap.find((r) => pathname.startsWith(r.path + "/"))
  return prefix?.id ?? null
}

function firstAllowedFallback(): string {
  if (isMaster()) return "/"
  const allowed = getCurrentUser()?.allowed_pages || []
  const route = routePageMap.find((r) => allowed.includes(r.id))
  return route?.path || "/login"
}

function detectPlatform(pathname: string, search = ""): Platform {
  if (pathname.startsWith("/douyin")) return "douyin"
  if (pathname.startsWith("/tmall")) return "tmall"
  if (pathname.startsWith("/wechat")) return "wechat"
  if (pathname === "/ai-wecom") {
    const platform = new URLSearchParams(search).get("platform") as Platform
    if (platform && platformTabs.some((t) => t.key === platform)) return platform
  }
  return "pdd"
}

function PlatformTabs({
  platform,
  onChange,
}: {
  platform: Platform
  onChange: (p: Platform) => void
}) {
  return (
    <div className="px-2 pb-3">
      <Select
        value={platform}
        onChange={(e) => onChange(e.target.value as Platform)}
      >
        {platformTabs.map((tab) => (
          <option key={tab.key} value={tab.key}>
            {tab.label}
          </option>
        ))}
      </Select>
    </div>
  )
}

function UserMenu({
  user,
  showMaster,
  onClose,
  updating,
  updateMsg,
  onUpdate,
}: {
  user: ReturnType<typeof getCurrentUser>
  showMaster: boolean
  onClose?: () => void
  updating: boolean
  updateMsg: string
  onUpdate: () => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const { theme, setTheme } = useTheme()

  useEffect(() => {
    if (!open) return
    const handle = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", handle)
    return () => document.removeEventListener("mousedown", handle)
  }, [open])

  const itemClass =
    "flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"

  return (
    <div className="px-2">
      <div className="flex items-center justify-between">
        <div className="text-sm">
          <div className="font-medium">{user?.username || "未知用户"}</div>
          <div className="text-xs text-muted-foreground">
            {user?.role === "master" ? "主账号" : "子账号"}
          </div>
        </div>
        <div className="relative" ref={ref}>
          <Button
            variant="ghost"
            size="sm"
            className="gap-1 text-muted-foreground"
            onClick={() => setOpen(!open)}
          >
            <User className="h-4 w-4" />
            <ChevronUp className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`} />
          </Button>
          {open && (
            <div className="absolute bottom-full right-0 mb-2 w-44 rounded-md border bg-popover p-1 shadow-lg z-50">
              {(showMaster || canAccessPage("users")) && (
                <NavLink
                  to="/users"
                  onClick={() => {
                    setOpen(false)
                    onClose?.()
                  }}
                  className={itemClass}
                >
                  <Users className="h-4 w-4" />
                  用户管理
                </NavLink>
              )}
              {(showMaster || canAccessPage("stores")) && (
                <NavLink
                  to="/stores"
                  onClick={() => {
                    setOpen(false)
                    onClose?.()
                  }}
                  className={itemClass}
                >
                  <Store className="h-4 w-4" />
                  店铺
                </NavLink>
              )}
              {showMaster && (
                <button
                  onClick={() => {
                    setOpen(false)
                    onUpdate()
                  }}
                  disabled={updating}
                  className={`${itemClass} ${updating ? "opacity-60" : ""}`}
                >
                  <RefreshCw className={`h-4 w-4 ${updating ? "animate-spin" : ""}`} />
                  {updating ? "更新中" : "系统更新"}
                </button>
              )}
              <NavLink
                to="/change-password"
                onClick={() => {
                  setOpen(false)
                  onClose?.()
                }}
                className={itemClass}
              >
                <Settings className="h-4 w-4" />
                修改密码
              </NavLink>
              <button
                onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
                className={itemClass}
              >
                {theme === "dark" ? (
                  <Sun className="h-4 w-4" />
                ) : (
                  <Moon className="h-4 w-4" />
                )}
                切换主题
              </button>
              <button
                onClick={() => {
                  setOpen(false)
                  logout()
                }}
                className={itemClass}
              >
                <LogOut className="h-4 w-4" />
                退出登录
              </button>
            </div>
          )}
        </div>
      </div>
      {updateMsg && <div className="pt-2 text-xs text-destructive">{updateMsg}</div>}
    </div>
  )
}

function Sidebar({
  platform,
  onPlatformChange,
  onClose,
}: {
  platform: Platform
  onPlatformChange: (p: Platform) => void
  onClose?: () => void
}) {
  const user = getCurrentUser()
  const showMaster = isMaster()
  const [updating, setUpdating] = useState(false)
  const [updateMsg, setUpdateMsg] = useState("")
  const [updateProgress, setUpdateProgress] = useState<any[]>([])
  const [costBadge, setCostBadge] = useState<{ pending: number; unmapped: number } | null>(null)
  const navItems =
    platform === "douyin" ? douyinNavItems : platform === "tmall" ? tmallNavItems : platform === "wechat" ? wechatNavItems : pddNavItems
  const visibleItems = navItems.filter((item) => (showMaster ? true : canAccessPage(item.id)))

  const costPageId =
    platform === "douyin" ? "douyin_costs" : platform === "tmall" ? "tmall_costs" : platform === "wechat" ? "wechat_costs" : "costs"

  useEffect(() => {
    const fetchCostBadge = async () => {
      if (!showMaster && !canAccessPage(costPageId)) {
        setCostBadge(null)
        return
      }
      try {
        let count
        if (platform === "douyin") {
          count = await getDouyinUnmappedCount()
        } else if (platform === "tmall") {
          count = await getTmallUnmappedCount()
        } else if (platform === "wechat") {
          count = await getWechatUnmappedCount()
        } else {
          count = await getGlobalUnmappedCount()
        }
        setCostBadge(
          count.pending > 0 || count.unmapped > 0
            ? { pending: count.pending, unmapped: count.unmapped }
            : null
        )
      } catch {
        setCostBadge(null)
      }
    }
    fetchCostBadge()
    const timer = setInterval(fetchCostBadge, 60000)
    return () => clearInterval(timer)
  }, [platform, showMaster, costPageId])

  const handleUpdate = async () => {
    if (!confirm("确定从 GitHub 拉取最新代码并重启服务？")) return
    setUpdating(true)
    setUpdateMsg("")
    setUpdateProgress([])
    try {
      const res = await updateFromGithub()
      if (res.up_to_date) {
        setUpdateMsg("当前已是最新版本，无需更新")
      } else if (res.success) {
        setUpdateProgress(res.steps || [])
        setUpdateMsg("更新成功，等待服务重启后自动刷新...")
        const waitForRestart = async (attempt = 0) => {
          if (attempt > 30) {
            setUpdateMsg("服务重启超时，请手动刷新页面")
            return
          }
          try {
            const r = await fetch("/api/health")
            if (r.ok) {
              window.location.reload()
            } else {
              throw new Error("not ready")
            }
          } catch {
            setTimeout(() => waitForRestart(attempt + 1), 2000)
          }
        }
        setTimeout(waitForRestart, 4000)
      } else {
        setUpdateProgress(res.steps || [])
        setUpdateMsg(`更新失败：${JSON.stringify(res.steps)}`)
      }
    } catch (err: any) {
      setUpdateMsg(err.message)
    } finally {
      setUpdating(false)
    }
  }

  return (
    <aside className="w-64 border-r bg-card min-h-screen p-4 flex flex-col">
      <div className="mb-4 px-2 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight">推广数据看板</h1>
          <p className="text-xs text-muted-foreground mt-1">多平台 BI</p>
        </div>
        {onClose && (
          <Button variant="ghost" size="icon" onClick={onClose} className="md:hidden">
            <X className="h-4 w-4" />
          </Button>
        )}
      </div>

      <PlatformTabs platform={platform} onChange={onPlatformChange} />

      <nav className="space-y-1">
        {visibleItems.map((item) => (
          <NavLink
            key={item.to}
            to={
              item.id === "ai_wecom"
                ? { pathname: item.to, search: `?platform=${platform}` }
                : item.to
            }
            end
            onClick={onClose}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              }`
            }
          >
            <item.icon className="h-4 w-4" />
            <span className="flex-1">{item.label}</span>
            {(item.id === "costs" || item.id.endsWith("_costs")) && costBadge != null && (
              <span className="ml-auto flex items-center gap-1">
                {costBadge.pending > 0 && (
                  <span className="inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-destructive px-1.5 text-[10px] font-bold text-destructive-foreground">
                    {costBadge.pending > 99 ? "99+" : costBadge.pending}
                  </span>
                )}
                {costBadge.unmapped > 0 && (
                  <span className="inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-green-500 px-1.5 text-[10px] font-bold text-white">
                    {costBadge.unmapped > 99 ? "99+" : costBadge.unmapped}
                  </span>
                )}
              </span>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="mt-auto pt-4 border-t">
        <UserMenu
          user={user}
          showMaster={showMaster}
          onClose={onClose}
          updating={updating}
          updateMsg={updateMsg}
          onUpdate={handleUpdate}
        />
      </div>

      {updateProgress.length > 0 && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-lg border bg-card p-6 shadow-lg">
            <h3 className="mb-4 text-lg font-semibold">系统更新</h3>
            <div className="max-h-80 space-y-2 overflow-auto">
              {updateProgress.map((step, idx) => (
                <div key={idx} className="flex items-start gap-2 text-sm">
                  {step.returncode === 0 ? (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-green-500" />
                  ) : (
                    <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                  )}
                  <span className="break-all">{step.cmd}</span>
                </div>
              ))}
            </div>
            {updateMsg && (
              <div className="mt-4 text-sm text-muted-foreground">{updateMsg}</div>
            )}
          </div>
        </div>
      )}
    </aside>
  )
}

function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const [platform, setPlatform] = useState<Platform>(detectPlatform(location.pathname, location.search))

  useEffect(() => {
    setPlatform(detectPlatform(location.pathname, location.search))
  }, [location.pathname, location.search])

  // 页面级权限守卫：无权限则重定向到第一个有权限的页面
  useEffect(() => {
    const pageId = getPageIdByPath(location.pathname)
    if (pageId && !canAccessPage(pageId)) {
      navigate(firstAllowedFallback(), { replace: true })
    }
  }, [location.pathname])

  const handlePlatformChange = (p: Platform) => {
    const tab = platformTabs.find((t) => t.key === p)
    if (tab) {
      setPlatform(p)
      navigate(tab.defaultTo)
      setSidebarOpen(false)
    }
  }

  return (
    <div className="flex min-h-screen bg-background">
      <div className="hidden md:block">
        <Sidebar platform={platform} onPlatformChange={handlePlatformChange} />
      </div>
      {sidebarOpen && (
        <div className="fixed inset-0 z-50 flex md:hidden">
          <div className="w-64">
            <Sidebar
              platform={platform}
              onPlatformChange={handlePlatformChange}
              onClose={() => setSidebarOpen(false)}
            />
          </div>
          <div className="flex-1 bg-black/50" onClick={() => setSidebarOpen(false)} />
        </div>
      )}
      <main className="flex-1 flex flex-col min-h-screen overflow-hidden">
        <header className="md:hidden border-b p-4 flex items-center justify-between bg-card">
          <span className="font-bold">{platformTabs.find((t) => t.key === platform)?.label}</span>
          <Button variant="ghost" size="icon" onClick={() => setSidebarOpen(true)}>
            <Menu className="h-5 w-5" />
          </Button>
        </header>
        <div className="flex-1 p-4 md:p-6 overflow-auto">
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/stores" element={<StoresPage />} />
            <Route path="/import" element={<ImportPage />} />
            <Route path="/metrics" element={<MetricsPage />} />
            <Route path="/orders" element={<OrdersPage />} />
            <Route path="/costs" element={<CostsPage />} />
            <Route path="/knowledge" element={<KnowledgeAssistantPage />} />
            <Route path="/ai-wecom" element={<AiWecomPage />} />
            <Route path="/users" element={<UsersPage />} />
            <Route path="/douyin" element={<DouyinDashboardPage />} />
            <Route path="/douyin/import" element={<DouyinImportPage />} />
            <Route path="/douyin/metrics" element={<DouyinMetricsPage />} />
            <Route path="/douyin/orders" element={<DouyinOrdersPage />} />
            <Route path="/douyin/costs" element={<DouyinCostsPage />} />
            <Route path="/tmall" element={<TmallDashboardPage />} />
            <Route path="/tmall/import" element={<TmallImportPage />} />
            <Route path="/tmall/metrics" element={<TmallMetricsPage />} />
            <Route path="/tmall/orders" element={<TmallOrdersPage />} />
            <Route path="/tmall/costs" element={<TmallCostsPage />} />
            <Route path="/wechat" element={<WechatDashboardPage />} />
            <Route path="/wechat/import" element={<WechatImportPage />} />
            <Route path="/wechat/metrics" element={<WechatMetricsPage />} />
            <Route path="/wechat/orders" element={<WechatOrdersPage />} />
            <Route path="/wechat/costs" element={<WechatCostsPage />} />
            <Route path="/change-password" element={<ChangePasswordPage />} />
          </Routes>
        </div>
      </main>
    </div>
  )
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/*"
          element={
            <AuthGuard>
              <Layout />
            </AuthGuard>
          }
        />
      </Routes>
    </BrowserRouter>
  )
}

export default App
