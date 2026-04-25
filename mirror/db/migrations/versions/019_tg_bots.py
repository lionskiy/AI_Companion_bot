"""Add tg_bots table for persistent multi-bot configuration

Revision ID: 019_tg_bots
Revises: 018_ingest_routing_seed
Create Date: 2026-04-25
"""
from alembic import op
import sqlalchemy as sa

revision = "019_tg_bots"
down_revision = "018_ingest_routing_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tg_bots",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("now()::text")),
        sa.PrimaryKeyConstraint("name"),
        sa.UniqueConstraint("tg_id"),
    )


def downgrade() -> None:
    op.drop_table("tg_bots")
