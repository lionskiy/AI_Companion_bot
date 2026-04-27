"""Numerology: life_path_number in user_profiles

Revision ID: 022_numerology
Revises: 020_stage2_infrastructure
Create Date: 2026-04-27
"""
from alembic import op

revision = "022_numerology"
down_revision = "020_stage2_infrastructure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE user_profiles
          ADD COLUMN IF NOT EXISTS life_path_number SMALLINT
            CHECK (life_path_number IS NULL OR life_path_number IN (
              1,2,3,4,5,6,7,8,9,11,22,33
            ))
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE user_profiles DROP COLUMN IF EXISTS life_path_number")
