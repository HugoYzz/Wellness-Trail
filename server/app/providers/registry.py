"""Provider 注册表：本地优先，云端按配置启用。"""
from app import config
from app.providers.base import AIProvider, ProviderSpec
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.providers.mock import MockProvider


def provider_specs() -> dict[str, ProviderSpec]:
    specs = (
        ProviderSpec(
            id="mock",
            name="本地 Mock（评测）",
            base_url="local://mock",
            model="kangji-mock-v1",
            is_local=True,
        ),
        ProviderSpec(
            id="ollama",
            name="本地 Qwen",
            base_url=config.OLLAMA_BASE_URL,
            model=config.OLLAMA_MODEL,
            api_key=config.OLLAMA_API_KEY,
            api_key_env="OLLAMA_API_KEY",
            is_local=True,
            include_stream_usage=False,
        ),
        ProviderSpec(
            id="deepseek",
            name="DeepSeek",
            base_url=config.DEEPSEEK_BASE_URL,
            model=config.DEEPSEEK_MODEL,
            api_key=config.DEEPSEEK_API_KEY,
            api_key_env="DEEPSEEK_API_KEY",
            include_stream_usage=True,
        ),
        ProviderSpec(
            id="glm",
            name="智谱 GLM",
            base_url=config.GLM_BASE_URL,
            model=config.GLM_MODEL,
            api_key=config.GLM_API_KEY,
            api_key_env="GLM_API_KEY",
        ),
        ProviderSpec(
            id="openai",
            name="OpenAI GPT",
            base_url=config.OPENAI_BASE_URL,
            model=config.OPENAI_MODEL,
            api_key=config.OPENAI_API_KEY,
            api_key_env="OPENAI_API_KEY",
            include_stream_usage=True,
        ),
        ProviderSpec(
            id="xai",
            name="xAI Grok",
            base_url=config.XAI_BASE_URL,
            model=config.XAI_MODEL,
            api_key=config.XAI_API_KEY,
            api_key_env="XAI_API_KEY",
        ),
    )
    return {spec.id: spec for spec in specs}


def get_provider_spec(provider_id: str) -> ProviderSpec:
    try:
        return provider_specs()[provider_id]
    except KeyError as exc:
        raise ValueError(f"未知 Provider：{provider_id}") from exc


def create_provider(provider_id: str, model: str | None = None) -> AIProvider:
    if provider_id == "mock":
        return MockProvider(model=model)
    return OpenAICompatibleProvider(get_provider_spec(provider_id), model=model)


def default_provider_id() -> str:
    specs = provider_specs()
    return config.LLM_DEFAULT_PROVIDER if config.LLM_DEFAULT_PROVIDER in specs else "ollama"
