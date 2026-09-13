<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { listRecords } from '../api'
import { SLOT_LABELS, TYPE_LABELS, recordSummary, type RecordItem } from '../labels'

const props = withDefaults(
  defineProps<{
    refreshKey?: number
  }>(),
  { refreshKey: 0 },
)

interface DailyRow {
  date: string
  items: RecordItem[]
}

const records = ref<RecordItem[]>([])
const loading = ref(true)
const error = ref('')
const showAll = ref(false)
const today = new Date().toISOString().slice(0, 10)
const SLOT_ORDER: Record<string, number> = {
  am: 1,
  evening: 2,
  breakfast: 1,
  lunch: 2,
  dinner: 3,
  snack: 4,
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    records.value = await listRecords({})
  } catch (e) {
    error.value = String((e as Error).message)
  } finally {
    loading.value = false
  }
}

const allDays = computed<DailyRow[]>(() => {
  const groups = new Map<string, RecordItem[]>()
  for (const record of records.value) {
    const items = groups.get(record.date) ?? []
    items.push(record)
    groups.set(record.date, items)
  }
  return [...groups.entries()]
    .sort(([a], [b]) => b.localeCompare(a))
    .map(([date, items]) => ({ date, items }))
})

const visibleDays = computed(() => (showAll.value ? allDays.value : allDays.value.slice(0, 10)))

function itemsOf(day: DailyRow, types: string[]): RecordItem[] {
  return day.items
    .filter((item) => types.includes(item.type))
    .sort((a, b) => (SLOT_ORDER[a.slot ?? ''] ?? 99) - (SLOT_ORDER[b.slot ?? ''] ?? 99))
}

function shortDate(date: string): string {
  const [, month, day] = date.split('-')
  return `${Number(month)}月${Number(day)}日`
}

function weekday(date: string): string {
  return new Intl.DateTimeFormat('zh-CN', { weekday: 'short', timeZone: 'UTC' }).format(
    new Date(`${date}T12:00:00Z`),
  )
}

function slotLabel(item: RecordItem): string {
  if (!item.slot) return TYPE_LABELS[item.type] ?? item.type
  return SLOT_LABELS[item.slot] ?? item.slot
}

watch(() => props.refreshKey, load)
onMounted(load)
</script>

