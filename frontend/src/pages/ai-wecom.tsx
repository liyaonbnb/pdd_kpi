import { useCallback, useEffect, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { Bot, CalendarClock, MessageCircle, RefreshCw, Save, Send, Sparkles, TestTube } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import {
  getStores,
  getAiConfigByPlatform,
  updateAiConfigByPlatform,
  testAiByPlatform,
  generateAiReportByPlatform,
  getWecomConfigByPlatform,
  updateWecomConfigByPlatform,
  previewWecomReportByPlatform,
  sendWecomReportByPlatform,
  getDailyWecomScheduleStatus,
  type DailyWecomScheduleStatus,
  type Store,
} from "@/api/client"

type Platform = "pdd" | "douyin" | "tmall" | "wechat"

const PLATFORM_OPTIONS: { key: Platform; label: string }[] = [
  { key: "pdd", label: "拼多多" },
  { key: "douyin", label: "抖音" },
  { key: "tmall", label: "天猫" },
  { key: "wechat", label: "微信小店" },
]

const SCHEDULE_STATUS_LABELS: Record<DailyWecomScheduleStatus["last_status"], string> = {
  sent: "发送成功",
  failed: "执行失败",
  skipped: "已跳过",
  never: "尚未执行",
}

function formatScheduleDate(value: string | null) {
  if (!value) return "—"
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value))
}

