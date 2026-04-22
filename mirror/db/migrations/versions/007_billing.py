"""billing tables

Revision ID: 007_billing
Revises: 006_daily_ritual
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa

revision = "007_billing"
down_revision = "006_daily_ritual"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quota_config",
        sa.Column("id", sa.Integer, sa.Identity(always=True), primary_key=True),
        sa.Column("tier", sa.Text, nullable=False, unique=True),
        sa.Column("daily_messages", sa.Integer, nullable=False),
        sa.Column("tarot_per_day", sa.Integer, nullable=False),
        sa.Column("astrology_per_day", sa.Integer, nullable=False),
    )

    op.execute(
        "INSERT INTO quota_config (tier, daily_messages, tarot_per_day, astrology_per_day) "
        "VALUES ('free', 20, 3, 3), ('pro', 200, 30, 30)"
    )


def downgrade() -> None:
    op.drop_table("quota_config")
