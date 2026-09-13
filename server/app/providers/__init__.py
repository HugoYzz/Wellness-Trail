"""本地优先、多厂商可切换的 AI Provider 层。"""

from app.providers.base import AIProvider, ProviderMessage, ProviderSpec, StreamEvent
from app.providers.registry import create_provider, default_provider_id, provider_specs

__all__ = [
    "AIProvider",
    "ProviderMessage",
    "ProviderSpec",
    "StreamEvent",
    "create_provider",
    "default_provider_id",
    "provider_specs",
]
