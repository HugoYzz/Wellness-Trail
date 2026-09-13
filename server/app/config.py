"""应用配置（.env 手工解析，避免额外依赖）。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


load_env()

# 本地会话有效期；PIN 哈希保存在本地数据库，不写入环境文件。
KANGJI_SESSION_HOURS = int(os.environ.get("KANGJI_SESSION_HOURS", "12"))

# 本地优先：未在用户设置中选择 Provider 时，默认走 Ollama。
LLM_DEFAULT_PROVIDER = os.environ.get("LLM_DEFAULT_PROVIDER", "ollama").strip().lower()

# 仅供自动化测试模拟模型流中的短暂停顿；生产默认不延迟。
MOCK_STREAM_DELAY_MS = max(0, int(os.environ.get("MOCK_STREAM_DELAY_MS", "0")))

OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.5:4b")

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

GLM_API_KEY = os.environ.get("GLM_API_KEY", "")
GLM_BASE_URL = os.environ.get("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
GLM_MODEL = os.environ.get("GLM_MODEL", "glm-4.5-flash")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-mini")

XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
XAI_BASE_URL = os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1")
XAI_MODEL = os.environ.get("XAI_MODEL", "grok-4.6")

# RAG 向量层为可选增强；依赖或本地服务不可用时仍使用现有 FTS5。
RAG_VECTOR_ENABLED = os.environ.get("RAG_VECTOR_ENABLED", "0").lower() in {
    "1", "true", "yes", "on"
}
RAG_VECTOR_PATH = os.environ.get(
    "RAG_VECTOR_PATH", str(ROOT / "data" / "qdrant")
)
RAG_VECTOR_COLLECTION = os.environ.get("RAG_VECTOR_COLLECTION", "kangji_kb")
RAG_EMBED_BASE_URL = os.environ.get("RAG_EMBED_BASE_URL", "http://127.0.0.1:11434")
RAG_EMBED_MODEL = os.environ.get("RAG_EMBED_MODEL", "qwen3-embedding:0.6b")
