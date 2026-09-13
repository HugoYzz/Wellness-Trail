"""个性化今日计划生成。

九类记录是候选输入，不等于每天都必须完成的九项任务。这里用可解释的
确定性规则组合日程、近期身体记录、历史习惯与用户当日选择；模型只需在
对话层帮助用户记录，不参与安全相关判定。
"""
from __future__ import annotations

from collections import Counter
from datetime import date as Date
from datetime import datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Record
from app.services.provider_settings import get_or_create_local_user

DEFAULT_STEP_GOAL = 8_000
DEFAULT_SLEEP_TARGET = "23:30"
STEADY_PHASE_START = Date(2026, 9, 21)

# 八月主线计划：冲刺期与开学后的稳态期。0=周一。
SPRINT_SCHEDULE: dict[int, list[str]] = {
    0: ["swim"],
    1: ["strength"],
    2: ["swim"],
    3: [],
    4: ["swim"],
    5: ["strength", "swim"],
    6: [],
}
STEADY_SCHEDULE: dict[int, list[str]] = {
    0: ["swim"],
    1: [],
    2: [],
    3: ["swim"],
    4: ["strength"],
    5: ["strength"],
    6: [],
}

SOURCE_LABELS = {
    "daily": "每日记录",
    "schedule": "计划日程",
    "habit": "历史习惯",
    "health": "身体状态",
    "manual": "今日调整",
}


def _task(
    key: str,
    label: str,
    prefill: str,
    *,
    source: str,
    reason: str,
    start: str,
    time_label: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "prefill": prefill,
        "source": source,
        "source_label": SOURCE_LABELS[source],
        "reason": reason,
        "time_window": {"start": start, "label": time_label},
        "status": "pending",
        "outcome": "unknown",
        "detail": "待记录",
    }


def _base_tasks(settings: dict[str, Any]) -> list[dict[str, Any]]:
    step_goal = int((settings.get("todo_plan") or {}).get("step_goal", DEFAULT_STEP_GOAL))
    sleep_target = str(
        (settings.get("todo_plan") or {}).get("sleep_target", DEFAULT_SLEEP_TARGET)
    )
    tasks = [
        _task(
            "weight-am",
            "晨重",
            "今早空腹 ",
            source="daily",
            reason="主线计划要求每日在相同条件下记录晨重",
            start="06:00",
            time_label="晨起后",
        ),
        _task(
            "step",
            f"步数 {step_goal:,}",
            "今天走了 步",
            source="daily",
            reason="日常活动量目标，按当天最终记录判断是否达成",
            start="18:00",
            time_label="全天累计",
        ),
        _task(
            "sleep",
            f"入睡 ≤ {sleep_target}",
            "昨晚 睡的",
            source="daily",
            reason="记录睡眠节律；晚于目标仍算已反馈，不算达成",
            start="20:00",
            time_label="晚间回顾",
        ),
        _task(
            "evening-checkin",
            "饮料与夜饿",
            "今天含糖饮料和夜饿情况：",
            source="daily",
            reason="回答“没喝”和“没饿”同样是有效完成",
            start="20:00",
            time_label="晚间回顾",
        ),
    ]
    if (settings.get("todo_plan") or {}).get("supplements_enabled", True):
        tasks.append(
            _task(
                "supplement",
                "维D3 + 锌",
                "今天维D3和锌的服用情况：",
                source="daily",
                reason="分别核对早餐后维D3与晚餐后锌，不再以任意一条代替全部",
                start="18:30",
                time_label="早餐后 / 晚餐后",
            )
        )
    return tasks


def _configured_schedule(settings: dict[str, Any], target: Date) -> list[str]:
    custom = (settings.get("todo_plan") or {}).get("weekly_schedule")
    if isinstance(custom, dict):
        value = custom.get(str(target.weekday()), [])
        if isinstance(value, list):
            return [str(kind) for kind in value if kind in {"swim", "strength"}]
    schedule = SPRINT_SCHEDULE if target < STEADY_PHASE_START else STEADY_SCHEDULE
    return list(schedule[target.weekday()])


