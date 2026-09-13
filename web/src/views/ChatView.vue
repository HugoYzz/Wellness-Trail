<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import RecordCard from '../components/RecordCard.vue'
import {
  getTrends,
  listChats,
  listMessages,
  sendMessageStream,
  type ChatMessage,
  type ChatSummary,
  type PendingCard,
  type TodayTask,
  type Trends,
} from '../api'
import { useTodoStore } from '../stores/todo'

const todoStore = useTodoStore()

interface Bubble {
  role: 'user' | 'assistant'
  content: string
  cards: PendingCard[]
  streaming?: boolean
}

const bubbles = ref<Bubble[]>([])
const input = ref('')
const sending = ref(false)
const error = ref('')
const chatId = ref<number | null>(null)
const lastAssistantMsgId = ref<number | null>(null)
const scrollEl = ref<HTMLElement | null>(null)
const chats = ref<ChatSummary[]>([])
const trends = ref<Trends | null>(null)
const planBusy = ref(false)
const planError = ref('')
const hasExercise = computed(() =>
  todoStore.items.some(
    (item) => ['swim', 'strength', 'exercise-combo'].includes(item.key) && item.status !== 'skipped',
  ),
)
const todayText = computed(() => {
  const now = new Date()
  return `${now.getMonth() + 1}月${now.getDate()}日`
})
const latestMorningWeight = computed(() => {
  const weights = trends.value?.weights ?? []
  return [...weights].reverse().find((w) => w.am !== null)?.am ?? null
})
const totalDrop = computed(() => {
  const start = trends.value?.baseline?.start
  const last = latestMorningWeight.value
  return start != null && last != null ? start - last : null
})
const totalDropText = computed(() => {
  const v = totalDrop.value
  if (v === null) return '—'
  return `${v >= 0 ? '-' : '+'}${Math.abs(v).toFixed(1)}`
})
const lastWeek = computed(() => trends.value?.weekly?.at(-1) ?? null)
const railSweetSummary = computed(() => {
  const counts = lastWeek.value?.sweet_counts
  if (!counts) return '暂无记录'
  return Object.entries(counts).map(([k, v]) => `${k} × ${v}`).join('  ') || '暂无记录'
})
const trendPolyline = computed(() => {
  const points = (trends.value?.weights ?? []).filter((w) => w.am !== null).slice(-7)
  if (points.length < 2) return '30,98 78,92 126,85 174,76 222,64 270,55 304,48'
  const values = points.map((p) => p.am as number)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const spread = Math.max(max - min, 1)
  return values
    .map((v, i) => {
      const x = 30 + (274 * i) / Math.max(values.length - 1, 1)
      const y = 108 - ((v - min) / spread) * 70
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
})
const trendLabels = computed(() => {
  const points = (trends.value?.weights ?? []).filter((w) => w.am !== null).slice(-7)
  if (!points.length) return ['开始', '中段', '最近']
  const pick = [points[0], points[Math.floor((points.length - 1) / 2)], points[points.length - 1]]
  return pick.map((p) => p.date.slice(5))
})

// 快捷 chips（架构 §7.3）：预填提示语
const chips: { label: string; text: string }[] = [
  { label: '记晨重', text: '今早空腹 ' },
  { label: '记夜重', text: '刚称了下夜重 ' },
  { label: '奶茶', text: '今天喝了' },
  { label: '游泳', text: '游了 分钟泳' },
  { label: '力量', text: '力量训练' },
  { label: '步数', text: '今天走了 步' },
  { label: '入睡', text: '昨晚 睡的' },
  { label: '夜饿', text: '晚上' },
  { label: '补剂', text: '补剂吃了吗' },
  { label: '不适', text: '今天' },
]

// 空会话引导示例（点击直接发送）
const examples = [
  { text: '今早空腹 106.5' },
  { text: '今天喝了半糖奶茶' },
  { text: '复盘一下这周的情况' },
]

function fill(text: string) {
  input.value = text
}

function clickTodo(item: TodayTask) {
  if (['done', 'reported', 'skipped'].includes(item.status)) return
  fill(item.prefill)
}

function taskStatusText(item: TodayTask): string {
  return {
    later: '稍后',
    pending: '待处理',
    done: '已达成',
    reported: '已反馈',
    skipped: '今日不安排',
  }[item.status]
}

async function changePlan(
  action: 'confirm' | 'skip' | 'restore' | 'rest' | 'reset',
  taskKey?: string,
) {
  if (planBusy.value) return
  planBusy.value = true
  planError.value = ''
  try {
    await todoStore.change(action, taskKey)
  } catch (e) {
    planError.value = `调整失败：${(e as Error).message}`
  } finally {
    planBusy.value = false
  }
}

function scrollBottom() {
  nextTick(() => {
    if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
  })
}

async function loadMessages(id: number) {
  const msgs: ChatMessage[] = await listMessages(id)
  bubbles.value = []
  for (const m of msgs) {
    if (m.role === 'user') bubbles.value.push({ role: 'user', content: m.content, cards: [] })
    else if (m.role === 'assistant' && m.content)
      bubbles.value.push({ role: 'assistant', content: m.content, cards: [] })
  }
  scrollBottom()
}

async function init() {
  try {
    chats.value = await listChats()
    const now = new Date()
    const localToday = [
      now.getFullYear(),
      String(now.getMonth() + 1).padStart(2, '0'),
      String(now.getDate()).padStart(2, '0'),
    ].join('-')
    const todayChat = chats.value.find((chat) => chat.date === localToday)
    if (todayChat) {
      chatId.value = todayChat.id
      todayChatId.value = todayChat.id
      await loadMessages(todayChat.id)
    } else {
      chatId.value = null
      todayChatId.value = null
      bubbles.value = []
    }
    try {
      trends.value = await getTrends()
    } catch {
      trends.value = null
    }
    // 待办条预填（点击待办项跳转过来）
    const pre = todoStore.consumePrefill()
    if (pre) input.value = pre
  } catch (e) {
    error.value = `连接后端失败：${(e as Error).message}`
  }
}

/** 切换历史会话 */
async function switchChat(id: number) {
  if (sending.value || id === chatId.value) return
  chatId.value = id
  error.value = ''
  try {
    await loadMessages(id)
  } catch (e) {
    error.value = `加载会话失败：${(e as Error).message}`
  }
}

const todayChatId = ref<number | null>(null)

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
  input.value = ''
  error.value = ''
  sending.value = true

  bubbles.value.push({ role: 'user', content: text, cards: [] })
  const ai = reactive<Bubble>({ role: 'assistant', content: '', cards: [], streaming: true })
  bubbles.value.push(ai)
  scrollBottom()

  try {
    const resolvedChatId = await sendMessageStream(chatId.value, text, {
      onMeta: (meta) => {
        chatId.value = meta.chat_id
      },
      onRetry: () => {
        error.value = '连接中断，正在从上次位置续传…'
      },
      onToken: (t) => {
        error.value = ''
        ai.content += t
        scrollBottom()
      },
      onCard: (card) => {
        ai.cards.push(card)
        scrollBottom()
      },
      onDone: (done) => {
        if (done.error) error.value = done.error
        lastAssistantMsgId.value = done.message_id ?? null
      },
    })
    chatId.value = resolvedChatId
    chats.value = await listChats()
    const now = new Date()
    const localToday = [
      now.getFullYear(),
      String(now.getMonth() + 1).padStart(2, '0'),
      String(now.getDate()).padStart(2, '0'),
    ].join('-')
    todayChatId.value = chats.value.find((chat) => chat.date === localToday)?.id ?? null
  } catch (e) {
    error.value = `发送失败：${(e as Error).message}`
  } finally {
    ai.streaming = false
    sending.value = false
    scrollBottom()
  }
}

function onConfirmed(card: PendingCard) {
  card.status = 'confirmed'
  window.dispatchEvent(new Event('kangji-refresh-todo'))
}

function onRejected(card: PendingCard) {
  card.status = 'rejected'
}

onMounted(init)

// 已在聊天页时点击待办条 → 直接填入输入框
watch(
  () => todoStore.prefill,
  (v) => {
    if (v) input.value = todoStore.consumePrefill()
  },
)
</script>

<template>
  <div class="workspace">
    <section class="chat-panel">
      <div class="panel-head">
        <div>
          <p class="eyebrow">{{ todayText }} · 对话记录</p>
          <h2>说句话就能记</h2>
        </div>
        <span class="safety-note">本工具不做疾病诊断</span>
      </div>

      <!-- 历史会话切换（§7.1：历史会话按天列表） -->
      <div v-if="chats.length" class="chat-switch">
        <span class="switch-label">会话</span>
        <button
          v-for="c in chats"
          :key="c.id"
          class="chat-tab"
          :class="{ active: c.id === chatId, today: c.id === todayChatId }"
          @click="switchChat(c.id)"
        >
          {{ c.date.slice(5) }}{{ c.id === todayChatId ? ' 今天' : '' }}
        </button>
      </div>

      <div ref="scrollEl" class="messages">
        <!-- 空会话引导：给第一次打开的落地感 -->
        <div v-if="!bubbles.length && !error" class="empty">
          <svg viewBox="0 0 24 24" width="48" height="48" aria-hidden="true" class="empty-icon">
            <rect x="1" y="1" width="22" height="22" rx="7" fill="url(#ke)" />
            <path
              d="M5.5 12.5h3l1.8-4.2 2.6 7.4 1.8-3.2h4"
              fill="none"
              stroke="#fff"
              stroke-width="1.9"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
            <defs>
              <linearGradient id="ke" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stop-color="#48bb78" />
                <stop offset="1" stop-color="#2563eb" />
              </linearGradient>
            </defs>
          </svg>
          <h3 class="empty-title">今天先从一句话开始</h3>
          <p class="empty-sub">体重、饮食、运动、睡眠都可以直接说，我会整理成待确认记录。</p>
          <div class="empty-examples">
            <button v-for="ex in examples" :key="ex.text" class="empty-chip" @click="fill(ex.text)">
              {{ ex.text }}
            </button>
          </div>
        </div>

        <div v-for="(b, i) in bubbles" :key="i" class="msg" :class="b.role">
          <div class="bubble" :class="{ streaming: b.streaming && !b.content }">
            {{ b.content }}<span v-if="b.streaming" class="cursor">▋</span>
          </div>
          <div v-for="(c, j) in b.cards" :key="j" class="card-wrap">
            <RecordCard
              :card="c"
              :chat-id="chatId ?? 0"
              :message-id="lastAssistantMsgId"
              @confirmed="onConfirmed(c)"
              @rejected="onRejected(c)"
            />
          </div>
        </div>
        <p v-if="error" class="error">{{ error }}</p>
      </div>

      <div class="composer-card">
        <div class="composer">
          <textarea
            v-model="input"
            rows="2"
            placeholder="一句话记录：今早空腹 106.5，昨晚 00:30 睡的"
            :disabled="sending"
            @keydown.enter.exact.prevent="send"
          />
          <button class="primary send" :disabled="sending || !input.trim()" @click="send">
            <svg
              viewBox="0 0 24 24"
              width="18"
              height="18"
              aria-hidden="true"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z" />
            </svg>
          </button>
        </div>
        <div class="chips">
          <span class="quick-label">快捷记录</span>
          <button v-for="c in chips" :key="c.label" class="chip" @click="fill(c.text)">
            {{ c.label }}
          </button>
        </div>
      </div>
    </section>

    <aside class="insight-rail">
      <section id="today-plan" class="rail-card todo-card">
        <div class="rail-head">
          <div>
            <p class="rail-kicker">个性化安排</p>
            <h3>今日计划</h3>
          </div>
          <span v-if="todoStore.plan">
            {{ todoStore.plan.progress.handled }}/{{ todoStore.plan.progress.active }} 已处理
          </span>
        </div>
        <p v-if="todoStore.plan" class="plan-summary">{{ todoStore.plan.summary }}</p>
        <div v-if="todoStore.loading && !todoStore.plan" class="plan-loading">正在生成今天的计划…</div>
        <template v-else>
          <div
            v-for="item in todoStore.items.filter((value) => value.status !== 'skipped')"
            :key="item.key"
            class="rail-todo"
            :class="item.status"
          >
            <button class="plan-main" type="button" @click="clickTodo(item)">
              <span class="check">{{ item.status === 'done' ? '✓' : item.status === 'reported' ? '·' : '' }}</span>
              <span class="plan-copy">
                <span class="plan-title">
                  {{ item.label }}
                  <small class="source-tag">{{ item.source_label }}</small>
                </span>
                <small>{{ item.detail }} · {{ item.time_window.label }}</small>
                <small class="plan-reason">{{ item.reason }}</small>
              </span>
              <span class="status-label">{{ taskStatusText(item) }}</span>
            </button>
            <button
              v-if="item.status === 'pending' || item.status === 'later'"
              class="plan-skip"
              type="button"
              :disabled="planBusy"
              :aria-label="`${item.label}今日不安排`"
              @click="changePlan('skip', item.key)"
            >
              不安排
            </button>
          </div>
        </template>

        <p v-if="todoStore.plan?.safety_note" class="plan-safety">{{ todoStore.plan.safety_note }}</p>
        <p v-if="planError" class="plan-error">{{ planError }}</p>

        <div v-if="todoStore.plan && !todoStore.plan.confirmed" class="plan-confirm-row">
          <button type="button" :disabled="planBusy" @click="changePlan('confirm')">确认今日计划</button>
          <button
            v-if="hasExercise"
            type="button"
            class="secondary"
            :disabled="planBusy"
            @click="changePlan('rest')"
          >
            运动改休息
          </button>
        </div>

        <div v-if="todoStore.plan?.progress.skipped" class="skipped-tasks">
          <span>今日不安排 {{ todoStore.plan.progress.skipped }} 项</span>
          <button
            v-for="item in todoStore.items.filter((value) => value.status === 'skipped')"
            :key="item.key"
            type="button"
            :disabled="planBusy"
            @click="changePlan('restore', item.key)"
          >
            恢复「{{ item.label }}」
          </button>
        </div>
      </section>

      <section class="rail-card metric-grid">
        <div class="metric">
          <span>今晨体重</span>
          <strong>{{ latestMorningWeight?.toFixed(1) ?? '—' }}</strong>
          <small>{{ latestMorningWeight !== null ? 'kg' : '待记录' }}</small>
        </div>
        <div class="metric good">
          <span>累计变化</span>
          <strong>{{ totalDropText }}</strong>
          <small>{{ totalDrop !== null ? 'kg' : '待计算' }}</small>
        </div>
      </section>

      <section class="rail-card tea-card">
        <div>
          <h3>本周奶茶</h3>
          <p>{{ railSweetSummary }}</p>
        </div>
        <span>戒断进度</span>
      </section>

      <section class="rail-card trend-card">
        <div class="rail-head">
          <h3>体重趋势（近 7 天）</h3>
          <span>kg</span>
        </div>
        <svg viewBox="0 0 320 150" role="img" aria-label="近 7 天体重趋势" class="trend-svg">
          <path d="M20 126H304M20 92H304M20 58H304M20 24H304" class="grid-line" />
          <polyline :points="trendPolyline" class="trend-line" />
          <text x="26" y="144">{{ trendLabels[0] }}</text>
          <text x="146" y="144">{{ trendLabels[1] }}</text>
          <text x="276" y="144">{{ trendLabels[2] }}</text>
        </svg>
      </section>

    </aside>
  </div>
</template>

<style scoped>
.workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 24px;
  align-items: start;
}
.chat-panel {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: calc(100dvh - 176px);
  background: rgba(255, 255, 255, 0.84);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: 18px;
}
.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}
.eyebrow {
  margin: 0 0 2px;
  color: var(--text-faint);
  font-size: 12px;
  font-weight: 700;
}
.panel-head h2 {
  margin: 0;
  font-size: 25px;
}
.safety-note {
  color: var(--text-dim);
  background: var(--bg-soft);
  border: 1px solid var(--border-soft);
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
  white-space: nowrap;
}

