"""admin config seed

Revision ID: 008_admin_config
Revises: 007_billing
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa

revision = "008_admin_config"
down_revision = "007_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO app_config (key, value) VALUES
          ('system_prompt', 'Ты Mirror — тёплый и мудрый AI-компаньон для самопознания.'),
          ('onboarding_prompt', 'Привет! Я Mirror. Давай познакомимся.'),
          ('ritual_hour_utc', '7'),
          ('crisis_response', 'Я слышу тебя. Ты не один. Если тебе сейчас очень тяжело, обратись на горячую линию: 8-800-2000-122 (бесплатно).'),
          ('referral_hint', 'Возможно, стоит поговорить со специалистом.')
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM app_config WHERE key IN "
        "('system_prompt','onboarding_prompt','ritual_hour_utc','crisis_response','referral_hint')"
    )
