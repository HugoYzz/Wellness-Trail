<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createRecord, getRecord, updateRecord } from '../api'
import DailyRecordTable from '../components/DailyRecordTable.vue'
import {
  BODY_SITES,
  NIGHT_HUNGER_LEVELS,
  SLOT_LABELS,
  SUPPLEMENT_ITEMS,
  SUPPLEMENT_TIMINGS,
  SWEET_LEVELS,
  TYPE_LABELS,
  type RecordItem,
} from '../labels'

interface FieldDef {
  key: string
  label: string
  kind: 'number' | 'text' | 'textarea' | 'select' | 'time' | 'bool'
  options?: readonly string[]
  min?: number
  max?: number
  step?: number
  required?: boolean
  placeholder?: string
  showIf?: (fields: Record<string, unknown>) => boolean
}

interface TypeDef {
  slots: string[]
  fields: FieldDef[]
}

// 表单定义（与后端 schemas.py §2.3 对齐）
const DEFS: Record<string, TypeDef> = {
  weight: {
    slots: ['am', 'evening'],
    fields: [
      { key: 'kg', label: '体重 (kg)', kind: 'number', min: 40, max: 200, step: 0.05, required: true, placeholder: '如 106.4' },
      { key: 'note', label: '备注', kind: 'text' },
    ],
  },
  sleep: {
    slots: [],
    fields: [{ key: 'bedtime', label: '入睡时间（躺下时刻，跨零点照实填）', kind: 'time', required: true }],
  },
  meal: {
    slots: ['breakfast', 'lunch', 'dinner', 'snack'],
    fields: [{ key: 'desc', label: '吃了什么', kind: 'textarea', required: true, placeholder: '如 两个水煮蛋+三分之一手抓饼' }],
  },
  sweet_drink: {
    slots: [],
    fields: [
      { key: 'level', label: '档位', kind: 'select', options: SWEET_LEVELS, required: true },
      { key: 'desc', label: '具体是什么', kind: 'text', placeholder: '如 焦糖海盐拿铁590ml' },
    ],
  },
  night_hunger: {
    slots: [],
    fields: [{ key: 'level', label: '处理结果', kind: 'select', options: NIGHT_HUNGER_LEVELS, required: true }],
  },
  exercise: {
    slots: [],
    fields: [
      { key: 'kind', label: '类型', kind: 'select', options: ['swim', 'strength'], required: true },
      { key: 'duration_min', label: '时长 (分钟)', kind: 'number', min: 0, max: 300, required: true, showIf: (f) => f.kind === 'swim' },
      { key: 'done', label: '完成了吗', kind: 'select', options: ['完成', '未做'], required: true, showIf: (f) => f.kind === 'strength' },
    ],
  },
  step: {
    slots: [],
    fields: [{ key: 'steps', label: '步数', kind: 'number', min: 0, max: 50000, required: true }],
  },
  waist: {
    slots: [],
    fields: [{ key: 'cm', label: '腰围 (cm)', kind: 'number', min: 50, max: 200, step: 0.5, required: true }],
  },
  supplement: {
    slots: [],
    fields: [
      { key: 'item', label: '补剂', kind: 'select', options: SUPPLEMENT_ITEMS, required: true },
      { key: 'dose', label: '剂量', kind: 'text', required: true, placeholder: '如 2000IU / 15-25mg' },
      { key: 'timing', label: '服用时点', kind: 'select', options: SUPPLEMENT_TIMINGS, required: true },
      { key: 'taken', label: '已服用', kind: 'bool' },
    ],
  },
  body: {
    slots: [],
    fields: [
      { key: 'site', label: '部位', kind: 'select', options: BODY_SITES, required: true },
      { key: 'level', label: '不适评分 (1-10)', kind: 'number', min: 1, max: 10 },
      { key: 'symptom', label: '症状描述', kind: 'text' },
    ],
  },
  note: {
    slots: [],
    fields: [{ key: 'text', label: '内容', kind: 'textarea', required: true, placeholder: '如 出差' }],
  },
}

const route = useRoute()
const router = useRouter()

const today = new Date().toISOString().slice(0, 10)

const form = reactive({
  type: (route.query.type as string) || 'weight',
  date: today,
  slot: (route.query.slot as string) || '',
  // 动态表单字段容器（按类型挂任意键，提交时转换）
  fields: {} as Record<string, any>,
})

