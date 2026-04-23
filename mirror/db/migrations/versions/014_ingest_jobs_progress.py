"""ingest_jobs: add chunks_done progress tracking

Revision ID: 014_ingest_jobs_progress
Revises: 013_ingest_jobs
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa

revision = "014_ingest_jobs_progress"
down_revision = "013_ingest_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingest_jobs", sa.Column("chunks_done", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("ingest_jobs", "chunks_done")
