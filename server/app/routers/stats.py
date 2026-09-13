"""统计与趋势 API（架构 §7.4 / §10-P2：趋势可见、异常可感知）。

- GET /api/stats/trends  全量趋势序列（图表页一次拉取）
- GET /api/stats/weekly  周报复刻 xlsx"体重趋势"口径（周均、较上周、腰围、达标评价）

图表统计全部由 SQL 实时聚合，不落派生表（架构 §6.5-3）。
"""
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import InsightState, Record, User

router = APIRouter(prefix="/api/stats", tags=["stats"])

# 前端后备基线（后端 settings 缺失时才用）
FALLBACK_BASELINE = {"start": 108.55, "date": "2026-08-30", "waist": 110}


def _baseline(db: Session) -> dict:
    """从 users.settings_json 读基线与目标（P0 导入时写入），带后备。"""
    user = db.scalars(select(User).where(User.username == "me")).first()
    b = (user.settings_json or {}).get("baseline") if user else None
    if not isinstance(b, dict):
        return dict(FALLBACK_BASELINE)
    targets = b.get("targets") or {}
    sprint = (targets.get("sprint_end") or {}).get("weight_kg_range")
    return {
        "start": b.get("initial_weight_kg") or FALLBACK_BASELINE["start"],
        "date": b.get("initial_weight_date") or FALLBACK_BASELINE["date"],
        "waist": b.get("initial_waist_cm") or FALLBACK_BASELINE["waist"],
        "sprint_target": f"{sprint[0]}-{sprint[1]}" if sprint else "104-105",
    }

# 奶茶档位数值化（戒断进度：数值越低越好）
SWEET_ORDER = {"0杯": 0, "无糖": 1, "三分糖": 2, "半糖": 3, "全糖": 4}
# plan.docx 5.2：之后每周 0.5-1.5kg；冲刺期上限可到 2kg
HEALTHY_DROP = (0.5, 1.5)


def _week_start(d: date) -> date:
    """周一为一周起点（ISO）。"""
    return d - timedelta(days=d.weekday())


def _to_num(v):
    return float(v) if isinstance(v, (int, float)) else None


def _bedtime_minutes(bedtime: str) -> int | None:
    """'HH:MM' → 距 0:00 的分钟数；跨零点(00:00-04:00)归前一日但仍线性可比。"""
    try:
        h, m = bedtime.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _trend_rows(db: Session) -> list[Record]:
    return list(
        db.scalars(select(Record).order_by(Record.date, Record.id)).all()
    )


def _build_trends(records: list[Record]) -> dict:
    weights: dict[str, dict] = {}
    waist: list[dict] = []
    steps: list[dict] = []
    sleep: list[dict] = []
    sweet: list[dict] = []
    night_hunger: list[dict] = []
    exercise: dict[str, dict] = {}

    for r in records:
        f = r.fields_json or {}
        d = r.date.isoformat()
        if r.type == "weight":
            w = weights.setdefault(d, {"date": d})
            w["am" if r.slot == "am" else "evening"] = _to_num(f.get("kg"))
        elif r.type == "waist":
            waist.append({"date": d, "cm": _to_num(f.get("cm"))})
        elif r.type == "step":
            steps.append({"date": d, "steps": int(f.get("steps") or 0)})
        elif r.type == "sleep":
            bm = _bedtime_minutes(f.get("bedtime") or "")
            sleep.append({"date": d, "bedtime": f.get("bedtime"), "minutes": bm})
        elif r.type == "sweet_drink":
            level = f.get("level", "")
            sweet.append(
                {"date": d, "level": level, "score": SWEET_ORDER.get(level)}
            )
        elif r.type == "night_hunger":
            night_hunger.append({"date": d, "level": f.get("level")})
        elif r.type == "exercise":
            e = exercise.setdefault(d, {"date": d, "swim_min": None, "strength_done": None})
            if f.get("kind") == "swim":
                e["swim_min"] = _to_num(f.get("duration_min"))
            elif f.get("kind") == "strength":
                e["strength_done"] = bool(f.get("done"))

    return {
        "weights": sorted(weights.values(), key=lambda x: x["date"]),
        "waist": waist,
        "steps": steps,
        "sleep": sleep,
        "sweet": sweet,
        "night_hunger": night_hunger,
        "exercise": sorted(exercise.values(), key=lambda x: x["date"]),
    }


