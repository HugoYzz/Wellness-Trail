"""Deterministic local Provider for offline development and evaluation."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import date

from app import config
from app.providers.base import AIProvider, ProviderMessage, StreamEvent, ToolCallDelta


class MockProvider(AIProvider):
    provider_id = "mock"
    name = "本地 Mock"
    base_url = "local://mock"
    api_key = ""
    model = "kangji-mock-v1"
    is_local = True
    supports_tools = True
    supports_stream = True
    supports_json = True

    def __init__(self, model: str | None = None) -> None:
        if model:
            self.model = model

    async def chat(
        self,
        messages: list[ProviderMessage],
        tools: list[dict] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[StreamEvent]:
        last = messages[-1] if messages else ProviderMessage(role="user", content="")
        user_text = next(
            (message.content or "" for message in reversed(messages) if message.role == "user"),
            "",
        )
        if last.role == "tool":
            answer = "已整理成待确认记录，请核对后入账。"
            yield StreamEvent(delta=answer)
        elif tools and "8000" in user_text:
            yield StreamEvent(
                tool_call=ToolCallDelta(
                    id="mock_step_1",
                    name="register_record",
                    arguments=json.dumps(
                        {
                            "type": "step",
                            "date": date.today().isoformat(),
                            "fields": {"steps": 8000},
                            "raw_text": "今天走了8000步",
                        },
                        ensure_ascii=False,
                    ),
                ),
                finish_reason="tool_calls",
            )
        elif "胸痛" in user_text:
            yield StreamEvent(delta="胸痛可能需要紧急评估，请立即联系急诊或医生。")
        else:
            yield StreamEvent(delta="收到")
        if config.MOCK_STREAM_DELAY_MS:
            await asyncio.sleep(config.MOCK_STREAM_DELAY_MS / 1000)
        prompt_tokens = max(1, sum(len(message.content or "") for message in messages))
        completion_tokens = 8
        yield StreamEvent(
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            }
        )

    async def check_connection(self) -> dict:
        return {"ok": True, "message": "本地 Mock 已就绪（不联网、不发送真实数据）"}
