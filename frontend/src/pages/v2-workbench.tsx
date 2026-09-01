import { useEffect, useMemo, useState } from "react"
import { Activity, ArrowUpRight, Boxes, ClipboardList, Database, FileUp, PackagePlus, RefreshCw, ShoppingCart, Sparkles, Warehouse, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

const API = import.meta.env.VITE_V2_API_URL || "http://23.148.212.141:18000"
const TOKEN = import.meta.env.VITE_V2_TEST_TOKEN || "c25a90988c6b3d6da097e813256b2eafad6c8f6f0652ef02"
const headers = { "Content-Type": "application/json", "X-V2-Test-Token": TOKEN }

async function request(path: string, options: RequestInit = {}) {
  const response = await fetch(`${API}${path}`, { ...options, headers: { ...headers, ...(options.headers || {}) } })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.detail || "请求失败")
  return body
}

type Tab = "overview" | "stores" | "imports" | "items" | "bundles" | "purchases" | "inventory" | "orders" | "returns" | "users"

export function V2WorkbenchPage() {
  const [tab, setTab] = useState<Tab>("overview")
  const [data, setData] = useState<any>({})
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("")

  const reload = async () => {
    setBusy(true)
    try {
      const keys = ["config", "stores", "imports", "items", "bundles", "balances", "batches", "purchases", "orders", "exceptions", "returns", "ledger", "users"] as const
      const paths = [
        "/api/v2/config", "/api/v2/stores", "/api/v2/imports/batches", "/api/v2/items", "/api/v2/bundles", "/api/v2/inventory/balances",
        "/api/v2/inventory/batches", "/api/v2/purchases", "/api/v2/orders", "/api/v2/exceptions",
        "/api/v2/returns", "/api/v2/inventory/ledger", "/api/v2/users",
      ]
      const results = await Promise.allSettled(paths.map((path) => request(path)))
      const nextData: Record<string, any> = {}
      const failed: string[] = []
      results.forEach((result, index) => {
        if (result.status === "fulfilled") nextData[keys[index]] = result.value
        else failed.push(keys[index])
      })
      setData((current: any) => ({ ...current, ...nextData }))
      if (failed.length) setMessage(`部分数据加载失败：${failed.join("、")}；其它模块仍可正常使用`)
    } catch (error: any) { setMessage(error.message) } finally { setBusy(false) }
  }
  useEffect(() => { void reload() }, [])

  const runDemo = async () => { setBusy(true); try { const result = await request("/api/v2/demo/run", { method: "POST" }); setMessage(`演练完成：${result.processed_order_sequence?.join(" → ")}，异常订单 ${result.exception_count} 条`); } catch (error: any) { setMessage(error.message) } finally { setBusy(false) } }
  const title = useMemo(() => ({ overview: "运营与库存总览", stores: "店铺与平台", imports: "数据导入批次", items: "库存单品", bundles: "组合 BOM", purchases: "采购入库", inventory: "库存台账", orders: "订单扣减", returns: "退货检验", users: "账号权限" }[tab]), [tab])

  return <div className="v2-shell min-h-screen text-slate-100 p-4 md:p-8">
    <div className="v2-orbit v2-orbit-a" /><div className="v2-orbit v2-orbit-b" />
    <div className="relative mx-auto max-w-[1440px] space-y-7">
      <header className="v2-topbar flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-4"><div className="v2-mark"><Activity className="h-5 w-5" /></div><div><div className="v2-kicker">OPERATIONS CONTROL / V2</div><h1 className="mt-1 text-3xl font-semibold tracking-tight">库存与成本工作台</h1><p className="mt-1 text-sm text-slate-400">批次 FIFO · 永续加权平均 · 订单级成本快照</p></div></div>
        <div className="flex items-center gap-2"><div className="v2-live"><span /> LIVE TEST ENV</div><Button variant="outline" className="v2-button-ghost" onClick={() => void reload()} disabled={busy}><RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />刷新</Button><Button className="v2-button-primary" onClick={() => void runDemo()} disabled={busy}><Sparkles className="h-4 w-4" />运行演练<ArrowUpRight className="h-4 w-4" /></Button></div>
      </header>
      {message && <div className="v2-toast"><div className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-cyan-300" />{message}</div><button onClick={() => setMessage("")} aria-label="关闭提示"><X className="h-4 w-4" /></button></div>}
      <nav className="v2-nav">{([ ["overview","总览",Database],["stores","店铺平台",Activity],["imports","数据导入",FileUp],["items","单品",Boxes],["bundles","组合 BOM",ClipboardList],["purchases","采购入库",PackagePlus],["inventory","库存台账",Warehouse],["orders","订单扣减",ShoppingCart],["returns","退货检验",RefreshCw] ] as const).map(([key,label,Icon]) => <button key={key} onClick={() => setTab(key)} className={`v2-nav-item ${tab===key?"is-active":""}`}><Icon className="h-4 w-4" />{label}</button>)}</nav>
      <div className="flex flex-wrap items-end justify-between gap-3"><div><div className="v2-section-index">{String((["overview","stores","imports","items","bundles","purchases","inventory","orders","returns","users"] as const).indexOf(tab)+1).padStart(2,"0")}</div><h2 className="mt-1 text-xl font-medium">{title}</h2><p className="mt-1 text-sm text-slate-400">当前测试环境：23 张表，三仓共享库存</p></div><span className="v2-status"><span />数据库在线</span></div>
      {tab === "overview" && <Overview data={data} />}
      {tab === "stores" && <Stores data={data} onDone={reload} />}
      {tab === "imports" && <FileImports data={data} onDone={reload} />}
      {tab === "items" && <Items data={data} onDone={reload} />}
      {tab === "bundles" && <Bundles data={data} onDone={reload} />}
      {tab === "purchases" && <Purchases data={data} onDone={reload} />}
      {tab === "inventory" && <Inventory data={data} />}
      {tab === "orders" && <Orders data={data} onDone={reload} />}
      {tab === "returns" && <Returns data={data} onDone={reload} />}
      {tab === "users" && <Users data={data} onDone={reload} />}
    </div>
  </div>
}

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) { return <Card className="v2-stat"><CardContent className="p-5"><div className="flex items-center justify-between"><div className="text-sm text-slate-400">{label}</div><ArrowUpRight className="h-4 w-4 text-cyan-300/70" /></div><div className="v2-stat-value mt-2 text-3xl font-semibold text-cyan-100">{value}</div>{hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}<div className="v2-scanline" /></CardContent></Card> }
function Overview({ data }: { data: any }) { const cfg=data.config||{}; const balances=data.balances||[]; const totalQty=balances.reduce((n:number,x:any)=>n+Number(x.sellable_qty||0),0); const totalValue=balances.reduce((n:number,x:any)=>n+Number(x.total_average_cost||0),0); return <div className="space-y-6"><div className="grid gap-4 md:grid-cols-4"><Stat label="仓库" value={cfg.warehouses?.length||0} hint="昆山 / 辉煌 / 外高桥"/><Stat label="库存单品" value={data.items?.length||0}/><Stat label="组合商品" value={data.bundles?.length||0}/><Stat label="可售库存" value={totalQty.toFixed(2)} hint={`库存金额 ¥${totalValue.toFixed(2)}`}/></div><div className="grid gap-6 lg:grid-cols-2"><Card className="border-slate-800 bg-slate-900/80"><CardHeader><CardTitle>库存启用设置</CardTitle></CardHeader><CardContent><div className="text-sm text-slate-400">启用日</div><div className="mt-2 text-lg">{cfg.inventory?.enabled_from || "尚未设置"}</div><div className="mt-4 text-sm text-slate-500">上线后选择启用日；启用后订单按支付时间升序扣减库存。</div></CardContent></Card><Card className="border-slate-800 bg-slate-900/80"><CardHeader><CardTitle>异常队列</CardTitle></CardHeader><CardContent><div className="text-3xl font-semibold text-amber-300">{data.exceptions?.length||0}</div><div className="mt-2 text-sm text-slate-400">库存不足的订单正常入账，不产生负库存，等待补货或人工处理。</div></CardContent></Card></div></div> }

