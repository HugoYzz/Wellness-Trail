import type { RecordItem } from './labels'

/** 后端 API 客户端（开发期经 Vite 代理 → localhost:8001）。 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    ...init,
  })
  if (!resp.ok) {
    if (resp.status === 401 || resp.status === 428) {
      window.dispatchEvent(new Event('kangji-auth-required'))
    }
    let detail = `${resp.status}`
    try {
      const body = await resp.json()
      const value = body.detail ?? body
      detail = typeof value === 'string' ? value : JSON.stringify(value)
    } catch {
      /* keep status */
    }
    throw new Error(detail)
  }
  return resp.json() as Promise<T>
}

export interface RecordPayload {
  type: string
  date: string
  slot?: string | null
  fields: Record<string, unknown>
  raw_text?: string
  source?: string
}

export function listRecords(params: {
  date?: string
  start?: string
  end?: string
  type?: string
}): Promise<RecordItem[]> {
  const q = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join('&')
  return request(`/records${q ? `?${q}` : ''}`)
}

export function createRecord(payload: RecordPayload): Promise<RecordItem> {
  return request('/records', { method: 'POST', body: JSON.stringify(payload) })
}

export function getRecord(id: number): Promise<RecordItem> {
  return request(`/records/${id}`)
}

export function updateRecord(id: number, payload: RecordPayload): Promise<RecordItem> {
  return request(`/records/${id}`, { method: 'PUT', body: JSON.stringify(payload) })
}

export function deleteRecord(id: number): Promise<{ deleted: number }> {
  return request(`/records/${id}`, { method: 'DELETE' })
}

// ---------- 个性化今日计划 ----------

export type TodayTaskStatus = 'later' | 'pending' | 'done' | 'reported' | 'skipped'

export interface TodayTask {
  key: string
  label: string
  prefill: string
  source: 'daily' | 'schedule' | 'habit' | 'health' | 'manual'
  source_label: string
  reason: string
  time_window: { start: string; label: string }
  status: TodayTaskStatus
  outcome: 'met' | 'not_met' | 'unknown'
  detail: string
}

export interface TodayPlan {
  date: string
  confirmed: boolean
  summary: string
  safety_note: string | null
  items: TodayTask[]
  progress: {
    handled: number
    achieved: number
    active: number
    skipped: number
  }
  next_item_key: string | null
}

export function getTodayPlan(): Promise<TodayPlan> {
  return request('/todos/today')
}

export function updateTodayPlan(payload: {
  action: 'confirm' | 'skip' | 'restore' | 'rest' | 'reset'
  task_key?: string
}): Promise<TodayPlan> {
  return request('/todos/today', { method: 'PATCH', body: JSON.stringify(payload) })
}

export function healthCheck(): Promise<{ status: string; app: string }> {
  return request('/health')
}

// ---------- 本地访问控制 ----------

export interface AuthStatus {
  pin_configured: boolean
  authenticated: boolean
  expires_at: string | null
}

export function getAuthStatus(): Promise<AuthStatus> {
  return request('/auth/status')
}

export function setupAccessPin(pin: string): Promise<{ ok: boolean; authenticated: boolean }> {
  return request('/auth/setup', { method: 'POST', body: JSON.stringify({ pin }) })
}

export function loginWithPin(pin: string): Promise<{ ok: boolean; authenticated: boolean }> {
  return request('/auth/login', { method: 'POST', body: JSON.stringify({ pin }) })
}

export function logoutAccess(): Promise<{ ok: boolean }> {
  return request('/auth/logout', { method: 'POST', body: '{}' })
}

// ---------- 聊天（P1，架构 §6.1 SSE 事件契约） ----------

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant' | 'tool'
  content: string
  record_id: number | null
  created_at?: string | null
}

export interface TodayChat {
  id: number
  date: string
  title: string
  opener: string | null
}

export interface RecordDraft {
  type: string
  date: string
  slot: string | null
  fields: Record<string, any>
  raw_text: string
  source: string
}

export interface PendingCard {
  draft: RecordDraft
  warnings: string[]
  /** 前端状态 */
  status?: 'pending' | 'confirmed' | 'rejected'
}

export function createTodayChat(): Promise<TodayChat> {
  return request('/chats', { method: 'POST', body: '{}' })
}

export function listMessages(chatId: number): Promise<ChatMessage[]> {
  return request(`/chats/${chatId}/messages`)
}

export interface StreamHandlers {
  onToken: (text: string) => void
  onCard: (card: PendingCard) => void
  onDone: (done: { usage?: Record<string, number>; message_id?: number; error?: string | null }) => void
  onMeta?: (meta: { chat_id: number; request_id: string }) => void
  onRetry?: (attempt: number) => void
}

