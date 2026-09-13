"""对话引擎（架构 §6.1 请求管线 ⑤⑥⑦⑧）。

- 组装上下文（系统提示 + 历史窗口 20 条）
- 调用 Provider（流式），拦截 register_record 工具调用：
  Pydantic 校验（闸二）→ 通过则产出 record_card（不入库），失败则回喂模型修正
- register_record 之外的工具（get_kb/get_today_summary）由本地执行后回喂
- 工具轮次上限 3，防死循环
"""
import json
import math
from datetime import date, timedelta
from typing import AsyncIterator, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.models import Message, Record
from app.providers.base import ProviderMessage, tool_result_message
from app.services import kb as kb_service
from app.services import prompts
from app.services.provider_settings import get_active_provider

MAX_TOOL_ROUNDS = 3
HISTORY_WINDOW = 20


def _estimate_tokens(text: str | None) -> int:
    """Provider 不回传 usage 时的保守估算；只用于标注为 estimated 的数据。"""
    if not text:
        return 0
    ascii_chars = sum(ord(char) < 128 for char in text)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, math.ceil(ascii_chars / 4) + non_ascii_chars)


def _estimate_prompt(messages: list[ProviderMessage]) -> int:
    return sum(
        _estimate_tokens(message.content)
        + _estimate_tokens(json.dumps(message.tool_calls, ensure_ascii=False) if message.tool_calls else "")
        + 4
        for message in messages
    )


# ---------- 工具定义（OpenAI function calling） ----------
def _register_record_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "register_record",
            "description": (
                "把用户口述的一条日常记录抽取为结构化数据（每条记录调用一次；"
                "一句话含多条就多次调用）。未确认前不会入库。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": list(schemas.FIELDS_MODEL.keys()),
                        "description": "记录类型",
                    },
                    "date": {
                        "type": "string",
                        "format": "date",
                        "description": "记录所属日（默认今天；入睡<12:00 归前一日）",
                    },
                    "slot": {
                        "type": "string",
                        "enum": ["am", "evening", "breakfast", "lunch", "dinner", "snack"],
                        "description": "时槽：weight→am/evening；meal→breakfast/lunch/dinner/snack；其余类型省略",
                    },
                    "fields": {
                        "type": "object",
                        "description": (
                            "按 type：weight{kg}；sleep{bedtime 'HH:MM'}；meal{desc}；"
                            "sweet_drink{level∈0杯/无糖/三分糖/半糖/全糖, desc}；"
                            "night_hunger{level∈没饿/加餐预案/破戒}；"
                            "exercise{kind∈swim/strength, duration_min|done}；"
                            "step{steps}；waist{cm}；supplement{item∈vitd3/zinc/copper, dose, timing, taken}；"
                            "body{site∈腰/踝/肠胃, level, symptom}；note{text}"
                        ),
                    },
                    "raw_text": {
                        "type": "string",
                        "description": "用户原话中对应这句的原文（溯源用）",
                    },
                },
                "required": ["type", "date", "fields", "raw_text"],
            },
        },
    }


def _get_kb_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "get_kb",
            "description": "检索知识库（8月减脂方案/7月健康知识库），返回带来源与章节号的原文块。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索词"},
                    "source_plan": {
                        "type": "string",
                        "enum": ["august_fatloss", "july_health"],
                        "description": "限定分域（可选）",
                    },
                },
                "required": ["query"],
            },
        },
    }


