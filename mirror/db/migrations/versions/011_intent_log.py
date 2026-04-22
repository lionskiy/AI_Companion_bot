"""intent_log — tracks per-message intents for dashboard analytics

Revision ID: 011_intent_log
Revises: 010_psych_profile
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "011_intent_log"
down_revision = "010_psych_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "intent_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("intent", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False, server_default="free"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_intent_log_user_date", "intent_log", ["user_id", "created_at"])
    op.create_index("idx_intent_log_intent_date", "intent_log", ["intent", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_intent_log_intent_date")
    op.drop_index("idx_intent_log_user_date")
    op.drop_table("intent_log")