def _habit_exercise(records: list[Record], target: Date) -> str | None:
    """休息日若近四周在同一星期训练至少两次，只作为待确认建议加入。"""
    counts: Counter[str] = Counter()
    for record in records:
        if record.type != "exercise" or record.date.weekday() != target.weekday():
            continue
        kind = str((record.fields_json or {}).get("kind", ""))
        if kind == "swim" and float((record.fields_json or {}).get("duration_min") or 0) > 0:
            counts[kind] += 1
        elif kind == "strength" and (record.fields_json or {}).get("done") is True:
            counts[kind] += 1
    if not counts:
        return None
    kind, count = counts.most_common(1)[0]
    return kind if count >= 2 else None


def _exercise_task(kinds: list[str], source: str) -> dict[str, Any]:
    if len(kinds) > 1:
        return _task(
            "exercise-combo",
            "力量 + 游泳",
            "今天力量训练和游泳的完成情况：",
            source=source,
            reason="今日计划包含两项训练，合并展示但分别判断结果",
            start="18:00",
            time_label="晚间训练",
        )
    kind = kinds[0]
    if kind == "swim":
        return _task(
            "swim",
            "游泳",
            "游了 分钟泳",
            source=source,
            reason=(
                "近四周常在今天游泳，等待你确认是否沿用"
                if source == "habit"
                else "来自当前阶段的每周训练安排"
            ),
            start="18:00",
            time_label="晚间训练",
        )
    return _task(
        "strength",
        "居家力量",
        "力量训练",
        source=source,
        reason=(
            "近四周常在今天力量训练，等待你确认是否沿用"
            if source == "habit"
            else "来自当前阶段的每周训练安排"
        ),
        start="18:00",
        time_label="晚间训练",
    )


def _recent_body_risk(records: list[Record], target: Date) -> tuple[bool, str]:
    risk_records = [
        r
        for r in records
        if r.type == "body" and target - timedelta(days=2) <= r.date <= target
    ]
    for record in sorted(risk_records, key=lambda item: (item.date, item.id or 0), reverse=True):
        fields = record.fields_json or {}
        site = str(fields.get("site") or "身体")
        level = int(fields.get("level") or 0)
        symptom = str(fields.get("symptom") or "")
        warning_words = ("加重", "放射", "麻木", "肿胀", "不稳", "持续疲劳")
        if level >= 5 or any(word in symptom for word in warning_words):
            return True, f"近3天记录到{site}不适{f' {level}/10' if level else ''}"
    return False, ""


def _latest(records: list[Record], record_type: str, **fields: Any) -> Record | None:
    matches = []
    for record in records:
        if record.type != record_type:
            continue
        values = record.fields_json or {}
        if all(values.get(key) == value for key, value in fields.items()):
            matches.append(record)
    return max(matches, key=lambda item: item.id or 0, default=None)


def _bedtime_met(value: str, target: str) -> bool:
    try:
        hour, minute = (int(part) for part in value.split(":"))
        target_hour, target_minute = (int(part) for part in target.split(":"))
    except (TypeError, ValueError):
        return False
    # 00:00–05:59 视为跨午夜后的晚睡。
    if hour < 6:
        return False
    return (hour, minute) <= (target_hour, target_minute)


