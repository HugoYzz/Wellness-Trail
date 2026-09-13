"""OpenAI Chat Completions 兼容 Provider。

Ollama、DeepSeek、GLM、OpenAI 与 xAI 的共同协议收敛在这里；厂商差异由
ProviderSpec 能力开关表达，避免聊天引擎出现 provider 分支。
"""
import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx

from app.providers.base import (
    AIProvider,
    ProviderMessage,
    ProviderSpec,
    StreamEvent,
    ToolCallDelta,
)

TIMEOUT = httpx.Timeout(connect=10, read=120, write=30, pool=10)
CHECK_TIMEOUT = httpx.Timeout(connect=3, read=5, write=5, pool=3)


class OpenAICompatibleProvider(AIProvider):
    def __init__(
        self,
        spec: ProviderSpec,
        *,
        model: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.spec = spec
        self.provider_id = spec.id
        self.name = spec.name
        self.base_url = spec.base_url.rstrip("/")
        self.api_key = spec.api_key
        self.model = (model or spec.model).strip()
        self.is_local = spec.is_local
        self.supports_tools = spec.supports_tools
        self.supports_stream = spec.supports_stream
        self.supports_json = spec.supports_json
        self._transport = transport

    @staticmethod
    def _encode_message(message: ProviderMessage) -> dict:
        out: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.tool_calls is not None:
            out["tool_calls"] = message.tool_calls
            out["content"] = None
        if message.tool_call_id is not None:
            out["tool_call_id"] = message.tool_call_id
        return out

    def _payload(
        self,
        messages: list[ProviderMessage],
        tools: list[dict] | None,
        *,
        stream: bool,
    ) -> dict:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                self._encode_message(message)
                for message in messages
                if message.content or message.tool_calls
            ],
            "stream": stream,
        }
        if stream and self.spec.include_stream_usage:
            payload["stream_options"] = {"include_usage": True}
        if tools and self.supports_tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _normalize_usage(raw: dict) -> dict:
        """收敛 OpenAI、DeepSeek 与 Ollama 常见的 token 字段。"""
        prompt = raw.get("prompt_tokens", raw.get("input_tokens", raw.get("prompt_eval_count")))
        completion = raw.get(
            "completion_tokens", raw.get("output_tokens", raw.get("eval_count"))
        )
        details = raw.get("prompt_tokens_details") or raw.get("input_tokens_details") or {}
        cache_hit = raw.get(
            "prompt_cache_hit_tokens",
            details.get("cached_tokens", details.get("cache_read_tokens")),
        )
        total = raw.get("total_tokens")
        if total is None and prompt is not None and completion is not None:
            total = int(prompt) + int(completion)
        normalized = dict(raw)
        if prompt is not None:
            normalized["prompt_tokens"] = int(prompt)
        if completion is not None:
            normalized["completion_tokens"] = int(completion)
        if cache_hit is not None:
            normalized["prompt_cache_hit_tokens"] = int(cache_hit)
        if total is not None:
            normalized["total_tokens"] = int(total)
        return normalized

    def _ensure_ready(self) -> None:
        if not self.model:
            raise RuntimeError(f"{self.name} 未配置模型名称")
        if not self.spec.configured:
            env_name = self.spec.api_key_env or f"{self.provider_id.upper()}_API_KEY"
            raise RuntimeError(f"{env_name} 未配置（server/.env）")

    @staticmethod
    def _tool_events(pending: dict[int, dict]) -> Iterator[StreamEvent]:
        for index in sorted(pending):
            slot = pending[index]
            yield StreamEvent(
                tool_call=ToolCallDelta(
                    id=slot["id"] or f"tool_{index}",
                    name=slot["name"],
                    arguments=slot["arguments"] or "{}",
                ),
                finish_reason="tool_calls",
            )
        pending.clear()

    async def chat(
        self,
        messages: list[ProviderMessage],
        tools: list[dict] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[StreamEvent]:
        self._ensure_ready()
        payload = self._payload(messages, tools, stream=stream)
        pending_tools: dict[int, dict[str, str]] = {}

        async with httpx.AsyncClient(
            timeout=TIMEOUT, transport=self._transport
        ) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            ) as response:
                if response.status_code != 200:
                    detail = (await response.aread()).decode("utf-8", "ignore")
                    raise RuntimeError(
                        f"{self.name} HTTP {response.status_code}: {detail[:300]}"
                    )

                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError(f"{self.name} 返回了无效 SSE 数据") from exc

                    usage = self._normalize_usage(chunk.get("usage") or {})
                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta", {}) or {}
                        text = delta.get("content")
                        if text:
                            yield StreamEvent(delta=text)

                        for tool_call in delta.get("tool_calls", []) or []:
                            index = int(tool_call.get("index", 0))
                            slot = pending_tools.setdefault(
                                index, {"id": "", "name": "", "arguments": ""}
                            )
                            if tool_call.get("id"):
                                slot["id"] = tool_call["id"]
                            function = tool_call.get("function", {}) or {}
                            if function.get("name"):
                                slot["name"] += function["name"]
                            if function.get("arguments"):
                                slot["arguments"] += function["arguments"]

                        finish_reason = choice.get("finish_reason")
                        if finish_reason:
                            if pending_tools:
                                for event in self._tool_events(pending_tools):
                                    yield event
                            else:
                                yield StreamEvent(finish_reason=finish_reason)
                    if usage:
                        yield StreamEvent(usage=usage)

        # 个别兼容端点在 [DONE] 前不返回 finish_reason，仍要交付完整工具调用。
        if pending_tools:
            for event in self._tool_events(pending_tools):
                yield event

    async def check_connection(self) -> dict:
        """调用 /models 验证地址和凭据，不产生模型 token 费用。"""
        self._ensure_ready()
        try:
            async with httpx.AsyncClient(
                timeout=CHECK_TIMEOUT, transport=self._transport
            ) as client:
                response = await client.get(
                    f"{self.base_url}/models", headers=self._headers()
                )
            if response.status_code != 200:
                return {
                    "ok": False,
                    "message": f"HTTP {response.status_code}: {response.text[:160]}",
                }
            return {"ok": True, "message": f"已连接 {self.name} / {self.model}"}
        except httpx.ConnectError:
            target = "本地 Ollama" if self.is_local else self.name
            return {"ok": False, "message": f"无法连接 {target}，请确认服务已启动"}
        except httpx.TimeoutException:
            return {"ok": False, "message": f"连接 {self.name} 超时"}
        except (httpx.HTTPError, RuntimeError) as exc:
            return {"ok": False, "message": str(exc)}