function Stores({ data, onDone }: { data: any; onDone: () => Promise<void> }) {
  const [form, setForm] = useState({ platform: "pdd", store_name: "", display_name: "", warehouse_code: "KUNSHAN", effective_from: new Date().toISOString().slice(0, 10) })
  const submit = async () => { try { await request("/api/v2/stores", { method: "POST", body: JSON.stringify({ platform: form.platform, store_name: form.store_name, display_name: form.display_name || form.store_name }) }); await request("/api/v2/stores/warehouse", { method: "POST", body: JSON.stringify(form) }); setForm({ ...form, store_name: "", display_name: "" }); await onDone() } catch (e: any) { alert(e.message) } }
  return <div className="grid gap-6 lg:grid-cols-[360px_1fr]"><Card className="border-slate-800 bg-slate-900/80"><CardHeader><CardTitle>新增店铺与共享仓库</CardTitle></CardHeader><CardContent className="space-y-3">{([ ["platform","平台（pdd/douyin/tmall/wechat）"], ["store_name","店铺名称"], ["display_name","显示名称"], ["warehouse_code","默认共享仓库"], ["effective_from","配置生效日"] ] as const).map(([key,label]) => <label key={key} className="block text-sm text-slate-400">{label}<Input type={key === "effective_from" ? "date" : "text"} className="mt-1 border-slate-700 bg-slate-950 text-slate-100" value={form[key]} onChange={e => setForm({ ...form, [key]: e.target.value })} /></label>)}<Button className="w-full" onClick={() => void submit()}>保存店铺配置</Button></CardContent></Card><Table columns={["平台","店铺","显示名称","仓库","生效日","状态"]} rows={data.stores || []} /></div>
}

