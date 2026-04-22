"""identity: users, channel_identities, user_profiles, subscriptions

Revision ID: 001
Revises:
Create Date: 2026-04-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "001_identity"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("subscription", sa.Text(), nullable=False, server_default="free"),
        sa.Column("is_tester", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("timezone", sa.Text(), nullable=False, server_default="Europe/Moscow"),
        sa.Column("language_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint("subscription IN ('free','basic','plus','pro')", name="users_subscription_check"),
    )

    op.create_table(
        "channel_identities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("channel_user_id", sa.Text(), nullable=False),
        sa.Column("global_user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("linked_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["global_user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("channel", "channel_user_id", name="uq_channel_identities"),
        sa.CheckConstraint("channel IN ('telegram','vk','whatsapp','web','mobile')", name="channel_identities_channel_check"),
    )
    op.create_index("idx_channel_identities_global", "channel_identities", ["global_user_id"])

    op.create_table(
        "user_profiles",
        sa.Column("user_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False, server_default="free"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.CheckConstraint("tier IN ('free','basic','plus','pro')", name="subscriptions_tier_check"),
    )
    op.create_index(
        "idx_subscriptions_active_user",
        "subscriptions", ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    op.drop_table("subscriptions")
    op.drop_table("user_profiles")
    op.drop_index("idx_channel_identities_global", table_name="channel_identities")
    op.drop_table("channel_identities")
    op.drop_table("users")
