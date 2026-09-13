import json
import unittest
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, InsightState, Record, User
from app.routers.settings import export_backup
from app.routers.stats import InsightActionIn, get_insights, update_insight


class InsightRouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.end = date(2026, 9, 12)
        self.db.add(
            User(
                username="me",
                settings_json={
                    "baseline": {
                        "initial_weight_kg": 108.5,
                        "initial_weight_date": "2026-08-30",
                        "initial_waist_cm": 110,
                    }
                },
            )
        )
        for offset in range(14):
            day = self.end - timedelta(days=13 - offset)
            self.db.add(
                Record(
                    type="weight",
                    date=day,
                    slot="am",
                    fields_json={"kg": 108.0 - offset * 0.08},
                    raw_text="",
                    source="manual",
                )
            )
            self.db.add(
                Record(
                    type="sleep",
                    date=day,
                    slot=None,
                    fields_json={"bedtime": "23:20" if offset < 7 else "00:10"},
                    raw_text="",
                    source="manual",
                )
            )
            if offset >= 7:
                self.db.add(
                    Record(
                        type="step",
                        date=day,
                        slot=None,
                        fields_json={"steps": 5200},
                        raw_text="",
                        source="manual",
                    )
                )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_generates_explainable_actionable_cards(self):
        result = get_insights(self.db)
        self.assertGreaterEqual(len(result["priority"]), 2)
        self.assertLessEqual(len(result["priority"]), 3)
        cards = {item["metric"]: item for item in result["priority"]}
        self.assertIn("步数", cards)
        self.assertIn("入睡时间", cards)
        self.assertTrue(cards["步数"]["evidence"])
        self.assertIn(cards["步数"]["confidence"]["level"], {"较高", "中等", "较低"})
        self.assertEqual(cards["步数"]["action"]["duration_days"], 3)

    def test_adopt_feedback_complete_and_reopen_lifecycle(self):
        card = get_insights(self.db)["priority"][0]
        adopted = update_insight(
            card["key"],
            InsightActionIn(
                action="adopt",
                reminder_at=datetime.now(timezone.utc) + timedelta(days=1),
                action_plan=card["action"],
            ),
            self.db,
        )
        self.assertEqual(adopted["status"], "adopted")
        self.assertEqual(len(get_insights(self.db)["active"]), 1)

        rated = update_insight(
            card["key"],
            InsightActionIn(action="feedback", helpful=False, reason="建议不适合我"),
            self.db,
        )
        self.assertEqual(rated["feedback"], "not_helpful")
        self.assertEqual(rated["feedback_reason"], "建议不适合我")

        completed = update_insight(
            card["key"], InsightActionIn(action="complete"), self.db
        )
        self.assertEqual(completed["status"], "completed")
        self.assertTrue(
            any(item["key"] == card["key"] for item in get_insights(self.db)["history"])
        )

        reopened = update_insight(
            card["key"], InsightActionIn(action="reopen"), self.db
        )
        self.assertEqual(reopened["status"], "new")
        self.assertEqual(
            self.db.query(InsightState).filter_by(insight_key=card["key"]).count(), 1
        )

    def test_snooze_requires_a_reminder_time(self):
        card = get_insights(self.db)["priority"][0]
        with self.assertRaisesRegex(Exception, "reminder_at"):
            update_insight(
                card["key"], InsightActionIn(action="snooze"), self.db
            )

    def test_insight_feedback_is_in_local_backup(self):
        card = get_insights(self.db)["priority"][0]
        update_insight(
            card["key"],
            InsightActionIn(action="feedback", helpful=True),
            self.db,
        )
        backup = json.loads(export_backup(self.db).body)
        self.assertEqual(backup["meta"]["counts"]["insight_states"], 1)
        self.assertEqual(backup["insight_states"][0]["feedback"], "helpful")


if __name__ == "__main__":
    unittest.main()