<template>
  <section class="daily-ledger" aria-labelledby="daily-ledger-title">
    <header class="ledger-head">
      <div>
        <p class="eyebrow">DAILY LEDGER</p>
        <h2 id="daily-ledger-title">每日记录一览</h2>
        <p class="ledger-note">一天一行，快速检查生活方式记录是否完整。</p>
      </div>
      <button class="refresh" type="button" :disabled="loading" @click="load">
        {{ loading ? '同步中…' : '刷新' }}
      </button>
    </header>

    <div v-if="loading" class="state" aria-live="polite">
      <span class="pulse-dot"></span>正在整理每日记录…
    </div>
    <div v-else-if="error" class="state error" role="alert">加载失败：{{ error }}</div>
    <div v-else-if="allDays.length === 0" class="state empty">
      <strong>还没有每日记录</strong>
      <span>在左侧保存第一条记录后，这里会自动形成每日视图。</span>
    </div>

    <template v-else>
      <div class="table-shell">
        <table>
          <thead>
            <tr>
              <th class="date-col">日期</th>
              <th>体重</th>
              <th>睡眠</th>
              <th class="meal-col">饮食</th>
              <th>活动</th>
              <th>习惯</th>
              <th>身体 / 其他</th>
              <th class="count-col">条目</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="day in visibleDays" :key="day.date" :class="{ today: day.date === today }">
              <th scope="row" class="day-cell">
                <span class="date-main">{{ shortDate(day.date) }}</span>
                <span class="date-meta">
                  {{ weekday(day.date) }}
                  <em v-if="day.date === today">今天</em>
                </span>
              </th>

              <td>
                <div v-if="itemsOf(day, ['weight']).length" class="cell-stack">
                  <span v-for="item in itemsOf(day, ['weight'])" :key="item.id" class="metric weight">
                    <small>{{ slotLabel(item) }}</small>{{ recordSummary(item) }}
                  </span>
                </div>
                <span v-else class="missing">—</span>
              </td>

              <td>
                <div v-if="itemsOf(day, ['sleep']).length" class="cell-stack">
                  <span v-for="item in itemsOf(day, ['sleep'])" :key="item.id" class="metric">
                    {{ recordSummary(item) }}
                  </span>
                </div>
                <span v-else class="missing">—</span>
              </td>

              <td>
                <div v-if="itemsOf(day, ['meal']).length" class="cell-stack meal-stack">
                  <span v-for="item in itemsOf(day, ['meal'])" :key="item.id" class="metric meal">
                    <small>{{ slotLabel(item) }}</small><span>{{ recordSummary(item) }}</span>
                  </span>
                </div>
                <span v-else class="missing">—</span>
              </td>

              <td>
                <div v-if="itemsOf(day, ['exercise', 'step']).length" class="cell-stack">
                  <span v-for="item in itemsOf(day, ['exercise', 'step'])" :key="item.id" class="metric">
                    <small>{{ TYPE_LABELS[item.type] }}</small>{{ recordSummary(item) }}
                  </span>
                </div>
                <span v-else class="missing">—</span>
              </td>

              <td>
                <div v-if="itemsOf(day, ['sweet_drink', 'night_hunger']).length" class="cell-stack">
                  <span
                    v-for="item in itemsOf(day, ['sweet_drink', 'night_hunger'])"
                    :key="item.id"
                    class="metric habit"
                  >
                    <small>{{ TYPE_LABELS[item.type] }}</small>{{ recordSummary(item) }}
                  </span>
                </div>
                <span v-else class="missing">—</span>
              </td>

              <td>
                <div v-if="itemsOf(day, ['waist', 'supplement', 'body', 'note']).length" class="cell-stack">
                  <span
                    v-for="item in itemsOf(day, ['waist', 'supplement', 'body', 'note'])"
                    :key="item.id"
                    class="metric other"
                  >
                    <small>{{ TYPE_LABELS[item.type] }}</small><span>{{ recordSummary(item) }}</span>
                  </span>
                </div>
                <span v-else class="missing">—</span>
              </td>

              <td class="count-cell">
                <span>{{ day.items.length }}</span>
                <small>条</small>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <footer class="ledger-foot">
        <span>共 {{ allDays.length }} 天 · {{ records.length }} 条记录</span>
        <button v-if="allDays.length > 10" type="button" class="text-button" @click="showAll = !showAll">
          {{ showAll ? '收起' : `查看全部 ${allDays.length} 天` }}
        </button>
      </footer>
    </template>
  </section>
</template>

<style scoped>
.daily-ledger {
  min-width: 0;
  overflow: hidden;
  background: var(--card);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}
