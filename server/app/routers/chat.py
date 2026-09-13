"""聊天 API（架构 §6.1 SSE 事件契约 / §6.7 打开即引导）。

- POST   /api/chats                    获取/创建今日会话（首次创建且晨重未记 → AI 晨检开场）
- GET    /api/chats                    会话列表
- GET    /api/chats/{id}/messages      消息列表
- POST   /api/chats/{id}/messages      发送消息 → SSE 流（token/record_card/done）
- POST   /api/chats/{id}/confirm       确认卡片入账（关联 message.record_id）
"""
import asyncio
import json
import time
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas
from app.database import SessionLocal, get_db
from app.models import Chat, ChatRun, Message, Record
from app.services import chat_engine
from app.services.kb import ensure_fts

router = APIRouter(prefix="/api/chats", tags=["chat"])


class NewChatOut(BaseModel):
    id: int
    date: str
    title: str
    opener: str | None = None  # 晨检/晚检引导语（§6.7）


def _sse(event: str, data: dict, event_id: int) -> str:
    return (
        f"id: {event_id}\n"
        "retry: 800\n"
        f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    )


def _get_or_create_chat(db: Session, today: date) -> tuple[Chat, bool]:
    chat = db.scalars(select(Chat).where(Chat.date == today)).first()
    if chat is not None:
        return chat, False
    chat = Chat(date=today, title=f"{today.month}月{today.day}日记录")
    db.add(chat)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        chat = db.scalars(select(Chat).where(Chat.date == today)).first()
        if chat is None:
            raise
        return chat, False
    db.refresh(chat)
    return chat, True


def _guidance_opener(db: Session, today: date) -> str | None:
    """晨检/晚检：当日首次打开且晨重未记 → 引导语（§6.7）。"""
    has_am = db.scalars(
        select(Record).where(
            Record.date == today, Record.type == "weight", Record.slot == "am"
        )
    ).first()
    if has_am is None:
        return "早，昨晚睡得怎么样？今早空腹称了吗？一句话告诉我，比如「今早空腹 106.5，昨晚 00:30 睡的」。"
    return None


@router.post("")
def create_today_chat(db: Session = Depends(get_db)) -> NewChatOut:
    today = date.today()
    chat, created = _get_or_create_chat(db, today)
    opener = None
    if created:
        opener = _guidance_opener(db, today)
    return NewChatOut(id=chat.id, date=chat.date.isoformat(), title=chat.title, opener=opener)


@router.get("")
def list_chats(db: Session = Depends(get_db)) -> list[dict]:
    chats = db.scalars(select(Chat).order_by(Chat.date.desc())).all()
    return [{"id": c.id, "date": c.date.isoformat(), "title": c.title} for c in chats]


@router.get("/{chat_id}/messages")
def get_messages(chat_id: int, db: Session = Depends(get_db)) -> list[dict]:
    chat = db.get(Chat, chat_id)
    if chat is None:
        raise HTTPException(404, "会话不存在")
    msgs = db.scalars(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.id)
    ).all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "record_id": m.record_id,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in msgs
    ]


class SendMessageIn(BaseModel):
    content: str
    request_id: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


_running_tasks: dict[int, asyncio.Task] = {}


