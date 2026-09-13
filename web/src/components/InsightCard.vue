<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import type { InsightActionPayload, InsightCard as InsightCardData } from '../api'

const props = withDefaults(defineProps<{
  card: InsightCardData
  busy?: boolean
  compact?: boolean
}>(), {
  busy: false,
  compact: false,
})

const emit = defineEmits<{
  action: [key: string, payload: InsightActionPayload, message: string]
}>()

const showSnooze = ref(false)
const showAdjust = ref(false)
const showReasons = ref(false)
const customReminder = ref('')
const form = reactive({
  target: String(props.card.action.target),
  durationDays: props.card.action.duration_days,
  reminderTime: props.card.action.reminder_time,
})

const statusLabel = computed(() => ({
  new: '待处理',
  adopted: '执行中',
  snoozed: '已延期',
  completed: '已完成',
  dismissed: '已忽略',
}[props.card.status]))

function nextAt(time: string, dayOffset = 0): string {
  const [hour, minute] = time.split(':').map(Number)
  const value = new Date()
  value.setDate(value.getDate() + dayOffset)
  value.setHours(hour || 0, minute || 0, 0, 0)
  if (dayOffset === 0 && value.getTime() <= Date.now()) value.setDate(value.getDate() + 1)
  return value.toISOString()
}

function adopt() {
  emit('action', props.card.key, {
    action: 'adopt',
    reminder_at: nextAt(props.card.action.reminder_time),
    action_plan: props.card.action,
  }, `已创建“${props.card.action.title}”行动`)
}

function snooze(offset: number, label: string) {
  const reminderAt = nextAt('20:00', offset)
  emit('action', props.card.key, {
    action: 'snooze',
    reminder_at: reminderAt,
  }, `${label}后会重新置顶（${formatReminder(reminderAt)}）`)
  showSnooze.value = false
}

function snoozeToWeekend() {
  const current = new Date()
  const offset = (6 - current.getDay() + 7) % 7 || 7
  snooze(offset, '周末')
}

function snoozeCustom() {
  if (!customReminder.value) return
  emit('action', props.card.key, {
    action: 'snooze',
    reminder_at: new Date(customReminder.value).toISOString(),
  }, '提醒时间已保存')
  showSnooze.value = false
}

function adjust() {
  const actionPlan = {
    ...props.card.action,
    target: form.target,
    duration_days: Math.max(1, Number(form.durationDays) || 1),
    reminder_time: form.reminderTime,
  }
  emit('action', props.card.key, {
    action: 'adjust',
    reminder_at: nextAt(form.reminderTime),
    action_plan: actionPlan,
  }, '目标已调整并开始执行')
  showAdjust.value = false
}

function feedback(helpful: boolean, reason?: string) {
  emit('action', props.card.key, { action: 'feedback', helpful, reason }, '感谢反馈，后续建议会参考这次选择')
  showReasons.value = false
}

function formatReminder(value: string | null): string {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}
</script>

<template>
  <article class="insight-card" :class="[`tone-${card.tone}`, { compact }]">
    <div class="card-topline">
      <span class="metric">{{ card.metric }}</span>
      <span class="status">{{ statusLabel }}</span>
    </div>

    <h3>{{ card.headline }}</h3>
    <p class="finding">{{ card.finding }}</p>

    <div v-if="!compact" class="confidence-row">
      <span class="confidence" :class="`confidence-${card.confidence.level}`">
        可信度{{ card.confidence.level }}
      </span>
      <span>{{ card.confidence.reason }}</span>
    </div>

    <details v-if="!compact" class="evidence">
      <summary>查看数据依据</summary>
      <ul>
        <li v-for="item in card.evidence" :key="item">{{ item }}</li>
      </ul>
      <p>数据来源：康迹中已确认的个人记录</p>
    </details>

    <div class="action-plan">
      <span class="action-label">建议行动</span>
      <strong>{{ card.action.title }}</strong>
      <p>{{ card.action.detail }}</p>
      <span v-if="card.reminder_at" class="reminder-copy">
        下次提醒：{{ formatReminder(card.reminder_at) }}
      </span>
    </div>

    <div v-if="card.status === 'new' || card.status === 'snoozed'" class="primary-actions">
      <button class="primary" type="button" :disabled="busy" @click="adopt">开始行动</button>
      <button type="button" :disabled="busy" @click="showAdjust = !showAdjust">调整目标</button>
      <button type="button" :disabled="busy" @click="showSnooze = !showSnooze">稍后提醒</button>
    </div>

    <div v-else-if="card.status === 'adopted'" class="primary-actions">
      <button class="primary" type="button" :disabled="busy" @click="emit('action', card.key, { action: 'complete' }, '行动已完成')">
        标记完成
      </button>
      <button type="button" :disabled="busy" @click="showAdjust = !showAdjust">调整目标</button>
    </div>

    <div v-else class="primary-actions">
      <button type="button" :disabled="busy" @click="emit('action', card.key, { action: 'reopen' }, '洞察已重新加入今日重点')">
        重新处理
      </button>
    </div>

    <div v-if="showSnooze" class="inline-panel">
      <p class="panel-title">希望何时再看到这条建议？到期后会在洞察页重新置顶。</p>
      <div class="quick-options">
        <button type="button" @click="snooze(0, '今晚')">今晚</button>
        <button type="button" @click="snooze(1, '明天')">明天</button>
        <button type="button" @click="snoozeToWeekend">周末</button>
      </div>
      <label>
        自定义时间
        <input v-model="customReminder" type="datetime-local" />
      </label>
      <button type="button" :disabled="!customReminder" @click="snoozeCustom">保存提醒</button>
    </div>

    <form v-if="showAdjust" class="inline-panel adjust-grid" @submit.prevent="adjust">
      <label>
        目标值
        <input v-model="form.target" required />
      </label>
      <label>
        持续天数
        <input v-model.number="form.durationDays" type="number" min="1" max="90" required />
      </label>
      <label>
        每日提醒
        <input v-model="form.reminderTime" type="time" required />
      </label>
      <button class="primary" type="submit" :disabled="busy">保存并执行</button>
    </form>

    <div v-if="!compact || (card.status === 'completed' && !card.feedback)" class="feedback-row">
      <template v-if="!card.feedback">
        <span>这条洞察有帮助吗？</span>
        <button type="button" :disabled="busy" @click="feedback(true)">有帮助</button>
        <button type="button" :disabled="busy" @click="showReasons = !showReasons">没帮助</button>
      </template>
      <span v-else>{{ card.feedback === 'helpful' ? '已标记为有帮助' : '已收到你的反馈' }}</span>
      <button
        v-if="card.status === 'new' || card.status === 'snoozed'"
        class="dismiss"
        type="button"
        :disabled="busy"
        @click="emit('action', card.key, { action: 'dismiss' }, '已移入历史回看')"
      >暂不处理</button>
    </div>

    <div v-if="showReasons" class="reason-list">
      <button v-for="reason in ['我已经知道了', '数据不准确', '建议不适合我', '建议太难执行', '结论解释不清楚', '我不想关注这个指标']" :key="reason" type="button" @click="feedback(false, reason)">
        {{ reason }}
      </button>
    </div>
  </article>
