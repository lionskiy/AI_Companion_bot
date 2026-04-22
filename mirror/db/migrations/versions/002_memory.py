"""memory tables

Revision ID: 002_memory
Revises: 001_identity
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002_memory"
down_revision = "001_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "memory_episodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("qdrant_point_id", postgresql.UUID(as_uuid=True)),
        sa.Column("importance", sa.Numeric(4, 3), server_default="0.5"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True)),
    )
    op.create_index(
        "idx_memory_episodes_user",
        "memory_episodes",
        ["user_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.execute("ALTER TABLE memory_episodes ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY memory_episodes_user_isolation ON memory_episodes "
        "USING (user_id = current_setting('app.current_user_id', true)::uuid)"
    )

    op.create_table(
        "memory_facts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("fact_type", sa.Text, nullable=False),
        sa.Column("key", sa.Text, nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("importance", sa.Numeric(4, 3), server_default="0.5"),
        sa.Column("confidence", sa.Numeric(4, 3), server_default="1.0"),
        sa.Column("consent_scope", sa.Text),
        sa.Column("qdrant_point_id", postgresql.UUID(as_uuid=True)),
        sa.Column("source", sa.Text),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True)),
        sa.CheckConstraint(
            "fact_type IN ('declared','observed','inferred','user_verified','external')",
            name="memory_facts_fact_type_check",
        ),
    )
    op.create_index(
        "idx_memory_facts_user",
        "memory_facts",
        ["user_id", sa.text("importance DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_memory_facts_type",
        "memory_facts",
        ["user_id", "fact_type"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.execute("ALTER TABLE memory_facts ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY memory_facts_user_isolation ON memory_facts "
        "USING (user_id = current_setting('app.current_user_id', true)::uuid)"
    )


def downgrade() -> None:
    op.drop_table("memory_facts")
    op.drop_table("memory_episodes")
