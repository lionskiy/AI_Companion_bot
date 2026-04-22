"""policy tables

Revision ID: 003_policy
Revises: 002_memory
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "003_policy"
down_revision = "002_memory"
branch_labels = None
depends_on = None

CRISIS_RESPONSE = """Я здесь, и я слышу тебя. То, что ты чувствуешь — важно.

Пожалуйста, позвони на бесплатную линию психологической помощи:
📞 8-800-2000-122 (бесплатно, круглосуточно)

Напиши мне, когда будешь готов. Я никуда не ухожу."""

REFERRAL_HINT = (
    "Если чувствуешь, что нужна поддержка живого специалиста — "
    "это нормально и правильно. Психолог поможет разобраться глубже 💙"
)


def upgrade() -> None:
    op.create_table(
        "app_config",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "safety_log",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True)),
        sa.Column("risk_level", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_safety_log_user", "safety_log", ["user_id", sa.text("created_at DESC")])

    # Seed app_config
    op.execute(
        sa.text(
            "INSERT INTO app_config (key, value, description) VALUES "
            "(:key, :value, :desc)"
        ).bindparams(
            key="crisis_response",
            value=CRISIS_RESPONSE,
            desc="Кризисный ответ с горячей линией. Не генерируется LLM.",
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO app_config (key, value, description) VALUES "
            "(:key, :value, :desc)"
        ).bindparams(
            key="referral_hint",
            value=REFERRAL_HINT,
            desc="Мягкий текст предложения живого специалиста.",
        )
    )


def downgrade() -> None:
    op.drop_table("safety_log")
    op.drop_table("app_config")
