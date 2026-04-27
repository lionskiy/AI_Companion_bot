"""Proactive messaging: proactive_log table, user_profiles settings

Revision ID: 025_proactive
Revises: 020_stage2_infrastructure
Create Date: 2026-04-27
"""
from alembic import op

revision = "025_proactive"
down_revision = "020_stage2_infrastructure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS proactive_log (
            id         BIGSERIAL PRIMARY KEY,
            user_id    UUID REFERENCES users(user_id) ON DELETE CASCADE NOT NULL,
            type       VARCHAR(50) NOT NULL,
            score      FLOAT CHECK (score >= 0.0 AND score <= 1.0),
            delivered  BOOLEAN DEFAULT FALSE NOT NULL,
            opened     BOOLEAN DEFAULT FALSE NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_proactive_log_user ON proactive_log (user_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_proactive_log_type ON proactive_log (type, created_at DESC)")

    op.execute("""
        ALTER TABLE user_profiles
          ADD COLUMN IF NOT EXISTS proactive_mode    VARCHAR(20) DEFAULT 'normal' NOT NULL
                                     CHECK (proactive_mode IN ('quiet','normal','active')),
          ADD COLUMN IF NOT EXISTS quiet_hours_start TIME DEFAULT '23:00:00',
          ADD COLUMN IF NOT EXISTS quiet_hours_end   TIME DEFAULT '08:00:00',
          ADD COLUMN IF NOT EXISTS busy_probability  FLOAT DEFAULT 0.03
                                     CHECK (busy_probability >= 0.0 AND busy_probability <= 1.0)
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE user_profiles
          DROP COLUMN IF EXISTS proactive_mode,
          DROP COLUMN IF EXISTS quiet_hours_start,
          DROP COLUMN IF EXISTS quiet_hours_end,
          DROP COLUMN IF EXISTS busy_probability
    """)
    op.execute("DROP INDEX IF EXISTS idx_proactive_log_type")
    op.execute("DROP INDEX IF EXISTS idx_proactive_log_user")
    op.execute("DROP TABLE IF EXISTS proactive_log")
