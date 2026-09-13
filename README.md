# 康迹 · Wellness Trail

单用户、本地优先的健康记录与 AI 复盘应用。它把自然语言记录、结构化时间线、趋势洞察、个性化今日计划和个人知识库放在一个 Web 界面中；默认数据保存在本机 SQLite，AI 可选择本地 Ollama、本地 Mock 或兼容 OpenAI 协议的云端 Provider。

> 本项目处理高度敏感的个人健康数据。根目录 `assets/` 已被 Git 忽略，仅用于本地资料；不要强制提交其中的个人文档。

## 已实现

- 首次发送消息才创建当天会话，避免空会话积累。
- AI 流式对话支持 `request_id` 幂等、`Last-Event-ID` 断线续传和自动重试。
- AI 生成记录卡，确认后入账；时间线支持新增、删除与历史纠错修改。
- 体重、腰围、步数、睡眠、饮食和运动趋势及周报。
- 个性化今日计划、洞察反馈闭环、FTS5 与可选 Qdrant/Ollama 混合 RAG。
- Ollama、DeepSeek、GLM、OpenAI、xAI 与本地 Mock Provider；内置评测集辅助模型选择。
- Token 实测/估算覆盖率与费用口径说明。
- 版本化 JSON 备份、隔离恢复演练和显式确认后的事务恢复。
- PIN 访问控制、默认仅监听本机、密钥仅由后端环境变量读取。

## 技术结构

```text
web/        Vue 3 + TypeScript + Vite
server/     FastAPI + SQLAlchemy + Alembic + SQLite
scripts/    数据导入、校验与本地 AI 辅助脚本
assets/     本地可导入知识资料（含个人隐私，已忽略，不入库）
docs/       部署、架构、用户手册与安全检查
```

## 本地启动（Windows）

要求：Python 3.12+、Node.js 22+。如需本地模型，另安装 Ollama。

```powershell
cd server
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
Copy-Item .env.example .env
cd ..\web
npm ci
cd ..
.\start.ps1
```

打开 [http://localhost:5173](http://localhost:5173)，首次访问创建 6–12 位数字 PIN。默认只监听 `127.0.0.1`；仅在可信网络且已设置 PIN 后使用 `./start.ps1 -Lan`。

Provider、RAG 和环境变量配置见 [本地 AI 与 RAG 部署](docs/本地AI与RAG部署.md)。日常使用见 [用户手册](docs/用户手册.md)。

## 测试

```powershell
# 后端
$env:PYTHONPATH = "server"
python -m unittest discover -s server/tests -v

# 前端单元测试与构建
cd web
npm run test:unit
npm run build

# 浏览器级 SSE 断线续传（自动启动隔离的前后端）
npx playwright install chromium
npm run test:e2e
```

GitHub Actions 会在推送和 Pull Request 时执行以上三组验证。E2E 使用独立临时数据库与本地 Mock，不会读取或发送真实健康数据。

## 备份与恢复

在“设置 → 数据备份与恢复”中：

1. 导出完整 JSON 备份并复制到非系统盘。
2. 选择备份文件，先执行隔离恢复演练；演练不会改动当前数据。
3. 核对对象数量和警告后，才可执行真实恢复。真实恢复会在事务中替换当前数据，请先保留第二份备份。

## 安全边界

当前版本适合单机或可信局域网内的个人使用，不应直接暴露到公网。HTTPS、持久化服务端会话、更强的文件权限自动检查等上线条件见 [安全检查清单](docs/安全检查清单.md)。漏洞披露方式见 [SECURITY.md](SECURITY.md)。

## 项目状态

P0–P3 产品主线已完成；P4 的文档、恢复演练、自动化测试和 CI 已落地。公网部署与运维加固仍属于后续范围。
