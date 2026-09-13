"""message_token_breakdown

Revision ID: 10d493fadae4
Revises: 271fb9261753
Create Date: 2026-09-04 22:20:08.591806

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '10d493fadae4'
down_revision: Union[str, Sequence[str], None] = '271fb9261753'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 注：kb_fts* 为 FTS5 运行时倒排表（ensure_fts 管理），不入迁移
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('prompt_tokens', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('completion_tokens', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('cache_hit_tokens', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_column('cache_hit_tokens')
        batch_op.drop_column('completion_tokens')
        batch_op.drop_column('prompt_tokens')
