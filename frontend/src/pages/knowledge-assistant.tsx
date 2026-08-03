import { useEffect, useState } from "react"
import {
  BookOpenCheck,
  Database,
  FileSearch,
  LoaderCircle,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  askKnowledgeAssistant,
  getKnowledgeStatus,
  getStores,
  searchKnowledge,
  type KnowledgeResponse,
  type KnowledgeResult,
  type KnowledgeStatus,
  type Store,
} from "@/api/client"

type Mode = "assist" | "search"

function formatDateOffset(days: number) {
  const value = new Date()
  value.setDate(value.getDate() + days)
  return value.toISOString().split("T")[0]
}

function SourceCard({ item }: { item: KnowledgeResult }) {
  return (
    <Card className="shadow-sm">
      <CardHeader className="p-4 pb-2">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 space-y-1">
            <CardTitle className="text-sm leading-5">{item.title}</CardTitle>
            <p className="break-all text-xs text-muted-foreground">{item.source_path}</p>
          </div>
          <Badge variant={item.decision_enabled ? "default" : "secondary"} className="shrink-0 self-start">
            {item.decision_enabled ? "已验证决策" : item.source_status || "参考资料"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 p-4 pt-1">
        <div className="flex flex-wrap gap-1.5">
          <Badge variant="outline">{item.course_id}</Badge>
          {item.topics.slice(0, 4).map((topic) => (
            <Badge key={topic} variant="outline">
              {topic}
            </Badge>
          ))}
          {item.risk_tags.slice(0, 3).map((risk) => (
            <Badge key={risk} variant="destructive">
              {risk}
            </Badge>
          ))}
        </div>
        <p className="whitespace-pre-wrap text-sm leading-6 text-foreground/90">{item.excerpt}</p>
        {item.applicable_conditions ? (
          <div className="border-l-2 border-primary/40 pl-3 text-xs leading-5 text-muted-foreground">
            适用条件：{item.applicable_conditions}
          </div>
        ) : null}
        {item.unproven_content ? (
          <div className="border-l-2 border-destructive/40 pl-3 text-xs leading-5 text-muted-foreground">
            未证明：{item.unproven_content}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

export function KnowledgeAssistantPage() {
  const [mode, setMode] = useState<Mode>("assist")
  const [status, setStatus] = useState<KnowledgeStatus | null>(null)
  const [stores, setStores] = useState<Store[]>([])
  const [query, setQuery] = useState("")
  const [courseId, setCourseId] = useState("")
  const [topic, setTopic] = useState("")
  const [decisionOnly, setDecisionOnly] = useState(false)
  const [useAi, setUseAi] = useState(true)
  const [storeName, setStoreName] = useState("")
  const [startDate, setStartDate] = useState(formatDateOffset(-6))
  const [endDate, setEndDate] = useState(formatDateOffset(0))
  const [response, setResponse] = useState<KnowledgeResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [statusLoading, setStatusLoading] = useState(false)
  const [error, setError] = useState("")

  const loadInitialData = async () => {
    setStatusLoading(true)
    setError("")
    try {
      const [nextStatus, nextStores] = await Promise.all([
        getKnowledgeStatus(),
        getStores("pdd"),
      ])
      setStatus(nextStatus)
      setStores(nextStores)
    } catch (err: any) {
      setError(err.message || "知识库状态加载失败")
    } finally {
      setStatusLoading(false)
    }
  }

  useEffect(() => {
    loadInitialData()
  }, [])

  const submit = async () => {
    const normalizedQuery = query.trim()
    if (normalizedQuery.length < 2) {
      setError("请输入至少 2 个字符的问题")
      return
    }
    setLoading(true)
    setError("")
    setResponse(null)
    try {
      if (mode === "search") {
        setResponse(
          await searchKnowledge({
            query: normalizedQuery,
            course_id: courseId || undefined,
            topic: topic || undefined,
            decision_only: decisionOnly,
            limit: 10,
          })
        )
      } else {
        setResponse(
          await askKnowledgeAssistant({
            query: normalizedQuery,
            course_id: courseId || undefined,
            topic: topic || undefined,
            limit: 8,
            use_ai: useAi,
            store_name: storeName || undefined,
            start_date: storeName ? startDate : undefined,
            end_date: storeName ? endDate : undefined,
          })
        )
      }
    } catch (err: any) {
      setError(err.message || "请求失败")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mx-auto w-full max-w-6xl space-y-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-2xl font-bold">
          <BookOpenCheck className="h-6 w-6" />
          运营知识助手
        </h2>
        <Button
          variant="ghost"
          size="icon"
          onClick={loadInitialData}
          disabled={statusLoading}
          title="刷新知识库状态"
        >
          <RefreshCw className={`h-4 w-4 ${statusLoading ? "animate-spin" : ""}`} />
        </Button>
      </div>

      {status ? (
        <div className="grid grid-cols-2 border-y md:grid-cols-4">
          {[
            { label: "资料", value: status.counts.documents, icon: Database },
            { label: "检索分块", value: status.counts.chunks, icon: FileSearch },
            { label: "结构化观点", value: status.counts.claims, icon: BookOpenCheck },
            { label: "已验证决策", value: status.counts.decisions, icon: ShieldCheck },
          ].map((item) => (
            <div key={item.label} className="flex min-h-20 items-center gap-3 border-r px-4 last:border-r-0">
              <item.icon className="h-5 w-5 text-muted-foreground" />
              <div>
                <div className="text-xl font-semibold">{item.value.toLocaleString()}</div>
                <div className="text-xs text-muted-foreground">{item.label}</div>
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {error ? (
        <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{error}</div>
      ) : null}
      {status && !status.available ? (
        <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          {status.error || "知识库不可用"}
        </div>
      ) : null}

      <Tabs value={mode} onValueChange={(value) => setMode(value as Mode)}>
        <TabsList>
          <TabsTrigger value="assist">
            <Sparkles className="mr-1 h-4 w-4" /> 知识问答
          </TabsTrigger>
          <TabsTrigger value="search">
            <Search className="mr-1 h-4 w-4" /> 资料检索
          </TabsTrigger>
        </TabsList>

        <Card className="mt-3 shadow-sm">
          <CardContent className="space-y-4 p-4 md:p-5">
            <div className="space-y-2">
              <Label htmlFor="knowledge-query">问题</Label>
              <textarea
                id="knowledge-query"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                rows={4}
                placeholder="例如：投产低应该先检查流量、转化还是退款？"
                className="min-h-28 w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm leading-6 shadow-sm outline-none placeholder:text-muted-foreground focus-visible:ring-1 focus-visible:ring-ring"
              />
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <div className="space-y-2">
                <Label>课程</Label>
                <Select value={courseId} onChange={(event) => setCourseId(event.target.value)}>
                  <option value="">全部课程</option>
                  {status?.courses.map((course) => (
                    <option key={course.course_id} value={course.course_id}>
                      {course.course_id} · {course.document_count} 份
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-2">
                <Label>主题</Label>
                <Select value={topic} onChange={(event) => setTopic(event.target.value)}>
                  <option value="">全部主题</option>
                  {status?.topics.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </Select>
              </div>

              <TabsContent value="assist" className="contents">
                <div className="space-y-2">
                  <Label>店铺数据</Label>
                  <Select value={storeName} onChange={(event) => setStoreName(event.target.value)}>
                    <option value="">不附带店铺数据</option>
                    {stores.map((store) => (
                      <option key={store.id} value={store.name}>
                        {store.name}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="flex items-end">
                  <label className="flex h-9 items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="h-4 w-4 rounded border-input"
                      checked={useAi}
                      onChange={(event) => setUseAi(event.target.checked)}
                    />
                    使用已配置 AI
                  </label>
                </div>
              </TabsContent>

              <TabsContent value="search" className="contents">
                <div className="flex items-end sm:col-span-2">
                  <label className="flex h-9 items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="h-4 w-4 rounded border-input"
                      checked={decisionOnly}
                      onChange={(event) => setDecisionOnly(event.target.checked)}
                    />
                    只看已验证决策
                  </label>
                </div>
              </TabsContent>
            </div>

            {mode === "assist" && storeName ? (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label>开始日期</Label>
                  <Input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label>结束日期</Label>
                  <Input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
                </div>
              </div>
            ) : null}

            <div className="flex justify-end">
              <Button onClick={submit} disabled={loading || status?.available === false}>
                {loading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : mode === "assist" ? <Sparkles className="h-4 w-4" /> : <Search className="h-4 w-4" />}
                {loading ? "处理中" : mode === "assist" ? "分析" : "检索"}
              </Button>
            </div>
          </CardContent>
        </Card>
      </Tabs>

      {response?.answer ? (
        <section className="space-y-2 border-y py-5">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold">分析结果</h3>
            <Badge variant={response.answer_source === "llm" ? "default" : "secondary"}>
              {response.answer_source === "llm" ? "AI + 知识库" : "知识库检索"}
            </Badge>
            {response.business_context ? <Badge variant="outline">已附带店铺数据</Badge> : null}
          </div>
          <div className="whitespace-pre-wrap text-sm leading-7">{response.answer}</div>
          {response.ai_error ? (
            <div className="text-xs text-destructive">AI 调用失败，已降级为知识检索：{response.ai_error}</div>
          ) : null}
        </section>
      ) : null}

      {response ? (
        <section className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-base font-semibold">来源证据</h3>
            <span className="text-xs text-muted-foreground">{response.count} 条</span>
          </div>
          {response.message ? (
            <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
              {response.message}
            </div>
          ) : response.results.length > 0 ? (
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
              {response.results.map((item) => (
                <SourceCard key={`${item.result_type}-${item.id}`} item={item} />
              ))}
            </div>
          ) : (
            <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
              没有匹配资料
            </div>
          )}
        </section>
      ) : null}
    </div>
  )
}