/* ---------- 会话切换 ---------- */
.chat-switch {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
}
.switch-label {
  font-size: 11px;
  color: var(--text-faint);
  font-weight: 700;
}
.chat-tab {
  font-size: 12px;
  padding: 3px 11px;
  border-radius: 999px;
  color: var(--text-dim);
  background: #fff;
}
.chat-tab.active {
  color: var(--accent-strong);
  border-color: var(--accent);
  background: var(--accent-dim);
}
.chat-tab.today:not(.active) {
  color: var(--accent);
}

/* ---------- 消息流 ---------- */
.messages {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 10px 4px;
  scroll-behavior: smooth;
}
.msg {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.msg.user {
  align-items: flex-end;
}
.msg.assistant {
  align-items: flex-start;
}
.bubble {
  max-width: 86%;
  border-radius: 14px;
  padding: 10px 14px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  animation: rise 0.18s var(--ease);
  box-shadow: 0 1px 2px rgba(22, 33, 43, 0.04);
}
@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
}
.msg.user .bubble {
  background: linear-gradient(135deg, #2f78f4, #2563eb);
  color: #fff;
  border-bottom-right-radius: 4px;
}
.msg.assistant .bubble {
  background: #fff;
  border: 1px solid var(--border);
  border-bottom-left-radius: 4px;
}
.bubble.streaming:empty::after {
  content: '…';
  color: var(--text-dim);
}
.cursor {
  animation: blink 1s infinite;
  color: var(--accent);
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}
.card-wrap {
  width: 100%;
  max-width: 760px;
}

/* ---------- 空状态 ---------- */
.empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  text-align: center;
  padding: 34px 0 42px;
}
.empty-icon {
  filter: drop-shadow(0 12px 20px rgba(37, 99, 235, 0.16));
  margin-bottom: 8px;
}
.empty-title {
  margin: 0;
  font-size: 19px;
  font-weight: 700;
  letter-spacing: 0;
}
.empty-sub {
  margin: 0;
  color: var(--text-dim);
  font-size: 13px;
}
.empty-examples {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 7px;
  margin-top: 14px;
}
.empty-chip {
  font-size: 13px;
  padding: 5px 14px;
  border-radius: 999px;
  color: var(--text-dim);
  background: #fff;
  border: 1px dashed var(--border);
}
.empty-chip:hover {
  color: var(--accent-strong);
  border-color: var(--accent);
  border-style: solid;
}

