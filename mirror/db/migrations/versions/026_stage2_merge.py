"""Merge Stage 2 parallel heads into a single head.

Revision ID: 026_stage2_merge
Revises: 021_golden_moment, 022_numerology, 023_psychology_journal, 024_memory_facts_access, 025_proactive
Create Date: 2026-04-27
"""
from alembic import op

revision = "026_stage2_merge"
down_revision = (
    "021_golden_moment",
    "022_numerology",
    "023_psychology_journal",
    "024_memory_facts_access",
    "025_proactive",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