/** POST-SSE：同一 request_id 自动重连，并用 Last-Event-ID 只补发缺失事件。 */
export async function sendMessageStream(
  chatId: number | null,
  content: string,
  h: StreamHandlers,
): Promise<number> {
  const requestId = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`
  let resolvedChatId = chatId
  let lastEventId = 0
  let lastError: Error = new Error('连接提前结束')

  for (let attempt = 0; attempt < 4; attempt += 1) {
    if (attempt > 0) {
      h.onRetry?.(attempt)
      await new Promise((resolve) => window.setTimeout(resolve, 300 * 2 ** (attempt - 1)))
    }
    try {
      const path = resolvedChatId === null
        ? '/api/chats/messages'
        : `/api/chats/${resolvedChatId}/messages`
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (lastEventId > 0) headers['Last-Event-ID'] = String(lastEventId)
      const resp = await fetch(path, {
        method: 'POST',
        headers,
        credentials: 'same-origin',
        body: JSON.stringify({ content, request_id: requestId }),
      })
      if (!resp.ok || !resp.body) {
        if (resp.status === 401 || resp.status === 428) {
          window.dispatchEvent(new Event('kangji-auth-required'))
        }
        let detail = `${resp.status}`
        try {
          const body = await resp.json()
          detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body)
        } catch {
          /* keep status */
        }
        const httpError = new Error(detail) as Error & { retryable?: boolean }
        httpError.retryable = resp.status === 408 || resp.status === 429 || resp.status >= 500
        throw httpError
      }
      const headerChatId = Number(resp.headers.get('X-Chat-Id'))
      if (Number.isInteger(headerChatId) && headerChatId > 0) resolvedChatId = headerChatId

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      let receivedDone = false
      for (;;) {
        const chunk = await reader.read()
        if (chunk.done) break
        buf = (buf + decoder.decode(chunk.value, { stream: true })).replaceAll('\r\n', '\n')
        let idx: number
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const block = buf.slice(0, idx)
          buf = buf.slice(idx + 2)
          let event = ''
          let eventId = 0
          let dataLine = ''
          for (const line of block.split('\n')) {
            if (line.startsWith('id: ')) eventId = Number(line.slice(4))
            else if (line.startsWith('event: ')) event = line.slice(7)
            else if (line.startsWith('data: ')) dataLine += line.slice(6)
          }
          if (!event || !dataLine) continue
          if (eventId > 0 && eventId <= lastEventId) continue
          if (eventId > 0) lastEventId = eventId
          const data = JSON.parse(dataLine)
          if (event === 'meta') {
            resolvedChatId = Number(data.chat_id)
            h.onMeta?.(data)
          } else if (event === 'token') h.onToken(data.text)
          else if (event === 'record_card') h.onCard({ ...data, status: 'pending' })
          else if (event === 'done') {
            receivedDone = true
            h.onDone(data)
          }
        }
      }
      if (!receivedDone) throw new Error('SSE 在完成事件前断开')
      if (resolvedChatId === null) throw new Error('服务端未返回会话 ID')
      return resolvedChatId
    } catch (error) {
      lastError = error as Error
      if ((error as Error & { retryable?: boolean }).retryable === false) throw error
    }
  }
  throw lastError
}

export function confirmCard(
  chatId: number,
  draft: RecordDraft,
  messageId: number | null,
): Promise<{ id: number }> {
  return request(`/chats/${chatId}/confirm`, {
    method: 'POST',
    body: JSON.stringify({ draft, message_id: messageId }),
  })
}

// ---------- 趋势与周报（P2，架构 §7.4） ----------

export interface WeightPoint {
  date: string
  am: number | null
  evening: number | null
}

export interface WeeklySummary {
  week_start: string
  week_end: string
  am_avg: number | null
  am_days: number
  diff_vs_last: number | null
  waist: number | null
  sweet_counts: Record<string, number>
  swim_total_min: number
  swim_times: number
  strength_times: number
  steps_avg: number | null
  verdict: string
}

export interface Baseline {
  start: number
  date: string
  waist: number
  sprint_target: string
}

export interface Trends {
  weights: WeightPoint[]
  waist: { date: string; cm: number | null }[]
  steps: { date: string; steps: number }[]
  sleep: { date: string; bedtime: string | null; minutes: number | null }[]
  sweet: { date: string; level: string; score: number | null }[]
  night_hunger: { date: string; level: string | null }[]
  exercise: { date: string; swim_min: number | null; strength_done: boolean | null }[]
  weekly?: WeeklySummary[]
  baseline?: Baseline
}

export function getTrends(): Promise<Trends> {
  return request('/stats/trends')
}

export type InsightStatus = 'new' | 'adopted' | 'snoozed' | 'completed' | 'dismissed'

export interface InsightActionPlan {
  title: string
  detail: string
  target: string | number
  unit: string
  duration_days: number
  reminder_time: string
}

export interface InsightCard {
  key: string
  kind: 'trend' | 'goal_gap' | 'milestone'
  metric: string
  headline: string
  finding: string
  evidence: string[]
  confidence: {
    level: '较高' | '中等' | '较低'
    coverage: number
    reason: string
  }
  action: InsightActionPlan
  period: { start: string; end: string }
  priority: number
  tone: 'attention' | 'positive' | 'neutral'
  status: InsightStatus
  feedback: 'helpful' | 'not_helpful' | null
  feedback_reason: string | null
  reminder_at: string | null
  updated_at?: string | null
}

export interface InsightsPayload {
  priority: InsightCard[]
  active: InsightCard[]
  history: InsightCard[]
  generated_at: string
  safety_note: string
}

export interface InsightActionPayload {
  action: 'adopt' | 'snooze' | 'adjust' | 'dismiss' | 'feedback' | 'complete' | 'reopen'
  helpful?: boolean
  reason?: string
  reminder_at?: string
  action_plan?: InsightActionPlan
}

export function getInsights(): Promise<InsightsPayload> {
  return request('/stats/insights')
}

export function updateInsight(
  insightKey: string,
  payload: InsightActionPayload,
): Promise<InsightCard> {
  return request(`/stats/insights/${encodeURIComponent(insightKey)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

// ---------- 设置（P3，架构 §7.5/§10-P3） ----------

export interface ChatSummary {
  id: number
  date: string
  title: string
}

export interface UsageInfo {
  provider: {
    id: string
    name: string
    model: string
    base_url: string
    credential_status: string
    is_local: boolean
    configured: boolean
    selected: boolean
    capabilities: ProviderCapabilities
  }
  assistant_messages: number
  usage_coverage: {
    measured_messages: number
    estimated_messages: number
    historical_estimated_messages: number
    unknown_messages: number
    legacy_assistant_rows: number
  }
  tokens: {
    prompt_total: number
    prompt_cache_hit: number
    prompt_cache_miss: number
    completion: number
    total_legacy: number
  }
  cost_yuan: number | null
  price_note: string
}

export interface ProviderCapabilities {
  stream: boolean
  tools: boolean
  json: boolean
}

export interface ProviderEvaluationCase {
  id: string
  label: string
  score: number
  latency_ms: number
  detail: string
}

export interface ProviderEvaluation {
  provider_id: string
  model: string
  score: number
  avg_latency_ms: number
  cases: ProviderEvaluationCase[]
  evaluated_at: string
  dataset: string
}

export interface ProviderInfo {
  id: string
  name: string
  model: string
  base_url: string
  is_local: boolean
  configured: boolean
  selected: boolean
  credential_status: string
  capabilities: ProviderCapabilities
  evaluation: ProviderEvaluation | null
}

export interface ProvidersInfo {
  selected_provider_id: string
  recommended_provider_id: string | null
  selection_note: string
  providers: ProviderInfo[]
  privacy_note: string
}

export interface RagStatus {
  enabled: boolean
  ready: boolean
  points: number
  collection: string
  path: string
  embedding_model: string
  message: string
  keyword_retrieval: string
  fusion: string
  reranker: string
}

export function listChats(): Promise<ChatSummary[]> {
  return request('/chats')
}

export function getUsage(): Promise<UsageInfo> {
  return request('/settings/usage')
}

export function getProviders(): Promise<ProvidersInfo> {
  return request('/settings/providers')
}

export function selectProvider(payload: {
  provider_id: string
  model: string
  allow_cloud_health_data: boolean
}): Promise<ProvidersInfo> {
  return request('/settings/provider', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function testProvider(providerId: string): Promise<{ ok: boolean; message: string }> {
  return request(`/settings/providers/${providerId}/test`, { method: 'POST', body: '{}' })
}

export function evaluateProvider(providerId: string, model: string): Promise<ProviderEvaluation> {
  return request(`/settings/providers/${providerId}/evaluate`, {
    method: 'POST',
    body: JSON.stringify({ model }),
  })
}

export function getRagStatus(): Promise<RagStatus> {
  return request('/settings/rag')
}

export function rebuildRagIndex(): Promise<RagStatus & { ok: boolean; indexed: number }> {
  return request('/settings/rag/reindex', { method: 'POST', body: '{}' })
}

export interface RestoreValidation {
  ok: boolean
  format_version: number
  counts: Record<string, number>
  warnings: string[]
  restored?: boolean
  drill?: {
    database: string
    restored: boolean
    verified_collections: string[]
  }
}

export function validateBackup(backup: Record<string, unknown>): Promise<RestoreValidation> {
  return request('/settings/restore/validate', {
    method: 'POST',
    body: JSON.stringify(backup),
  })
}

export function restoreBackup(backup: Record<string, unknown>): Promise<RestoreValidation> {
  return request('/settings/restore', {
    method: 'POST',
    body: JSON.stringify({ backup, confirmation: 'RESTORE' }),
  })
}