def _week_summaries(records: list[Record]) -> list[dict]:
    """xlsx"体重趋势"周报口径：7 天晨重平均、较上周、腰围、达标评价（plan 5.2）。"""
    weeks: dict[date, list[Record]] = {}
    for r in records:
        weeks.setdefault(_week_start(r.date), []).append(r)
    weeks = dict(sorted(weeks.items()))

    out: list[dict] = []
    prev_avg: float | None = None
    for ws, recs in weeks.items():
        am = [
            _to_num((r.fields_json or {}).get("kg"))
            for r in recs
            if r.type == "weight" and r.slot == "am"
        ]
        am = [v for v in am if v is not None]
        avg = round(sum(am) / len(am), 2) if am else None

        waists = [
            _to_num((r.fields_json or {}).get("cm"))
            for r in recs
            if r.type == "waist"
        ]
        waists = [v for v in waists if v is not None]

        sweet_counts: dict[str, int] = {}
        swim_mins: list[float] = []
        strength_n = 0
        steps_list: list[int] = []
        for r in recs:
            f = r.fields_json or {}
            if r.type == "sweet_drink":
                sweet_counts[f.get("level", "?")] = sweet_counts.get(f.get("level", "?"), 0) + 1
            elif r.type == "exercise":
                if f.get("kind") == "swim":
                    swim_mins.append(_to_num(f.get("duration_min")) or 0)
                elif f.get("kind") == "strength" and f.get("done"):
                    strength_n += 1
            elif r.type == "step":
                steps_list.append(int(f.get("steps") or 0))

        diff = round(avg - prev_avg, 2) if (avg is not None and prev_avg is not None) else None
        verdict = _verdict(diff)
        out.append(
            {
                "week_start": ws.isoformat(),
                "week_end": (ws + timedelta(days=6)).isoformat(),
                "am_avg": avg,
                "am_days": len(am),
                "diff_vs_last": diff,
                "waist": waists[-1] if waists else None,
                "sweet_counts": sweet_counts,
                "swim_total_min": round(sum(swim_mins)) if swim_mins else 0,
                "swim_times": len(swim_mins),
                "strength_times": strength_n,
                "steps_avg": round(sum(steps_list) / len(steps_list)) if steps_list else None,
                "verdict": verdict,
            }
        )
        if avg is not None:
            prev_avg = avg
    return out


def _verdict(diff: float | None) -> str:
    """达标评价（plan.docx 5.2：之后每周 0.5-1.5kg）。"""
    if diff is None:
        return "数据不足"
    drop = -diff
    if drop >= HEALTHY_DROP[0] and drop <= HEALTHY_DROP[1]:
        return "达标（每周 0.5-1.5kg）"
    if drop > HEALTHY_DROP[1]:
        return "下降偏快（>1.5kg/周），注意肌肉流失与精力"
    if diff > 0:
        return "回升，检查隐性热量（奶茶/夜宵/零食）"
    if drop == 0:
        return "持平"
    return "降幅偏慢（<0.5kg/周）"


@router.get("/trends")
def get_trends(db: Session = Depends(get_db)) -> dict:
    records = _trend_rows(db)
    trends = _build_trends(records)
    trends["weekly"] = _week_summaries(records)
    trends["baseline"] = _baseline(db)
    return trends


@router.get("/weekly")
def get_weekly(db: Session = Depends(get_db)) -> list[dict]:
    return _week_summaries(_trend_rows(db))


# ---------- 可行动洞察 ----------

INSIGHT_STATUSES = {"new", "adopted", "snoozed", "completed", "dismissed"}


class InsightActionIn(BaseModel):
    """洞察卡交互。反馈与状态拆开保存，便于后续评估建议质量。"""

    model_config = ConfigDict(extra="forbid")

    action: Literal["adopt", "snooze", "adjust", "dismiss", "feedback", "complete", "reopen"]
    helpful: bool | None = None
    reason: str | None = Field(default=None, max_length=128)
    reminder_at: datetime | None = None
    action_plan: dict | None = None


def _confidence(observed: int, expected: int, note: str = "") -> dict:
    coverage = observed / expected if expected else 0
    if coverage >= 0.75:
        level = "较高"
    elif coverage >= 0.4:
        level = "中等"
    else:
        level = "较低"
    reason = f"统计窗口内记录 {observed}/{expected} 天"
    if note:
        reason += f"，{note}"
    return {"level": level, "coverage": round(coverage, 2), "reason": reason}


