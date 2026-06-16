"""Psychology and journal: journal settings, life wheel snapshots

Revision ID: 023_psychology_journal
Revises: 020_stage2_infrastructure
Create Date: 2026-04-27
"""
from alembic import op

revision = "023_psychology_journal"
down_revision = "020_stage2_infrastructure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE user_profiles
          ADD COLUMN IF NOT EXISTS journal_evening_time          TIME DEFAULT '21:00:00',
          ADD COLUMN IF NOT EXISTS journal_notifications_enabled BOOLEAN DEFAULT TRUE NOT NULL
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS life_wheel_snapshots (
            id         BIGSERIAL PRIMARY KEY,
            user_id    UUID REFERENCES users(user_id) ON DELETE CASCADE NOT NULL,
            scores     JSONB NOT NULL
                         CHECK (
                           jsonb_typeof(scores) = 'object'
                           AND scores ?& ARRAY['work','finances','health','relationships',
                                               'growth','leisure','social','spirituality']
                         ),
            created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_life_wheel_user_time
        ON life_wheel_snapshots (user_id, created_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_life_wheel_user_time")
    op.execute("DROP TABLE IF EXISTS life_wheel_snapshots")
    op.execute("""
        ALTER TABLE user_profiles
          DROP COLUMN IF EXISTS journal_evening_time,
          DROP COLUMN IF EXISTS journal_notifications_enabled
    """)
