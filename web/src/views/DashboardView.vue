<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { BarChart, LineChart, ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { init, use, type ECharts, type EChartsCoreOption as EChartsOption } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import InsightCard from '../components/InsightCard.vue'
import {
  getInsights,
  getTrends,
  updateInsight,
  type InsightActionPayload,
  type InsightsPayload,
  type Trends,
} from '../api'

use([BarChart, LineChart, ScatterChart, GridComponent, TooltipComponent, CanvasRenderer])

const trends = ref<Trends | null>(null)
const insights = ref<InsightsPayload | null>(null)
const error = ref('')
const loading = ref(true)
const actionBusy = ref('')
const toast = ref('')

const totalDrop = computed(() => {
  const ws = trends.value?.weights ?? []
  const last = ws.at(-1)?.am
  return last != null ? BASELINE.start - last : null
})
const lastWeek = computed(() => trends.value?.weekly?.at(-1) ?? null)
const sweetSummary = computed(() => {
  const w = lastWeek.value
  if (!w) return '暂无'
  const parts = Object.entries(w.sweet_counts).map(([k, v]) => `${k}×${v}`)
  return parts.join(' ') || '未记录'
})
const diffClass = (d: number | null) => (d === null ? '' : d <= 0 ? 'good' : 'bad')

function fmtSweetCounts(c: Record<string, number> | undefined): string {
  if (!c) return '暂无'
  return Object.entries(c).map(([k, v]) => `${k}×${v}`).join(' ') || '暂无'
}

// 基线后备（API 返回 trends.baseline 后覆盖）
const BASELINE = reactive({
  start: 108.55,
  date: '2026-08-30',
  waist: 110,
  sprint_target: '104-105',
})

const charts: ECharts[] = []
let chartsRendered = false

const DARK = {
  text: '#17212b',
  dim: '#71808d',
  border: '#e4eee8',
  bg: 'transparent',
}

function baseOption(dates: string[]): EChartsOption {
  return {
    backgroundColor: DARK.bg,
    grid: { left: 46, right: 14, top: 28, bottom: 26 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { color: DARK.dim, fontSize: 10 },
      axisLine: { lineStyle: { color: DARK.border } },
    },
  }
}

function mk(id: string, option: EChartsOption) {
  const el = document.getElementById(id)
  if (!el) return
  const c = init(el)
  c.setOption(option)
  charts.push(c)
}

function render(t: Trends) {
  const dates = t.weights.map((w) => w.date.slice(5))

  // 1. 晨/夜重双曲线 + 3周目标带
  mk('chart-weight', {
    ...baseOption(dates),
    yAxis: {
      type: 'value',
      scale: true,
      min: (v: { min: number }) => Math.floor(v.min - 1),
      axisLabel: { color: DARK.dim },
      splitLine: { lineStyle: { color: DARK.border } },
    },
    series: [
      {
        name: '晨重',
        type: 'line',
        data: t.weights.map((w) => w.am),
        symbol: 'circle',
        symbolSize: 6,
        itemStyle: { color: '#2563eb' },
        lineStyle: { width: 2 },
        connectNulls: true,
      },
      {
        name: '夜重',
        type: 'line',
        data: t.weights.map((w) => w.evening),
        symbol: 'diamond',
        symbolSize: 6,
        itemStyle: { color: '#16a34a' },
        lineStyle: { width: 2, type: 'dashed' },
        connectNulls: true,
      },
      {
        name: '基线 108.55',
        type: 'line',
        data: dates.map(() => BASELINE.start),
        symbol: 'none',
        lineStyle: { color: DARK.dim, type: 'dotted' },
      },
    ],
  })

  // 2. 奶茶档位趋势（戒断进度）
  const sweetDates = t.sweet.map((s) => s.date.slice(5))
  mk('chart-sweet', {
    ...baseOption(sweetDates),
    yAxis: {
      type: 'value',
      max: 4,
      min: 0,
      interval: 1,
      axisLabel: {
        color: DARK.dim,
        formatter: (v: number) =>
          ['', '0杯', '无糖', '三分糖', '半糖', '全糖'][v + 1] ?? '',
      },
      splitLine: { lineStyle: { color: DARK.border } },
    },
    series: [
      {
        name: '奶茶档位',
        type: 'line',
        step: 'middle',
        data: t.sweet.map((s) => s.score),
        symbol: 'circle',
        symbolSize: 8,
        itemStyle: { color: '#d97706' },
        areaStyle: { color: 'rgba(217,119,6,0.12)' },
      },
    ],
  })

  // 3. 步数（≥8000 达标线）
  const stepDates = t.steps.map((s) => s.date.slice(5))
    mk('chart-steps', {
      ...baseOption(stepDates),
      yAxis: {
        type: 'value',
        axisLabel: { color: DARK.dim },
        splitLine: { lineStyle: { color: DARK.border } },
      },
      series: [
        {
          name: '步数',
          type: 'bar',
          data: t.steps.map((s) => s.steps),
          itemStyle: { color: '#16a34a', borderRadius: [3, 3, 0, 0] },
          barMaxWidth: 26,
        },
        {
          name: '目标 8000',
          type: 'line',
          data: stepDates.map(() => 8000),
          symbol: 'none',
          lineStyle: { color: '#dc2626', type: 'dashed' },
        },
      ],
    })

  // 4. 入睡时间
  if (t.sleep.length) {
    const sleepDates = t.sleep.map((s) => s.date.slice(5))
    mk('chart-sleep', {
      ...baseOption(sleepDates),
      yAxis: {
        type: 'category',
        data: ['22:00', '22:30', '23:00', '23:30', '00:00', '00:30', '01:00', '01:30'],
        inverse: true,
        axisLabel: { color: DARK.dim, fontSize: 10 },
      },
      xAxis: { type: 'category', data: sleepDates, axisLabel: { color: DARK.dim, fontSize: 10 }, axisLine: { lineStyle: { color: DARK.border } } },
      series: [
        {
          name: '入睡',
          type: 'line',
          data: t.sleep.map((s) => (s.minutes !== null ? bedtimeToAxis(s.bedtime) : null)),
          symbol: 'circle',
          symbolSize: 7,
          itemStyle: { color: '#2563eb' },
          connectNulls: true,
          label: { show: true, color: DARK.dim, formatter: '{c}' },
        },
      ],
    })
  }

  // 5. 游泳时长 + 力量频次
  if (t.exercise.length) {
    const exDates = t.exercise.map((e) => e.date.slice(5))
    mk('chart-exercise', {
      ...baseOption(exDates),
      yAxis: [
        { type: 'value', name: '游泳(分)', nameTextStyle: { color: DARK.dim }, axisLabel: { color: DARK.dim }, splitLine: { lineStyle: { color: DARK.border } } },
      ],
      series: [
        {
          name: '游泳(分)',
          type: 'bar',
          data: t.exercise.map((e) => e.swim_min),
          itemStyle: { color: '#2563eb', borderRadius: [3, 3, 0, 0] },
          barMaxWidth: 26,
        },
        {
          name: '力量完成',
          type: 'scatter',
          data: t.exercise.map((e, i) => (e.strength_done ? [i, 0] : null)),
          symbolSize: 10,
          itemStyle: { color: '#d97706' },
        },
      ],
    })
  }

  // 6. 腰围（周测量）
  if (t.waist.length) {
    const wDates = t.waist.map((w) => w.date.slice(5))
    mk('chart-waist', {
      ...baseOption(wDates),
      yAxis: { type: 'value', scale: true, min: 95, max: 115, axisLabel: { color: DARK.dim }, splitLine: { lineStyle: { color: DARK.border } } },
      series: [
        {
          name: '腰围(cm)',
          type: 'line',
          data: t.waist.map((w) => w.cm),
          symbol: 'rect',
          symbolSize: 8,
          itemStyle: { color: '#d97706' },
        },
        {
          name: '基线 110',
          type: 'line',
          data: wDates.map(() => BASELINE.waist),
          symbol: 'none',
          lineStyle: { color: DARK.dim, type: 'dotted' },
        },
      ],
    })
  }

  // 7. 夜饿分布（分类散点）
  if (t.night_hunger.length) {
    const levels = ['没饿', '加餐预案', '破戒']
    const nhDates = t.night_hunger.map((n) => n.date.slice(5))
    mk('chart-night-hunger', {
      ...baseOption(nhDates),
      yAxis: {
        type: 'value',
        min: -0.5,
        max: 2.5,
        interval: 1,
        axisLabel: { color: DARK.dim, formatter: (v: number) => levels[v] ?? '' },
        splitLine: { lineStyle: { color: DARK.border } },
      },
      series: [
        {
          name: '夜饿处理',
          type: 'scatter',
          data: t.night_hunger.map((n) => levels.indexOf(n.level ?? '')),
          symbolSize: 12,
          itemStyle: {
            color: (p: any) =>
              ['#16a34a', '#d97706', '#dc2626'][p.value] ?? '#888',
          },
        },
      ],
    })
  }
}

function bedtimeToAxis(bedtime: string | null): string | null {
  // ECharts 分类轴上直接展示原始时间字符串
  return bedtime
}

function onResize() {
  charts.forEach((c) => c.resize())
}

onMounted(async () => {
  try {
    const [trendResult, insightResult] = await Promise.all([getTrends(), getInsights()])
    trends.value = trendResult
    insights.value = insightResult
    if (trends.value.baseline) Object.assign(BASELINE, trends.value.baseline)
  } catch (e) {
    error.value = `加载洞察失败：${(e as Error).message}`
  } finally {
    loading.value = false
  }
})

async function handleInsightAction(
  key: string,
  payload: InsightActionPayload,
  message: string,
) {
  actionBusy.value = key
  error.value = ''
  try {
    await updateInsight(key, payload)
    insights.value = await getInsights()
    toast.value = message
    window.setTimeout(() => {
      if (toast.value === message) toast.value = ''
    }, 3200)
  } catch (e) {
    error.value = `保存失败：${(e as Error).message}`
  } finally {
    actionBusy.value = ''
  }
}

async function nextTickRender() {
  if (chartsRendered) return
  await new Promise((r) => requestAnimationFrame(r))
  if (trends.value) {
    render(trends.value)
    chartsRendered = true
  }
  window.addEventListener('resize', onResize)
}

async function handleRawToggle(event: Event) {
  const element = event.currentTarget as HTMLDetailsElement
  if (element.open) await nextTickRender()
}

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  charts.forEach((c) => c.dispose())
})
</script>