</template>

<style scoped>
.insight-card {
  --tone: var(--warn);
  --tone-bg: var(--warn-dim);
  position: relative;
  overflow: hidden;
  padding: 20px;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  background: var(--card);
  box-shadow: var(--shadow-card);
}
.insight-card::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 4px;
  background: var(--tone);
}
.tone-positive { --tone: var(--ok); --tone-bg: var(--ok-dim); }
.tone-neutral { --tone: var(--accent); --tone-bg: var(--accent-dim); }
.card-topline, .confidence-row, .primary-actions, .feedback-row, .quick-options {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.card-topline { justify-content: space-between; }
.metric {
  color: var(--tone);
  font-size: 12px;
  font-weight: 700;
}
.status {
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--tone-bg);
  color: var(--text-dim);
  font-size: 11px;
}
h3 {
  margin: 10px 0 5px;
  color: var(--text);
  font-size: 20px;
  line-height: 1.4;
  letter-spacing: -0.2px;
}
.finding, .action-plan p, .evidence p, .panel-title { margin: 0; }
.finding { color: var(--text-dim); }
.confidence-row {
  margin-top: 13px;
  color: var(--text-faint);
  font-size: 12px;
}
.confidence {
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--bg-soft);
  color: var(--text-dim);
  font-weight: 600;
}
.confidence-较高 { color: var(--ok); background: var(--ok-dim); }
.confidence-较低 { color: var(--warn); background: var(--warn-dim); }
.evidence {
  margin-top: 12px;
  border-top: 1px solid var(--border-soft);
  padding-top: 10px;
  color: var(--text-dim);
  font-size: 13px;
}
.evidence summary { cursor: pointer; color: var(--accent-strong); font-weight: 600; }
.evidence ul { margin: 8px 0 4px; padding-left: 18px; }
.evidence p { color: var(--text-faint); font-size: 11px; }
.action-plan {
  margin-top: 15px;
  padding: 13px 14px;
  border-radius: var(--radius);
  background: var(--tone-bg);
}
.action-label { display: block; color: var(--text-faint); font-size: 11px; }
.action-plan strong { display: block; margin-top: 2px; color: var(--text); }
.action-plan p { margin-top: 2px; color: var(--text-dim); font-size: 13px; }
.reminder-copy { display: block; margin-top: 6px; color: var(--tone); font-size: 12px; font-weight: 600; }
.primary-actions { margin-top: 14px; }
.primary-actions button { white-space: nowrap; }
.inline-panel {
  margin-top: 12px;
  padding: 13px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-soft);
}
.panel-title { margin-bottom: 9px; font-weight: 600; }
.inline-panel label { display: grid; gap: 4px; margin-top: 10px; color: var(--text-dim); font-size: 12px; }
.inline-panel > button { margin-top: 10px; }
.adjust-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; align-items: end; }
.adjust-grid label { margin: 0; }
.adjust-grid button { margin: 0; white-space: nowrap; }
.feedback-row {
  margin-top: 15px;
  padding-top: 12px;
  border-top: 1px solid var(--border-soft);
  color: var(--text-faint);
  font-size: 12px;
}
.feedback-row button { padding: 3px 9px; font-size: 12px; }
.feedback-row .dismiss { margin-left: auto; border-color: transparent; background: transparent; }
.reason-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }
.reason-list button { padding: 4px 9px; font-size: 12px; }
.compact { padding: 15px 16px; box-shadow: none; }
.compact h3 { margin-top: 6px; font-size: 15px; }
.compact .finding { font-size: 13px; }
.compact .action-plan { margin-top: 10px; padding: 10px 11px; }

@media (max-width: 640px) {
  .insight-card { padding: 16px; }
  h3 { font-size: 18px; }
  .primary-actions button { flex: 1 1 auto; }
  .adjust-grid { grid-template-columns: 1fr; }
  .feedback-row .dismiss { margin-left: 0; }
}
</style>
