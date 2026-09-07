import { useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { BarChart3, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { login } from "@/api/auth"

export function LoginPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [username, setUsername] = useState("admin")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)
  const forced = searchParams.get("forced") === "1"

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError("")
    try {
      const result = await login(username, password)
      if (result.requirePasswordChange) {
        navigate("/change-password?forced=1", { replace: true })
      } else {
        navigate("/", { replace: true })
      }
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-b from-background to-muted/40 p-4">
      <Card className="w-full max-w-sm shadow-sm">
        <CardHeader className="items-center text-center">
          <div className="mb-2 flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
            <BarChart3 className="h-5 w-5" />
          </div>
          <CardTitle className="text-xl tracking-tight">PDD BI Dashboard</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            {forced && (
              <div className="rounded-md border border-chart-3/30 bg-chart-3/10 px-3 py-2 text-center text-sm text-chart-3">
                请先修改默认密码后再继续使用
              </div>
            )}
            {error && (
              <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-center text-sm text-destructive">{error}</div>
            )}
            <div className="space-y-2">
              <Label>用户名</Label>
              <Input value={username} onChange={(e) => setUsername(e.target.value)} required />
            </div>
            <div className="space-y-2">
              <Label>密码</Label>
              <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </div>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading && <Loader2 className="h-4 w-4 animate-spin" />}
              {loading ? "登录中..." : "登录"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
