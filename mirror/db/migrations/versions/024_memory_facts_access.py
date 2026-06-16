"""Memory facts access tracking: access_count, last_accessed

Revision ID: 024_memory_facts_access
Revises: 020_stage2_infrastructure
Create Date: 2026-04-27
"""
from alembic import op

revision = "024_memory_facts_access"
down_revision = "020_stage2_infrastructure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE memory_facts
          ADD COLUMN IF NOT EXISTS access_count  INTEGER DEFAULT 0 NOT NULL,
          ADD COLUMN IF NOT EXISTS last_accessed TIMESTAMPTZ
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_memory_facts_pinned
        ON memory_facts (user_id, importance DESC)
        WHERE deleted_at IS NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_memory_facts_stale
        ON memory_facts (last_accessed)
        WHERE deleted_at IS NULL AND importance > 0.1
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_memory_facts_stale")
    op.execute("DROP INDEX IF EXISTS idx_memory_facts_pinned")
    op.execute("""
        ALTER TABLE memory_facts
          DROP COLUMN IF EXISTS access_count,
          DROP COLUMN IF EXISTS last_accessed
    """)