const def = computed(() => DEFS[form.type])
const error = ref('')
const warnings = ref<string[]>([])
const saved = ref<RecordItem | null>(null)
const historyVersion = ref(0)
const editingId = computed(() => {
  const value = Number(route.query.edit)
  return Number.isInteger(value) && value > 0 ? value : null
})
const loadingEdit = ref(false)
const originalRawText = ref('')

async function loadEdit() {
  if (editingId.value === null) return
  loadingEdit.value = true
  error.value = ''
  try {
    const record = await getRecord(editingId.value)
    form.type = record.type
    form.date = record.date
    form.slot = record.slot ?? ''
    form.fields = { ...record.fields }
    if (record.type === 'exercise' && typeof form.fields.done === 'boolean') {
      form.fields.done = form.fields.done ? '完成' : '未做'
    }
    originalRawText.value = record.raw_text
  } catch (e) {
    error.value = `加载待修改记录失败：${(e as Error).message}`
  } finally {
    loadingEdit.value = false
  }
}

function switchType(t: string) {
  form.type = t
  form.slot = DEFS[t].slots[0] ?? ''
  form.fields = {}
  error.value = ''
  warnings.value = []
  saved.value = null
}

function visible(f: FieldDef): boolean {
  return !f.showIf || f.showIf(form.fields)
}

function boolValue(key: string): boolean {
  return form.fields[key] !== false
}

async function submit() {
  error.value = ''
  warnings.value = []
  saved.value = null

  const fields: Record<string, unknown> = {}
  for (const f of def.value.fields) {
    if (!visible(f)) continue
    const raw = form.fields[f.key]
    if (raw === undefined || raw === '') {
      if (f.required) {
        error.value = `请填写「${f.label}」`
        return
      }
      continue
    }
    fields[f.key] = f.kind === 'number' ? Number(raw) : raw
  }
  // 布尔默认值：补剂 taken 未改时视为 true
  if (form.type === 'supplement' && fields.taken === undefined) fields.taken = true
  // 力量训练 done：中文选项转布尔
  if (form.type === 'exercise' && fields.done !== undefined) {
    fields.done = fields.done === '完成'
  }

  try {
    const payload = {
      type: form.type,
      date: form.date,
      slot: def.value.slots.length ? form.slot || null : null,
      fields,
      raw_text: originalRawText.value,
    }
    const res = editingId.value === null
      ? await createRecord({ ...payload, source: 'manual' })
      : await updateRecord(editingId.value, payload)
    saved.value = res
    warnings.value = res.warnings ?? []
    if (editingId.value === null) form.fields = {}
    historyVersion.value += 1
    // 同步刷新顶栏待办条（今日新增记录 → 对应项 ✓）
    window.dispatchEvent(new Event('kangji-refresh-todo'))
  } catch (e) {
    error.value = String((e as Error).message)
  }
}

function goTimeline() {
  router.push('/timeline')
}

function cancelEdit() {
  router.replace('/record')
  form.type = 'weight'
  form.date = today
  form.slot = 'am'
  form.fields = {}
  originalRawText.value = ''
  saved.value = null
  error.value = ''
}

onMounted(loadEdit)
</script>