def _apply_record_status(
    item: dict[str, Any],
    records: list[Record],
    settings: dict[str, Any],
) -> None:
    key = item["key"]
    outcome: str | None = None
    detail = "待记录"

    if key == "weight-am":
        record = next((r for r in records if r.type == "weight" and r.slot == "am"), None)
        if record:
            outcome, detail = "met", f"{(record.fields_json or {}).get('kg', '—')} kg"
    elif key == "step":
        found = [r for r in records if r.type == "step"]
        if found:
            steps = max(int((r.fields_json or {}).get("steps") or 0) for r in found)
            goal = int((settings.get("todo_plan") or {}).get("step_goal", DEFAULT_STEP_GOAL))
            outcome = "met" if steps >= goal else "not_met"
            detail = f"{steps:,} / {goal:,} 步"
    elif key == "sleep":
        record = _latest(records, "sleep")
        if record:
            bedtime = str((record.fields_json or {}).get("bedtime") or "")
            target = str((settings.get("todo_plan") or {}).get("sleep_target", DEFAULT_SLEEP_TARGET))
            outcome = "met" if _bedtime_met(bedtime, target) else "not_met"
            detail = f"{bedtime} 入睡"
    elif key == "evening-checkin":
        sweet = _latest(records, "sweet_drink")
        hunger = _latest(records, "night_hunger")
        count = int(sweet is not None) + int(hunger is not None)
        detail = f"已回答 {count}/2"
        if sweet and hunger:
            sweet_ok = (sweet.fields_json or {}).get("level") in {"0杯", "无糖"}
            hunger_ok = (hunger.fields_json or {}).get("level") != "破戒"
            outcome = "met" if sweet_ok and hunger_ok else "not_met"
            detail = "饮料、夜饿均已反馈"
    elif key == "supplement":
        vitd3 = _latest(records, "supplement", item="vitd3")
        zinc = _latest(records, "supplement", item="zinc")
        count = int(vitd3 is not None) + int(zinc is not None)
        detail = f"已回答 {count}/2"
        if vitd3 and zinc:
            taken = all((r.fields_json or {}).get("taken") is True for r in (vitd3, zinc))
            outcome = "met" if taken else "not_met"
            detail = "维D3、锌均已反馈"
    elif key in {"swim", "strength", "exercise-combo"}:
        swim = _latest(records, "exercise", kind="swim")
        strength = _latest(records, "exercise", kind="strength")
        if key == "swim" and swim:
            minutes = int((swim.fields_json or {}).get("duration_min") or 0)
            outcome = "met" if minutes > 0 else "not_met"
            detail = f"游泳 {minutes} 分钟"
        elif key == "strength" and strength:
            done = (strength.fields_json or {}).get("done") is True
            outcome = "met" if done else "not_met"
            detail = "力量已完成" if done else "已反馈：未训练"
        elif key == "exercise-combo":
            count = int(swim is not None) + int(strength is not None)
            detail = f"已反馈 {count}/2"
            if swim and strength:
                met = (
                    float((swim.fields_json or {}).get("duration_min") or 0) > 0
                    and (strength.fields_json or {}).get("done") is True
                )
                outcome = "met" if met else "not_met"
    elif key == "body-checkin":
        body = _latest(records, "body")
        if body:
            outcome = "met"
            detail = "身体状态已反馈"

    if outcome is not None:
        item["outcome"] = outcome
        item["status"] = "done" if outcome == "met" else "reported"
        item["detail"] = detail
    elif detail != "待记录":
        item["detail"] = detail


def _time_status(item: dict[str, Any], target: Date, now: datetime) -> None:
    if item["status"] in {"done", "reported", "skipped"}:
        return
    if target > now.date():
        item["status"] = "later"
        return
    if target < now.date():
        item["status"] = "pending"
        return
    start_hour, start_minute = (int(part) for part in item["time_window"]["start"].split(":"))
    item["status"] = "later" if now.time() < time(start_hour, start_minute) else "pending"


