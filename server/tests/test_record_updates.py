import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import schemas
from app.models import Base, Record
from app.routers.records import update_record


class RecordUpdateTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_history_can_be_corrected_across_record_types(self):
        record = Record(
            type="weight", date=date(2026, 9, 12), slot="am",
            fields_json={"kg": 80.0}, raw_text="误记为体重", source="manual",
        )
        self.db.add(record)
        self.db.commit()

        result = update_record(
            record.id,
            schemas.RecordUpdate(
                type="step", slot=None, fields={"steps": 8000}, raw_text="实际是 8000 步"
            ),
            self.db,
        )
        self.assertEqual(result["type"], "step")
        self.assertIsNone(result["slot"])
        self.assertEqual(result["fields"], {"steps": 8000})
        self.assertEqual(result["source"], "manual")


if __name__ == "__main__":
    unittest.main()
