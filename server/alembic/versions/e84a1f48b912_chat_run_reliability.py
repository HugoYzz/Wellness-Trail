"""chat run reliability and per-run usage

Revision ID: e84a1f48b912
Revises: 7c1a3f29d810
Create Date: 2026-09-13 10:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e84a1f48b912"
down_revision: Union[str, Sequence[str], None] = "7c1a3f29d810"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "chat_runs" not in inspector.get_table_names():
        op.create_table(
            "chat_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("request_key", sa.String(length=128), nullable=False),
            sa.Column("chat_id", sa.Integer(), nullable=False),
            sa.Column("user_message_id", sa.Integer(), nullable=False),
            sa.Column("assistant_message_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("events_json", sa.JSON(), nullable=False),
            sa.Column("provider_id", sa.String(length=32), nullable=True),
            sa.Column("provider_model", sa.String(length=128), nullable=True),
            sa.Column("usage_json", sa.JSON(), nullable=False),
            sa.Column("usage_source", sa.String(length=16), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["assistant_message_id"], ["messages.id"]),
            sa.ForeignKeyConstraint(["chat_id"], ["chats.id"]),
            sa.ForeignKeyConstraint(["user_message_id"], ["messages.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("request_key", name="uq_chat_runs_request_key"),
        )
        op.create_index("ix_chat_runs_chat_id", "chat_runs", ["chat_id"])

    chat_indexes = {item["name"] for item in sa.inspect(bind).get_indexes("chats")}
    if "uq_chats_date" not in chat_indexes:
        # 早期版本可能因重复打开页面留下同日空会话。保留最早会话，
        # 把消息和已有运行记录并入后再建立唯一索引。
        bind.execute(
            sa.text(
                "UPDATE messages SET chat_id = ("
                "SELECT MIN(c2.id) FROM chats c2 "
                "WHERE c2.date = (SELECT c1.date FROM chats c1 WHERE c1.id = messages.chat_id)"
                ") WHERE chat_id IN ("
                "SELECT id FROM chats WHERE date IN (SELECT date FROM chats GROUP BY date HAVING COUNT(*) > 1)"
                ")"
            )
        )
        if "chat_runs" in sa.inspect(bind).get_table_names():
            bind.execute(
                sa.text(
                    "UPDATE chat_runs SET chat_id = ("
                    "SELECT MIN(c2.id) FROM chats c2 "
                    "WHERE c2.date = (SELECT c1.date FROM chats c1 WHERE c1.id = chat_runs.chat_id)"
                    ") WHERE chat_id IN ("
                    "SELECT id FROM chats WHERE date IN (SELECT date FROM chats GROUP BY date HAVING COUNT(*) > 1)"
                    ")"
                )
            )
        bind.execute(
            sa.text(
                "DELETE FROM chats WHERE id NOT IN (SELECT MIN(id) FROM chats GROUP BY date)"
            )
        )
        op.create_index("uq_chats_date", "chats", ["date"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    chat_indexes = {item["name"] for item in inspector.get_indexes("chats")}
    if "uq_chats_date" in chat_indexes:
        op.drop_index("uq_chats_date", table_name="chats")
    if "chat_runs" in inspector.get_table_names():
        op.drop_index("ix_chat_runs_chat_id", table_name="chat_runs")
        op.drop_table("chat_runs")