def build_today_plan(
    db: Session,
    target: Date | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now()
    target = target or now.date()
    user = get_or_create_local_user(db)
    settings = dict(user.settings_json or {})
    history_start = target - timedelta(days=28)
    history = list(
        db.scalars(
            select(Record)
            .where(Record.date >= history_start, Record.date <= target)
            .order_by(Record.date, Record.id)
        ).all()
    )
    today_records = [record for record in history if record.date == target]

    tasks = _base_tasks(settings)
    schedule = _configured_schedule(settings, target)
    if not schedule:
        habit = _habit_exercise([r for r in history if r.date < target], target)
        if habit:
            schedule = [habit]
            exercise_source = "habit"
        else:
            exercise_source = "schedule"
    else:
        exercise_source = "schedule"

    has_risk, risk_reason = _recent_body_risk(history, target)
    safety_note = None
    if has_risk and schedule:
        tasks.append(
            _task(
                "body-checkin",
                "先确认身体状态",
                "今天腰、踝和精力状态：",
                source="health",
                reason=f"{risk_reason}，今天先复核状态，不自动安排训练",
                start="08:00",
                time_label="训练前",
            )
        )
        safety_note = "近期不适已影响训练安排；若症状持续或加重，请线下就医。"
    elif schedule:
        tasks.append(_exercise_task(schedule, exercise_source))

    overrides = (settings.get("daily_todo_overrides") or {}).get(target.isoformat(), {})
    skipped = set(overrides.get("skipped") or [])
    for item in tasks:
        if item["key"] in skipped:
            item["status"] = "skipped"
            item["source"] = "manual"
            item["source_label"] = SOURCE_LABELS["manual"]
            item["detail"] = "今日不安排"
        else:
            _apply_record_status(item, today_records, settings)
            _time_status(item, target, now)

    active = [item for item in tasks if item["status"] != "skipped"]
    handled = [item for item in active if item["status"] in {"done", "reported"}]
    achieved = [item for item in active if item["status"] == "done"]
    next_item = next(
        (
            item
            for item in sorted(active, key=lambda value: value["time_window"]["start"])
            if item["status"] in {"pending", "later"}
        ),
        None,
    )
    reasons = ["当前阶段的计划日程", "今日已有记录"]
    if any(item["source"] == "habit" for item in tasks):
        reasons.append("近四周习惯")
    if has_risk:
        reasons.append("近三天身体状态")

    return {
        "date": target.isoformat(),
        "confirmed": bool(overrides.get("confirmed", False)),
        "summary": "、".join(reasons) + "共同生成",
        "safety_note": safety_note,
        "items": tasks,
        "progress": {
            "handled": len(handled),
            "achieved": len(achieved),
            "active": len(active),
            "skipped": len(tasks) - len(active),
        },
        "next_item_key": next_item["key"] if next_item else None,
    }


def update_today_plan(
    db: Session,
    target: Date,
    *,
    action: str,
    task_key: str | None = None,
) -> dict[str, Any]:
    user = get_or_create_local_user(db)
    settings = dict(user.settings_json or {})
    all_overrides = dict(settings.get("daily_todo_overrides") or {})
    current = dict(all_overrides.get(target.isoformat()) or {})
    skipped = set(current.get("skipped") or [])

    available_keys = {item["key"] for item in build_today_plan(db, target)["items"]}
    if action == "confirm":
        current["confirmed"] = True
    elif action == "skip":
        if not task_key or task_key not in available_keys:
            raise ValueError("task_key 不属于当天计划")
        skipped.add(task_key)
        current["confirmed"] = True
    elif action == "restore":
        if not task_key:
            raise ValueError("restore 需要 task_key")
        skipped.discard(task_key)
    elif action == "rest":
        skipped.update(key for key in available_keys if key in {"swim", "strength", "exercise-combo"})
        current["confirmed"] = True
    elif action == "reset":
        current = {"confirmed": False, "skipped": []}
        skipped = set()
    else:
        raise ValueError("未知的今日计划操作")

    current["skipped"] = sorted(skipped)
    all_overrides[target.isoformat()] = current
    cutoff = (target - timedelta(days=45)).isoformat()
    settings["daily_todo_overrides"] = {
        key: value for key, value in all_overrides.items() if key >= cutoff
    }
    user.settings_json = settings
    db.add(user)
    db.commit()
    return build_today_plan(db, target)