.ledger-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 19px 20px 15px;
  border-bottom: 1px solid var(--border-soft);
  background:
    linear-gradient(110deg, rgba(37, 99, 235, 0.055), transparent 38%),
    linear-gradient(180deg, #fff, #fbfdfc);
}
.eyebrow {
  margin: 0 0 2px;
  color: var(--accent);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 1.8px;
}
.ledger-head h2 {
  margin: 0;
  font-size: 18px;
  letter-spacing: 0.2px;
}
.ledger-note {
  margin: 2px 0 0;
  color: var(--text-dim);
  font-size: 12px;
}
.refresh {
  flex: none;
  padding: 5px 12px;
  color: var(--text-dim);
  font-size: 12px;
}
.table-shell {
  width: 100%;
  overflow-x: auto;
}
table {
  width: 100%;
  min-width: 860px;
  border-collapse: separate;
  border-spacing: 0;
  table-layout: fixed;
  font-size: 12px;
}
thead th {
  padding: 9px 10px;
  color: var(--text-faint);
  background: #f8fbf9;
  border-bottom: 1px solid var(--border-soft);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.8px;
  text-align: left;
  white-space: nowrap;
}
thead th:not(.date-col):not(.count-col) {
  width: 13%;
}
.date-col {
  width: 92px;
}
.meal-col {
  width: 18%;
}
.count-col {
  width: 54px;
  text-align: center;
}
tbody th,
tbody td {
  padding: 10px;
  border-bottom: 1px solid var(--border-soft);
  vertical-align: top;
  text-align: left;
}
tbody tr:last-child th,
tbody tr:last-child td {
  border-bottom: none;
}
tbody tr {
  transition: background 0.15s var(--ease);
}
tbody tr:hover {
  background: #f9fcfa;
}
tbody tr.today {
  background: linear-gradient(90deg, rgba(37, 99, 235, 0.06), rgba(37, 99, 235, 0.015));
}
.day-cell {
  position: relative;
  padding-left: 15px;
  background: rgba(249, 252, 250, 0.72);
}
.today .day-cell::before {
  position: absolute;
  top: 10px;
  bottom: 10px;
  left: 0;
  width: 3px;
  border-radius: 0 4px 4px 0;
  background: var(--accent);
  content: '';
}
.date-main {
  display: block;
  color: var(--text);
  font-size: 13px;
  font-weight: 750;
  line-height: 1.3;
}
.date-meta {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 3px;
  color: var(--text-faint);
  font-size: 10px;
  font-weight: 500;
}
.date-meta em {
  padding: 0 5px;
  color: var(--accent-strong);
  background: var(--accent-dim);
  border-radius: 999px;
  font-style: normal;
}
.cell-stack {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}
.metric {
  display: block;
  min-width: 0;
  color: var(--text-dim);
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.metric small {
  display: inline-block;
  margin-right: 4px;
  color: var(--text-faint);
  font-size: 9px;
  font-weight: 700;
}
.metric.weight {
  color: var(--accent-strong);
  font-size: 13px;
  font-weight: 750;
}
.metric.meal,
.metric.other {
  display: flex;
  min-width: 0;
  align-items: baseline;
}
.metric.meal span,
.metric.other span {
  display: -webkit-box;
  min-width: 0;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.metric.habit {
  color: #8a5a16;
}
.missing {
  color: #ccd5d0;
}
.count-cell {
  text-align: center;
}
.count-cell span {
  display: block;
  color: var(--text);
  font-size: 16px;
  font-weight: 800;
  line-height: 1.15;
}
.count-cell small {
  color: var(--text-faint);
  font-size: 9px;
}
.ledger-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 16px;
  color: var(--text-faint);
  background: #fbfdfc;
  border-top: 1px solid var(--border-soft);
  font-size: 11px;
}
.text-button {
  padding: 1px 4px;
  color: var(--accent);
  background: transparent;
  border: 0;
  font-size: 11px;
}
.text-button:hover {
  color: var(--accent-strong);
  background: transparent;
}
.state {
  display: flex;
  min-height: 170px;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  color: var(--text-dim);
  font-size: 13px;
}
.state.empty {
  flex-direction: column;
  text-align: center;
}
.state.empty strong {
  color: var(--text);
  font-size: 15px;
}
.state.empty span {
  color: var(--text-faint);
}
.state.error {
  color: var(--danger);
}
.pulse-dot {
  width: 7px;
  height: 7px;
  background: var(--accent);
  border-radius: 50%;
  animation: pulse 1.1s ease-in-out infinite;
}
@keyframes pulse {
  50% {
    opacity: 0.25;
    transform: scale(0.72);
  }
}
@media (max-width: 760px) {
  .ledger-head {
    padding: 16px;
  }
  .ledger-note {
    max-width: 220px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .pulse-dot {
    animation: none;
  }
}
</style>
