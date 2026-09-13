"""Versioned JSON backup validation and transactional restore."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session

from app import schemas
from app.models import (
    Chat,
    ChatRun,
    Base,
    ImportLedger,
    InsightState,
    KbChunk,
    KbDoc,
    Message,
    Record,
    User,
)

FORMAT_VERSION = 2
CORE_COLLECTIONS = ("records", "chats", "messages", "kb_docs", "kb_chunks", "users")
OPTIONAL_COLLECTIONS = ("imports", "insight_states", "chat_runs")


class BackupValidationError(ValueError):
    pass


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _ids(rows: list[dict], name: str) -> set[int]:
    values: list[int] = []
    for row in rows:
        value = row.get("id")
        if not isinstance(value, int) or value <= 0:
            raise BackupValidationError(f"{name} 存在非法 id")
        values.append(value)
    if len(values) != len(set(values)):
        raise BackupValidationError(f"{name} 存在重复 id")
    return set(values)


def validate_backup(backup: Any) -> dict:
    if not isinstance(backup, dict):
        raise BackupValidationError("备份根节点必须是 JSON 对象")
    meta = backup.get("meta")
    if not isinstance(meta, dict) or meta.get("app") != "康迹":
        raise BackupValidationError("不是有效的康迹备份")

    version = int(meta.get("format_version") or 1)
    if version not in {1, FORMAT_VERSION}:
        raise BackupValidationError(f"不支持的备份格式版本：{version}")

    for name in CORE_COLLECTIONS:
        if not isinstance(backup.get(name), list):
            raise BackupValidationError(f"缺少集合：{name}")
    for name in OPTIONAL_COLLECTIONS:
        if name in backup and not isinstance(backup[name], list):
            raise BackupValidationError(f"集合 {name} 必须是数组")

    rows = {name: list(backup.get(name) or []) for name in (*CORE_COLLECTIONS, *OPTIONAL_COLLECTIONS)}
    record_ids = _ids(rows["records"], "records")
    chat_ids = _ids(rows["chats"], "chats")
    message_ids = _ids(rows["messages"], "messages")
    doc_ids = _ids(rows["kb_docs"], "kb_docs")
    _ids(rows["kb_chunks"], "kb_chunks")
    _ids(rows["users"], "users")
    import_ids = _ids(rows["imports"], "imports")
    _ids(rows["insight_states"], "insight_states")
    _ids(rows["chat_runs"], "chat_runs")

    dates: set[str] = set()
    for row in rows["chats"]:
        day = date.fromisoformat(str(row.get("date")))
        if day.isoformat() in dates:
            raise BackupValidationError("chats 存在同日重复会话")
        dates.add(day.isoformat())

    for row in rows["records"]:
        try:
            schemas.RecordCreate(
                type=row.get("type"),
                date=row.get("date"),
                slot=row.get("slot"),
                fields=row.get("fields") or {},
                raw_text=row.get("raw_text") or "",
                source=row.get("source") or "manual",
                confirmed=bool(row.get("confirmed", True)),
            )
        except Exception as exc:
            raise BackupValidationError(f"record {row.get('id')} 校验失败：{exc}") from exc

    for row in rows["messages"]:
        if row.get("chat_id") not in chat_ids:
            raise BackupValidationError(f"message {row.get('id')} 引用了不存在的 chat")
        if row.get("record_id") is not None and row.get("record_id") not in record_ids:
            raise BackupValidationError(f"message {row.get('id')} 引用了不存在的 record")
        if row.get("role") not in {"user", "assistant", "tool"}:
            raise BackupValidationError(f"message {row.get('id')} role 非法")

    for row in rows["kb_chunks"]:
        if row.get("doc_id") not in doc_ids:
            raise BackupValidationError(f"kb_chunk {row.get('id')} 引用了不存在的 doc")

    for row in rows["imports"]:
        if row.get("record_id") is not None and row.get("record_id") not in record_ids:
            raise BackupValidationError(f"import {row.get('id')} 引用了不存在的 record")

    request_keys: set[str] = set()
    for row in rows["chat_runs"]:
        key = str(row.get("request_key") or "")
        if not key or key in request_keys:
            raise BackupValidationError("chat_runs 存在空或重复 request_key")
        request_keys.add(key)
        if row.get("chat_id") not in chat_ids:
            raise BackupValidationError(f"chat_run {row.get('id')} 引用了不存在的 chat")
        if row.get("user_message_id") not in message_ids:
            raise BackupValidationError(f"chat_run {row.get('id')} 缺少用户消息")
        user_message = next(
            item for item in rows["messages"] if item["id"] == row["user_message_id"]
        )
        if (
            user_message.get("role") != "user"
            or user_message.get("chat_id") != row.get("chat_id")
        ):
            raise BackupValidationError(f"chat_run {row.get('id')} 的用户消息归属非法")
        assistant_id = row.get("assistant_message_id")
        if assistant_id is not None and assistant_id not in message_ids:
            raise BackupValidationError(f"chat_run {row.get('id')} 缺少助手消息")
        if assistant_id is not None:
            assistant = next(
                item for item in rows["messages"] if item["id"] == assistant_id
            )
            if (
                assistant.get("role") != "assistant"
                or assistant.get("chat_id") != row.get("chat_id")
            ):
                raise BackupValidationError(f"chat_run {row.get('id')} 的助手消息归属非法")

    counts = {name: len(value) for name, value in rows.items()}
    declared = meta.get("counts") or {}
    for name, count in declared.items():
        if name in counts and int(count) != counts[name]:
            raise BackupValidationError(f"{name} 数量与 meta.counts 不一致")

    warnings = []
    if version == 1:
        warnings.append("旧版备份不含导入台账、SSE 运行记录或 PIN 哈希；恢复时将保留当前 PIN。")
    if import_ids and version == 1:
        warnings.append("旧版备份出现 imports 集合，将按兼容格式恢复。")
    return {"ok": True, "format_version": version, "counts": counts, "warnings": warnings}


def build_backup(db: Session) -> dict:
    def iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    records = [
        {
            "id": item.id,
            "type": item.type,
            "date": item.date.isoformat(),
            "slot": item.slot,
            "fields": item.fields_json,
            "raw_text": item.raw_text,
            "source": item.source,
            "confirmed": item.confirmed,
            "created_at": iso(item.created_at),
        }
        for item in db.scalars(select(Record).order_by(Record.id)).all()
    ]
    chats = [
        {"id": item.id, "date": item.date.isoformat(), "title": item.title, "summary": item.summary}
        for item in db.scalars(select(Chat).order_by(Chat.id)).all()
    ]
    messages = [
        {
            "id": item.id,
            "chat_id": item.chat_id,
            "role": item.role,
            "content": item.content,
            "record_id": item.record_id,
            "token_usage": item.token_usage,
            "prompt_tokens": item.prompt_tokens,
            "completion_tokens": item.completion_tokens,
            "cache_hit_tokens": item.cache_hit_tokens,
            "created_at": iso(item.created_at),
        }
        for item in db.scalars(select(Message).order_by(Message.id)).all()
    ]
    kb_docs = [
        {
            "id": item.id,
            "title": item.title,
            "source_plan": item.source_plan,
            "version": item.version,
            "imported_at": iso(item.imported_at),
        }
        for item in db.scalars(select(KbDoc).order_by(KbDoc.id)).all()
    ]
    kb_chunks = [
        {
            "id": item.id,
            "doc_id": item.doc_id,
            "title": item.title,
            "heading": item.heading,
            "source_plan": item.source_plan,
            "section_no": item.section_no,
            "content": item.content,
            "tags": item.tags,
            "created_at": iso(item.created_at),
        }
        for item in db.scalars(select(KbChunk).order_by(KbChunk.id)).all()
    ]
    users = [
        {
            "id": item.id,
            "username": item.username,
            "password_hash": item.password_hash,
            "settings_json": item.settings_json,
        }
        for item in db.scalars(select(User).order_by(User.id)).all()
    ]
    imports = [
        {
            "id": item.id,
            "source_file": item.source_file,
            "sheet": item.sheet,
            "row_no": item.row_no,
            "record_id": item.record_id,
            "note": item.note,
            "imported_at": iso(item.imported_at),
        }
        for item in db.scalars(select(ImportLedger).order_by(ImportLedger.id)).all()
    ]
    insight_states = [
        {
            "id": item.id,
            "insight_key": item.insight_key,
            "status": item.status,
            "feedback": item.feedback,
            "feedback_reason": item.feedback_reason,
            "reminder_at": iso(item.reminder_at),
            "action_plan": item.action_plan_json,
            "snapshot": item.snapshot_json,
            "created_at": iso(item.created_at),
            "updated_at": iso(item.updated_at),
        }
        for item in db.scalars(select(InsightState).order_by(InsightState.id)).all()
    ]
    chat_runs = [
        {
            "id": item.id,
            "request_key": item.request_key,
            "chat_id": item.chat_id,
            "user_message_id": item.user_message_id,
            "assistant_message_id": item.assistant_message_id,
            "status": item.status,
            "events": item.events_json,
            "provider_id": item.provider_id,
            "provider_model": item.provider_model,
            "usage": item.usage_json,
            "usage_source": item.usage_source,
            "latency_ms": item.latency_ms,
            "error": item.error,
            "created_at": iso(item.created_at),
            "updated_at": iso(item.updated_at),
        }
        for item in db.scalars(select(ChatRun).order_by(ChatRun.id)).all()
    ]
    collections = {
        "records": records,
        "chats": chats,
        "messages": messages,
        "kb_docs": kb_docs,
        "kb_chunks": kb_chunks,
        "users": users,
        "imports": imports,
        "insight_states": insight_states,
        "chat_runs": chat_runs,
    }
    return {
        "meta": {
            "app": "康迹",
            "format_version": FORMAT_VERSION,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "export_date": date.today().isoformat(),
            "counts": {name: len(rows) for name, rows in collections.items()},
        },
        **collections,
    }


def restore_backup(db: Session, backup: dict) -> dict:
    report = validate_backup(backup)
    current_user = db.scalars(select(User).order_by(User.id)).first()
    preserved_password_hash = current_user.password_hash if current_user else None
    db.rollback()

    try:
        for model in (ChatRun, ImportLedger, InsightState, Message, Chat, Record, KbChunk, KbDoc, User):
            db.execute(delete(model))

        user_rows = backup["users"]
        if not user_rows and preserved_password_hash:
            user_rows = [
                {
                    "id": 1,
                    "username": "local",
                    "password_hash": preserved_password_hash,
                    "settings_json": {},
                }
            ]
        for row in user_rows:
            db.add(
                User(
                    id=row["id"],
                    username=row["username"],
                    password_hash=row.get("password_hash") or preserved_password_hash,
                    settings_json=row.get("settings_json") or {},
                )
            )
        for row in backup["records"]:
            payload = schemas.RecordCreate(
                type=row["type"], date=row["date"], slot=row.get("slot"),
                fields=row.get("fields") or {}, raw_text=row.get("raw_text") or "",
                source=row.get("source") or "manual", confirmed=bool(row.get("confirmed", True)),
            )
            db.add(
                Record(
                    id=row["id"], type=payload.type, date=payload.date, slot=payload.slot,
                    fields_json=payload.fields, raw_text=payload.raw_text, source=payload.source,
                    confirmed=payload.confirmed, created_at=_dt(row.get("created_at")) or datetime.now(),
                )
            )
        for row in backup["chats"]:
            db.add(Chat(id=row["id"], date=date.fromisoformat(row["date"]), title=row.get("title") or "", summary=row.get("summary")))
        for row in backup["messages"]:
            db.add(
                Message(
                    id=row["id"], chat_id=row["chat_id"], role=row["role"], content=row.get("content") or "",
                    record_id=row.get("record_id"), token_usage=row.get("token_usage"),
                    prompt_tokens=row.get("prompt_tokens"), completion_tokens=row.get("completion_tokens"),
                    cache_hit_tokens=row.get("cache_hit_tokens"), created_at=_dt(row.get("created_at")) or datetime.now(),
                )
            )
        for row in backup["kb_docs"]:
            db.add(KbDoc(id=row["id"], title=row["title"], source_plan=row["source_plan"], version=row.get("version") or "", imported_at=_dt(row.get("imported_at")) or datetime.now()))
        for row in backup["kb_chunks"]:
            db.add(
                KbChunk(
                    id=row["id"], doc_id=row["doc_id"], title=row["title"], heading=row.get("heading") or "",
                    source_plan=row["source_plan"], section_no=row.get("section_no") or "",
                    content=row.get("content") or "", tags=row.get("tags") or [],
                    created_at=_dt(row.get("created_at")) or datetime.now(),
                )
            )
        for row in backup.get("imports") or []:
            db.add(
                ImportLedger(
                    id=row["id"], source_file=row["source_file"], sheet=row["sheet"], row_no=row["row_no"],
                    record_id=row.get("record_id"), note=row.get("note"), imported_at=_dt(row.get("imported_at")) or datetime.now(),
                )
            )
        for row in backup.get("insight_states") or []:
            db.add(
                InsightState(
                    id=row["id"], insight_key=row["insight_key"], status=row.get("status") or "new",
                    feedback=row.get("feedback"), feedback_reason=row.get("feedback_reason"),
                    reminder_at=_dt(row.get("reminder_at")), action_plan_json=row.get("action_plan") or {},
                    snapshot_json=row.get("snapshot") or {}, created_at=_dt(row.get("created_at")) or datetime.now(),
                    updated_at=_dt(row.get("updated_at")) or datetime.now(),
                )
            )
        db.flush()
        for row in backup.get("chat_runs") or []:
            db.add(
                ChatRun(
                    id=row["id"], request_key=row["request_key"], chat_id=row["chat_id"],
                    user_message_id=row["user_message_id"], assistant_message_id=row.get("assistant_message_id"),
                    status=row.get("status") or "completed", events_json=row.get("events") or [],
                    provider_id=row.get("provider_id"), provider_model=row.get("provider_model"),
                    usage_json=row.get("usage") or {}, usage_source=row.get("usage_source"),
                    latency_ms=row.get("latency_ms"), error=row.get("error"),
                    created_at=_dt(row.get("created_at")) or datetime.now(),
                    updated_at=_dt(row.get("updated_at")) or datetime.now(),
                )
            )
        # FTS 是可派生索引，和业务数据在同一事务内失效；下次检索会自动重建。
        db.execute(text("DROP TABLE IF EXISTS kb_fts"))
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {**report, "restored": True}


def drill_restore(backup: dict) -> dict:
    """在隔离数据库真正恢复并回读，绝不触碰当前业务库。"""
    expected = validate_backup(backup)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as rehearsal_db:
            restore_backup(rehearsal_db, backup)
            round_trip = build_backup(rehearsal_db)
            actual = validate_backup(round_trip)

        checked = []
        for name, expected_count in expected["counts"].items():
            actual_count = actual["counts"].get(name, 0)
            if actual_count != expected_count:
                raise BackupValidationError(
                    f"恢复演练后 {name} 数量不一致：{actual_count} != {expected_count}"
                )
            expected_ids = {row["id"] for row in (backup.get(name) or [])}
            actual_ids = {row["id"] for row in (round_trip.get(name) or [])}
            if actual_ids != expected_ids:
                raise BackupValidationError(f"恢复演练后 {name} 主键集合不一致")
            checked.append(name)
    finally:
        engine.dispose()

    return {
        **expected,
        "drill": {
            "database": "isolated-memory",
            "restored": True,
            "verified_collections": checked,
        },
    }
