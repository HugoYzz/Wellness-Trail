import unittest
from datetime import date

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models import Base, Chat, ChatRun, KbChunk, KbDoc, Message, Record, User
from app.services.backup_restore import (
    BackupValidationError,
    build_backup,
    drill_restore,
    restore_backup,
)


class BackupRestoreTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _seed(self):
        user = User(username="local", password_hash="hash", settings_json={"theme": "calm"})
        record = Record(
            type="step", date=date(2026, 9, 13), slot=None,
            fields_json={"steps": 8000}, raw_text="8000 步", source="manual",
        )
        chat = Chat(date=date(2026, 9, 13), title="测试")
        doc = KbDoc(title="plan.md", source_plan="july_health", version="v1")
        self.db.add_all([user, record, chat, doc])
        self.db.flush()
        message = Message(chat_id=chat.id, role="user", content="你好")
        self.db.add(message)
        self.db.flush()
        self.db.add_all([
            KbChunk(
                doc_id=doc.id, title=doc.title, heading="H", source_plan=doc.source_plan,
                section_no="1", content="内容", tags=["行动"],
            ),
            ChatRun(
                request_key="backup-run-1", chat_id=chat.id, user_message_id=message.id,
                status="completed", events_json=[], provider_id="mock",
                provider_model="kangji-mock-v1",
                usage_json={"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
                usage_source="provider",
            ),
        ])
        self.db.commit()

    def test_export_validate_restore_round_trip(self):
        self._seed()
        backup = build_backup(self.db)
        self.assertEqual(backup["meta"]["format_version"], 2)
        rehearsal = drill_restore(backup)
        self.assertTrue(rehearsal["drill"]["restored"])
        self.assertIn("chat_runs", rehearsal["drill"]["verified_collections"])
        record = self.db.scalars(select(Record)).one()
        record.fields_json = {"steps": 1}
        self.db.commit()

        report = restore_backup(self.db, backup)
        self.assertTrue(report["restored"])
        restored = self.db.scalars(select(Record)).one()
        self.assertEqual(restored.fields_json["steps"], 8000)
        self.assertEqual(self.db.scalar(select(func.count(ChatRun.id))), 1)
        self.assertEqual(self.db.scalars(select(User)).one().password_hash, "hash")

    def test_invalid_reference_is_rejected_before_current_data_changes(self):
        self._seed()
        backup = build_backup(self.db)
        backup["messages"][0]["chat_id"] = 999
        with self.assertRaises(BackupValidationError):
            restore_backup(self.db, backup)
        self.assertEqual(self.db.scalar(select(func.count(Record.id))), 1)


if __name__ == "__main__":
    unittest.main()
