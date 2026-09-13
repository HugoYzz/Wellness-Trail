<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import type { PendingCard, RecordDraft } from '../api'
import { confirmCard } from '../api'
import {
  BODY_SITES,
  NIGHT_HUNGER_LEVELS,
  SLOT_LABELS,
  SUPPLEMENT_ITEMS,
  SUPPLEMENT_TIMINGS,
  SWEET_LEVELS,
  TYPE_LABELS,
} from '../labels'

const props = defineProps<{ card: PendingCard; chatId: number; messageId: number | null }>()
const emit = defineEmits<{ (e: 'confirmed', recordId: number): void; (e: 'rejected'): void }>()

const draft = reactive<RecordDraft>({ ...props.card.draft, fields: { ...props.card.draft.fields } })
const error = ref('')
const busy = ref(false)

const slotsByType: Record<string, string[]> = {
  weight: ['am', 'evening'],
  meal: ['breakfast', 'lunch', 'dinner', 'snack'],
}

const slotOptions = computed(() => slotsByType[draft.type] ?? [])

interface FieldSpec {
  key: string
  label: string
  kind: 'number' | 'text' | 'select'
  options?: readonly string[]
}

const fieldSpecs = computed<FieldSpec[]>(() => {
  const t = draft.type
  if (t === 'weight') return [{ key: 'kg', label: '体重 (kg)', kind: 'number' }]
  if (t === 'sleep') return [{ key: 'bedtime', label: '入睡时间', kind: 'text' }]
  if (t === 'meal') return [{ key: 'desc', label: '内容', kind: 'text' }]
  if (t === 'sweet_drink')
    return [
      { key: 'level', label: '档位', kind: 'select', options: SWEET_LEVELS },
      { key: 'desc', label: '具体', kind: 'text' },
    ]
  if (t === 'night_hunger')
    return [{ key: 'level', label: '处理', kind: 'select', options: NIGHT_HUNGER_LEVELS }]
  if (t === 'exercise')
    return [
      { key: 'kind', label: '类型', kind: 'select', options: ['swim', 'strength'] },
      { key: 'duration_min', label: '时长 (分)', kind: 'number' },
      { key: 'done', label: '完成(是/否)', kind: 'select', options: ['是', '否'] },
    ]
  if (t === 'step') return [{ key: 'steps', label: '步数', kind: 'number' }]
  if (t === 'waist') return [{ key: 'cm', label: '腰围 (cm)', kind: 'number' }]
  if (t === 'supplement')
    return [
      { key: 'item', label: '补剂', kind: 'select', options: SUPPLEMENT_ITEMS },
      { key: 'dose', label: '剂量', kind: 'text' },
      { key: 'timing', label: '时点', kind: 'select', options: SUPPLEMENT_TIMINGS },
      { key: 'taken', label: '已服(是/否)', kind: 'select', options: ['是', '否'] },
    ]
  if (t === 'body')
    return [
      { key: 'site', label: '部位', kind: 'select', options: BODY_SITES },
      { key: 'level', label: '评分', kind: 'number' },
      { key: 'symptom', label: '症状', kind: 'text' },
    ]
  if (t === 'note') return [{ key: 'text', label: '内容', kind: 'text' }]
  return []
})

async function confirm() {
  busy.value = true
  error.value = ''
  try {
    // 布尔字段转换
    const fields = { ...draft.fields }
    if (draft.type === 'exercise' && fields.done !== undefined)
      fields.done = fields.done === '是' || fields.done === true
    if (draft.type === 'supplement' && fields.taken !== undefined)
      fields.taken = fields.taken === '是' || fields.taken === true
    const result = await confirmCard(props.chatId, { ...draft, fields }, props.messageId)
    emit('confirmed', result.id)
  } catch (e) {
    error.value = String((e as Error).message)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="card" :class="{ done: card.status !== 'pending' }">
    <div class="card-head">
      <span class="badge">{{ TYPE_LABELS[draft.type] ?? draft.type }}</span>
      <span v-if="draft.slot && slotOptions.length" class="slot">
        <select v-model="draft.slot">
          <option v-for="s in slotOptions" :key="s" :value="s">{{ SLOT_LABELS[s] ?? s }}</option>
        </select>
      </span>
      <span class="date">
        <input v-model="draft.date" type="date" />
      </span>
    </div>

    <div class="fields">
      <label v-for="f in fieldSpecs" :key="f.key" class="field">
        <span class="fl">{{ f.label }}</span>
        <select v-if="f.kind === 'select'" v-model="draft.fields[f.key]">
          <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
        </select>
        <input
          v-else
          v-model="draft.fields[f.key]"
          :type="f.kind === 'number' ? 'number' : 'text'"
          :step="f.kind === 'number' ? 'any' : undefined"
        />
      </label>
    </div>

    <p v-if="draft.raw_text" class="raw">"{{ draft.raw_text }}"</p>
    <p v-for="w in card.warnings" :key="w" class="warn">提醒：{{ w }}</p>
    <p v-if="error" class="error">{{ error }}</p>

    <div v-if="card.status === 'pending'" class="actions">
      <button class="primary" :disabled="busy" @click="confirm">
        {{ busy ? '入账中…' : '确认入账' }}
      </button>
      <button :disabled="busy" @click="emit('rejected')">不要了</button>
    </div>
    <div v-else-if="card.status === 'confirmed'" class="status ok">✓ 已入账</div>
    <div v-else class="status dim">已放弃</div>
  </div>
</template>

<style scoped>
.card {
  border: 1px solid rgba(22, 163, 74, 0.22);
  border-radius: var(--radius);
  background:
    linear-gradient(180deg, rgba(240, 248, 244, 0.9), rgba(255, 255, 255, 0.96)),
    var(--card);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 11px;
  max-width: 100%;
  box-shadow: var(--shadow-card);
  animation: rise 0.2s var(--ease);
}
@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
}
.card.done {
  opacity: 0.72;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.badge {
  font-size: 12px;
  font-weight: 600;
  color: var(--ok);
  background: var(--ok-dim);
  border: 1px solid rgba(22, 163, 74, 0.16);
  border-radius: 8px;
  padding: 3px 10px;
}
.slot select,
.date input {
  font-size: 12px;
  padding: 4px 7px;
}
.fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.fl {
  font-size: 11px;
  color: var(--text-faint);
}
.field input,
.field select {
  padding: 5px 9px;
}
.raw {
  margin: 0;
  font-size: 12px;
  color: var(--text-faint);
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-sm);
  padding: 6px 9px;
}
.warn {
  margin: 0;
  font-size: 13px;
  color: var(--warn);
  background: var(--warn-dim);
  border-radius: var(--radius-sm);
  padding: 5px 10px;
}
.error {
  margin: 0;
  font-size: 13px;
  color: var(--danger);
}
.actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
.status {
  font-size: 13px;
  font-weight: 600;
}
.status.ok {
  color: var(--ok);
}
.status.dim {
  color: var(--text-faint);
}
</style>