<template>
  <div class="dashboard">
    <header class="page-heading">
      <div>
        <h2>从数据到下一步</h2>
        <p>优先展示值得关注的变化，并把建议变成可以完成的小行动。</p>
      </div>
      <a href="#raw-trends" class="text-link">查看原始趋势</a>
    </header>

    <div v-if="toast" class="toast" role="status" aria-live="polite">{{ toast }}</div>
    <div v-if="error" class="error-state" role="alert">
      <strong>暂时无法完成操作</strong>
      <span>{{ error }}</span>
      <button type="button" @click="error = ''">关闭</button>
    </div>

    <section v-if="loading" class="skeleton-section" aria-label="正在加载洞察">
      <div class="skeleton-title"></div>
      <div class="skeleton-grid">
        <div v-for="index in 2" :key="index" class="skeleton-card"></div>
      </div>
    </section>

    <template v-else-if="insights">
      <section class="insight-section priority-section">
        <div class="section-heading">
          <div>
            <h3>今日重点</h3>
            <p>最多展示 3 条，按重要性、数据完整度和可行动性排序。</p>
          </div>
          <span class="section-count">{{ insights.priority.length }} 条待处理</span>
        </div>
        <div v-if="insights.priority.length" class="priority-grid">
          <InsightCard
            v-for="card in insights.priority"
            :key="card.key"
            :card="card"
            :busy="actionBusy === card.key"
            @action="handleInsightAction"
          />
        </div>
        <div v-else class="empty-state">
          <strong>今天没有需要立即处理的洞察</strong>
          <p>继续记录体重、步数、睡眠或运动，数据足够后会在这里给出下一步。</p>
        </div>
      </section>

      <section v-if="insights.active.length" class="insight-section">
        <div class="section-heading">
          <div>
            <h3>正在进行</h3>
            <p>已采纳和已安排提醒的建议会保留在这里。</p>
          </div>
          <span class="section-count">{{ insights.active.length }} 项</span>
        </div>
        <div class="active-grid">
          <InsightCard
            v-for="card in insights.active"
            :key="card.key"
            :card="card"
            :busy="actionBusy === card.key"
            @action="handleInsightAction"
          />
        </div>
      </section>

      <section v-if="insights.history.length" class="insight-section history-section">
        <details>
          <summary>
            <span>
              <strong>历史回看</strong>
              <small>已完成或暂不处理的建议</small>
            </span>
            <span>{{ insights.history.length }} 条</span>
          </summary>
          <div class="history-grid">
            <InsightCard
              v-for="card in insights.history"
              :key="card.key"
              :card="card"
              compact
              :busy="actionBusy === card.key"
              @action="handleInsightAction"
            />
          </div>
        </details>
      </section>
    </template>

    <section v-if="trends" class="snapshot-section" aria-label="本周数据快照">
      <div class="snapshot-main">
        <span>今晨体重</span>
        <strong>{{ trends.weights.at(-1)?.am?.toFixed(1) ?? '暂无' }}<small> kg</small></strong>
        <p>基线 {{ BASELINE.start }} kg（{{ BASELINE.date }}）</p>
      </div>
      <div class="snapshot-item">
        <span>累计变化</span>
        <strong :class="{ good: (totalDrop ?? 0) > 0 }">
          {{ totalDrop !== null ? `${totalDrop > 0 ? '-' : '+'}${Math.abs(totalDrop).toFixed(1)} kg` : '暂无' }}
        </strong>
        <p>3 周目标 {{ BASELINE.sprint_target }} kg</p>
      </div>
      <div class="snapshot-item">
        <span>本周奶茶</span>
        <strong>{{ sweetSummary }}</strong>
        <p>档位越低越好</p>
      </div>
      <div class="snapshot-item">
        <span>本周训练</span>
        <strong>{{ lastWeek?.swim_times ?? 0 }} 次游泳</strong>
        <p>{{ lastWeek?.swim_total_min ?? 0 }} 分钟，力量 {{ lastWeek?.strength_times ?? 0 }} 次</p>
      </div>
    </section>

    <section id="raw-trends" v-if="trends" class="raw-section">
      <details @toggle="handleRawToggle">
        <summary>
          <span>
            <strong>原始趋势与周报</strong>
            <small>展开核对每条洞察背后的完整数据</small>
          </span>
          <span>7 组趋势</span>
        </summary>

        <div v-if="trends.weekly?.length" class="weekly-card">
          <h3>每周晨重均值</h3>
          <table>
            <thead>
              <tr>
                <th>周</th><th>晨重均值</th><th>较上周</th><th>腰围</th>
                <th>奶茶</th><th>步数日均</th><th>达标评价</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="w in trends.weekly" :key="w.week_start">
                <td>{{ w.week_start.slice(5) }}~{{ w.week_end.slice(5) }}</td>
                <td>{{ w.am_avg ?? '暂无' }} <small v-if="w.am_days">（{{ w.am_days }}天）</small></td>
                <td :class="diffClass(w.diff_vs_last)">{{ w.diff_vs_last === null ? '暂无' : (w.diff_vs_last > 0 ? '+' : '') + w.diff_vs_last }}</td>
                <td>{{ w.waist ?? '暂无' }}</td>
                <td>{{ fmtSweetCounts(w.sweet_counts) }}</td>
                <td>{{ w.steps_avg ?? '暂无' }}</td>
                <td>{{ w.verdict }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="charts-grid">
          <div class="chart-box wide"><h3>晨重与夜重</h3><div id="chart-weight" class="chart"></div></div>
          <div class="chart-box wide"><h3>奶茶档位</h3><div id="chart-sweet" class="chart"></div></div>
          <div class="chart-box"><h3>步数</h3><div id="chart-steps" class="chart"></div></div>
          <div class="chart-box"><h3>入睡时间</h3><div id="chart-sleep" class="chart"></div></div>
          <div class="chart-box"><h3>游泳与力量</h3><div id="chart-exercise" class="chart"></div></div>
          <div class="chart-box">
            <h3>腰围</h3>
            <div v-if="trends.waist.length" id="chart-waist" class="chart"></div>
            <div v-else class="chart-empty">暂无腰围记录<small>建议每周固定一天测量</small></div>
          </div>
          <div class="chart-box"><h3>夜饿处理</h3><div id="chart-night-hunger" class="chart"></div></div>
        </div>
      </details>
    </section>

    <p v-if="insights" class="foot-hint">{{ insights.safety_note }} 症状持续或加重时，请咨询专业医疗人员。</p>
  </div>
</template>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.page-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  padding: 8px 0 2px;
}
.page-heading h2 {
  margin: 0;
  font-size: clamp(25px, 3vw, 34px);
  letter-spacing: -0.7px;
}
.page-heading p,
.section-heading p {
  margin: 4px 0 0;
  color: var(--text-dim);
}
.text-link {
  flex: none;
  font-size: 13px;
  font-weight: 600;
}
.insight-section {
  display: grid;
  gap: 13px;
}
.section-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
}
.section-heading h3 {
  margin: 0;
  color: var(--text);
  font-size: 17px;
  letter-spacing: 0;
}
.section-heading p { font-size: 13px; }
.section-count {
  flex: none;
  color: var(--text-faint);
  font-size: 12px;
}
.priority-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr);
  gap: 14px;
}
.priority-grid > :first-child:last-child { grid-column: 1 / -1; }
.active-grid,
.history-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.snapshot-section {
  display: grid;
  grid-template-columns: 1.25fr repeat(3, minmax(0, 1fr));
  overflow: hidden;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  background: var(--card);
}
.snapshot-main,
.snapshot-item {
  min-width: 0;
  padding: 15px 17px;
  border-right: 1px solid var(--border-soft);
}
.snapshot-item:last-child { border-right: 0; }
.snapshot-main { background: var(--accent-dim); }
.snapshot-main span,
.snapshot-item span {
  display: block;
  color: var(--text-dim);
  font-size: 11px;
}
.snapshot-main strong,
.snapshot-item strong {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  color: var(--text);
  font-size: 18px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.snapshot-main strong { color: var(--accent-strong); font-size: 25px; }
.snapshot-main strong small { font-size: 12px; }
.snapshot-main p,
.snapshot-item p {
  margin: 2px 0 0;
  color: var(--text-faint);
  font-size: 11px;
}
.snapshot-item strong.good { color: var(--ok); }
.empty-state {
  padding: 28px;
  border: 1px dashed var(--border);
  border-radius: var(--radius-lg);
  background: rgba(255, 255, 255, 0.46);
  text-align: center;
}
.empty-state p { margin: 5px auto 0; max-width: 520px; color: var(--text-dim); font-size: 13px; }
.toast {
  position: fixed;
  right: 22px;
  bottom: 22px;
  z-index: 20;
  max-width: min(380px, calc(100vw - 24px));
  padding: 10px 14px;
  border: 1px solid rgba(22, 163, 74, 0.2);
  border-radius: var(--radius);
  background: #eefaf2;
  color: #116b32;
  box-shadow: var(--shadow-pop);
  font-size: 13px;
}
.error-state {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid rgba(220, 38, 38, 0.18);
  border-radius: var(--radius);
  background: var(--danger-dim);
  color: var(--danger);
  font-size: 13px;
}
.error-state span { flex: 1; }
.error-state button { padding: 3px 9px; }
.skeleton-section { display: grid; gap: 12px; }
.skeleton-title,
.skeleton-card {
  background: linear-gradient(90deg, var(--bg-soft), #fff, var(--bg-soft));
  background-size: 200% 100%;
  animation: shimmer 1.4s ease-in-out infinite;
}
.skeleton-title { width: 150px; height: 24px; border-radius: var(--radius-sm); }
.skeleton-grid { display: grid; grid-template-columns: 1.15fr 0.85fr; gap: 14px; }
.skeleton-card { height: 300px; border: 1px solid var(--border-soft); border-radius: var(--radius-lg); }
@keyframes shimmer { 50% { background-position: -100% 0; } }
.history-section,
.raw-section {
  border-top: 1px solid var(--border);
  padding-top: 15px;
}
.history-section summary,
.raw-section > details > summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  cursor: pointer;
  color: var(--text-dim);
}
.history-section summary::marker,
.raw-section summary::marker { color: var(--accent); }
.history-section summary span:first-child,
.raw-section summary span:first-child { display: grid; }
.history-section summary strong,
.raw-section summary strong { color: var(--text); }
.history-section summary small,
.raw-section summary small { font-size: 12px; }
.history-grid,
.raw-section .weekly-card { margin-top: 14px; }
.raw-section .charts-grid { margin-top: 14px; }
.weekly-card {
  background: var(--card);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius);
  padding: 14px 16px;
  overflow-x: auto;
  box-shadow: var(--shadow-card);
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
th,
td {
  padding: 7px 10px;
  text-align: left;
  border-bottom: 1px solid var(--border-soft);
  white-space: nowrap;
}
thead th {
  position: sticky;
  top: 0;
  color: var(--text-faint);
  font-weight: 600;
  font-size: 11px;
  letter-spacing: 0.5px;
}
tbody tr {
  transition: background 0.12s var(--ease);
}
tbody tr:hover {
  background: var(--bg-soft);
}
tbody tr:last-child td {
  border-bottom: none;
}
td.good {
  color: var(--ok);
  font-weight: 600;
}
td.bad {
  color: var(--danger);
  font-weight: 600;
}
small {
  color: var(--text-faint);
}
.charts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: 14px;
}
.chart-box {
  background: var(--card);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius);
  padding: 13px 15px;
  box-shadow: var(--shadow-card);
  transition: border-color 0.18s var(--ease);
}
.chart-box:hover {
  border-color: #c8ddd2;
}
.chart-box.wide {
  grid-column: span 2;
}
@media (max-width: 760px) {
  .chart-box.wide {
    grid-column: span 1;
  }
}
.chart {
  width: 100%;
  height: 240px;
}
.chart-empty {
  height: 240px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  color: var(--text-dim);
  font-size: 13px;
  border: 1px dashed var(--border);
  border-radius: var(--radius-sm);
}
.chart-empty small {
  font-size: 11px;
}
.foot-hint {
  margin: 0;
  font-size: 11px;
  color: var(--text-faint);
  text-align: center;
}
.error {
  color: var(--danger);
}
.loading {
  color: var(--text-dim);
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse {
  50% {
    opacity: 0.45;
  }
}
@media (prefers-reduced-motion: reduce) {
  .skeleton-title,
  .skeleton-card { animation: none; }
}
@media (max-width: 820px) {
  .priority-grid,
  .active-grid,
  .history-grid,
  .skeleton-grid { grid-template-columns: 1fr; }
  .snapshot-section { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .snapshot-main,
  .snapshot-item { border-bottom: 1px solid var(--border-soft); }
  .snapshot-item:nth-child(2) { border-right: 0; }
  .snapshot-item:nth-last-child(-n + 2) { border-bottom: 0; }
}
@media (max-width: 560px) {
  .dashboard { gap: 20px; }
  .page-heading { align-items: flex-start; }
  .page-heading p { max-width: 34ch; }
  .section-heading { align-items: flex-start; }
  .section-heading p { max-width: 30ch; }
  .snapshot-section { grid-template-columns: 1fr; }
  .snapshot-main,
  .snapshot-item { border-right: 0; border-bottom: 1px solid var(--border-soft); }
  .snapshot-item:nth-last-child(-n + 2) { border-bottom: 1px solid var(--border-soft); }
  .snapshot-item:last-child { border-bottom: 0; }
  .charts-grid { grid-template-columns: 1fr; }
  .toast { right: 12px; bottom: 12px; }
  .error-state { align-items: flex-start; flex-wrap: wrap; }
}
</style>
