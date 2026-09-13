"""DeepSeek 兼容入口。

保留原模块和类名，避免既有脚本失效；实现已统一到 OpenAICompatibleProvider。
"""
from app.providers.base import AIProvider
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.providers.registry import create_provider, default_provider_id, get_provider_spec


class DeepSeekProvider(OpenAICompatibleProvider):
    def __init__(self) -> None:
        super().__init__(get_provider_spec("deepseek"))


def get_default_provider() -> AIProvider:
    """环境级默认 Provider；聊天请求使用用户设置中的 active provider。"""
    return create_provider(default_provider_id())
