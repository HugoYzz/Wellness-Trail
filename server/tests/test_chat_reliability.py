import asyncio
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Chat, ChatRun, Message
from app.routers import chat
from app.services.chat_engine import EngineEvent


class ChatReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.factory()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_opening_chat_explicitly_does_not_create_assistant_message(self):
        created = chat.create_today_chat(self.db)
        self.assertIsNotNone(created.id)
        count = self.db.scalar(select(func.count(Message.id)))
        self.assertEqual(count, 0)

    def test_same_request_id_reuses_chat_run_and_user_message(self):
        payload = chat.SendMessageIn(content="今天走了 8000 步", request_id="req-idempotent-1")
        first, first_chat = chat._prepare_run(self.db, None, payload)
        second, second_chat = chat._prepare_run(self.db, None, payload)
        self.assertEqual(first.id, second.id)
        self.assertEqual(first_chat.id, second_chat.id)
        self.assertEqual(self.db.scalar(select(func.count(Chat.id))), 1)
        self.assertEqual(self.db.scalar(select(func.count(Message.id))), 1)

    def test_completed_run_is_not_executed_twice(self):
        run, _ = chat._prepare_run(
            self.db,
            None,
            chat.SendMessageIn(content="你好", request_id="req-complete-1"),
        )

        async def fake_run_chat(*_args, **_kwargs):
            yield EngineEvent("token", {"text": "收到"})
            yield EngineEvent(
                "done",
                {
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
                    "usage_source": "provider",
                    "provider_id": "mock",
                    "provider_model": "kangji-mock-v1",
                    "error": None,
                },
            )

        with (
            patch.object(chat, "SessionLocal", self.factory),
            patch.object(chat, "ensure_fts", lambda _db: None),
            patch.object(chat.chat_engine, "run_chat", fake_run_chat),
        ):
            asyncio.run(chat._execute_run(run.id))
            asyncio.run(chat._execute_run(run.id))

        self.db.expire_all()
        stored = self.db.get(ChatRun, run.id)
        self.assertEqual(stored.status, "completed")
        self.assertEqual(stored.usage_source, "provider")
        self.assertEqual(self.db.scalar(select(func.count(Message.id))), 2)
        self.assertEqual([item["id"] for item in stored.events_json], [1, 2, 3])
        self.assertIn("id: 2", chat._sse("token", {"text": "收到"}, 2))


if __name__ == "__main__":
    unittest.main()
