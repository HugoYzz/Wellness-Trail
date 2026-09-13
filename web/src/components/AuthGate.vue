<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import {
  getAuthStatus,
  loginWithPin,
  logoutAccess,
  setupAccessPin,
  type AuthStatus,
} from '../api'

const props = withDefaults(defineProps<{ refreshKey?: number }>(), { refreshKey: 0 })

const status = ref<AuthStatus | null>(null)
const pin = ref('')
const confirmPin = ref('')
const loading = ref(true)
const busy = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    status.value = await getAuthStatus()
  } catch (e) {
    error.value = `无法连接康迹服务：${(e as Error).message}`
  } finally {
    loading.value = false
  }
}

async function submit() {
  error.value = ''
  if (!/^\d{6,12}$/.test(pin.value)) {
    error.value = '请输入 6-12 位数字 PIN'
    return
  }
  if (!status.value?.pin_configured && pin.value !== confirmPin.value) {
    error.value = '两次输入的 PIN 不一致'
    return
  }

  busy.value = true
  try {
    if (status.value?.pin_configured) {
      await loginWithPin(pin.value)
    } else {
      await setupAccessPin(pin.value)
    }
    pin.value = ''
    confirmPin.value = ''
    await load()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function lock() {
  try {
    await logoutAccess()
  } finally {
    status.value = status.value
      ? { ...status.value, authenticated: false, expires_at: null }
      : null
  }
}

watch(() => props.refreshKey, load)
onMounted(load)
</script>

<template>
  <slot v-if="status?.authenticated" :lock="lock" />

  <main v-else class="auth-shell">
    <section class="auth-card">
      <div class="auth-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="28" height="28">
          <path d="M7 10V8a5 5 0 0 1 10 0v2" fill="none" stroke="currentColor" stroke-width="1.8" />
          <rect x="4" y="10" width="16" height="11" rx="4" fill="none" stroke="currentColor" stroke-width="1.8" />
          <circle cx="12" cy="15.5" r="1.3" fill="currentColor" />
        </svg>
      </div>

      <p class="eyebrow">PRIVATE HEALTH SPACE</p>
      <h1>{{ status?.pin_configured ? '欢迎回来' : '先锁好你的健康档案' }}</h1>
      <p class="lead">
        {{
          status?.pin_configured
            ? '输入访问 PIN 以查看记录、对话与洞察。'
            : '首次使用请创建访问 PIN。PIN 只以加盐哈希形式保存在本机，无法从系统中找回。'
        }}
      </p>

      <div v-if="loading" class="auth-state">正在检查访问状态…</div>
      <form v-else-if="status" @submit.prevent="submit">
        <label>
          <span>{{ status.pin_configured ? '访问 PIN' : '创建 PIN' }}</span>
          <input
            v-model="pin"
            type="password"
            inputmode="numeric"
            pattern="[0-9]*"
            minlength="6"
            maxlength="12"
            :autocomplete="status.pin_configured ? 'current-password' : 'new-password'"
            placeholder="6-12 位数字"
            autofocus
          />
        </label>
        <label v-if="!status.pin_configured">
          <span>再次输入</span>
          <input
            v-model="confirmPin"
            type="password"
            inputmode="numeric"
            pattern="[0-9]*"
            minlength="6"
            maxlength="12"
            autocomplete="new-password"
            placeholder="确认访问 PIN"
          />
        </label>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <button class="primary" type="submit" :disabled="busy">
          {{ busy ? '验证中…' : status.pin_configured ? '解锁康迹' : '创建并进入' }}
        </button>
      </form>
      <div v-else class="auth-state error" role="alert">
        {{ error }}
        <button type="button" @click="load">重新连接</button>
      </div>

      <footer>
        <span>HttpOnly 会话</span><i></i><span>5 次失败限流</span><i></i><span>默认仅本机访问</span>
      </footer>
    </section>
  </main>
</template>

<style scoped>
.auth-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(circle at 20% 10%, rgba(37, 99, 235, 0.13), transparent 31%),
    radial-gradient(circle at 83% 82%, rgba(22, 163, 74, 0.11), transparent 29%),
    var(--bg);
}
.auth-card {
  width: min(100%, 420px);
  padding: 34px;
  background: rgba(255, 255, 255, 0.91);
  border: 1px solid rgba(216, 230, 222, 0.92);
  border-radius: 22px;
  box-shadow: 0 30px 90px rgba(47, 92, 72, 0.16);
  backdrop-filter: blur(18px);
}
.auth-mark {
  display: grid;
  width: 52px;
  height: 52px;
  place-items: center;
  margin-bottom: 22px;
  color: #fff;
  background: linear-gradient(145deg, var(--accent), #24875b);
  border-radius: 16px;
  box-shadow: 0 14px 30px rgba(37, 99, 235, 0.24);
}
.eyebrow {
  margin: 0 0 5px;
  color: var(--accent);
  font: 800 10px/1.2 ui-monospace, Consolas, monospace;
  letter-spacing: 1.7px;
}
h1 {
  margin: 0;
  color: var(--text);
  font-size: 27px;
  line-height: 1.3;
  letter-spacing: -0.7px;
}
.lead {
  margin: 8px 0 24px;
  color: var(--text-dim);
  font-size: 13px;
  line-height: 1.65;
}
form,
label {
  display: grid;
  gap: 7px;
}
form {
  gap: 14px;
}
label span {
  color: var(--text-dim);
  font-size: 12px;
  font-weight: 600;
}
input {
  width: 100%;
  padding: 11px 13px;
  font-size: 18px;
  letter-spacing: 4px;
}
form .primary {
  width: 100%;
  margin-top: 4px;
  padding: 10px 14px;
}
.auth-state {
  display: flex;
  min-height: 100px;
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
  font-size: 13px;
}
.auth-state.error {
  flex-direction: column;
  gap: 12px;
  color: var(--danger);
  text-align: center;
}
.error {
  margin: 0;
  color: var(--danger);
  font-size: 12px;
}
footer {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  margin-top: 24px;
  padding-top: 16px;
  color: var(--text-faint);
  border-top: 1px solid var(--border-soft);
  font-size: 9px;
}
footer i {
  width: 3px;
  height: 3px;
  background: #c2cdc7;
  border-radius: 50%;
}
@media (max-width: 480px) {
  .auth-card {
    padding: 26px 22px;
  }
  footer {
    flex-wrap: wrap;
  }
}
</style>
