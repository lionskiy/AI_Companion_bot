"""tg_metadata — add Telegram user metadata to channel_identities

Revision ID: 012_tg_metadata
Revises: 011_intent_log
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa

revision = "012_tg_metadata"
down_revision = "011_intent_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channel_identities", sa.Column("first_name", sa.Text(), nullable=True))
    op.add_column("channel_identities", sa.Column("last_name", sa.Text(), nullable=True))
    op.add_column("channel_identities", sa.Column("username", sa.Text(), nullable=True))
    op.add_column("channel_identities", sa.Column("is_premium", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("channel_identities", sa.Column("meta_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("channel_identities", "meta_updated_at")
    op.drop_column("channel_identities", "is_premium")
    op.drop_column("channel_identities", "username")
    op.drop_column("channel_identities", "last_name")
    op.drop_column("channel_identities", "first_name")
