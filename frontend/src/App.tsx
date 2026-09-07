import { lazy, Suspense, useEffect, useState } from "react"
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
  ChevronUp,
  Sun,
  Moon,
  XCircle,
  CheckCircle2,
  BookOpenCheck,
  ClipboardList,
  Package,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { cn } from "@/lib/utils"
import { useTheme } from "@/components/theme-context"
import { AuthGuard } from "@/components/auth-guard"
import { canAccessPage, getCurrentUser, isMaster, logout } from "@/api/auth"
import {
  updateFromGithub,
  getGlobalUnmappedCount,
  getDouyinUnmappedCount,
  getTmallUnmappedCount,
  getWechatUnmappedCount,
} from "@/api/client"

// 页面按路由懒加载，避免首次打开总览时把所有平台页面和图表组件一次性打进主包。
const LoginPage = lazy(async () => ({ default: (await import("@/pages/login")).LoginPage }))
const DashboardPage = lazy(async () => ({ default: (await import("@/pages/dashboard")).DashboardPage }))
const StoresPage = lazy(async () => ({ default: (await import("@/pages/stores")).StoresPage }))
const ImportPage = lazy(async () => ({ default: (await import("@/pages/import")).ImportPage }))
const MetricsPage = lazy(async () => ({ default: (await import("@/pages/metrics")).MetricsPage }))
const OrdersPage = lazy(async () => ({ default: (await import("@/pages/orders")).OrdersPage }))
const CostsPage = lazy(async () => ({ default: (await import("@/pages/costs")).CostsPage }))
const AiWecomPage = lazy(async () => ({ default: (await import("@/pages/ai-wecom")).AiWecomPage }))
const UsersPage = lazy(async () => ({ default: (await import("@/pages/users")).UsersPage }))
const DouyinDashboardPage = lazy(async () => ({ default: (await import("@/pages/douyin-dashboard")).DouyinDashboardPage }))
const DouyinImportPage = lazy(async () => ({ default: (await import("@/pages/douyin-import")).DouyinImportPage }))
const DouyinMetricsPage = lazy(async () => ({ default: (await import("@/pages/douyin-metrics")).DouyinMetricsPage }))
const DouyinOrdersPage = lazy(async () => ({ default: (await import("@/pages/douyin-orders")).DouyinOrdersPage }))
const DouyinCostsPage = lazy(async () => ({ default: (await import("@/pages/douyin-costs")).DouyinCostsPage }))
const TmallDashboardPage = lazy(async () => ({ default: (await import("@/pages/tmall-dashboard")).TmallDashboardPage }))
const TmallImportPage = lazy(async () => ({ default: (await import("@/pages/tmall-import")).TmallImportPage }))
const TmallMetricsPage = lazy(async () => ({ default: (await import("@/pages/tmall-metrics")).TmallMetricsPage }))
const TmallOrdersPage = lazy(async () => ({ default: (await import("@/pages/tmall-orders")).TmallOrdersPage }))
const TmallCostsPage = lazy(async () => ({ default: (await import("@/pages/tmall-costs")).TmallCostsPage }))
const WechatDashboardPage = lazy(async () => ({ default: (await import("@/pages/wechat-dashboard")).WechatDashboardPage }))
const WechatImportPage = lazy(async () => ({ default: (await import("@/pages/wechat-import")).WechatImportPage }))
const WechatMetricsPage = lazy(async () => ({ default: (await import("@/pages/wechat-metrics")).WechatMetricsPage }))
const WechatOrdersPage = lazy(async () => ({ default: (await import("@/pages/wechat-orders")).WechatOrdersPage }))
const WechatCostsPage = lazy(async () => ({ default: (await import("@/pages/wechat-costs")).WechatCostsPage }))
const ChangePasswordPage = lazy(async () => ({ default: (await import("@/pages/change-password")).ChangePasswordPage }))
const KnowledgeAssistantPage = lazy(async () => ({ default: (await import("@/pages/knowledge-assistant")).KnowledgeAssistantPage }))
const OperationsDailyPage = lazy(async () => ({ default: (await import("@/pages/operations-daily")).OperationsDailyPage }))
const V2WorkbenchPage = lazy(async () => ({ default: (await import("@/pages/v2-workbench")).V2WorkbenchPage }))

type Platform = "pdd" | "douyin" | "tmall" | "wechat"

interface NavItem {
  id: string
  to: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  masterOnly?: boolean
}