export function Imports({ data, onDone }: { data: any; onDone: () => Promise<void> }) {
  const [form, setForm] = useState({ platform: "pdd", store_name: "测试店", data_type: "orders", metric_date: new Date().toISOString().slice(0, 10), source_filename: "", rows: '[{\n  "order_id": "ORDER-001",\n  "product_id": "PID-001",\n  "quantity": 1,\n  "payment_time": "2026-09-01T10:00:00+08:00",\n  "order_status": "支付成功"\n}]' })
  const [preview, setPreview] = useState<any>(null)
  const parse = () => { try { const rows = JSON.parse(form.rows); if (!Array.isArray(rows)) throw new Error("rows 必须是数组"); return rows } catch (e: any) { throw new Error(`JSON 格式错误：${e.message}`) } }
  const check = async () => { try { const result = await request("/api/v2/imports/preview", { method: "POST", body: JSON.stringify({ ...form, rows: parse() }) }); setPreview(result) } catch (e: any) { alert(e.message) } }
  const submit = async () => { try { const result = await request("/api/v2/imports", { method: "POST", body: JSON.stringify({ ...form, rows: parse() }) }); setPreview(result); await onDone() } catch (e: any) { alert(e.message) } }
  return <div className="space-y-6"><Card className="border-slate-800 bg-slate-900/80"><CardHeader><CardTitle>订单 / 推广原始数据导入</CardTitle></CardHeader><CardContent className="grid gap-3 lg:grid-cols-4">{([['platform','平台'],['store_name','店铺'],['data_type','数据类型'],['metric_date','数据日期'],['source_filename','源文件名']] as const).map(([key,label])=><label key={key} className="text-sm text-slate-400">{label}<Input type={key==='metric_date'?'date':'text'} className="mt-1 border-slate-700 bg-slate-950 text-slate-100" value={form[key]} onChange={e=>setForm({...form,[key]:e.target.value})}/></label>)}<label className="text-sm text-slate-400 lg:col-span-4">行数据 JSON（先预览校验，再正式导入）<textarea className="mt-1 min-h-56 w-full rounded-md border border-slate-700 bg-slate-950 p-3 font-mono text-xs text-slate-100" value={form.rows} onChange={e=>setForm({...form,rows:e.target.value})}/></label><div className="flex gap-2 lg:col-span-4"><Button variant="outline" onClick={()=>void check()}>预览校验</Button><Button onClick={()=>void submit()}>正式导入</Button></div>{preview&&<div className="rounded-md border border-cyan-900 bg-cyan-950/30 p-3 text-sm text-cyan-100 lg:col-span-4">{JSON.stringify(preview)}</div>}</CardContent></Card><Card className="border-slate-800 bg-slate-900/80"><CardHeader><CardTitle>最近导入批次</CardTitle></CardHeader><CardContent><Table columns={["ID","平台","店铺","类型","日期","状态","行数","错误","创建时间"]} rows={data.imports||[]} /></CardContent></Card></div>
}