def _prepare_run(
    db: Session,
    chat_id: int | None,
    payload: SendMessageIn,
) -> tuple[ChatRun, Chat]:
    """原子建立一次消息运行；相同 request_id 永远复用已有运行。"""
    content = payload.content.strip()
    if not content:
        raise HTTPException(422, "消息不能为空")

    existing = db.scalars(
        select(ChatRun).where(ChatRun.request_key == payload.request_id)
    ).first()
    if existing is not None:
        user_message = db.get(Message, existing.user_message_id)
        if user_message is None or user_message.content != content:
            raise HTTPException(409, "request_id 已用于另一条消息")
        if chat_id is not None and existing.chat_id != chat_id:
            raise HTTPException(409, "request_id 已用于另一会话")
        chat = db.get(Chat, existing.chat_id)
        if chat is None:
            raise HTTPException(409, "幂等请求关联的会话已不存在")
        return existing, chat

    if chat_id is None:
        chat, _ = _get_or_create_chat(db, date.today())
    else:
        chat = db.get(Chat, chat_id)
        if chat is None:
            raise HTTPException(404, "会话不存在")

    user_message = Message(chat_id=chat.id, role="user", content=content)
    db.add(user_message)
    db.flush()
    run = ChatRun(
        request_key=payload.request_id,
        chat_id=chat.id,
        user_message_id=user_message.id,
        status="pending",
        events_json=[
            {
                "id": 1,
                "event": "meta",
                "data": {"chat_id": chat.id, "request_id": payload.request_id},
            }
        ],
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalars(
            select(ChatRun).where(ChatRun.request_key == payload.request_id)
        ).first()
        if existing is None:
            raise
        return _prepare_run(db, chat_id, payload)
    db.refresh(run)
    return run, chat


def _append_run_event(db: Session, run: ChatRun, event: str, data: dict) -> int:
    events = list(run.events_json or [])
    event_id = (int(events[-1]["id"]) if events else 0) + 1
    events.append({"id": event_id, "event": event, "data": data})
    run.events_json = events
    run.updated_at = datetime.now(timezone.utc)
    db.add(run)
    db.commit()
    return event_id


async def _execute_run(run_id: int) -> None:
    """后台完成模型调用；HTTP 客户端断开不会取消这个任务。"""
    with SessionLocal() as db:
        run = db.get(ChatRun, run_id)
        if run is None or run.status in {"completed", "failed"}:
            return
        if run.status == "running":
            run.status = "failed"
            run.error = "服务曾在响应期间重启，请重新发送"
            _append_run_event(db, run, "done", {"usage": {}, "error": run.error})
            return

        user_message = db.get(Message, run.user_message_id)
        if user_message is None:
            run.status = "failed"
            run.error = "用户消息不存在"
            _append_run_event(db, run, "done", {"usage": {}, "error": run.error})
            return

        run.status = "running"
        db.add(run)
        db.commit()
        started = time.perf_counter()
        full_text: list[str] = []
        received_done = False
        try:
            ensure_fts(db)
            async for event in chat_engine.run_chat(
                db,
                run.chat_id,
                user_message.content,
                user_msg_id=user_message.id,
            ):
                if event.kind == "token":
                    full_text.append(event.data["text"])
                    _append_run_event(db, run, "token", event.data)
                elif event.kind == "record_card":
                    _append_run_event(db, run, "record_card", event.data)
                elif event.kind == "done":
                    received_done = True
                    usage = event.data.get("usage") or {}
                    error = event.data.get("error")
                    run.provider_id = event.data.get("provider_id")
                    run.provider_model = event.data.get("provider_model")
                    run.usage_json = usage
                    run.usage_source = event.data.get("usage_source")
                    run.latency_ms = round((time.perf_counter() - started) * 1000)
                    run.error = error
                    if error is None:
                        assistant = Message(
                            chat_id=run.chat_id,
                            role="assistant",
                            content="".join(full_text),
                            token_usage=usage.get("total_tokens"),
                            prompt_tokens=usage.get("prompt_tokens"),
                            completion_tokens=usage.get("completion_tokens"),
                            cache_hit_tokens=usage.get("prompt_cache_hit_tokens"),
                        )
                        db.add(assistant)
                        db.flush()
                        run.assistant_message_id = assistant.id
                        run.status = "completed"
                        payload_out = {
                            "usage": usage,
                            "usage_source": run.usage_source,
                            "message_id": assistant.id,
                            "error": None,
                        }
                    else:
                        run.status = "failed"
                        payload_out = {"usage": usage, "error": error}
                    _append_run_event(db, run, "done", payload_out)
                    break
            if not received_done:
                run.status = "failed"
                run.error = "模型流未返回完成事件"
                _append_run_event(db, run, "done", {"usage": {}, "error": run.error})
        except Exception as exc:  # noqa: BLE001 - 持久化明确错误，供重连客户端读取
            db.rollback()
            run = db.get(ChatRun, run_id)
            if run is not None and run.status not in {"completed", "failed"}:
                run.status = "failed"
                run.error = f"消息处理失败：{exc}"
                _append_run_event(db, run, "done", {"usage": {}, "error": run.error})


def _ensure_run_task(run: ChatRun) -> None:
    task = _running_tasks.get(run.id)
    if task is not None and not task.done():
        return
    if run.status in {"completed", "failed"}:
        return
    task = asyncio.create_task(_execute_run(run.id))
    _running_tasks[run.id] = task

    def cleanup(done: asyncio.Task) -> None:
        if _running_tasks.get(run.id) is done:
            _running_tasks.pop(run.id, None)

    task.add_done_callback(cleanup)


async def _stream_run(run_id: int, after_event_id: int):
    sent = max(after_event_id, 0)
    ping_at = time.monotonic() + 10
    while True:
        with SessionLocal() as db:
            run = db.get(ChatRun, run_id)
            if run is None:
                yield _sse("done", {"usage": {}, "error": "消息运行不存在"}, sent + 1)
                return
            events = [item for item in (run.events_json or []) if int(item["id"]) > sent]
            status = run.status
        for item in events:
            sent = int(item["id"])
            yield _sse(item["event"], item["data"], sent)
        if status in {"completed", "failed"} and not events:
            return
        if time.monotonic() >= ping_at:
            yield ": keep-alive\n\n"
            ping_at = time.monotonic() + 10
        await asyncio.sleep(0.12)


def _last_event_id(value: str | None) -> int:
    try:
        return max(int(value or 0), 0)
    except ValueError:
        raise HTTPException(400, "Last-Event-ID 必须是非负整数") from None


def _message_response(
    db: Session,
    payload: SendMessageIn,
    chat_id: int | None,
    last_event_id: str | None,
) -> StreamingResponse:
    run, chat = _prepare_run(db, chat_id, payload)
    _ensure_run_task(run)
    return StreamingResponse(
        _stream_run(run.id, _last_event_id(last_event_id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Chat-Id": str(chat.id),
            "X-Request-Id": run.request_key,
        },
    )


@router.post("/messages")
async def send_first_message(
    payload: SendMessageIn,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """首次发送时才创建今天的会话。"""
    return _message_response(db, payload, None, last_event_id)


@router.post("/{chat_id}/messages")
async def send_message(
    chat_id: int,
    payload: SendMessageIn,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    return _message_response(db, payload, chat_id, last_event_id)


class ConfirmIn(BaseModel):
    draft: schemas.RecordCreate
    message_id: int | None = None


@router.post("/{chat_id}/confirm")
def confirm_record(
    chat_id: int,
    payload: ConfirmIn,
    db: Session = Depends(get_db),
) -> dict:
    """确认卡入账：创建 record（source=chat, confirmed=True）并回链 message。"""
    chat = db.get(Chat, chat_id)
    if chat is None:
        raise HTTPException(404, "会话不存在")
    draft = payload.draft
    rec = Record(
        type=draft.type,
        date=draft.date,
        slot=draft.slot,
        fields_json=draft.fields,
        raw_text=draft.raw_text,
        source="chat",
        confirmed=True,
    )
    db.add(rec)
    db.flush()
    if payload.message_id is not None:
        msg = db.get(Message, payload.message_id)
        if msg is not None and msg.chat_id == chat_id:
            msg.record_id = rec.id
    db.commit()
    db.refresh(rec)
    return {
        "id": rec.id,
        "type": rec.type,
        "date": rec.date.isoformat(),
        "slot": rec.slot,
        "fields": rec.fields_json,
    }
