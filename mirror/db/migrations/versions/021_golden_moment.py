"""Golden moment and onboarding fields

Revision ID: 021_golden_moment
Revises: 020_stage2_infrastructure
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa

revision = "021_golden_moment"
down_revision = "020_stage2_infrastructure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE user_profiles
          ADD COLUMN IF NOT EXISTS golden_moment_pending  BOOLEAN DEFAULT FALSE NOT NULL,
          ADD COLUMN IF NOT EXISTS golden_moment_shown_at TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS preferred_name         VARCHAR(100),
          ADD COLUMN IF NOT EXISTS partner_birth_date     DATE,
          ADD COLUMN IF NOT EXISTS registered_at          TIMESTAMPTZ
    """)
    # Backfill registered_at from users.created_at for existing rows
    op.execute("""
        UPDATE user_profiles up
        SET registered_at = u.created_at
        FROM users u
        WHERE up.user_id = u.user_id
          AND up.registered_at IS NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_profiles_golden_moment
        ON user_profiles (user_id)
        WHERE golden_moment_pending = TRUE
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_user_profiles_golden_moment")
    op.execute("""
        ALTER TABLE user_profiles
          DROP COLUMN IF EXISTS golden_moment_pending,
          DROP COLUMN IF EXISTS golden_moment_shown_at,
          DROP COLUMN IF EXISTS preferred_name,
          DROP COLUMN IF EXISTS partner_birth_date,
          DROP COLUMN IF EXISTS registered_at
    """)