const pddNavItems: NavItem[] = [
  { id: "operations_daily", to: "/operations-daily", label: "运营日报", icon: ClipboardList, masterOnly: true },
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
  { path: "/operations-daily", id: "operations_daily" },
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
    <div className="mb-3 grid grid-cols-4 gap-1 rounded-lg bg-muted p-1">
      {platformTabs.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onChange(tab.key)}
          className={cn(
            "rounded-md px-1 py-1.5 text-xs font-medium transition-colors",
            platform === tab.key
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}

function PageLoading() {
  return (
    <div className="space-y-4 p-2">
      <Skeleton className="h-8 w-48" />
      <div className="grid gap-4 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <Skeleton className="h-64" />
    </div>
  )
}

function UserMenu({
  user,
  showMaster,
  updating,
  updateMsg,
  onUpdate,
}: {
  user: ReturnType<typeof getCurrentUser>
  showMaster: boolean
  updating: boolean
  updateMsg: string
  onUpdate: () => void
}) {
  const { theme, setTheme } = useTheme()
  const navigate = useNavigate()

  return (
    <div>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left transition-colors hover:bg-muted">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary/10 text-sm font-semibold text-primary">
              {(user?.username || "?").slice(0, 1).toUpperCase()}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">{user?.username || "未知用户"}</span>
              <span className="block text-xs text-muted-foreground">
                {user?.role === "master" ? "主账号" : "子账号"}
              </span>
            </span>
            <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="top" align="start" className="w-48">
          {(showMaster || canAccessPage("users")) && (
            <DropdownMenuItem onSelect={() => navigate("/users")}>
              <Users />
              用户管理
            </DropdownMenuItem>
          )}
          {(showMaster || canAccessPage("stores")) && (
            <DropdownMenuItem onSelect={() => navigate("/stores")}>
              <Store />
              店铺
            </DropdownMenuItem>
          )}
          {showMaster && (
            <DropdownMenuItem disabled={updating} onSelect={() => onUpdate()}>
              <RefreshCw className={updating ? "animate-spin" : ""} />
              {updating ? "更新中" : "系统更新"}
            </DropdownMenuItem>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => navigate("/change-password")}>
            <Settings />
            修改密码
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setTheme(theme === "dark" ? "light" : "dark")}>
            {theme === "dark" ? <Sun /> : <Moon />}
            切换主题
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => logout()}>
            <LogOut />
            退出登录
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {updateMsg && <div className="px-2 pt-2 text-xs text-destructive">{updateMsg}</div>}
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
  const visibleItems = navItems.filter((item) => (
    item.masterOnly ? showMaster : showMaster || canAccessPage(item.id)
  ))

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
    <aside className="w-60 shrink-0 border-r bg-card min-h-screen p-3 flex flex-col">
      <div className="mb-4 flex items-center justify-between px-1 pt-1">
        <div className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-primary text-primary-foreground">
            <BarChart3 className="h-4 w-4" />
          </span>
          <div>
            <h1 className="text-[15px] font-semibold tracking-tight">推广数据看板</h1>
            <p className="text-[11px] text-muted-foreground">多平台 BI</p>
          </div>
        </div>
        {onClose && (
          <Button variant="ghost" size="icon" onClick={onClose} className="md:hidden">
            <X className="h-4 w-4" />
          </Button>
        )}
      </div>

      <PlatformTabs platform={platform} onChange={onPlatformChange} />

      <nav className="space-y-0.5">
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
              cn(
                "relative flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] font-medium transition-colors",
                isActive
                  ? "bg-accent text-accent-foreground shadow-[inset_2.5px_0_0_hsl(var(--primary))]"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )
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
                  <span className="inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-success px-1.5 text-[10px] font-bold text-success-foreground">
                    {costBadge.unmapped > 99 ? "99+" : costBadge.unmapped}
                  </span>
                )}
              </span>
            )}
          </NavLink>
        ))}
      </nav>
      {(showMaster || canAccessPage("v2_supply")) && (
        <div className="mt-3 border-t pt-3">
          <NavLink
            to="/v2"
            onClick={onClose}
            className="relative flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <Package className="h-4 w-4" />
            <span className="flex-1">供应链中心</span>
          </NavLink>
        </div>
      )}
      <div className="mt-auto pt-3 border-t">
        <UserMenu
          user={user}
          showMaster={showMaster}
          updating={updating}
          updateMsg={updateMsg}
          onUpdate={handleUpdate}
        />
      </div>

      <Dialog open={updateProgress.length > 0} onOpenChange={() => {}}>
        <DialogContent className="max-w-md" onPointerDownOutside={(e) => e.preventDefault()}>
          <DialogHeader>
            <DialogTitle>系统更新</DialogTitle>
          </DialogHeader>
          <div className="max-h-80 space-y-2 overflow-auto">
            {updateProgress.map((step, idx) => (
              <div key={idx} className="flex items-start gap-2 text-sm">
                {step.returncode === 0 ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
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
        </DialogContent>
      </Dialog>
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
    if (pageId && ((pageId === "operations_daily" && !isMaster()) || !canAccessPage(pageId))) {
      navigate(firstAllowedFallback(), { replace: true })
    }
  }, [location.pathname, navigate])

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
          <div className="w-60">
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
        <div className="flex-1 overflow-auto">
          <div key={location.pathname} className="page-enter mx-auto w-full max-w-[1400px] p-4 md:p-6">
            <Suspense fallback={<PageLoading />}>
              <Routes>
            <Route path="/operations-daily" element={<OperationsDailyPage />} />
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
            </Suspense>
          </div>
        </div>
      </main>
    </div>
  )
}

function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<PageLoading />}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/v2"
            element={
              <AuthGuard>
                <V2WorkbenchPage />
              </AuthGuard>
            }
          />
          <Route
            path="/*"
            element={
              <AuthGuard>
                <Layout />
              </AuthGuard>
            }
          />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}

export default App