function FileImports({ data, onDone }: { data: any; onDone: () => Promise<void> }) {
  const [form, setForm] = useState({ platform: "pdd", store_name: "测试店", data_type: "orders", metric_date: new Date().toISOString().slice(0, 10) })
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<any>(null)
  const upload = async (mode: "preview" | "import") => {
    if (!file) { alert("请先选择 CSV、XLS 或 XLSX 文件"); return }
    setBusy(true)
    try {
      const body = new FormData()
      body.append("platform", form.platform); body.append("store_name", form.store_name); body.append("data_type", form.data_type); body.append("metric_date", form.metric_date); body.append("mode", mode); body.append("file", file)
      const response = await fetch(`${API}/api/v2/imports/file`, { method: "POST", headers: { "X-V2-Test-Token": TOKEN }, body })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.detail || "文件导入失败")
      setResult(payload)
      if (mode === "import") await onDone()
    } catch (error: any) { alert(error.message) } finally { setBusy(false) }
  }
  return <div className="space-y-6">
    <Card className="border-slate-800 bg-slate-900/80"><CardHeader><CardTitle>真实文件导入</CardTitle></CardHeader><CardContent className="grid gap-4 lg:grid-cols-4">
      <label className="text-sm text-slate-400">平台<Input className="mt-1 border-slate-700 bg-slate-950 text-slate-100" value={form.platform} onChange={e=>setForm({...form,platform:e.target.value})}/></label>
      <label className="text-sm text-slate-400">店铺<Input className="mt-1 border-slate-700 bg-slate-950 text-slate-100" value={form.store_name} onChange={e=>setForm({...form,store_name:e.target.value})}/></label>
      <label className="text-sm text-slate-400">数据类型<select className="mt-1 h-10 w-full rounded-md border border-slate-700 bg-slate-950 px-3 text-slate-100" value={form.data_type} onChange={e=>setForm({...form,data_type:e.target.value})}><option value="orders">订单</option><option value="promotions">推广</option></select></label>
      <label className="text-sm text-slate-400">数据日期<Input type="date" className="mt-1 border-slate-700 bg-slate-950 text-slate-100" value={form.metric_date} onChange={e=>setForm({...form,metric_date:e.target.value})}/></label>
      <label className="text-sm text-slate-400 lg:col-span-4">选择文件<Input type="file" accept=".csv,.xls,.xlsx" className="mt-1 border-slate-700 bg-slate-950 text-slate-100" onChange={e=>setFile(e.target.files?.[0] || null)}/></label>
      <div className="flex flex-wrap items-center gap-2 lg:col-span-4"><Button variant="outline" disabled={busy} onClick={()=>void upload("preview")}>文件预览校验</Button><Button disabled={busy} onClick={()=>void upload("import")}>{busy?"处理中…":"正式导入"}</Button><span className="text-xs text-slate-500">自动识别编码和字段别名；历史订单不会扣库存</span></div>
      {result&&<pre className="max-h-72 overflow-auto rounded-md border border-cyan-900 bg-cyan-950/30 p-3 text-xs text-cyan-100 lg:col-span-4">{JSON.stringify(result,null,2)}</pre>}
    </CardContent></Card>
    <Card className="border-slate-800 bg-slate-900/80"><CardHeader><CardTitle>最近导入批次</CardTitle></CardHeader><CardContent><Table columns={["ID","平台","店铺","类型","日期","状态","行数","错误","创建时间"]} rows={data.imports||[]} /></CardContent></Card>
  </div>
}

