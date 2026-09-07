import { useMemo, useState, type ComponentType } from "react"
import {
  Activity,
  ArrowDownToLine,
  ArrowUpFromLine,
  Boxes,
  ClipboardList,
  FileUp,
  LayoutDashboard,
  Link2,
  ListOrdered,
  PackagePlus,
  ReceiptText,
  RotateCcw,
  ScrollText,
  Store,
  Tags,
  Users,
  Warehouse,
  AlertTriangle,
  Layers,
  BookOpenText,
  Undo2,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { canAccessPage, isMaster } from "@/api/auth"
import { Link } from "react-router-dom"
import { OverviewModule } from "./modules/overview"
import { BalancesModule } from "./modules/balances"
import { LedgerSummaryModule } from "./modules/ledger-summary"
import { LedgerModule } from "./modules/ledger"
import { BatchesModule } from "./modules/batches"
import { PurchasesModule } from "./modules/purchases"
import { InboundModule } from "./modules/inbound"
import { OutboundModule } from "./modules/outbound"
import { OrderDeductionsModule } from "./modules/order-deductions"
import { ReturnsModule } from "./modules/returns"
import { ExceptionsModule } from "./modules/exceptions"
import { StoreOutboundModule } from "./modules/store-outbound"
import { ItemCostsModule } from "./modules/item-costs"
import { BundleCostsModule } from "./modules/bundle-costs"
import { UnmappedModule } from "./modules/unmapped"
import { ItemsModule } from "./modules/items"
import { BundlesModule } from "./modules/bundles"
import { ListingsModule } from "./modules/listings"
import { StoresModule } from "./modules/stores"
import { UsersModule } from "./modules/users"
import { ImportsModule } from "./modules/imports"

type ModuleDef = { id: string; label: string; icon: any; component: ComponentType }
type GroupDef = { group: string; items: ModuleDef[] }

const NAV: GroupDef[] = [
  {
    group: "总览",
    items: [{ id: "overview", label: "运营总览", icon: LayoutDashboard, component: OverviewModule }],
  },
  {
    group: "库存报表",
    items: [
      { id: "balances", label: "库存余额", icon: Warehouse, component: BalancesModule },
      { id: "ledger-summary", label: "台账汇总", icon: BookOpenText, component: LedgerSummaryModule },
      { id: "ledger", label: "库存流水", icon: ScrollText, component: LedgerModule },
      { id: "batches", label: "批次台账", icon: Layers, component: BatchesModule },
    ],
  },
  {
    group: "入库",
    items: [
      { id: "purchases", label: "采购入库单", icon: PackagePlus, component: PurchasesModule },
      { id: "inbound", label: "入库流水", icon: ArrowDownToLine, component: InboundModule },
    ],
  },
  {
    group: "出库",
    items: [
      { id: "order-deductions", label: "订单扣减", icon: ListOrdered, component: OrderDeductionsModule },
      { id: "store-outbound", label: "店铺出库", icon: Store, component: StoreOutboundModule },
      { id: "outbound", label: "出库流水", icon: ArrowUpFromLine, component: OutboundModule },
      { id: "returns", label: "退货检验", icon: RotateCcw, component: ReturnsModule },
      { id: "exceptions", label: "异常队列", icon: AlertTriangle, component: ExceptionsModule },
    ],
  },
  {
    group: "成本",
    items: [
      { id: "item-costs", label: "单品成本", icon: Tags, component: ItemCostsModule },
      { id: "bundle-costs", label: "组合成本", icon: ReceiptText, component: BundleCostsModule },
      { id: "unmapped", label: "未映射治理", icon: Undo2, component: UnmappedModule },
    ],
  },
  {
    group: "基础资料",
    items: [
      { id: "items", label: "单品档案", icon: Boxes, component: ItemsModule },
      { id: "bundles", label: "组合 BOM", icon: ClipboardList, component: BundlesModule },
      { id: "listings", label: "链接映射", icon: Link2, component: ListingsModule },
      { id: "stores", label: "店铺仓库", icon: Store, component: StoresModule },
      { id: "users", label: "账号权限", icon: Users, component: UsersModule },
    ],
  },
  {
    group: "数据导入",
    items: [{ id: "imports", label: "导入中心", icon: FileUp, component: ImportsModule }],
  },
]

export function V2WorkbenchPage() {
  const [active, setActive] = useState("overview")
  const current = useMemo(() => NAV.flatMap((g) => g.items).find((m) => m.id === active) ?? NAV[0].items[0], [active])
  const Current = current.component

  // 页面级权限：v2_supply（主账号默认全权限）
  if (!isMaster() && !canAccessPage("v2_supply")) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="text-center">
          <p className="text-sm text-muted-foreground">没有供应链中心访问权限，请联系主账号开通</p>
          <Link to="/" className="mt-3 inline-block text-sm text-primary underline">返回经营看板</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r bg-card">
        <div className="flex items-center gap-2.5 border-b px-4 py-4">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-primary text-primary-foreground">
            <Activity className="h-4.5 w-4.5" />
          </span>
          <div>
            <div className="text-sm font-semibold tracking-tight">供应链报表中心</div>
            <div className="text-[11px] text-muted-foreground">库存与成本 · V2</div>
          </div>
        </div>
        <nav className="flex-1 space-y-4 overflow-y-auto px-2.5 py-3">
          {NAV.map((group) => (
            <div key={group.group}>
              <div className="px-2 pb-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70">
                {group.group}
              </div>
              <div className="space-y-0.5">
                {group.items.map((item) => {
                  const Icon = item.icon
                  const isActive = item.id === active
                  return (
                    <button
                      key={item.id}
                      onClick={() => setActive(item.id)}
                      className={cn(
                        "relative flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] font-medium transition-colors",
                        isActive ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground"
                      )}
                    >
                      {isActive && <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-primary" />}
                      <Icon className="h-4 w-4 shrink-0" />
                      {item.label}
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </nav>
        <div className="space-y-2 border-t px-4 py-3">
          <Link to="/" className="block text-[12px] text-muted-foreground transition-colors hover:text-foreground">
            ← 返回经营看板
          </Link>
          <span className="inline-flex items-center gap-2 rounded-full border bg-background px-2.5 py-1 text-[10px] tracking-wider text-muted-foreground">
            <span className="h-1.5 w-1.5 rounded-full bg-success" />
            LIVE TEST ENV
          </span>
        </div>
      </aside>
      <main key={active} className="page-enter min-w-0 flex-1 p-4 md:p-6">
        <Current />
      </main>
    </div>
  )
}
