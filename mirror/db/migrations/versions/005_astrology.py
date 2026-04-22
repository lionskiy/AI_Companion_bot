"""astrology columns

Revision ID: 005_astrology
Revises: 004_llm_routing
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "005_astrology"
down_revision = "004_llm_routing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("birth_date", sa.Date))
    op.add_column("user_profiles", sa.Column("birth_time", sa.Time))
    op.add_column("user_profiles", sa.Column("birth_city", sa.Text))
    op.add_column("user_profiles", sa.Column("birth_lat", sa.Numeric(9, 6)))
    op.add_column("user_profiles", sa.Column("birth_lon", sa.Numeric(9, 6)))
    op.add_column("user_profiles", sa.Column("zodiac_sign", sa.Text))
    op.add_column("user_profiles", sa.Column("natal_data", postgresql.JSONB))


def downgrade() -> None:
    op.drop_column("user_profiles", "natal_data")
    op.drop_column("user_profiles", "zodiac_sign")
    op.drop_column("user_profiles", "birth_lon")
    op.drop_column("user_profiles", "birth_lat")
    op.drop_column("user_profiles", "birth_city")
    op.drop_column("user_profiles", "birth_time")
    op.drop_column("user_profiles", "birth_date")