function Table({ columns, rows }: { columns: string[]; rows: any[] }) { return <div className="overflow-auto rounded-lg border border-slate-800"><table className="w-full text-left text-sm"><thead className="bg-slate-900 text-slate-400"><tr>{columns.map(c=><th key={c} className="whitespace-nowrap px-3 py-3 font-medium">{c}</th>)}</tr></thead><tbody>{rows.length===0?<tr><td colSpan={columns.length} className="px-3 py-10 text-center text-slate-500">暂无数据</td></tr>:rows.map((row,i)=><tr key={i} className="border-t border-slate-800 hover:bg-slate-900/70">{Object.values(row).slice(0,columns.length).map((v:any,j)=><td key={j} className="whitespace-nowrap px-3 py-3">{typeof v==='object'?JSON.stringify(v):String(v??'—')}</td>)}</tr>)}</tbody></table></div> }

function Items({ data, onDone }: { data: any; onDone: () => Promise<void> }) { const [form,setForm]=useState({code:"",name:"",base_unit:"件",category:""}); const submit=async()=>{try{await request("/api/v2/items",{method:"POST",body:JSON.stringify(form)});setForm({code:"",name:"",base_unit:"件",category:""});await onDone()}catch(e:any){alert(e.message)}}; return <div className="grid gap-6 lg:grid-cols-[340px_1fr]"><Card className="border-slate-800 bg-slate-900/80"><CardHeader><CardTitle>新增库存单品</CardTitle></CardHeader><CardContent className="space-y-3">{([['code','单品编码'],['name','单品名称'],['base_unit','基础单位'],['category','分类']] as const).map(([key,label])=><label key={key} className="block text-sm text-slate-400">{label}<Input className="mt-1 border-slate-700 bg-slate-950 text-slate-100" value={form[key]} onChange={e=>setForm({...form,[key]:e.target.value})}/></label>)}<Button className="w-full" onClick={() => void submit()}>保存单品</Button></CardContent></Card><Table columns={["ID","编码","名称","单位","分类","安全库存","状态","创建时间"]} rows={data.items||[]} /></div> }

function Bundles({ data, onDone }: { data: any; onDone: () => Promise<void> }) { const [form,setForm]=useState({code:"",name:"",estimated_shipping_fee:"",effective_from:new Date().toISOString().slice(0,10),item_code:"",quantity:"1"}); const submit=async()=>{try{await request("/api/v2/bundles",{method:"POST",body:JSON.stringify({...form,estimated_shipping_fee:Number(form.estimated_shipping_fee||0),components:[{item_code:form.item_code,quantity:Number(form.quantity||1)}]})});await onDone()}catch(e:any){alert(e.message)}}; return <div className="grid gap-6 lg:grid-cols-[380px_1fr]"><Card className="border-slate-800 bg-slate-900/80"><CardHeader><CardTitle>新增组合及 BOM 版本</CardTitle></CardHeader><CardContent className="space-y-3">{([['code','组合编码'],['name','组合名称'],['estimated_shipping_fee','预计快递费'],['effective_from','生效日'],['item_code','单品编码'],['quantity','单品数量']] as const).map(([key,label])=><label key={key} className="block text-sm text-slate-400">{label}<Input className="mt-1 border-slate-700 bg-slate-950 text-slate-100" value={form[key]} onChange={e=>setForm({...form,[key]:e.target.value})}/></label>)}<Button className="w-full" onClick={() => void submit()}>保存组合版本</Button></CardContent></Card><Table columns={["ID","编码","名称","快递费","启用","版本","生效日","BOM"]} rows={data.bundles||[]} /></div> }