def _card(
    *,
    key: str,
    kind: str,
    metric: str,
    headline: str,
    finding: str,
    evidence: list[str],
    confidence: dict,
    action: dict,
    period_start: date,
    period_end: date,
    priority: int,
    tone: str = "attention",
) -> dict:
    return {
        "key": key,
        "kind": kind,
        "metric": metric,
        "headline": headline,
        "finding": finding,
        "evidence": evidence,
        "confidence": confidence,
        "action": action,
        "period": {"start": period_start.isoformat(), "end": period_end.isoformat()},
        "priority": priority,
        "tone": tone,
        "status": "new",
        "feedback": None,
        "feedback_reason": None,
        "reminder_at": None,
    }


def _generate_insights(records: list[Record], baseline: dict) -> list[dict]:
    """从个人时间序列生成少量、可解释、可执行的洞察。

    这里只陈述数据事实与趋势，不推断疾病，也不把相关性写成因果关系。
    """
    if not records:
        return []

    end = max(r.date for r in records)
    start = end - timedelta(days=6)
    previous_start = start - timedelta(days=7)
    cards: list[dict] = []

    step_rows = [
        r for r in records if r.type == "step" and start <= r.date <= end
    ]
    step_days = len({r.date for r in step_rows})
    if step_rows:
        step_avg = round(
            sum(int((r.fields_json or {}).get("steps") or 0) for r in step_rows)
            / len(step_rows)
        )
        gap = max(0, 8000 - step_avg)
        if gap:
            headline = f"最近一周日均步数距离目标还差 {gap:,} 步"
            finding = f"最近 7 天有 {step_days} 天记录步数，日均为 {step_avg:,} 步。"
            action = {
                "title": "晚饭后步行 15 分钟",
                "detail": "连续 3 天执行，先把日均活动量向 8,000 步靠近。",
                "target": 15,
                "unit": "分钟",
                "duration_days": 3,
                "reminder_time": "19:30",
            }
            tone, priority = "attention", 90
        else:
            headline = "最近一周步数已达到当前目标"
            finding = f"有记录的 {step_days} 天中，日均达到 {step_avg:,} 步。"
            action = {
                "title": "保持当前步行安排",
                "detail": "未来 7 天继续维持日均 8,000 步。",
                "target": 8000,
                "unit": "步/天",
                "duration_days": 7,
                "reminder_time": "19:30",
            }
            tone, priority = "positive", 65
        cards.append(
            _card(
                key=f"steps:{end.isoformat()}",
                kind="goal_gap",
                metric="步数",
                headline=headline,
                finding=finding,
                evidence=[
                    f"当前日均：{step_avg:,} 步",
                    "个人计划目标：8,000 步/天",
                    f"数据范围：{start.isoformat()} 至 {end.isoformat()}",
                ],
                confidence=_confidence(step_days, 7),
                action=action,
                period_start=start,
                period_end=end,
                priority=priority,
                tone=tone,
            )
        )

    weekly = [w for w in _week_summaries(records) if w["am_avg"] is not None]
    if len(weekly) >= 2:
        current = weekly[-1]
        diff = current["diff_vs_last"]
        if diff is not None:
            abs_diff = abs(diff)
            if diff > 0:
                headline = f"本周晨重均值较上周回升 {abs_diff:.2f} kg"
                action = {
                    "title": "连续记录 3 天晚餐与夜间加餐",
                    "detail": "先补齐饮食记录，再判断体重变化可能与哪些行为同时出现。",
                    "target": 3,
                    "unit": "天",
                    "duration_days": 3,
                    "reminder_time": "20:30",
                }
                tone, priority = "attention", 100
            elif abs_diff > HEALTHY_DROP[1]:
                headline = f"本周晨重均值较上周下降较快，变化 {abs_diff:.2f} kg"
                action = {
                    "title": "先补齐晨重并观察身体状态",
                    "detail": "连续记录 3 天，暂不因单周变化继续加大计划强度。若伴随明显不适，请咨询专业人员。",
                    "target": 3,
                    "unit": "天",
                    "duration_days": 3,
                    "reminder_time": "07:30",
                }
                tone, priority = "attention", 100
            elif abs_diff >= HEALTHY_DROP[0]:
                headline = f"本周晨重均值较上周下降 {abs_diff:.2f} kg"
                action = {
                    "title": "继续完成晨重记录",
                    "detail": "保持当前节奏 7 天，同时关注精力和训练表现。",
                    "target": 7,
                    "unit": "天",
                    "duration_days": 7,
                    "reminder_time": "07:30",
                }
                tone, priority = "positive", 75
            else:
                headline = f"本周晨重均值小幅下降 {abs_diff:.2f} kg"
                action = {
                    "title": "继续观察 7 天",
                    "detail": "维持晨重记录，暂不根据单周小幅变化调整计划。",
                    "target": 7,
                    "unit": "天",
                    "duration_days": 7,
                    "reminder_time": "07:30",
                }
                tone, priority = "neutral", 60
            week_start = date.fromisoformat(current["week_start"])
            week_end = date.fromisoformat(current["week_end"])
            cards.append(
                _card(
                    key=f"weight:{current['week_start']}",
                    kind="trend",
                    metric="晨重",
                    headline=headline,
                    finding=(
                        f"本周 {current['am_days']} 天晨重均值为 "
                        f"{current['am_avg']:.2f} kg，上周为 "
                        f"{current['am_avg'] - diff:.2f} kg。"
                    ),
                    evidence=[
                        f"本周均值：{current['am_avg']:.2f} kg",
                        f"较上周：{diff:+.2f} kg",
                        f"初始基线：{baseline['start']} kg",
                    ],
                    confidence=_confidence(
                        current["am_days"], 7, "按晨重记录计算周均值"
                    ),
                    action=action,
                    period_start=week_start,
                    period_end=week_end,
                    priority=priority,
                    tone=tone,
                )
            )

    recent_sleep = [
        r for r in records if r.type == "sleep" and start <= r.date <= end
    ]
    previous_sleep = [
        r for r in records
        if r.type == "sleep" and previous_start <= r.date < start
    ]

    def sleep_value(record: Record) -> int | None:
        value = _bedtime_minutes((record.fields_json or {}).get("bedtime") or "")
        if value is not None and value < 12 * 60:
            value += 24 * 60
        return value

    recent_values = [v for r in recent_sleep if (v := sleep_value(r)) is not None]
    previous_values = [v for r in previous_sleep if (v := sleep_value(r)) is not None]
    if len(recent_values) >= 2 and len(previous_values) >= 2:
        recent_avg = round(sum(recent_values) / len(recent_values))
        previous_avg = round(sum(previous_values) / len(previous_values))
        later = recent_avg - previous_avg
        if later >= 20:
            def fmt_minutes(value: int) -> str:
                value %= 24 * 60
                return f"{value // 60:02d}:{value % 60:02d}"

            cards.append(
                _card(
                    key=f"sleep:{end.isoformat()}",
                    kind="trend",
                    metric="入睡时间",
                    headline=f"最近一周平均入睡时间推迟了 {later} 分钟",
                    finding=(
                        f"最近一周平均约 {fmt_minutes(recent_avg)} 入睡，"
                        f"前一周约为 {fmt_minutes(previous_avg)}。"
                    ),
                    evidence=[
                        f"最近一周：{fmt_minutes(recent_avg)}",
                        f"前一周：{fmt_minutes(previous_avg)}",
                        f"有效记录：最近 {len(recent_values)} 天，前期 {len(previous_values)} 天",
                    ],
                    confidence=_confidence(
                        len(recent_values), 7, "前一窗口也有可比较记录"
                    ),
                    action={
                        "title": "23:30 开始睡前准备",
                        "detail": "连续 3 天执行，目标是在 00:00 前上床。",
                        "target": "00:00",
                        "unit": "前上床",
                        "duration_days": 3,
                        "reminder_time": "23:30",
                    },
                    period_start=start,
                    period_end=end,
                    priority=85,
                )
            )

    week_records = [r for r in records if start <= r.date <= end]
    swim = [
        r for r in week_records
        if r.type == "exercise" and (r.fields_json or {}).get("kind") == "swim"
    ]
    strength = [
        r for r in week_records
        if r.type == "exercise"
        and (r.fields_json or {}).get("kind") == "strength"
        and (r.fields_json or {}).get("done")
    ]
    if swim or strength:
        total_minutes = round(
            sum(float((r.fields_json or {}).get("duration_min") or 0) for r in swim)
        )
        cards.append(
            _card(
                key=f"exercise:{end.isoformat()}",
                kind="milestone",
                metric="运动",
                headline=f"最近一周完成了 {len(swim) + len(strength)} 次训练",
                finding=f"游泳 {len(swim)} 次，共 {total_minutes} 分钟；力量训练 {len(strength)} 次。",
                evidence=[
                    f"游泳：{len(swim)} 次 / {total_minutes} 分钟",
                    f"力量：{len(strength)} 次",
                    f"数据范围：{start.isoformat()} 至 {end.isoformat()}",
                ],
                confidence=_confidence(len({r.date for r in swim + strength}), 7, "按已记录训练统计"),
                action={
                    "title": "安排下一次 30 分钟运动",
                    "detail": "选择一个容易执行的时段，延续当前运动节奏。",
                    "target": 30,
                    "unit": "分钟",
                    "duration_days": 3,
                    "reminder_time": "18:30",
                },
                period_start=start,
                period_end=end,
                priority=55,
                tone="positive",
            )
        )

    return sorted(cards, key=lambda item: item["priority"], reverse=True)


