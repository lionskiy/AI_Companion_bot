"""ingest_jobs: add chunks_total for X/N progress display

Revision ID: 016_ingest_jobs_total
Revises: 015_ingest_jobs_retry
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa

revision = "016_ingest_jobs_total"
down_revision = "015_ingest_jobs_retry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingest_jobs", sa.Column("chunks_total", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("ingest_jobs", "chunks_total")
