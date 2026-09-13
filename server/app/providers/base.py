"""AI Provider 抽象层（架构 §6.2）。

Provider 统一描述连接信息与能力；聊天引擎只依赖此抽象，不绑定厂商。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class ToolCallDelta:
    """一次工具调用（完成后聚合）。"""

    id: str
    name: str
    arguments: str  # JSON 字符串


@dataclass
class StreamEvent:
    """流式事件：增量 token 或完成的工具调用。"""

    delta: str = ""
    tool_call: ToolCallDelta | None = None
    finish_reason: str | None = None
    usage: dict = field(default_factory=dict)


@dataclass
class ProviderMessage:
    """对话消息（OpenAI 兼容格式）。"""

    role: str  # system/user/assistant/tool
    content: str | None = None
    tool_calls: list[dict] | None = None  # assistant 消息携带
    tool_call_id: str | None = None  # tool 消息携带


@dataclass(frozen=True)
class ProviderSpec:
    """Provider 的静态配置和能力声明。API Key 只存在后端内存中。"""

    id: str
    name: str
    base_url: str
    model: str
    api_key: str = ""
    api_key_env: str = ""
    is_local: bool = False
    supports_tools: bool = True
    supports_stream: bool = True
    supports_json: bool = True
    include_stream_usage: bool = False

    @property
    def configured(self) -> bool:
        return self.is_local or bool(self.api_key)


class AIProvider(ABC):
    provider_id: str
    name: str
    base_url: str
    api_key: str
    model: str
    is_local: bool = False
    supports_tools: bool = True
    supports_stream: bool = True
    supports_json: bool = True

    @abstractmethod
    async def chat(
        self,
        messages: list[ProviderMessage],
        tools: list[dict] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[StreamEvent]:
        """流式对话；yield StreamEvent。"""
        raise NotImplementedError

    @abstractmethod
    async def check_connection(self) -> dict:
        """低成本连接检测，不发送用户健康数据。"""
        raise NotImplementedError


def tool_result_message(tool_call_id: str, content: str) -> ProviderMessage:
    return ProviderMessage(role="tool", content=content, tool_call_id=tool_call_id)