def _overlay_state(card: dict, state: InsightState) -> dict:
    merged = dict(card)
    merged["status"] = state.status if state.status in INSIGHT_STATUSES else "new"
    merged["feedback"] = state.feedback
    merged["feedback_reason"] = state.feedback_reason
    merged["reminder_at"] = state.reminder_at.isoformat() if state.reminder_at else None
    if state.action_plan_json:
        merged["action"] = state.action_plan_json
    merged["updated_at"] = state.updated_at.isoformat() if state.updated_at else None
    return merged


def _insight_payload(db: Session) -> dict:
    records = _trend_rows(db)
    generated = _generate_insights(records, _baseline(db))
    current = {item["key"]: item for item in generated}
    states = list(db.scalars(select(InsightState).order_by(InsightState.updated_at.desc())))
    state_by_key = {item.insight_key: item for item in states}

    cards: list[dict] = []
    for key, card in current.items():
        state = state_by_key.get(key)
        cards.append(_overlay_state(card, state) if state else card)
    for state in states:
        if state.insight_key not in current and state.snapshot_json:
            cards.append(_overlay_state(state.snapshot_json, state))

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    priority: list[dict] = []
    active: list[dict] = []
    history: list[dict] = []
    for card in cards:
        status = card["status"]
        reminder = card.get("reminder_at")
        reminder_due = False
        if reminder:
            try:
                reminder_due = datetime.fromisoformat(reminder).replace(tzinfo=None) <= now
            except ValueError:
                reminder_due = False
        if status == "new" or (status == "snoozed" and reminder_due):
            priority.append(card)
        elif status in {"adopted", "snoozed"}:
            active.append(card)
        else:
            history.append(card)

    priority.sort(key=lambda item: item.get("priority", 0), reverse=True)
    return {
        "priority": priority[:3],
        "active": active,
        "history": history[:12],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "safety_note": "洞察用于生活方式记录与自我观察，不构成疾病诊断或处方级建议。",
    }


