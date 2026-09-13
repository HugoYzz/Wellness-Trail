"""insight feedback loop

Revision ID: 7c1a3f29d810
Revises: 10d493fadae4
Create Date: 2026-09-12 18:10:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7c1a3f29d810"
down_revision: Union[str, Sequence[str], None] = "10d493fadae4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "insight_states" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "insight_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("insight_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("feedback", sa.String(length=20), nullable=True),
        sa.Column("feedback_reason", sa.String(length=128), nullable=True),
        sa.Column("reminder_at", sa.DateTime(), nullable=True),
        sa.Column("action_plan_json", sa.JSON(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("insight_states", schema=None) as batch_op:
        batch_op.create_index(
            "ix_insight_states_insight_key", ["insight_key"], unique=True
        )


def downgrade() -> None:
    with op.batch_alter_table("insight_states", schema=None) as batch_op:
        batch_op.drop_index("ix_insight_states_insight_key")
    op.drop_table("insight_states")
