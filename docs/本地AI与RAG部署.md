# 康迹本地 AI 与 RAG 部署

康迹现在采用“本地优先、手动上云”的模型策略：默认通过 Ollama 调用
`qwen3.5:4b`，并保留 DeepSeek、智谱 GLM、OpenAI GPT、xAI Grok 的接口。
系统不会因为本地模型不可用而静默切换云端。

## 架构与隐私边界

- 本地推理：Ollama + `qwen3.5:4b`。
- 基础检索：SQLite FTS5 / BM25，始终可用。
- 可选向量检索：Ollama `qwen3-embedding:0.6b` + 本地磁盘 Qdrant，
  与 FTS5 结果通过 RRF 融合。
- 云端模型：只在设置页由用户主动切换；切换时会再次提示本轮问题、必要历史和
  RAG 上下文将发送给服务商。
- API Key：只从 `server/.env` 读取，不保存进数据库，也不会返回浏览器。

首版暂不启用 Reranker。待真实问题集积累后，再评估
`Qwen3-Reranker-0.6B` 带来的准确率收益和延迟成本。

## 首次准备

1. 安装 Python 3.12、Node.js 和 [Ollama](https://ollama.com/download)，并启动 Ollama。
2. 在项目根目录运行：

   ```powershell
   .\scripts\setup_local_ai.ps1
   ```

   该脚本会安装 Qdrant/PyMuPDF 依赖，并下载聊天与 Embedding 模型。模型约占
   4.6 GB，另需为知识库索引预留空间。
3. 将 `server/.env.example` 中需要的配置合并进 `server/.env`。如果当前只需要
   本地对话，保留 `RAG_VECTOR_ENABLED=0` 即可。
4. 在确认 Embedding 模型可用后，将 `RAG_VECTOR_ENABLED=1`，重启后端，然后前往
   “设置 → RAG 检索链 → 重建向量索引”。

## 云端 Provider

按需在 `server/.env` 填入以下任一密钥，未配置的 Provider 会在设置页保持禁用：

```dotenv
DEEPSEEK_API_KEY=
GLM_API_KEY=
OPENAI_API_KEY=
XAI_API_KEY=
```

模型名称和 Base URL 均可通过环境变量调整；完整字段见
`server/.env.example`。模型选择保存在本机数据库中，切回“本地 Qwen”后不会继续
向云端发送请求。

## 启动与验收

```powershell
.\start.ps1
```

- 前端：<http://localhost:5173>
- 后端健康检查：<http://localhost:8001/api/health>
- 设置页先点击“本地 Qwen → 测试连接”。
- 开启向量检索后点击“重建向量索引”，确认状态显示索引块数。
- 再用同一问题分别测试本地 Qwen 和一个云端模型，验证手动切换与无静默回退。

8 GB 显存设备建议先保持 8K–16K 上下文；不要把超长上下文能力直接等同于本机
可承受的运行长度。