@router.get("/insights")
def get_insights(db: Session = Depends(get_db)) -> dict:
    return _insight_payload(db)


@router.patch("/insights/{insight_key}")
def update_insight(
    insight_key: str,
    payload: InsightActionIn,
    db: Session = Depends(get_db),
) -> dict:
    state = db.scalars(
        select(InsightState).where(InsightState.insight_key == insight_key)
    ).first()
    generated = {
        item["key"]: item
        for item in _generate_insights(_trend_rows(db), _baseline(db))
    }
    card = generated.get(insight_key) or (state.snapshot_json if state else None)
    if not card:
        raise HTTPException(status_code=404, detail="洞察不存在或已经失效")

    if state is None:
        state = InsightState(insight_key=insight_key, snapshot_json=card)
        db.add(state)

    if payload.action in {"adopt", "adjust"}:
        state.status = "adopted"
        state.reminder_at = payload.reminder_at
        state.action_plan_json = payload.action_plan or state.action_plan_json or card["action"]
    elif payload.action == "snooze":
        if payload.reminder_at is None:
            raise HTTPException(status_code=422, detail="稍后提醒需要 reminder_at")
        state.status = "snoozed"
        state.reminder_at = payload.reminder_at
    elif payload.action == "dismiss":
        state.status = "dismissed"
        state.reminder_at = None
    elif payload.action == "complete":
        state.status = "completed"
        state.reminder_at = None
    elif payload.action == "reopen":
        state.status = "new"
        state.reminder_at = None

    if payload.action == "feedback" or payload.helpful is not None:
        if payload.helpful is None:
            raise HTTPException(status_code=422, detail="反馈需要 helpful")
        state.feedback = "helpful" if payload.helpful else "not_helpful"
        state.feedback_reason = payload.reason

    state.snapshot_json = card
    state.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(state)
    return _overlay_state(card, state)