function Purchases({ data, onDone }: { data: any; onDone: () => Promise<void> }) { const [form,setForm]=useState({receipt_no:"",warehouse_code:"KUNSHAN",supplier_name:"",item_code:"",batch_no:"",quantity:"",base_unit_cost:"",line_amount:"",freight_fee:"",other_fee:""}); const submit=async()=>{try{await request("/api/v2/purchases",{method:"POST",body:JSON.stringify({...form,freight_fee:Number(form.freight_fee||0),other_fee:Number(form.other_fee||0),lines:[{item_code:form.item_code,batch_no:form.batch_no,quantity:Number(form.quantity),base_unit_cost:Number(form.base_unit_cost),line_amount:Number(form.line_amount)}]})});await onDone()}catch(e:any){alert(e.message)}}; const approve=async(no:string)=>{try{await request(`/api/v2/purchases/${encodeURIComponent(no)}/approve`,{method:"POST"});await onDone()}catch(e:any){alert(e.message)}}; return <div className="space-y-6"><Card className="border-slate-800 bg-slate-900/80"><CardHeader><CardTitle>创建采购入库单（审核后才更新库存）</CardTitle></CardHeader><CardContent className="grid gap-3 md:grid-cols-4">{([['receipt_no','采购单号'],['warehouse_code','仓库'],['supplier_name','供应商'],['item_code','单品编码'],['batch_no','批次号'],['quantity','数量'],['base_unit_cost','采购单价'],['line_amount','行金额'],['freight_fee','采购运费'],['other_fee','其它费用']] as const).map(([key,label])=><label key={key} className="text-sm text-slate-400">{label}<Input className="mt-1 border-slate-700 bg-slate-950 text-slate-100" value={form[key]} onChange={e=>setForm({...form,[key]:e.target.value})}/></label>)}<div className="md:col-span-4"><Button onClick={() => void submit()}>保存待审核采购单</Button></div></CardContent></Card><div className="overflow-auto rounded-lg border border-slate-800"><table className="w-full text-left text-sm"><thead className="bg-slate-900 text-slate-400"><tr><th className="px-3 py-3">采购单</th><th className="px-3 py-3">仓库</th><th className="px-3 py-3">金额</th><th className="px-3 py-3">费用</th><th className="px-3 py-3">状态</th><th className="px-3 py-3">操作</th></tr></thead><tbody>{(data.purchases||[]).map((p:any)=><tr key={p.receipt_no} className="border-t border-slate-800"><td className="px-3 py-3">{p.receipt_no}</td><td className="px-3 py-3">{p.warehouse_code}</td><td className="px-3 py-3">¥{p.purchase_amount}</td><td className="px-3 py-3">¥{Number(p.freight_fee||0)+Number(p.other_fee||0)}</td><td className="px-3 py-3">{p.status}</td><td className="px-3 py-3">{p.status==='pending'&&<Button size="sm" onClick={()=>void approve(p.receipt_no)}>审核入库</Button>}</td></tr>)}</tbody></table></div></div> }