<template>
  <div class="record-page">
    <header class="page-intro">
      <div>
        <p class="eyebrow">HEALTH LOG</p>
        <h1>记录</h1>
        <p>随手记下一项，也能从整天的视角看到生活节奏。</p>
      </div>
      <button type="button" class="timeline-link" @click="goTimeline">查看完整时间线 →</button>
    </header>

    <div class="record-workspace">
      <section class="entry-panel">
        <div class="panel-head">
          <span class="step-number">01</span>
          <div>
            <h2>{{ editingId === null ? '手动记录' : `修改记录 #${editingId}` }}</h2>
            <p>{{ editingId === null ? '选择类型并填写本次数据' : '可纠正类型、日期、时槽和具体内容' }}</p>
          </div>
        </div>

        <div class="types">
          <button
            v-for="(label, t) in TYPE_LABELS"
            :key="t"
            :class="['chip', { active: form.type === t }]"
            @click="switchType(String(t))"
          >
            {{ label }}
          </button>
        </div>

        <div class="form">
          <label>
            <span>日期</span>
            <input v-model="form.date" type="date" />
          </label>

          <label v-if="def.slots.length">
            <span>时槽</span>
            <select v-model="form.slot">
              <option v-for="s in def.slots" :key="s" :value="s">{{ SLOT_LABELS[s] ?? s }}</option>
            </select>
          </label>

          <template v-for="f in def.fields" :key="f.key">
            <label v-if="visible(f)">
              <span>{{ f.label }}<em v-if="f.required">*</em></span>
              <select v-if="f.kind === 'select'" v-model="form.fields[f.key]">
                <option value="" disabled>请选择</option>
                <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
              </select>
              <textarea
                v-else-if="f.kind === 'textarea'"
                v-model="form.fields[f.key]"
                :placeholder="f.placeholder"
                rows="2"
              />
              <input
                v-else-if="f.kind === 'bool'"
                type="checkbox"
                :checked="boolValue(f.key)"
                @change="form.fields[f.key] = ($event.target as HTMLInputElement).checked"
              />
              <input
                v-else
                v-model="form.fields[f.key]"
                :type="f.kind === 'number' ? 'number' : f.kind === 'time' ? 'time' : 'text'"
                :min="f.min"
                :max="f.max"
                :step="f.step"
                :placeholder="f.placeholder"
              />
            </label>
          </template>

          <div class="actions">
            <button class="primary" :disabled="loadingEdit" @click="submit">
              {{ loadingEdit ? '正在加载…' : editingId === null ? '保存入账' : '保存修改' }}
            </button>
            <button v-if="editingId !== null" @click="cancelEdit">取消</button>
          </div>

          <p v-if="error" class="error">{{ error }}</p>
          <p v-for="w in warnings" :key="w" class="warn">⚠ {{ w }}</p>
          <p v-if="saved" class="ok">
            {{ editingId === null ? '已入账' : '已修改' }}（#{{ saved.id }}），右侧每日记录已同步更新。
          </p>
        </div>
      </section>

      <DailyRecordTable :refresh-key="historyVersion" />
    </div>
  </div>
</template>

<style scoped>
.record-page {
  display: flex;
  flex-direction: column;
  gap: 17px;
}
.page-intro {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
}
.eyebrow {
  margin: 0 0 1px;
  color: var(--accent);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 2px;
}
.page-intro h1 {
  margin: 0;
  font-size: 27px;
  line-height: 1.25;
  letter-spacing: -0.7px;
}
.page-intro p {
  margin: 3px 0 0;
  color: var(--text-dim);
  font-size: 13px;
}
.timeline-link {
  flex: none;
  padding: 5px 10px;
  color: var(--accent);
  background: transparent;
  border-color: transparent;
  font-size: 12px;
}
.timeline-link:hover {
  background: var(--accent-dim);
  border-color: transparent;
}
.record-workspace {
  display: grid;
  grid-template-columns: minmax(240px, 270px) minmax(0, 1fr);
  align-items: start;
  gap: 16px;
}
.entry-panel {
  position: sticky;
  top: 104px;
  padding: 17px;
  background:
    linear-gradient(150deg, rgba(37, 99, 235, 0.055), transparent 36%),
    var(--card);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}
.panel-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.step-number {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  color: #fff;
  background: var(--accent);
  border-radius: 10px;
  box-shadow: 0 7px 16px var(--accent-glow);
  font-size: 11px;
  font-weight: 800;
}
.panel-head h2 {
  margin: 0;
  font-size: 16px;
}
.panel-head p {
  margin: 0;
  color: var(--text-faint);
  font-size: 11px;
}
.types {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 14px;
}
.chip {
  border-radius: 999px;
  padding: 3px 10px;
  font-size: 11px;
  color: var(--text-dim);
}
.chip.active {
  color: #fff;
  background: var(--accent);
  border-color: var(--accent);
}
.form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-top: 13px;
  border-top: 1px solid var(--border-soft);
}
label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
label span em {
  color: var(--danger);
  font-style: normal;
  margin-left: 2px;
}
label input[type='checkbox'] {
  width: 18px;
  height: 18px;
}
.actions {
  display: flex;
  gap: 10px;
  margin-top: 5px;
}
.actions .primary {
  flex: 1;
}
.error {
  color: var(--danger);
}
.warn {
  color: #e8b35a;
}
.ok {
  color: var(--ok);
  margin: 2px 0 0;
  padding: 8px 10px;
  background: var(--ok-dim);
  border-radius: var(--radius-sm);
  font-size: 12px;
}
@media (max-width: 980px) {
  .record-workspace {
    grid-template-columns: 1fr;
  }
  .entry-panel {
    position: static;
  }
}
@media (max-width: 560px) {
  .page-intro {
    align-items: flex-start;
    flex-direction: column;
    gap: 6px;
  }
  .timeline-link {
    padding-left: 0;
  }
}
</style>
