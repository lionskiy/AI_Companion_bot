"""ingest_jobs — tracks background KB ingestion tasks

Revision ID: 013_ingest_jobs
Revises: 012_tg_metadata
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa

revision = "013_ingest_jobs"
down_revision = "012_tg_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingest_jobs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("collection", sa.Text(), nullable=False),
        sa.Column("chunks_added", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_ingest_jobs_created", "ingest_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_ingest_jobs_created")
    op.drop_table("ingest_jobs")