function Inventory({ data }: { data: any }) { return <div className="space-y-6"><Card className="border-slate-800 bg-slate-900/80"><CardHeader><CardTitle>仓库 + 单品加权余额</CardTitle></CardHeader><CardContent><Table columns={["仓库","仓库名","单品","单品名","可售数量","加权均价","库存金额","更新时间"]} rows={data.balances||[]} /></CardContent></Card><Card className="border-slate-800 bg-slate-900/80"><CardHeader><CardTitle>实际批次台账（FIFO）</CardTitle></CardHeader><CardContent><Table columns={["ID","批次号","仓库","单品","入库数量","剩余数量","批次成本","状态","入库时间"]} rows={data.batches||[]} /></CardContent></Card><Card className="border-slate-800 bg-slate-900/80"><CardHeader><CardTitle>库存交易流水</CardTitle></CardHeader><CardContent><Table columns={["ID","类型","仓库","单品","数量","批次成本","平均成本","引用类型","引用号","发生时间"]} rows={data.ledger||[]} /></CardContent></Card></div> }

function Orders({ data, onDone }: { data: any; onDone: () => Promise<void> }) { const [form,setForm]=useState({order_id:"",store_name:"",warehouse_code:"KUNSHAN",bundle_code:"",quantity:"1",payment_time:new Date().toISOString().slice(0,16)}); const submit=async()=>{try{await request("/api/v2/orders",{method:"POST",body:JSON.stringify({...form,quantity:undefined,payment_time:new Date(form.payment_time).toISOString(),lines:[{bundle_code:form.bundle_code,quantity:Number(form.quantity)}]})});await onDone()}catch(e:any){alert(e.message)}}; return <div className="space-y-6"><Card className="border-slate-800 bg-slate-900/80"><CardHeader><CardTitle>导入支付成功订单并扣减库存</CardTitle></CardHeader><CardContent className="grid gap-3 md:grid-cols-3">{([['order_id','订单号'],['store_name','店铺'],['warehouse_code','仓库'],['bundle_code','组合编码'],['quantity','数量'],['payment_time','支付时间']] as const).map(([key,label])=><label key={key} className="text-sm text-slate-400">{label}<Input type={key==='payment_time'?'datetime-local':'text'} className="mt-1 border-slate-700 bg-slate-950 text-slate-100" value={form[key]} onChange={e=>setForm({...form,[key]:e.target.value})}/></label>)}<div className="md:col-span-3"><Button onClick={() => void submit()}>导入订单</Button></div></CardContent></Card><Table columns={["订单号","平台","店铺","支付时间","状态","库存状态","创建时间"]} rows={data.orders||[]} /><Card className="border-slate-800 bg-slate-900/80"><CardHeader><CardTitle>库存异常队列</CardTitle></CardHeader><CardContent><Table columns={["ID","订单号","仓库","单品","需要","可用","状态","时间"]} rows={data.exceptions||[]} /></CardContent></Card></div> }

