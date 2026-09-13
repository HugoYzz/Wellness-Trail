import unittest
from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Record, User
from app.services.todo_plan import build_today_plan, update_today_plan


class TodayPlanTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add(User(username="me", settings_json={}))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def add_record(
        self,
        record_type: str,
        day: date,
        fields: dict,
        *,
        slot: str | None = None,
    ) -> None:
        self.db.add(
            Record(
                type=record_type,
                date=day,
                slot=slot,
                fields_json=fields,
                raw_text="",
                source="manual",
                confirmed=True,
            )
        )
        self.db.commit()

    def item(self, plan: dict, key: str) -> dict:
        return next(value for value in plan["items"] if value["key"] == key)

    def test_rest_day_does_not_create_a_false_missed_workout(self):
        day = date(2026, 9, 13)  # 周日
        plan = build_today_plan(self.db, day, now=datetime(2026, 9, 13, 21, 0))
        keys = {item["key"] for item in plan["items"]}
        self.assertFalse(keys & {"swim", "strength", "exercise-combo"})
        self.assertEqual(plan["progress"]["active"], 5)

    def test_strength_not_done_is_reported_not_achieved(self):
        day = date(2026, 9, 15)  # 冲刺期周二：力量
        self.add_record("exercise", day, {"kind": "strength", "done": False})
        plan = build_today_plan(self.db, day, now=datetime(2026, 9, 15, 21, 0))
        strength = self.item(plan, "strength")
        self.assertEqual(strength["status"], "reported")
        self.assertEqual(strength["outcome"], "not_met")
        self.assertEqual(plan["progress"]["achieved"], 0)

    def test_negative_event_answers_can_achieve_evening_checkin(self):
        day = date(2026, 9, 14)
        self.add_record("sweet_drink", day, {"level": "0杯"})
        self.add_record("night_hunger", day, {"level": "没饿"})
        plan = build_today_plan(self.db, day, now=datetime(2026, 9, 14, 21, 0))
        checkin = self.item(plan, "evening-checkin")
        self.assertEqual(checkin["status"], "done")
        self.assertEqual(checkin["outcome"], "met")

    def test_supplements_are_evaluated_separately(self):
        day = date(2026, 9, 14)
        self.add_record(
            "supplement",
            day,
            {"item": "vitd3", "dose": "2000IU", "timing": "早餐后", "taken": True},
        )
        partial = build_today_plan(self.db, day, now=datetime(2026, 9, 14, 21, 0))
        self.assertEqual(self.item(partial, "supplement")["status"], "pending")
        self.assertEqual(self.item(partial, "supplement")["detail"], "已回答 1/2")

        self.add_record(
            "supplement",
            day,
            {"item": "zinc", "dose": "15mg", "timing": "晚餐后", "taken": False},
        )
        complete = build_today_plan(self.db, day, now=datetime(2026, 9, 14, 21, 0))
        self.assertEqual(self.item(complete, "supplement")["status"], "reported")
        self.assertEqual(self.item(complete, "supplement")["outcome"], "not_met")

    def test_recent_body_risk_replaces_scheduled_training(self):
        day = date(2026, 9, 12)  # 周六原计划力量+游泳
        self.add_record(
            "body",
            date(2026, 9, 11),
            {"site": "腰", "level": 6, "symptom": "酸胀加重"},
        )
        plan = build_today_plan(self.db, day, now=datetime(2026, 9, 12, 10, 0))
        keys = {item["key"] for item in plan["items"]}
        self.assertIn("body-checkin", keys)
        self.assertNotIn("exercise-combo", keys)
        self.assertIsNotNone(plan["safety_note"])

    def test_repeated_rest_day_habit_is_suggested_for_confirmation(self):
        target = date(2026, 9, 13)
        for day in (date(2026, 8, 30), date(2026, 9, 6)):
            self.add_record("exercise", day, {"kind": "swim", "duration_min": 45})
        plan = build_today_plan(self.db, target, now=datetime(2026, 9, 13, 10, 0))
        swim = self.item(plan, "swim")
        self.assertEqual(swim["source"], "habit")
        self.assertFalse(plan["confirmed"])

    def test_confirm_and_skip_are_persisted_without_counting_skip(self):
        day = date(2026, 9, 14)
        confirmed = update_today_plan(self.db, day, action="confirm")
        self.assertTrue(confirmed["confirmed"])
        skipped = update_today_plan(self.db, day, action="skip", task_key="swim")
        self.assertEqual(self.item(skipped, "swim")["status"], "skipped")
        self.assertEqual(skipped["progress"]["active"], 5)
        self.assertEqual(skipped["progress"]["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
