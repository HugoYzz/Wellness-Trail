<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import AuthGate from './components/AuthGate.vue'
import TodoStrip from './components/TodoStrip.vue'

const authRefresh = ref(0)
function requireAuth() {
  authRefresh.value += 1
}
onMounted(() => window.addEventListener('kangji-auth-required', requireAuth))
onBeforeUnmount(() => window.removeEventListener('kangji-auth-required', requireAuth))
</script>

<template>
  <AuthGate :refresh-key="authRefresh" v-slot="{ lock }">
    <header class="topbar">
      <div class="topbar-inner">
        <RouterLink to="/" class="brand">
        <svg class="brand-mark" viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
          <rect x="1" y="1" width="22" height="22" rx="7" fill="url(#kg)" />
          <path
            d="M5.5 12.5h3l1.8-4.2 2.6 7.4 1.8-3.2h4"
            fill="none"
            stroke="#fff"
            stroke-width="1.9"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
          <defs>
            <linearGradient id="kg" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stop-color="#5aa7fb" />
              <stop offset="1" stop-color="#3f7fe0" />
            </linearGradient>
          </defs>
        </svg>
        <span class="brand-name">康迹</span>
        </RouterLink>
        <nav>
          <RouterLink to="/">对话</RouterLink>
          <RouterLink to="/timeline">时间线</RouterLink>
          <RouterLink to="/dashboard">洞察</RouterLink>
          <RouterLink to="/record">记录</RouterLink>
          <RouterLink to="/settings">设置</RouterLink>
          <button class="lock-button" type="button" title="锁定康迹" @click="lock">锁定</button>
        </nav>
      </div>
      <TodoStrip />
    </header>

    <main class="page">
      <RouterView />
    </main>

    <footer class="foot">
    <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true" class="foot-icon">
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2" />
      <path d="M12 8v5M12 16.5v.01" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
    </svg>
    康迹为记录与生活方式管理工具，不做疾病诊断、不提供处方级建议；症状持续或加重请线下就医。
    </footer>
  </AuthGate>
</template>

<style scoped>
.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: blur(18px) saturate(150%);
  -webkit-backdrop-filter: blur(18px) saturate(150%);
  border-bottom: 1px solid var(--border-soft);
}
.topbar-inner {
  max-width: 1240px;
  margin: 0 auto;
  padding: 12px 24px 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 9px;
  color: var(--text);
}
.brand-mark {
  filter: drop-shadow(0 8px 14px rgba(37, 99, 235, 0.14));
  flex: none;
}
.brand-name {
  font-size: 21px;
  font-weight: 700;
  letter-spacing: 0;
}
nav {
  display: flex;
  gap: 8px;
}
nav a {
  color: var(--text-dim);
  padding: 8px 13px;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 600;
  transition: color 0.15s var(--ease), background 0.15s var(--ease);
}
nav a:hover {
  color: var(--text);
  background: rgba(237, 246, 241, 0.86);
}
nav a.router-link-active {
  color: var(--accent-strong);
  background: var(--accent-dim);
  font-weight: 600;
}
.lock-button {
  padding: 7px 10px;
  color: var(--text-faint);
  background: transparent;
  border-color: transparent;
  font-size: 12px;
}
.lock-button:hover {
  color: var(--text);
  background: var(--bg-soft);
  border-color: transparent;
}
.foot {
  padding: 14px 16px 22px;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  gap: 6px;
  color: var(--text-faint);
  font-size: 12px;
  line-height: 1.5;
  border-top: 1px solid var(--border-soft);
  max-width: 1240px;
  margin: 0 auto;
}
.foot-icon {
  flex: none;
  margin-top: 3px;
}

@media (max-width: 480px) {
  .topbar-inner {
    padding: 10px 12px 8px;
    flex-wrap: wrap;
  }
  .brand-name {
    font-size: 18px;
  }
  nav {
    gap: 0;
    width: 100%;
    overflow-x: auto;
  }
  nav a {
    padding: 6px 9px;
    font-size: 13px;
    white-space: nowrap;
  }
  .lock-button {
    padding: 5px 8px;
    white-space: nowrap;
  }
}
</style>
