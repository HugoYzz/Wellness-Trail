"""ORM 模型（架构 §5 数据模型 + §6.4 KB 版本化）。

表清单：
- users      单用户预留（settings_json 存目标体重/Provider 配置/提醒偏好）
- records    全部记录，唯一事实源（11 类 type，fields_json 按 type 各有 schema）
- chats      会话（聊天页按天开新会话）
- messages   消息（record_id 关联经确认产生的 records，可溯源）
- chat_runs  一次用户请求的幂等状态与 SSE 事件日志
- insight_states 洞察采纳、提醒、完成与帮助度反馈
- kb_docs    知识库文档版本（源文件更新后重新导入覆盖并保留版本时间戳）
- kb_chunks  知识库块（source_plan 两代分域 + section_no 章节锚点）
- imports    迁移台账（sheet+行号幂等，防重复导入）
"""
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    settings_json: Mapped[dict] = mapped_column(JSON, default=dict)


class Record(Base):
    __tablename__ = "records"
    __table_args__ = (Index("ix_records_date_type", "date", "type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # weight/sleep/meal/sweet_drink/night_hunger/exercise/step/waist/supplement/body/note
    type: Mapped[str] = mapped_column(String(20))
    date: Mapped[date] = mapped_column(Date)
    # weight: am/evening；meal: breakfast/lunch/dinner/snack；其余为 NULL
    slot: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fields_json: Mapped[dict] = mapped_column(JSON)
    raw_text: Mapped[str] = mapped_column(Text, default="")  # 用户原话，溯源用
    source: Mapped[str] = mapped_column(String(10))  # chat/manual/import
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Chat(Base):
    __tablename__ = "chats"
    __table_args__ = (UniqueConstraint("date", name="uq_chats_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date)
    title: Mapped[str] = mapped_column(String(128), default="")  # 如"9月4日晨间复盘"
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # 长会话压缩摘要


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_chat_id", "chat_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id"))
    role: Mapped[str] = mapped_column(String(16))  # user/assistant/tool
    content: Mapped[str] = mapped_column(Text)
    record_id: Mapped[int | None] = mapped_column(
        ForeignKey("records.id"), nullable=True
    )
    token_usage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # P3：token 细分（费用统计用，旧数据为 NULL）
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_hit_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class KbDoc(Base):
    """知识库文档版本（§6.4：重新导入覆盖旧版并保留版本戳）。"""

    __tablename__ = "kb_docs"
    __table_args__ = (UniqueConstraint("title", "source_plan", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(128))  # 来源文件名
    # august_fatloss（8 月主线）/ july_health（7 月背景）
    source_plan: Mapped[str] = mapped_column(String(20))
    version: Mapped[str] = mapped_column(String(32), default="")  # 如 2026-08-30
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class KbChunk(Base):
    __tablename__ = "kb_chunks"
    __table_args__ = (
        Index("ix_kb_chunks_doc", "doc_id"),
        Index("ix_kb_chunks_source_plan", "source_plan"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("kb_docs.id"))
    title: Mapped[str] = mapped_column(String(128))  # 来源文件名（冗余，检索展示用）
    heading: Mapped[str] = mapped_column(String(256), default="")  # 所在章节标题
    source_plan: Mapped[str] = mapped_column(String(20))
    section_no: Mapped[str] = mapped_column(String(16), default="")  # 3.4/5.2/6.1…
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)  # 补剂/菜单/行动/监测/就医
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ImportLedger(Base):
    """迁移台账（§8.1：sheet+行号记入，幂等可重跑）。"""

    __tablename__ = "imports"
    __table_args__ = (UniqueConstraint("source_file", "sheet", "row_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_file: Mapped[str] = mapped_column(String(256))
    sheet: Mapped[str] = mapped_column(String(64))
    row_no: Mapped[int] = mapped_column(Integer)
    record_id: Mapped[int | None] = mapped_column(
        ForeignKey("records.id"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class InsightState(Base):
    """洞察建议的用户反馈与行动状态。

    洞察本身由实时记录计算生成；一旦用户交互，就保存当时快照，确保建议在
    原始统计窗口滚动后仍能出现在“进行中”或“历史回看”中。
    """

    __tablename__ = "insight_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    insight_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="new")
    feedback: Mapped[str | None] = mapped_column(String(20), nullable=True)
    feedback_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reminder_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    action_plan_json: Mapped[dict] = mapped_column(JSON, default=dict)
    snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class ChatRun(Base):
    """一次可重放的模型调用。

    request_key 由客户端生成并全局唯一；断线重连只读取 events_json，绝不重复
    写入用户消息。后台任务与 HTTP 流解耦，因此浏览器断线不会取消模型调用。
    """

    __tablename__ = "chat_runs"
    __table_args__ = (
        UniqueConstraint("request_key", name="uq_chat_runs_request_key"),
        Index("ix_chat_runs_chat_id", "chat_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_key: Mapped[str] = mapped_column(String(128))
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id"))
    user_message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"))
    assistant_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending")
    events_json: Mapped[list] = mapped_column(JSON, default=list)
    provider_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    usage_json: Mapped[dict] = mapped_column(JSON, default=dict)
    usage_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
