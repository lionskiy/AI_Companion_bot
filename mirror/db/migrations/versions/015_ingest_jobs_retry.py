"""ingest_jobs: add file_data for retry support and job_type

Revision ID: 015_ingest_jobs_retry
Revises: 014_ingest_jobs_progress
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa

revision = "015_ingest_jobs_retry"
down_revision = "014_ingest_jobs_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingest_jobs", sa.Column("file_data", sa.LargeBinary(), nullable=True))
    op.add_column("ingest_jobs", sa.Column("file_mime", sa.Text(), nullable=False, server_default=""))
    op.add_column("ingest_jobs", sa.Column("file_topic", sa.Text(), nullable=False, server_default=""))
    op.add_column("ingest_jobs", sa.Column("source_lang", sa.Text(), nullable=False, server_default="auto"))
    op.add_column("ingest_jobs", sa.Column("job_type", sa.Text(), nullable=False, server_default="file"))


def downgrade() -> None:
    for col in ("file_data", "file_mime", "file_topic", "source_lang", "job_type"):
        op.drop_column("ingest_jobs", col)
