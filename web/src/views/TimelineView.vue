<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { deleteRecord, listRecords } from '../api'
import { SLOT_LABELS, TYPE_LABELS, recordSummary, type RecordItem } from '../labels'

const records = ref<RecordItem[]>([])
const error = ref('')
const loading = ref(true)
const router = useRouter()

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

async function remove(id: number) {
  if (!confirm('确定删除这条记录？')) return
  await deleteRecord(id)
  await load()
  // 同步刷新顶栏待办条（删除今日记录后 ✓ 应回退为 ✗）
  window.dispatchEvent(new Event('kangji-refresh-todo'))
}

// 按日期分组（倒序）
const byDate = computed(() => {
  const groups: Record<string, RecordItem[]> = {}
  for (const r of records.value) {
    ;(groups[r.date] ??= []).push(r)
  }
  return Object.entries(groups).sort(([a], [b]) => (a < b ? 1 : -1))
})

const SOURCE_LABELS: Record<string, string> = {
  import: '迁移',
  manual: '手动',
  chat: '对话',
}

onMounted(load)
</script>

<template>
  <div>
    <div class="head">
      <h2>时间线</h2>
      <button @click="load">刷新</button>
    </div>

    <p v-if="loading" class="dim">加载中…</p>
    <p v-else-if="error" class="error">{{ error }}（请确认后端已启动）</p>
    <p v-else-if="records.length === 0" class="dim">暂无记录，去「记录」页添加第一条吧。</p>

    <section v-for="[date, items] in byDate" :key="date" class="day">
      <h3>{{ date }} <span class="count">{{ items.length }} 条</span></h3>
      <ul>
        <li v-for="r in items" :key="r.id">
          <span class="type" :data-type="r.type">{{ TYPE_LABELS[r.type] ?? r.type }}</span>
          <span v-if="r.slot" class="slot">{{ SLOT_LABELS[r.slot] ?? r.slot }}</span>
          <span class="summary">{{ recordSummary(r) }}</span>
          <span class="source">{{ SOURCE_LABELS[r.source] ?? r.source }}</span>
          <button class="edit" title="修改" @click="router.push({ path: '/record', query: { edit: r.id } })">修改</button>
          <button class="danger del" title="删除" @click="remove(r.id)">✕</button>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
h2 {
  margin: 8px 0;
}
h3 {
  margin: 20px 0 10px;
  font-size: 13px;
  color: var(--text-dim);
  font-weight: 600;
  letter-spacing: 0.5px;
  display: flex;
  align-items: center;
  gap: 8px;
}
h3::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border-soft);
}
.count {
  font-weight: 400;
  font-size: 11px;
  color: var(--text-faint);
  font-variant-numeric: tabular-nums;
  background: var(--bg-soft);
  border-radius: 999px;
  padding: 0 8px;
}
ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
li {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--card);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-sm);
  padding: 8px 12px;
  transition: border-color 0.15s var(--ease), background 0.15s var(--ease);
}
li:hover {
  border-color: #c8ddd2;
  background: var(--card-hover);
}
.type {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--accent-strong);
  background: var(--accent-dim);
  border-radius: 8px;
  padding: 1px 7px;
}
.slot {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--ok);
}
.summary {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
  font-variant-numeric: tabular-nums;
}
.source {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--text-faint);
  border: 1px solid var(--border-soft);
  border-radius: 999px;
  padding: 0 8px;
}
.del,
.edit {
  flex-shrink: 0;
  padding: 2px 8px;
  border: none;
  background: none;
  opacity: 0;
  transition: opacity 0.15s var(--ease);
}
li:hover .del,
li:focus-within .del,
li:hover .edit,
li:focus-within .edit {
  opacity: 1;
}
.edit {
  color: var(--accent);
}
@media (hover: none) {
  .del,
  .edit {
    opacity: 1;
  }
}
.dim {
  color: var(--text-dim);
}
.error {
  color: var(--danger);
}
</style>
