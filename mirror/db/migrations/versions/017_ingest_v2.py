"""KB Ingest v2: staging tables + ingest_jobs new columns

Revision ID: 017_ingest_v2
Revises: 016_ingest_jobs_total
Create Date: 2026-04-24
"""
from alembic import op
import sqlalchemy as sa

revision = "017_ingest_v2"
down_revision = "016_ingest_jobs_total"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── ingest_files ────────────────────────────────────────────────────────────
    op.create_table(
        "ingest_files",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("collection", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_lang", sa.Text(), nullable=False, server_default="auto"),
        sa.Column("text_path", sa.Text(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("document_context", sa.Text(), nullable=True),
        sa.Column("file_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["job_id"], ["ingest_jobs.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_ingest_files_job_id", "ingest_files", ["job_id"])
    op.create_index("idx_ingest_files_status", "ingest_files", ["file_status"])

    # ── ingest_chunks ────────────────────────────────────────────────────────────
    op.create_table(
        "ingest_chunks",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("file_id", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("keywords", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("chunk_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("qdrant_point_id", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["job_id"], ["ingest_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_id"], ["ingest_files.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_ingest_chunks_job_id", "ingest_chunks", ["job_id"])
    op.create_index("idx_ingest_chunks_file_id", "ingest_chunks", ["file_id"])
    op.create_index("idx_ingest_chunks_status", "ingest_chunks", ["chunk_status"])
    op.create_index("idx_ingest_chunks_job_status", "ingest_chunks", ["job_id", "chunk_status"])

    # ── ingest_logs ──────────────────────────────────────────────────────────────
    op.create_table(
        "ingest_logs",
        sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column("job_id", sa.Text(), nullable=True),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["job_id"], ["ingest_jobs.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_ingest_logs_job_id", "ingest_logs", ["job_id"])
    op.create_index("idx_ingest_logs_created", "ingest_logs", ["created_at"])

    # ── ALTER ingest_jobs ────────────────────────────────────────────────────────
    op.add_column("ingest_jobs", sa.Column("stage", sa.Text(), nullable=False, server_default="upload"))
    op.add_column("ingest_jobs", sa.Column("files_total", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("ingest_jobs", sa.Column("files_extracted", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("ingest_jobs", sa.Column("files_chunked", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("ingest_jobs", sa.Column("enrichment_total", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("ingest_jobs", sa.Column("enrichment_done", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("ingest_jobs", sa.Column("qdrant_upserted", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("ingest_jobs", sa.Column("tier", sa.Text(), nullable=True))
    op.add_column("ingest_jobs", sa.Column("tmp_path", sa.Text(), nullable=True))


def downgrade() -> None:
    for col in ("stage", "files_total", "files_extracted", "files_chunked",
                "enrichment_total", "enrichment_done", "qdrant_upserted", "tier", "tmp_path"):
        op.drop_column("ingest_jobs", col)

    op.drop_index("idx_ingest_logs_created")
    op.drop_index("idx_ingest_logs_job_id")
    op.drop_table("ingest_logs")

    op.drop_index("idx_ingest_chunks_job_status")
    op.drop_index("idx_ingest_chunks_status")
    op.drop_index("idx_ingest_chunks_file_id")
    op.drop_index("idx_ingest_chunks_job_id")
    op.drop_table("ingest_chunks")

    op.drop_index("idx_ingest_files_status")
    op.drop_index("idx_ingest_files_job_id")
    op.drop_table("ingest_files")
