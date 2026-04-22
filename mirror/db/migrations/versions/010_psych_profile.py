"""psych_profile — psychological portrait fields on user_profiles

Revision ID: 010_psych_profile
Revises: 009_persona_prompts
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "010_psych_profile"
down_revision = "009_persona_prompts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("mbti_type", sa.Text(), nullable=True))
    op.add_column("user_profiles", sa.Column("attachment_style", sa.Text(), nullable=True))
    op.add_column("user_profiles", sa.Column("communication_style", sa.Text(), nullable=True))
    op.add_column("user_profiles", sa.Column("dominant_themes", JSONB(), nullable=True))
    op.add_column("user_profiles", sa.Column("profile_summary", sa.Text(), nullable=True))
    op.add_column("user_profiles", sa.Column("profile_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("user_profiles", "profile_updated_at")
    op.drop_column("user_profiles", "profile_summary")
    op.drop_column("user_profiles", "dominant_themes")
    op.drop_column("user_profiles", "communication_style")
    op.drop_column("user_profiles", "attachment_style")
    op.drop_column("user_profiles", "mbti_type")
