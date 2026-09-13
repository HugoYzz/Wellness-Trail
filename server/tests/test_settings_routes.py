import asyncio
import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Chat, ChatRun, Message
from app.routers.settings import (
    ProviderSelectionIn,
    ProviderEvaluationIn,
    get_providers,
    get_usage,
    run_provider_evaluation,
    select_provider,
)


class SettingsRouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_provider_catalog_never_exposes_raw_keys(self):
        result = get_providers(self.db)
        self.assertEqual(result["selected_provider_id"], "ollama")
        self.assertEqual(len(result["providers"]), 6)
        self.assertTrue(
            all(not any("api_key" in key for key in item) for item in result["providers"])
        )
        self.assertTrue(
            all(
                item["credential_status"] in {"本地无需", "已配置", "未配置"}
                for item in result["providers"]
            )
        )

    def test_local_provider_can_be_selected_without_cloud_consent(self):
        result = select_provider(
            ProviderSelectionIn(provider_id="ollama", model="qwen3.5:4b"),
            self.db,
        )
        self.assertEqual(result["selected_provider_id"], "ollama")

    def test_mock_evaluation_is_saved_and_drives_recommendation(self):
        result = asyncio.run(
            run_provider_evaluation(
                "mock", ProviderEvaluationIn(model="kangji-mock-v1"), self.db
            )
        )
        self.assertEqual(result["score"], 100)
        self.assertEqual(len(result["cases"]), 3)
        catalog = get_providers(self.db)
        self.assertEqual(catalog["recommended_provider_id"], "mock")
        mock = next(item for item in catalog["providers"] if item["id"] == "mock")
        self.assertEqual(mock["evaluation"]["dataset"], "kangji-synthetic-v1")

    def test_usage_separates_measured_runs_from_fixed_legacy_openers(self):
        chat = Chat(date=date(2026, 9, 13), title="测试")
        self.db.add(chat)
        self.db.flush()
        user_message = Message(chat_id=chat.id, role="user", content="你好")
        opener = Message(chat_id=chat.id, role="assistant", content="早，昨晚睡得怎么样？固定引导")
        assistant = Message(chat_id=chat.id, role="assistant", content="收到")
        self.db.add_all([user_message, opener, assistant])
        self.db.flush()
        self.db.add(
            ChatRun(
                request_key="usage-run-1",
                chat_id=chat.id,
                user_message_id=user_message.id,
                assistant_message_id=assistant.id,
                status="completed",
                events_json=[],
                provider_id="mock",
                provider_model="kangji-mock-v1",
                usage_json={"prompt_tokens": 11, "completion_tokens": 2, "total_tokens": 13},
                usage_source="provider",
            )
        )
        self.db.commit()

        result = get_usage(self.db)
        self.assertEqual(result["assistant_messages"], 1)
        self.assertEqual(result["usage_coverage"]["measured_messages"], 1)
        self.assertEqual(result["usage_coverage"]["unknown_messages"], 0)
        self.assertEqual(result["tokens"]["prompt_total"], 11)
        self.assertEqual(result["tokens"]["completion"], 2)

    def test_legacy_reply_gets_visible_token_estimate_without_cost_claim(self):
        chat = Chat(date=date(2026, 9, 13), title="旧会话")
        self.db.add(chat)
        self.db.flush()
        self.db.add_all(
            [
                Message(chat_id=chat.id, role="user", content="今天感觉不错"),
                Message(chat_id=chat.id, role="assistant", content="继续保持，晚上早点休息。"),
            ]
        )
        self.db.commit()

        result = get_usage(self.db)
        self.assertEqual(result["assistant_messages"], 1)
        self.assertEqual(result["usage_coverage"]["historical_estimated_messages"], 1)
        self.assertGreater(result["tokens"]["prompt_total"], 0)
        self.assertGreater(result["tokens"]["completion"], 0)
        self.assertEqual(result["cost_yuan"], 0)


if __name__ == "__main__":
    unittest.main()