function Returns({ data, onDone }: { data: any; onDone: () => Promise<void> }) { const [form,setForm]=useState({return_no:"",order_id:"",warehouse_code:"KUNSHAN",item_code:"",quantity:"",unit_cost:""}); const submit=async()=>{try{await request("/api/v2/returns",{method:"POST",body:JSON.stringify({...form,quantity:Number(form.quantity),unit_cost:Number(form.unit_cost)})});await onDone()}catch(e:any){alert(e.message)}}; const inspect=async(no:string,target_status:string)=>{try{await request(`/api/v2/returns/${encodeURIComponent(no)}/inspect`,{method:"POST",body:JSON.stringify({target_status})});await onDone()}catch(e:any){alert(e.message)}}; return <div className="space-y-6"><Card className="border-slate-800 bg-slate-900/80"><CardHeader><CardTitle>退货确认收货后进入待检</CardTitle></CardHeader><CardContent className="grid gap-3 md:grid-cols-3">{([['return_no','退货单号'],['order_id','原订单号'],['warehouse_code','仓库'],['item_code','单品编码'],['quantity','数量'],['unit_cost','成本']] as const).map(([key,label])=><label key={key} className="text-sm text-slate-400">{label}<Input className="mt-1 border-slate-700 bg-slate-950 text-slate-100" value={form[key]} onChange={e=>setForm({...form,[key]:e.target.value})}/></label>)}<div className="md:col-span-3"><Button onClick={() => void submit()}>确认收货并进入待检</Button></div></CardContent></Card><div className="overflow-auto rounded-lg border border-slate-800"><table className="w-full text-left text-sm"><thead className="bg-slate-900 text-slate-400"><tr><th className="px-3 py-3">退货单</th><th className="px-3 py-3">原订单</th><th className="px-3 py-3">仓库</th><th className="px-3 py-3">状态</th><th className="px-3 py-3">操作</th></tr></thead><tbody>{(data.returns||[]).map((r:any)=><tr key={r.return_no} className="border-t border-slate-800"><td className="px-3 py-3">{r.return_no}</td><td className="px-3 py-3">{r.order_id}</td><td className="px-3 py-3">{r.warehouse_code}</td><td className="px-3 py-3">{r.status}</td><td className="flex gap-2 px-3 py-3">{r.status==='inspected'&&<><Button size="sm" onClick={()=>void inspect(r.return_no,'sellable')}>可售</Button><Button size="sm" variant="secondary" onClick={()=>void inspect(r.return_no,'defective')}>残次</Button><Button size="sm" variant="destructive" onClick={()=>void inspect(r.return_no,'scrapped')}>报废</Button></>}</td></tr>)}</tbody></table></div></div> }
function Users({ data, onDone }: { data: any; onDone: () => Promise<void> }) {
  const [form, setForm] = useState({ username: "", password: "", role: "sub", allowed_stores: "", allowed_pages: "overview,stores,imports,orders" })
  const submit = async () => {
    try {
      await request("/api/v2/users", { method: "POST", body: JSON.stringify({
        username: form.username.trim(), password: form.password, role: form.role,
        display_name: form.username.trim(),
        allowed_stores: form.allowed_stores.split(",").map((x) => x.trim()).filter(Boolean),
        allowed_pages: form.allowed_pages.split(",").map((x) => x.trim()).filter(Boolean),
      }) })
      setForm({ ...form, username: "", password: "", allowed_stores: "" })
      await onDone()
    } catch (e: any) { alert(e.message) }
  }
  return <div className="grid gap-6 lg:grid-cols-[390px_1fr]"><Card className="border-slate-800 bg-slate-900/80"><CardHeader><CardTitle>新增 V2 账号</CardTitle></CardHeader><CardContent className="space-y-3">{([["username","账号"],["password","初始密码"],["allowed_stores","店铺（逗号分隔）"],["allowed_pages","页面权限（逗号分隔）"]] as const).map(([key,label])=><label key={key} className="block text-sm text-slate-400">{label}<Input type={key === "password" ? "password" : "text"} className="mt-1 border-slate-700 bg-slate-950 text-slate-100" value={form[key]} onChange={e=>setForm({...form,[key]:e.target.value})}/></label>)}<label className="block text-sm text-slate-400">角色<select className="mt-1 h-10 w-full rounded-md border border-slate-700 bg-slate-950 px-3 text-slate-100" value={form.role} onChange={e=>setForm({...form,role:e.target.value})}><option value="sub">子账号</option><option value="master">主账号</option><option value="admin">管理员</option><option value="viewer">只读</option></select></label><Button className="w-full" onClick={() => void submit()}>保存账号</Button></CardContent></Card><Table columns={["账号","角色","店铺授权","页面授权","状态"]} rows={(data.users||[]).map((u:any)=>({...u, allowed_stores:(u.allowed_stores||[]).map((s:any)=>s.platform + ":" + s.store_name).join("、")||"全部/未限制", allowed_pages:(u.allowed_pages||[]).join("、")||"全部", is_active:u.is_active?"启用":"停用"}))} /></div>
}
