import json
import unittest

import httpx

from app.providers.base import ProviderMessage, ProviderSpec
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.providers.registry import default_provider_id, provider_specs


class ProviderRegistryTests(unittest.TestCase):
    def test_local_provider_is_default_and_cloud_options_exist(self):
        specs = provider_specs()
        self.assertEqual(default_provider_id(), "ollama")
        self.assertTrue(specs["ollama"].is_local)
        self.assertTrue({"deepseek", "glm", "openai", "xai"} <= specs.keys())

    def test_ollama_payload_omits_vendor_specific_stream_usage(self):
        provider = OpenAICompatibleProvider(provider_specs()["ollama"])
        payload = provider._payload(
            [ProviderMessage(role="user", content="你好")], [], stream=True
        )
        self.assertNotIn("stream_options", payload)
        self.assertEqual(payload["model"], "qwen3.5:4b")


class ProviderStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_streaming_text_and_chunked_tool_call_are_normalized(self):
        chunks = [
            {"choices": [{"delta": {"content": "收到"}, "finish_reason": None}]},
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {
                                        "name": "register_record",
                                        "arguments": '{"type":"weight",',
                                    },
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {"arguments": '"fields":{"kg":80}}'},
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        ]
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
        body += "data: [DONE]\n\n"

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1/chat/completions")
            return httpx.Response(200, text=body)

        spec = ProviderSpec(
            id="test",
            name="Test",
            base_url="http://provider.test/v1",
            model="test-model",
            is_local=True,
        )
        provider = OpenAICompatibleProvider(
            spec, transport=httpx.MockTransport(handler)
        )
        events = [
            event
            async for event in provider.chat(
                [ProviderMessage(role="user", content="80kg")], tools=[]
            )
        ]

        self.assertEqual(events[0].delta, "收到")
        call = next(event.tool_call for event in events if event.tool_call)
        self.assertEqual(call.id, "call_1")
        self.assertEqual(call.name, "register_record")
        self.assertEqual(json.loads(call.arguments)["fields"]["kg"], 80)

    async def test_connection_check_uses_models_endpoint(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": []})

        spec = ProviderSpec(
            id="local",
            name="Local",
            base_url="http://provider.test/v1",
            model="model",
            is_local=True,
        )
        provider = OpenAICompatibleProvider(
            spec, transport=httpx.MockTransport(handler)
        )
        result = await provider.check_connection()
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
