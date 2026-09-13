<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  evaluateProvider,
  getProviders,
  getRagStatus,
  getUsage,
  rebuildRagIndex,
  restoreBackup,
  selectProvider,
  testProvider,
  validateBackup,
  type ProviderInfo,
  type ProvidersInfo,
  type RagStatus,
  type RestoreValidation,
  type UsageInfo,
} from '../api'

const usage = ref<UsageInfo | null>(null)
const providers = ref<ProvidersInfo | null>(null)
const rag = ref<RagStatus | null>(null)
const modelDrafts = ref<Record<string, string>>({})
const testResults = ref<Record<string, { ok: boolean; message: string }>>({})
const error = ref('')
const notice = ref('')
const loading = ref(true)
const exporting = ref(false)
const selecting = ref('')
const testing = ref('')
const evaluating = ref('')
const indexing = ref(false)
const restoring = ref(false)
const restorePayload = ref<Record<string, unknown> | null>(null)
const restoreReport = ref<RestoreValidation | null>(null)

const activeProvider = computed(() =>
  providers.value?.providers.find((provider) => provider.selected),
)

function fmt(n: number): string {
  return n.toLocaleString('zh-CN')
}

function applyProviderData(data: ProvidersInfo) {
  providers.value = data
  modelDrafts.value = Object.fromEntries(
    data.providers.map((provider) => [provider.id, provider.model]),
  )
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [usageData, providerData, ragData] = await Promise.all([
      getUsage(),
      getProviders(),
      getRagStatus(),
    ])
    usage.value = usageData
    applyProviderData(providerData)
    rag.value = ragData
  } catch (e) {
    error.value = `加载失败：${(e as Error).message}`
  } finally {
    loading.value = false
  }
}

async function rebuildIndex() {
  indexing.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await rebuildRagIndex()
    rag.value = result
    notice.value = `向量索引已更新：${result.indexed} 个知识块`
  } catch (e) {
    error.value = `索引失败：${(e as Error).message}`
  } finally {
    indexing.value = false
  }
}

async function runConnectionTest(provider: ProviderInfo) {
  testing.value = provider.id
  error.value = ''
  notice.value = ''
  try {
    testResults.value = {
      ...testResults.value,
      [provider.id]: await testProvider(provider.id),
    }
  } catch (e) {
    testResults.value = {
      ...testResults.value,
      [provider.id]: { ok: false, message: (e as Error).message },
    }
  } finally {
    testing.value = ''
  }
}

async function runEvaluation(provider: ProviderInfo) {
  if (!provider.configured) return
  if (
    !provider.is_local &&
    !window.confirm(`将向 ${provider.name} 发送 3 条不含个人健康数据的合成测试，并可能产生少量 Token 费用。是否继续？`)
  ) return
  evaluating.value = provider.id
  error.value = ''
  notice.value = ''
  try {
    const result = await evaluateProvider(provider.id, modelDrafts.value[provider.id] || provider.model)
    applyProviderData(await getProviders())
    notice.value = `${provider.name} 评测完成：${result.score} 分，平均 ${result.avg_latency_ms} ms`
  } catch (e) {
    error.value = `评测失败：${(e as Error).message}`
  } finally {
    evaluating.value = ''
  }
}

async function activate(provider: ProviderInfo) {
  error.value = ''
  notice.value = ''
  if (!provider.configured) {
    error.value = `${provider.name} 尚未配置 API Key，请先编辑 server/.env。`
    return
  }
  let allowCloud = false
  if (!provider.is_local) {
    allowCloud = window.confirm(
      `切换到 ${provider.name} 后，本轮问题、必要历史和 RAG 检索上下文会发送给该服务商。是否继续？`,
    )
    if (!allowCloud) return
  }
  selecting.value = provider.id
  try {
    const data = await selectProvider({
      provider_id: provider.id,
      model: modelDrafts.value[provider.id] || provider.model,
      allow_cloud_health_data: allowCloud,
    })
    applyProviderData(data)
    usage.value = await getUsage()
    notice.value = `已切换到 ${provider.name}`
  } catch (e) {
    error.value = `切换失败：${(e as Error).message}`
  } finally {
    selecting.value = ''
  }
}