/* ---------- 输入区（卡片化） ---------- */
.composer-card {
  background: #fff;
  border: 1px solid rgba(37, 99, 235, 0.2);
  border-radius: var(--radius-lg);
  padding: 10px 12px 12px;
  box-shadow: 0 14px 34px rgba(37, 99, 235, 0.1);
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  align-items: center;
}
.quick-label {
  color: var(--text-dim);
  font-size: 13px;
  margin-right: 4px;
}
.chip {
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 12.5px;
  color: var(--text-dim);
  background: var(--bg-soft);
}
.chip:hover {
  color: var(--text);
  border-color: var(--accent);
}
.composer {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
.composer textarea {
  flex: 1;
  resize: none;
  background: #fff;
  border-radius: 10px;
  border-color: transparent;
}
.send {
  height: 54px;
  width: 54px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
}
.send:disabled {
  background: var(--bg-soft);
  border-color: var(--border);
  color: var(--text-faint);
  box-shadow: none;
}

/* ---------- 其他 ---------- */
.foot-hint {
  margin: 0;
  font-size: 11px;
  color: var(--text-faint);
  text-align: center;
}
.error {
  color: var(--danger);
  font-size: 13px;
  margin: 0;
}
.insight-rail {
  display: flex;
  flex-direction: column;
  gap: 14px;
  position: sticky;
  top: 126px;
}
.rail-card {
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  padding: 16px;
  box-shadow: var(--shadow-card);
}
.rail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.rail-head h3,
.tea-card h3,
.compact h3 {
  margin: 0;
  color: var(--text);
  font-size: 15px;
  letter-spacing: 0;
}
.rail-head span,
.tea-card span {
  color: var(--text-dim);
  font-size: 12px;
}
.todo-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.rail-kicker {
  margin: 0 0 2px;
  color: var(--accent-strong);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.plan-summary,
.plan-loading {
  margin: -3px 0 3px;
  color: var(--text-dim);
  font-size: 12px;
  line-height: 1.45;
}
.rail-todo {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 4px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 10px;
  padding: 3px;
}
.rail-todo:hover {
  background: var(--bg-soft);
}
.plan-main {
  min-width: 0;
  flex: 1;
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
  padding: 6px 5px;
  border: 0;
  background: transparent;
  text-align: left;
}
.plan-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.plan-title {
  color: var(--text);
  font-size: 13px;
  font-weight: 650;
}
.source-tag {
  margin-left: 4px;
  padding: 1px 5px;
  border-radius: 999px;
  color: var(--accent-strong);
  background: var(--accent-dim);
  font-size: 9px;
  font-weight: 700;
}
.plan-copy > small {
  color: var(--text-faint);
  font-size: 10.5px;
}
.plan-copy .plan-reason {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.status-label {
  color: var(--text-faint);
  font-size: 10px;
  white-space: nowrap;
}
.rail-todo .check {
  width: 18px;
  height: 18px;
  border: 1px solid var(--border);
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 12px;
}
.rail-todo.done .check {
  background: var(--ok);
  border-color: var(--ok);
}
.rail-todo.reported .check {
  color: #9a6700;
  border-color: rgba(154, 103, 0, 0.35);
  background: #fff7d6;
}
.rail-todo.later {
  opacity: 0.78;
}
.plan-skip {
  flex: none;
  padding: 4px 6px;
  border: 0;
  background: transparent;
  color: var(--text-faint);
  font-size: 10px;
}
.plan-skip:hover {
  color: var(--text);
  background: #fff;
}
.plan-confirm-row {
  display: flex;
  gap: 7px;
  margin-top: 4px;
}
.plan-confirm-row button {
  flex: 1;
  padding: 7px 9px;
  font-size: 11px;
}
.plan-confirm-row .secondary {
  color: var(--text-dim);
  background: var(--bg-soft);
  border-color: var(--border);
}
.plan-safety,
.plan-error {
  margin: 2px 0 0;
  padding: 7px 9px;
  border-radius: 8px;
  font-size: 11px;
  line-height: 1.45;
}
.plan-safety {
  color: #7a4f00;
  background: #fff7d6;
}
.plan-error {
  color: var(--danger);
  background: rgba(220, 38, 38, 0.07);
}
.skipped-tasks {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  padding-top: 3px;
  color: var(--text-faint);
  font-size: 10px;
}
.skipped-tasks button {
  padding: 2px 6px;
  color: var(--text-dim);
  background: transparent;
  border-color: var(--border-soft);
  font-size: 10px;
}
.metric-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.metric + .metric {
  border-left: 1px solid var(--border-soft);
  padding-left: 14px;
}
.metric span,
.metric small {
  display: block;
  color: var(--text-dim);
  font-size: 12px;
}
.metric strong {
  display: inline-block;
  color: var(--accent);
  font-size: 34px;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}
.metric.good strong {
  color: var(--ok);
}
.tea-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.tea-card p {
  margin: 6px 0 0;
  color: var(--text);
  font-size: 18px;
  font-weight: 700;
}
.trend-svg {
  width: 100%;
  height: auto;
  display: block;
}
.grid-line {
  fill: none;
  stroke: #e8f0eb;
  stroke-width: 1;
}
.trend-line {
  fill: none;
  stroke: var(--accent);
  stroke-width: 3;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.trend-points circle {
  fill: #fff;
  stroke: var(--accent);
  stroke-width: 3;
}
.trend-svg text {
  fill: var(--text-faint);
  font-size: 12px;
}
.compact {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.compact-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--text-dim);
}
.compact-row strong {
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 960px) {
  .workspace {
    grid-template-columns: 1fr;
  }
  .insight-rail {
    position: static;
    order: -1;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .todo-card,
  .trend-card {
    grid-column: 1 / -1;
  }
}

@media (max-width: 600px) {
  .chat-panel {
    padding: 14px;
    min-height: calc(100dvh - 210px);
  }
  .panel-head {
    flex-direction: column;
  }
  .safety-note {
    white-space: normal;
  }
  .bubble {
    max-width: 92%;
  }
  .chip {
    padding: 3px 9px;
    font-size: 12px;
  }
  .send {
    height: 50px;
    width: 50px;
  }
  .insight-rail {
    grid-template-columns: 1fr;
    order: 0;
  }
  .metric strong {
    font-size: 28px;
  }
}
</style>
