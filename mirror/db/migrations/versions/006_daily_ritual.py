"""daily ritual tables

Revision ID: 006_daily_ritual
Revises: 005_astrology
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "006_daily_ritual"
down_revision = "005_astrology"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_ritual_log",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("ritual_date", sa.Date, nullable=False),
        sa.Column("card_name", sa.Text),
        sa.Column("transit_info", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="'sent'"),
    )
    op.create_index("idx_ritual_log_user", "daily_ritual_log",
                    ["user_id", sa.text("ritual_date DESC")])
    op.create_index("idx_ritual_log_unique", "daily_ritual_log",
                    ["user_id", "ritual_date"], unique=True)

    op.add_column("user_profiles",
                  sa.Column("daily_ritual_enabled", sa.Boolean,
                            nullable=False, server_default="true"))


def downgrade() -> None:
    op.drop_column("user_profiles", "daily_ritual_enabled")
    op.drop_table("daily_ritual_log")