async function exportBackup() {
  exporting.value = true
  error.value = ''
  try {
    const resp = await fetch('/api/settings/export', { credentials: 'same-origin' })
    if (resp.status === 401 || resp.status === 428) {
      window.dispatchEvent(new Event('kangji-auth-required'))
    }
    if (!resp.ok) throw new Error(`${resp.status}`)
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const cd = resp.headers.get('Content-Disposition') ?? ''
    const match = /filename="?([^";]+)"?/.exec(cd)
    a.download = match?.[1] ?? 'kangji-backup.json'
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    error.value = `导出失败：${(e as Error).message}`
  } finally {
    exporting.value = false
  }
}

async function inspectBackup(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  restorePayload.value = null
  restoreReport.value = null
  error.value = ''
  notice.value = ''
  if (!file) return
  try {
    const parsed = JSON.parse(await file.text()) as Record<string, unknown>
    restoreReport.value = await validateBackup(parsed)
    restorePayload.value = parsed
    notice.value = `恢复演练通过：${Object.values(restoreReport.value.counts).reduce((a, b) => a + b, 0)} 个对象可恢复`
  } catch (e) {
    error.value = `备份验证失败：${(e as Error).message}`
  }
}

async function applyRestore() {
  if (!restorePayload.value || !restoreReport.value?.ok) return
  const counts = restoreReport.value.counts
  const summary = `记录 ${counts.records ?? 0} 条、会话 ${counts.chats ?? 0} 个、消息 ${counts.messages ?? 0} 条`
  if (!window.confirm(`将用所选备份替换当前业务数据（${summary}）。恢复过程使用单个事务，失败会回滚。是否继续？`)) return
  restoring.value = true
  error.value = ''
  try {
    restoreReport.value = await restoreBackup(restorePayload.value)
    notice.value = '恢复完成，页面数据已重新加载。'
    await load()
  } catch (e) {
    error.value = `恢复失败，原数据已保留：${(e as Error).message}`
  } finally {
    restoring.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="settings">
    <header class="settings-head">
      <div>
        <p class="eyebrow">LOCAL-FIRST AI CONTROL</p>
        <h2>模型与数据设置</h2>
        <p class="intro">默认在本机完成推理，需要更强能力时再由你选择云端模型。</p>
      </div>
      <div v-if="activeProvider" class="active-pill" :class="{ local: activeProvider.is_local }">
        <span class="status-dot" aria-hidden="true"></span>
        <span>当前 · {{ activeProvider.name }}</span>
      </div>
    </header>

    <p v-if="loading" class="loading">正在读取模型配置…</p>
    <p v-if="error" class="feedback error" role="alert">{{ error }}</p>
    <p v-if="notice" class="feedback success" role="status">{{ notice }}</p>

    <section v-if="providers" class="provider-section">
      <div class="section-title">
        <div>
          <span class="section-no">01</span>
          <h3>推理引擎</h3>
        </div>
        <div class="provider-notes">
          <p>{{ providers.privacy_note }}</p>
          <p class="selection-note">{{ providers.selection_note }}</p>
        </div>
      </div>

      <div class="provider-grid">
        <article
          v-for="provider in providers.providers"
          :key="provider.id"
          class="provider-card"
          :class="{ active: provider.selected, unavailable: !provider.configured }"
        >
          <div class="provider-topline">
            <span class="provider-kind">{{ provider.is_local ? 'LOCAL' : 'CLOUD' }}</span>
            <span v-if="provider.selected" class="selected-mark">使用中</span>
            <span v-else-if="!provider.configured" class="missing-mark">待配置</span>
          </div>

          <div>
            <h4>{{ provider.name }}</h4>
            <p class="endpoint">{{ provider.base_url }}</p>
          </div>

          <label class="model-field">
            <span>模型标识</span>
            <input v-model="modelDrafts[provider.id]" :aria-label="`${provider.name} 模型标识`" />
          </label>

          <div class="capabilities" aria-label="模型能力">
            <span :class="{ on: provider.capabilities.stream }">流式</span>
            <span :class="{ on: provider.capabilities.tools }">工具</span>
            <span :class="{ on: provider.capabilities.json }">JSON</span>
          </div>

          <div v-if="provider.evaluation" class="evaluation">
            <div>
              <strong>{{ provider.evaluation.score }}</strong><span>/100</span>
              <small>平均 {{ provider.evaluation.avg_latency_ms }} ms</small>
            </div>
            <ul>
              <li v-for="item in provider.evaluation.cases" :key="item.id">
                <span>{{ item.label }}</span><b>{{ item.score }}</b>
              </li>
            </ul>
            <p v-if="providers.recommended_provider_id === provider.id">当前评测推荐</p>
          </div>

          <p
            v-if="testResults[provider.id]"
            class="test-result"
            :class="testResults[provider.id].ok ? 'ok' : 'bad'"
          >
            {{ testResults[provider.id].message }}
          </p>

          <div class="provider-actions">
            <button
              :disabled="evaluating === provider.id || !provider.configured"
              @click="runEvaluation(provider)"
            >
              {{ evaluating === provider.id ? '评测中…' : '运行评测' }}
            </button>
            <button
              :disabled="testing === provider.id || !provider.configured"
              @click="runConnectionTest(provider)"
            >
              {{ testing === provider.id ? '检测中…' : '测试连接' }}
            </button>
            <button
              class="activate"
              :disabled="selecting === provider.id || !provider.configured"
              @click="activate(provider)"
            >
              {{ provider.selected ? '保存模型名' : selecting === provider.id ? '切换中…' : '设为使用' }}
            </button>
          </div>
        </article>
      </div>
    </section>

    <section v-if="usage" class="lower-grid">
      <article v-if="rag" class="data-card rag-card">
        <div class="rag-heading">
          <div class="section-title compact">
            <div><span class="section-no">02</span><h3>RAG 检索链</h3></div>
          </div>
          <span class="rag-state" :class="{ ready: rag.ready }">
            {{ rag.ready ? '混合检索已就绪' : rag.enabled ? '等待建索引' : 'FTS5 稳定模式' }}
          </span>
        </div>
        <div class="rag-flow" aria-label="RAG 检索流程">
          <span>{{ rag.keyword_retrieval }}</span><i>+</i>
          <span>{{ rag.embedding_model }}</span><i>→</i>
          <span>Qdrant · {{ rag.points }} 块</span><i>→</i>
          <span>{{ rag.fusion }}</span>
        </div>
        <div class="rag-footer">
          <p>{{ rag.message }}；{{ rag.reranker }}</p>
          <button :disabled="!rag.enabled || indexing" @click="rebuildIndex">
            {{ indexing ? '正在向量化…' : '重建向量索引' }}
          </button>
        </div>
      </article>

      <article class="data-card dataflow-card">
        <div class="section-title compact">
          <div><span class="section-no">03</span><h3>数据流向</h3></div>
        </div>
        <div class="flow-compare">
          <div class="flow-local">
            <strong>本地模型</strong>
            <p>问题、必要历史与 RAG 检索片段只在本机 Ollama 中处理，不离开设备。</p>
          </div>
          <div class="flow-cloud">
            <strong>云端模型</strong>
            <p>仅在你主动切换后，发送本轮问题、必要对话历史和命中的知识片段；不会自动上传完整数据库或备份。</p>
          </div>
        </div>
        <p class="flow-key">API Key 仅由后端读取；页面只显示“已配置 / 未配置”，不返回任何字符片段。</p>
      </article>

      <article class="data-card usage-card">
        <div class="section-title compact">
          <div><span class="section-no">04</span><h3>用量脉搏</h3></div>
        </div>
        <div class="metric-grid">
          <div><span>AI 回复</span><strong>{{ fmt(usage.assistant_messages) }}</strong></div>
          <div><span>输入 token</span><strong>{{ fmt(usage.tokens.prompt_total) }}</strong></div>
          <div><span>输出 token</span><strong>{{ fmt(usage.tokens.completion) }}</strong></div>
          <div>
            <span>API 费用估算</span>
            <strong>{{ usage.cost_yuan === null ? '本地 ¥0' : `¥${usage.cost_yuan.toFixed(4)}` }}</strong>
          </div>
        </div>
        <p class="usage-coverage">
          Provider 实测 {{ usage.usage_coverage.measured_messages }} 条 · 透明估算
          {{ usage.usage_coverage.estimated_messages }} 条（其中历史补算
          {{ usage.usage_coverage.historical_estimated_messages }} 条）· 历史未知
          {{ usage.usage_coverage.unknown_messages }} 条
        </p>
        <p class="hint">{{ usage.price_note }}</p>
      </article>

      <article class="data-card backup-card">
        <div class="section-title compact">
          <div><span class="section-no">05</span><h3>数据保险箱</h3></div>
        </div>
        <p class="backup-copy">导出记录、会话、消息与知识库元数据。建议在每周复盘后保存到非系统盘。</p>
        <button class="primary" :disabled="exporting" @click="exportBackup">
          {{ exporting ? '正在封装数据…' : '导出完整 JSON 备份' }}
        </button>
        <label class="restore-picker">
          <span>恢复演练与恢复</span>
          <input type="file" accept="application/json,.json" :disabled="restoring" @change="inspectBackup" />
        </label>
        <div v-if="restoreReport" class="restore-report">
          <strong>
            {{ restoreReport.drill?.restored ? '隔离恢复演练通过' : '校验通过' }} · 格式 v{{ restoreReport.format_version }}
          </strong>
          <span>
            records {{ restoreReport.counts.records ?? 0 }} · chats {{ restoreReport.counts.chats ?? 0 }} ·
            messages {{ restoreReport.counts.messages ?? 0 }}
          </span>
          <small v-for="warning in restoreReport.warnings" :key="warning">{{ warning }}</small>
          <button class="danger" :disabled="restoring" @click="applyRestore">
            {{ restoring ? '正在事务恢复…' : '确认恢复此备份' }}
          </button>
        </div>
      </article>
    </section>

    <p class="foot-hint">健康数据接口由 PIN 会话统一保护；点击顶部“锁定”可立即注销当前会话。</p>
  </div>
</template>

<style scoped>
.settings {
  display: flex;
  flex-direction: column;
  gap: 18px;
  max-width: 1040px;
  margin: 0 auto;
}
.settings-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  padding: 8px 2px 2px;
}
.eyebrow {
  margin: 0 0 4px;
  color: var(--accent);
  font: 700 10px/1.2 ui-monospace, Consolas, monospace;
  letter-spacing: 1.8px;
}
.settings-head h2 {
  font-size: clamp(24px, 4vw, 36px);
  letter-spacing: -1.2px;
}
.intro {
  margin: 6px 0 0;
  color: var(--text-dim);
  font-size: 13px;
}
.active-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex: none;
  border: 1px solid #d9e1ed;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.84);
  padding: 7px 12px;
  color: var(--text-dim);
  font-size: 12px;
  box-shadow: var(--shadow-card);
}
.active-pill.local {
  color: #167443;
  border-color: #bfe3cf;
  background: #f1fbf5;
}
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 0 4px color-mix(in srgb, currentColor 13%, transparent);
}
.provider-section,
.data-card {
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  background: rgba(255, 255, 255, 0.8);
  box-shadow: var(--shadow-card);
}
.provider-section {
  padding: 18px;
}
.section-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 15px;
}
.section-title > div {
  display: flex;
  align-items: center;
  gap: 10px;
}
.section-title h3 {
  margin: 0;
  color: var(--text);
  font-size: 14px;
  letter-spacing: 0.4px;
}
.section-title p {
  max-width: 540px;
  margin: 0;
  color: var(--text-faint);
  font-size: 11px;
  text-align: right;
}
.provider-notes {
  display: grid !important;
  justify-items: end;
  gap: 3px !important;
}
.section-title .selection-note { color: var(--accent-strong); }
.section-no {
  color: var(--accent);
  font: 700 10px/1 ui-monospace, Consolas, monospace;
}
.provider-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 11px;
}
.provider-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 13px;
  min-width: 0;
  padding: 15px;
  overflow: hidden;
  border: 1px solid var(--border-soft);
  border-radius: 13px;
  background: #fff;
  transition: transform 0.18s var(--ease), border-color 0.18s var(--ease), box-shadow 0.18s var(--ease);
}
.provider-card::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: transparent;
}
.provider-card:hover {
  transform: translateY(-1px);
  border-color: #bfd2c8;
}
.provider-card.active {
  border-color: #91b7f5;
  box-shadow: 0 12px 30px rgba(37, 99, 235, 0.11);
}
.provider-card.active::before {
  background: linear-gradient(#4c8df6, #2bb673);
}
.provider-card.unavailable {
  background: #fafcfb;
}
.provider-topline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 18px;
}
.provider-kind,
.selected-mark,
.missing-mark {
  font: 700 9px/1 ui-monospace, Consolas, monospace;
  letter-spacing: 1px;
}
.provider-kind { color: var(--text-faint); }
.selected-mark { color: var(--ok); }
.missing-mark { color: var(--warn); }
.provider-card h4 {
  margin: 0;
  font-size: 17px;
}
.endpoint {
  margin: 2px 0 0;
  overflow: hidden;
  color: var(--text-faint);
  font: 10px/1.4 ui-monospace, Consolas, monospace;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.model-field {
  display: grid;
  gap: 5px;
}
.model-field span {
  color: var(--text-dim);
  font-size: 11px;
}
.model-field input {
  width: 100%;
  min-width: 0;
  font: 12px/1.4 ui-monospace, Consolas, monospace;
}
.capabilities {
  display: flex;
  gap: 6px;
}
.capabilities span {
  border: 1px solid var(--border-soft);
  border-radius: 999px;
  padding: 3px 7px;
  color: var(--text-faint);
  font-size: 10px;
}
.capabilities span.on {
  color: #176b43;
  border-color: #c6e3d3;
  background: #f0faf4;
}
.evaluation {
  display: grid;
  gap: 7px;
  border-radius: 10px;
  padding: 9px 10px;
  background: var(--panel);
}
.evaluation > div {
  display: flex;
  align-items: baseline;
  gap: 3px;
}
.evaluation strong { font: 700 18px/1 ui-monospace, Consolas, monospace; }
.evaluation span,
.evaluation small { color: var(--text-faint); font-size: 10px; }
.evaluation small { margin-left: auto; }
.evaluation ul {
  display: flex;
  gap: 5px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.evaluation li {
  display: flex;
  gap: 4px;
  border: 1px solid var(--border-soft);
  border-radius: 999px;
  padding: 3px 6px;
  background: #fff;
}
.evaluation li b { color: var(--text-dim); font-size: 10px; }
.evaluation p { margin: 0; color: var(--ok); font-size: 10px; font-weight: 700; }
.provider-actions {
  display: flex;
  justify-content: flex-end;
  gap: 7px;
  margin-top: auto;
}
.provider-actions button {
  padding: 6px 10px;
  font-size: 11px;
}
.provider-actions .activate {
  color: var(--accent-strong);
  border-color: #c7d9fa;
  background: #f4f8ff;
  font-weight: 600;
}
.test-result {
  margin: 0;
  font-size: 11px;
  line-height: 1.45;
}
.test-result.ok { color: var(--ok); }
.test-result.bad { color: var(--danger); }
.lower-grid {
  display: grid;
  grid-template-columns: 1.2fr 0.8fr;
  gap: 12px;
}
.data-card {
  padding: 17px;
}
.rag-card {
  grid-column: 1 / -1;
}
.dataflow-card {
  grid-column: 1 / -1;
}
.flow-compare {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 9px;
}
.flow-compare > div {
  padding: 11px 12px;
  border: 1px solid var(--border-soft);
  border-radius: 10px;
}
.flow-local {
  background: var(--ok-dim);
}
.flow-cloud {
  background: var(--warn-dim);
}
.flow-compare strong {
  display: block;
  margin-bottom: 3px;
  font-size: 12px;
}
.flow-compare p,
.flow-key {
  margin: 0;
  color: var(--text-dim);
  font-size: 11px;
  line-height: 1.6;
}
.flow-key {
  margin-top: 9px;
  color: var(--text-faint);
}
.rag-heading,
.rag-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}
.rag-heading .section-title {
  margin-bottom: 0;
}
.rag-state {
  border-radius: 999px;
  padding: 4px 9px;
  color: var(--text-dim);
  background: var(--panel);
  font-size: 10px;
  font-weight: 700;
}
.rag-state.ready {
  color: #167443;
  background: var(--ok-dim);
}
.rag-flow {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 14px 0;
  overflow-x: auto;
}
.rag-flow span {
  flex: none;
  border: 1px solid var(--border-soft);
  border-radius: 8px;
  padding: 7px 9px;
  background: #fff;
  color: var(--text-dim);
  font: 10px/1.2 ui-monospace, Consolas, monospace;
}
.rag-flow i {
  color: var(--text-faint);
  font-style: normal;
}
.rag-footer p {
  margin: 0;
  color: var(--text-faint);
  font-size: 11px;
}
.rag-footer button {
  flex: none;
  font-size: 11px;
}
.section-title.compact {
  margin-bottom: 12px;
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.metric-grid > div {
  display: grid;
  gap: 3px;
  border-radius: 10px;
  padding: 10px 11px;
  background: var(--panel);
}
.metric-grid span {
  color: var(--text-faint);
  font-size: 10px;
}
.metric-grid strong {
  font: 700 16px/1.2 ui-monospace, Consolas, monospace;
}
.usage-coverage {
  margin: 10px 0 0;
  color: var(--text-dim);
  font-size: 10px;
}
.hint,
.backup-copy {
  margin: 12px 0 0;
  color: var(--text-faint);
  font-size: 11px;
  line-height: 1.6;
}
.backup-copy {
  margin: 0 0 18px;
  color: var(--text-dim);
}
.backup-card {
  display: flex;
  flex-direction: column;
}
.backup-card .primary {
  margin-top: auto;
}
.restore-picker {
  display: grid;
  gap: 6px;
  margin-top: 14px;
  padding-top: 13px;
  border-top: 1px solid var(--border-soft);
  color: var(--text-dim);
  font-size: 11px;
}
.restore-picker input {
  max-width: 100%;
  font-size: 11px;
}
.restore-report {
  display: grid;
  gap: 6px;
  margin-top: 10px;
  padding: 10px;
  border: 1px solid #bfe3cf;
  border-radius: 10px;
  background: var(--ok-dim);
  font-size: 11px;
}
.restore-report span,
.restore-report small { color: var(--text-dim); }
.restore-report .danger { justify-self: start; }
.feedback,
.loading {
  margin: 0;
  border-radius: 10px;
  padding: 9px 12px;
  font-size: 12px;
}
.loading { color: var(--text-dim); background: var(--panel); }
.feedback.error { color: var(--danger); background: var(--danger-dim); }
.feedback.success { color: var(--ok); background: var(--ok-dim); }
.foot-hint {
  margin: 0;
  color: var(--text-faint);
  font-size: 10px;
  text-align: center;
}

@media (max-width: 760px) {
  .settings-head,
  .section-title {
    align-items: flex-start;
    flex-direction: column;
  }
  .section-title p { text-align: left; }
  .provider-notes { justify-items: start; }
  .provider-grid,
  .lower-grid,
  .flow-compare { grid-template-columns: 1fr; }
  .rag-footer { align-items: flex-start; flex-direction: column; }
}

@media (max-width: 480px) {
  .provider-section { padding: 12px; }
  .provider-card { padding: 13px; }
  .metric-grid { grid-template-columns: 1fr; }
}
</style>
