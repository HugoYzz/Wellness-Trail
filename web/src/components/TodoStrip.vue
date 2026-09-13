<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTodoStore } from '../stores/todo'

const store = useTodoStore()
const router = useRouter()
const route = useRoute()

const progress = computed(() => store.plan?.progress)
const allHandled = computed(
  () => !!progress.value?.active && progress.value.handled === progress.value.active,
)

function openPlan() {
  if (route.path !== '/') {
    router.push('/').then(() => document.getElementById('today-plan')?.scrollIntoView({ behavior: 'smooth' }))
    return
  }
  document.getElementById('today-plan')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/** 确认入账等数据变化后触发（ChatView dispatch） */
const onRefresh = () => store.refresh()

onMounted(() => {
  store.refresh()
  window.addEventListener('kangji-refresh-todo', onRefresh)
})
onUnmounted(() => window.removeEventListener('kangji-refresh-todo', onRefresh))
</script>

<template>
  <button
    class="todo-strip"
    :class="{ all: allHandled }"
    :title="store.plan ? `今日计划：${store.plan.progress.handled}/${store.plan.progress.active} 已处理` : '加载今日计划'"
    type="button"
    @click="openPlan"
  >
    <span class="todo-label" :class="{ full: allHandled }">
      今日 {{ progress?.handled ?? '—' }}/{{ progress?.active ?? '—' }}
    </span>
    <span v-if="store.nextItem" class="todo-next">
      下一项 · {{ store.nextItem.time_window.label }} {{ store.nextItem.label }}
    </span>
    <span v-else-if="allHandled" class="todo-next">今日计划已处理</span>
    <span v-else class="todo-next">正在生成计划…</span>
    <span v-if="store.plan && !store.plan.confirmed" class="todo-confirm">待确认</span>
    <span class="todo-arrow">›</span>
  </button>
</template>

<style scoped>
.todo-strip {
  display: flex;
  align-items: center;
  gap: 9px;
  width: calc(100% - 48px);
  max-width: 1240px;
  margin: 0 auto 10px;
  padding: 7px 10px;
  border: 1px solid var(--border-soft);
  border-radius: 11px;
  background: rgba(248, 251, 249, 0.78);
  color: var(--text);
  text-align: left;
}
.todo-strip:hover {
  border-color: rgba(37, 99, 235, 0.26);
  background: #fff;
}
.todo-label {
  flex: none;
  font-size: 11px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--accent-strong);
  background: var(--accent-dim);
  padding: 2px 9px;
  border-radius: 999px;
}
.todo-label.full {
  color: var(--ok);
  background: var(--ok-dim);
}
.todo-next {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--text-dim);
}
.todo-confirm {
  margin-left: auto;
  flex: none;
  font-size: 11px;
  color: #9a6700;
  background: #fff7d6;
  padding: 2px 7px;
  border-radius: 999px;
}
.todo-arrow {
  flex: none;
  color: var(--text-faint);
  font-size: 18px;
  line-height: 1;
}

@media (max-width: 480px) {
  .todo-strip {
    width: calc(100% - 24px);
    margin-bottom: 8px;
  }
  .todo-confirm { display: none; }
}
</style>