export function AiWecomPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const initialPlatform = (searchParams.get("platform") as Platform) || "pdd"
  const [platform, setPlatformState] = useState<Platform>(
    PLATFORM_OPTIONS.some((p) => p.key === initialPlatform) ? initialPlatform : "pdd"
  )
  const setPlatform = (p: Platform) => {
    setPlatformState(p)
    setSearchParams({ platform: p }, { replace: true })
  }
  const [stores, setStores] = useState<Store[]>([])
  const [aiConfig, setAiConfig] = useState<Record<string, any>>({})
  const [wecomConfig, setWecomConfig] = useState<Record<string, any>>({})
  const [storeName, setStoreName] = useState("")
  const [startDate, setStartDate] = useState(new Date().toISOString().split("T")[0])
  const [endDate, setEndDate] = useState(new Date().toISOString().split("T")[0])
  const [report, setReport] = useState("")
  const [reportLoading, setReportLoading] = useState(false)
  const [reportDate, setReportDate] = useState(new Date().toISOString().split("T")[0])
  const [wecomPreviewLoading, setWecomPreviewLoading] = useState(false)
  const [wecomSendLoading, setWecomSendLoading] = useState(false)
  const [wecomDraftId, setWecomDraftId] = useState("")
  const [wecomDraftContent, setWecomDraftContent] = useState("")
  const [wecomDraftSent, setWecomDraftSent] = useState(false)
  const [scheduleStatus, setScheduleStatus] = useState<DailyWecomScheduleStatus | null>(null)
  const [scheduleLoading, setScheduleLoading] = useState(false)
  const [scheduleError, setScheduleError] = useState("")
  const [message, setMessage] = useState("")
  const [messageKind, setMessageKind] = useState<"success" | "error">("success")
  const [activeTab, setActiveTab] = useState("ai-config")

  const supported = platform !== "wechat"

  const loadScheduleStatus = useCallback(async () => {
    if (platform !== "pdd") return
    setScheduleLoading(true)
    setScheduleError("")
    try {
      setScheduleStatus(await getDailyWecomScheduleStatus())
    } catch (err: any) {
      setScheduleError(err.message || "定时任务状态加载失败")
    } finally {
      setScheduleLoading(false)
    }
  }, [platform])

  useEffect(() => {
    setMessage("")
    setMessageKind("success")
    setReport("")
    setStoreName("")
    setWecomDraftId("")
    setWecomDraftContent("")
    setWecomDraftSent(false)
    getStores(platform).then(setStores)
    if (supported) {
      getAiConfigByPlatform(platform).then(setAiConfig)
      getWecomConfigByPlatform(platform).then(setWecomConfig)
    } else {
      setAiConfig({})
      setWecomConfig({})
    }
  }, [platform, supported])

  useEffect(() => {
    if (platform === "pdd" && activeTab === "wecom-send") {
      loadScheduleStatus()
    }
  }, [platform, activeTab, loadScheduleStatus])

  const updateAi = (key: string, value: any) => {
    setAiConfig((prev) => ({ ...prev, [key]: value }))
  }

  const updateWecom = (key: string, value: any) => {
    setWecomConfig((prev) => ({ ...prev, [key]: value }))
  }

  const handleAiSave = async () => {
    try {
      await updateAiConfigByPlatform(platform, aiConfig)
      setMessageKind("success")
      setMessage("AI 配置已保存")
    } catch (err: any) {
      setMessageKind("error")
      setMessage(err.message)
    }
  }

  const handleAiTest = async () => {
    try {
      const res = await testAiByPlatform(platform, aiConfig)
      setMessageKind("success")
      setMessage(`AI 测试连接：${res.status || JSON.stringify(res)}`)
    } catch (err: any) {
      setMessageKind("error")
      setMessage(err.message)
    }
  }

  const handleReport = async () => {
    if (!storeName) return
    setReportLoading(true)
    setReport("")
    try {
      const res = await generateAiReportByPlatform(platform, storeName, startDate, endDate, aiConfig)
      setReport(res.report || res.content || JSON.stringify(res, null, 2))
    } catch (err: any) {
      setMessageKind("error")
      setMessage(err.message)
    } finally {
      setReportLoading(false)
    }
  }

  const handleWecomSave = async () => {
    try {
      await updateWecomConfigByPlatform(platform, wecomConfig)
      setMessageKind("success")
      setMessage("企微配置已保存")
    } catch (err: any) {
      setMessageKind("error")
      setMessage(err.message)
    }
  }

  const handleReportDateChange = (value: string) => {
    setReportDate(value)
    setWecomDraftId("")
    setWecomDraftContent("")
    setWecomDraftSent(false)
  }

  const handleWecomPreview = async () => {
    if (wecomPreviewLoading || wecomSendLoading || !reportDate) return
    setWecomPreviewLoading(true)
    setWecomDraftId("")
    setWecomDraftContent("")
    setWecomDraftSent(false)
    setMessage("")
    try {
      const draft = await previewWecomReportByPlatform(platform, reportDate)
      setWecomDraftId(draft.draft_id)
      setWecomDraftContent(draft.content)
      setMessageKind("success")
      setMessage("日报已生成，请确认预览内容后再发送到企微")
    } catch (err: any) {
      setMessageKind("error")
      setMessage(err.message)
    } finally {
      setWecomPreviewLoading(false)
    }
  }

  const handleWecomSend = async () => {
    if (wecomSendLoading || wecomPreviewLoading || wecomDraftSent) return
    if (!wecomDraftId) {
      setMessageKind("error")
      setMessage("请先点击“生成日报”，确认预览后再发送")
      return
    }
    setWecomSendLoading(true)
    setMessage("")
    try {
      const res = await sendWecomReportByPlatform(platform, reportDate, wecomConfig, wecomDraftId)
      setWecomDraftSent(true)
      setMessageKind("success")
      setMessage(`企微发送结果：${res.status || JSON.stringify(res)}`)
    } catch (err: any) {
      setMessageKind("error")
      setMessage(err.message)
    } finally {
      setWecomSendLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <h2 className="text-2xl font-bold flex items-center gap-2">
          <Bot className="h-6 w-6" />
          AI & 企微
        </h2>
        <div className="flex rounded-lg bg-muted p-1 gap-1">
          {PLATFORM_OPTIONS.map((p) => {
            const active = platform === p.key
            return (
              <button
                key={p.key}
                onClick={() => setPlatform(p.key)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  active
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                }`}
              >
                {p.label}
              </button>
            )
          })}
        </div>
      </div>

      {message && (
        <div
          className={`text-sm p-3 rounded-md ${
            messageKind === "success" ? "bg-green-100 text-green-800" : "bg-destructive/10 text-destructive"
          }`}
        >
          {message}
        </div>
      )}

      {!supported ? (
        <Card>
          <CardContent className="p-8 text-center text-muted-foreground">
            微信小店暂不支持 AI 分析与企微日报功能。
          </CardContent>
        </Card>
      ) : (
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList>
            <TabsTrigger value="ai-config">
              <Bot className="h-4 w-4 mr-1" /> AI 配置
            </TabsTrigger>
            <TabsTrigger value="ai-report">
              <Sparkles className="h-4 w-4 mr-1" /> 生成报告
            </TabsTrigger>
            <TabsTrigger value="wecom-config">
              <MessageCircle className="h-4 w-4 mr-1" /> 企微配置
            </TabsTrigger>
            <TabsTrigger value="wecom-send">
              <Send className="h-4 w-4 mr-1" /> 发送日报
            </TabsTrigger>
          </TabsList>

          <TabsContent value="ai-config" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>AI API 配置</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>API Key</Label>
                    <Input
                      value={aiConfig.api_key || ""}
                      onChange={(e) => updateAi("api_key", e.target.value)}
                      placeholder="sk-..."
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Base URL</Label>
                    <Input
                      value={aiConfig.base_url || ""}
                      onChange={(e) => updateAi("base_url", e.target.value)}
                      placeholder="https://api.kimi.com/coding/v1"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>模型</Label>
                    <Input
                      value={aiConfig.model || ""}
                      onChange={(e) => updateAi("model", e.target.value)}
                      placeholder="kimi-coding"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Temperature</Label>
                    <Input
                      type="number"
                      value={aiConfig.temperature ?? 1}
                      onChange={(e) => updateAi("temperature", parseFloat(e.target.value))}
                    />
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={handleAiTest}>
                    <TestTube className="h-4 w-4 mr-1" /> 测试连接
                  </Button>
                  <Button onClick={handleAiSave}>
                    <Save className="h-4 w-4 mr-1" /> 保存配置
                  </Button>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="ai-report" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>生成 AI 报告</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 items-end">
                  <div className="space-y-2">
                    <Label>店铺</Label>
                    <Select value={storeName} onChange={(e) => setStoreName(e.target.value)}>
                      <option value="">选择店铺</option>
                      {stores.map((s) => (
                        <option key={s.id} value={s.name}>
                          {s.name}
                        </option>
                      ))}
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>开始日期</Label>
                    <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
                  </div>
                  <div className="space-y-2">
                    <Label>结束日期</Label>
                    <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
                  </div>
                  <Button onClick={handleReport} disabled={reportLoading}>
                    <Sparkles className="h-4 w-4 mr-1" /> {reportLoading ? "生成中..." : "生成报告"}
                  </Button>
                </div>
                {report && (
                  <div className="rounded-md border bg-muted p-4 whitespace-pre-wrap text-sm">{report}</div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="wecom-config" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>企业微信机器人配置</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Bot ID</Label>
                    <Input value={wecomConfig.bot_id || ""} onChange={(e) => updateWecom("bot_id", e.target.value)} />
                  </div>
                  <div className="space-y-2">
                    <Label>Secret</Label>
                    <Input value={wecomConfig.secret || ""} onChange={(e) => updateWecom("secret", e.target.value)} />
                  </div>
                  <div className="space-y-2">
                    <Label>Webhook Key</Label>
                    <Input
                      value={wecomConfig.webhook_key || ""}
                      onChange={(e) => updateWecom("webhook_key", e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Chat ID</Label>
                    <Input value={wecomConfig.chat_id || ""} onChange={(e) => updateWecom("chat_id", e.target.value)} />
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={handleWecomSave}>
                    <Save className="h-4 w-4 mr-1" /> 保存配置
                  </Button>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="wecom-send" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>发送日报</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {platform === "pdd" && (
                  <section className="rounded-md border bg-muted/30 p-4" aria-labelledby="daily-schedule-title">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="flex items-center gap-2">
                          <CalendarClock className="h-4 w-4" />
                          <h4 id="daily-schedule-title" className="text-sm font-semibold">自动日报任务</h4>
                          {scheduleStatus && (
                            <Badge variant={scheduleStatus.enabled ? "secondary" : "destructive"}>
                              {scheduleStatus.enabled ? "已启用" : "未启用"}
                            </Badge>
                          )}
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">拼多多全店日报自动发送状态</p>
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={loadScheduleStatus}
                        disabled={scheduleLoading}
                        title="刷新定时任务状态"
                      >
                        <RefreshCw className={`h-4 w-4 ${scheduleLoading ? "animate-spin" : ""}`} />
                        刷新
                      </Button>
                    </div>

                    {scheduleError ? (
                      <div className="mt-3 text-sm text-destructive">{scheduleError}</div>
                    ) : scheduleStatus ? (
                      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                        <div>
                          <div className="text-xs text-muted-foreground">执行时间</div>
                          <div className="mt-1 text-sm font-medium">每天 {scheduleStatus.schedule_time}</div>
                        </div>
                        <div>
                          <div className="text-xs text-muted-foreground">下次执行</div>
                          <div className="mt-1 text-sm font-medium">{formatScheduleDate(scheduleStatus.next_run_at)}</div>
                        </div>
                        <div>
                          <div className="text-xs text-muted-foreground">上次结果</div>
                          <div className="mt-1 flex items-center gap-2 text-sm font-medium">
                            <Badge
                              variant={
                                scheduleStatus.last_status === "failed"
                                  ? "destructive"
                                  : scheduleStatus.last_status === "sent"
                                    ? "secondary"
                                    : "outline"
                              }
                            >
                              {SCHEDULE_STATUS_LABELS[scheduleStatus.last_status]}
                            </Badge>
                            <span>{formatScheduleDate(scheduleStatus.last_run_at)}</span>
                          </div>
                        </div>
                        <div>
                          <div className="text-xs text-muted-foreground">数据日期</div>
                          <div className="mt-1 text-sm font-medium">{scheduleStatus.last_data_date || "—"}</div>
                        </div>
                      </div>
                    ) : (
                      <div className="mt-3 text-sm text-muted-foreground">正在读取任务状态...</div>
                    )}

                    {scheduleStatus?.last_error && (
                      <div className="mt-3 rounded border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                        上次失败原因：{scheduleStatus.last_error}
                      </div>
                    )}
                  </section>
                )}
                <div className="flex flex-wrap items-end gap-4">
                  <div className="space-y-2 w-64">
                    <Label>报告日期</Label>
                    <Input type="date" value={reportDate} onChange={(e) => handleReportDateChange(e.target.value)} />
                  </div>
                  <Button variant="outline" onClick={handleWecomPreview} disabled={wecomPreviewLoading || wecomSendLoading}>
                    <Sparkles className={`h-4 w-4 mr-1 ${wecomPreviewLoading ? "animate-pulse" : ""}`} />
                    {wecomPreviewLoading ? "生成中..." : "生成日报"}
                  </Button>
                  <Button onClick={handleWecomSend} disabled={wecomSendLoading || wecomPreviewLoading || !wecomDraftId || wecomDraftSent}>
                    <Send className={`h-4 w-4 mr-1 ${wecomSendLoading ? "animate-pulse" : ""}`} />
                    {wecomDraftSent ? "已发送" : wecomSendLoading ? "发送中..." : "发送到企微"}
                  </Button>
                </div>
                {wecomDraftContent && (
                  <Card className="border-dashed">
                    <CardHeader className="pb-3">
                      <CardTitle className="text-base">日报预览</CardTitle>
                      <p className="text-xs text-muted-foreground">内容已生成并保存 30 分钟，发送时不会重新生成。</p>
                    </CardHeader>
                    <CardContent>
                      <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap rounded-md bg-muted/50 p-4 text-sm leading-6">
                        {wecomDraftContent}
                      </pre>
                    </CardContent>
                  </Card>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      )}
    </div>
  )
}