def _get_today_summary_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "get_today_summary",
            "description": "查看今天的已入账记录清单（各类型/时槽）。",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _get_trend_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "get_trend",
            "description": (
                "查询趋势与周报（周均晨重/较上周/腰围/奶茶档位分布/步数日均/达标评价），"
                "用于周复盘与趋势问答。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    }


TOOLS = [
    _register_record_tool(),
    _get_kb_tool(),
    _get_today_summary_tool(),
    _get_trend_tool(),
]


# ---------- 引擎输出事件（router 转 SSE） ----------
class EngineEvent:
    __slots__ = ("kind", "data")

    def __init__(self, kind: str, data: dict):
        self.kind = kind  # token / record_card / done
        self.data = data


def _recent_records(db: Session, today: date) -> list[Record]:
    # 窗口 21 天：近 3 日摘要 + 异常信号检测（体重2周不变）都够用
    since = today - timedelta(days=21)
    return list(
        db.scalars(
            select(Record)
            .where(Record.date >= since)
            .order_by(Record.date.desc(), Record.id.desc())
            .limit(500)
        ).all()
    )


def _history_messages(db: Session, chat_id: int, before_id: int | None = None) -> list[ProviderMessage]:
    stmt = (
        select(Message)
        .where(Message.chat_id == chat_id)
        .order_by(Message.id.desc())
        .limit(HISTORY_WINDOW)
    )
    if before_id is not None:
        stmt = stmt.where(Message.id < before_id)
    msgs = list(db.scalars(stmt).all())[::-1]
    out = []
    for m in msgs:
        if m.role == "user":
            out.append(ProviderMessage(role="user", content=m.content))
        elif m.role == "assistant" and m.content:
            out.append(ProviderMessage(role="assistant", content=m.content))
        # tool 消息不回放（其结果已体现在当轮 record_card）
    return out


def _exec_local_tool(db: Session, name: str, arguments: dict) -> str:
    if name == "get_kb":
        chunks = kb_service.search(db, arguments.get("query", ""),
                                   arguments.get("source_plan"))
        return kb_service.format_context(chunks) if chunks else "（无命中）"
    if name == "get_today_summary":
        today = date.today()
        items = db.scalars(
            select(Record).where(Record.date == today).order_by(Record.id)
        ).all()
        if not items:
            return "今日尚无记录。"
        return "今日已入账：\n" + "\n".join(prompts._fmt_record(r) for r in items)
    if name == "get_trend":
        from app.routers.stats import _trend_rows, _week_summaries

        weeks = _week_summaries(_trend_rows(db))
        if not weeks:
            return "尚无趋势数据。"
        lines = ["周报（每周晨重均值，达标口径：每周 -0.5~-1.5kg，plan §5.2）："]
        for w in weeks:
            diff = w["diff_vs_last"]
            diff_s = f"{diff:+.2f}kg" if diff is not None else "—"
            sweet = " ".join(f"{k}×{v}" for k, v in w["sweet_counts"].items()) or "未记录"
            lines.append(
                f"- {w['week_start']}~{w['week_end']}：晨重均值 {w['am_avg']}kg"
                f"（{w['am_days']}天），较上周 {diff_s}；腰围 {w['waist'] or '—'}cm；"
                f"奶茶：{sweet}；游泳 {w['swim_times']}次/{w['swim_total_min']}min；"
                f"力量 {w['strength_times']}次；步数日均 {w['steps_avg'] or '—'}；评价：{w['verdict']}"
            )
        return "\n".join(lines)
    return f"未知工具 {name}"


async def run_chat(
    db: Session,
    chat_id: int,
    user_text: str,
    user_msg_id: int | None = None,
) -> AsyncIterator[EngineEvent]:
    """一次用户消息的完整管线；yield EngineEvent(token/record_card/done)。

    user_msg_id：本轮用户消息已先落库，历史回放需排除（避免重复发送）。
    """
    today = date.today()
    recent = _recent_records(db, today)
    kb_chunks = kb_service.search(db, user_text)
    system = prompts.build_system_prompt(recent, kb_service.format_context(kb_chunks), today)

    messages: list[ProviderMessage] = [
        ProviderMessage(role="system", content=system),
        *_history_messages(db, chat_id, before_id=user_msg_id),
        ProviderMessage(role="user", content=user_text),
    ]
    provider = get_active_provider(db)

    total_usage: dict = {}
    estimated_prompt_tokens = 0
    cards: list[dict] = []
    assistant_text_parts: list[str] = []

    for _round in range(MAX_TOOL_ROUNDS):
        round_text: list[str] = []
        tool_events: list = []
        try:
            estimated_prompt_tokens += _estimate_prompt(messages)
            async for ev in provider.chat(messages, tools=TOOLS):
                if ev.delta:
                    round_text.append(ev.delta)
                    yield EngineEvent("token", {"text": ev.delta})
                if ev.tool_call is not None:
                    tool_events.append(ev.tool_call)
                if ev.usage:
                    for k, v in ev.usage.items():
                        if isinstance(v, int):
                            total_usage[k] = total_usage.get(k, 0) + v
        except Exception as e:  # noqa: BLE001 上抛为明确错误（§6.2 不静默降级）
            yield EngineEvent(
                "done",
                {
                    "error": f"Provider 调用失败: {e}",
                    "usage": total_usage,
                    "usage_source": "provider" if total_usage else None,
                    "provider_id": provider.provider_id,
                    "provider_model": provider.model,
                },
            )
            return

        assistant_text_parts.append("".join(round_text))

        if not tool_events:
            break  # 纯文本回应，结束

        # 把 assistant 工具调用消息入栈（OpenAI 协议要求回放）
        messages.append(
            ProviderMessage(
                role="assistant",
                content="".join(round_text) or None,
                tool_calls=[
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in tool_events
                ],
            )
        )

        more_rounds = False
        for tc in tool_events:
            try:
                arguments = json.loads(tc.arguments or "{}")
            except json.JSONDecodeError:
                arguments = None

            if tc.name == "register_record" and isinstance(arguments, dict):
                card, err = _validate_record(db, arguments)
                if card is not None:
                    cards.append(card)
                    yield EngineEvent("record_card", card)
                    result = (
                        "已生成确认卡片（未入库），等用户确认。"
                        "请用一两句话自然回应（如与近期数据对比），不要重复卡片里的字段清单。"
                    )
                else:
                    result = f"校验失败，未生成卡片：{err}。请修正后重新调用，或放弃并向用户说明。"
            elif isinstance(arguments, dict):
                result = _exec_local_tool(db, tc.name, arguments)
            else:
                result = "参数不是合法 JSON 对象，请重试。"
            messages.append(tool_result_message(tc.id, result))
            more_rounds = True

        if more_rounds:
            continue  # 模型基于工具结果生成最终回应

    usage_source = "provider"
    if not total_usage.get("prompt_tokens") or not total_usage.get("completion_tokens"):
        if not total_usage.get("prompt_tokens"):
            total_usage["prompt_tokens"] = estimated_prompt_tokens
        if not total_usage.get("completion_tokens"):
            total_usage["completion_tokens"] = _estimate_tokens(
                "".join(assistant_text_parts)
            )
        total_usage["total_tokens"] = (
            total_usage["prompt_tokens"] + total_usage["completion_tokens"]
        )
        usage_source = "estimated"

    yield EngineEvent(
        "done",
        {
            "usage": total_usage,
            "usage_source": usage_source,
            "provider_id": provider.provider_id,
            "provider_model": provider.model,
            "text": "".join(assistant_text_parts),
            "cards": len(cards),
        },
    )


def _validate_record(db: Session, arguments: dict) -> tuple[dict | None, str | None]:
    """闸二：Pydantic 校验 + 体重相对闸 → 确认卡数据（不入库）。"""
    try:
        payload = schemas.RecordCreate(
            type=arguments.get("type"),
            date=arguments.get("date") or date.today().isoformat(),
            slot=arguments.get("slot"),
            fields=arguments.get("fields") or {},
            raw_text=arguments.get("raw_text", ""),
            source="chat",
            confirmed=False,
        )
    except Exception as e:  # noqa: BLE001
        return None, str(e)[:300]

    warnings: list[str] = []
    if payload.type == "weight":
        from app.routers.records import _weight_relative_check

        warnings = _weight_relative_check(db, payload)

    return (
        {
            "draft": {
                "type": payload.type,
                "date": payload.date.isoformat(),
                "slot": payload.slot,
                "fields": payload.fields,
                "raw_text": payload.raw_text,
                "source": "chat",
            },
            "warnings": warnings,
        },
        None,
    )
