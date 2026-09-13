import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { getTodayPlan, updateTodayPlan, type TodayPlan, type TodayTask } from '../api'

/**
 * 跨页共享：个性化今日计划 + 聊天输入预填。
 */
export const useTodoStore = defineStore('todo', () => {
  const plan = ref<TodayPlan | null>(null)
  const loading = ref(false)
  const prefill = ref('')
  const items = computed(() => plan.value?.items ?? [])
  const nextItem = computed<TodayTask | null>(() => {
    const key = plan.value?.next_item_key
    return items.value.find((item) => item.key === key) ?? null
  })

  async function refresh() {
    loading.value = true
    try {
      plan.value = await getTodayPlan()
    } catch {
      /* 后端未起时静默 */
    } finally {
      loading.value = false
    }
  }

  async function change(
    action: 'confirm' | 'skip' | 'restore' | 'rest' | 'reset',
    taskKey?: string,
  ) {
    plan.value = await updateTodayPlan({ action, task_key: taskKey })
  }

  function setPrefill(text: string) {
    prefill.value = text
  }

  function consumePrefill(): string {
    const t = prefill.value
    prefill.value = ''
    return t
  }

  return { plan, items, nextItem, loading, prefill, refresh, change, setPrefill, consumePrefill }
})
