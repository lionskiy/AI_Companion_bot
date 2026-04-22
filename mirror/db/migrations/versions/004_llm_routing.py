"""llm routing tables

Revision ID: 004_llm_routing
Revises: 003_policy
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa

revision = "004_llm_routing"
down_revision = "003_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_providers",
        sa.Column("provider_id", sa.Text, primary_key=True),
        sa.Column("base_url", sa.Text),
        sa.Column("api_key_env", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
    )

    op.create_table(
        "llm_routing",
        sa.Column("task_kind", sa.Text, nullable=False),
        sa.Column("tier", sa.Text, nullable=False, server_default="*"),
        sa.Column("provider_id", sa.Text, sa.ForeignKey("llm_providers.provider_id"), nullable=False),
        sa.Column("model_id", sa.Text, nullable=False),
        sa.Column("fallback_chain", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("max_tokens", sa.Integer, nullable=False, server_default="1000"),
        sa.Column("temperature", sa.Numeric(3, 2), nullable=False, server_default="0.7"),
        sa.PrimaryKeyConstraint("task_kind", "tier"),
    )

    # Seed providers
    op.execute(
        "INSERT INTO llm_providers (provider_id, base_url, api_key_env, is_active) VALUES "
        "('openai', NULL, 'OPENAI_API_KEY', true), "
        "('anthropic', NULL, 'ANTHROPIC_API_KEY', true)"
    )

    # Seed routing (12 canonical task_kinds)
    op.execute("""
        INSERT INTO llm_routing (task_kind, tier, provider_id, model_id, fallback_chain) VALUES
        ('main_chat',            '*', 'openai',    'gpt-4o-mini',            '[{"provider_id":"anthropic","model_id":"claude-haiku-4-5-20251001"}]'),
        ('main_chat_premium',    '*', 'openai',    'gpt-4o',                 '[{"provider_id":"anthropic","model_id":"claude-sonnet-4-6"}]'),
        ('intent_classify',      '*', 'openai',    'gpt-4o-mini',            '[{"provider_id":"anthropic","model_id":"claude-haiku-4-5-20251001"}]'),
        ('crisis_classify',      '*', 'anthropic', 'claude-sonnet-4-6',      '[{"provider_id":"openai","model_id":"gpt-4o"}]'),
        ('memory_summarize',     '*', 'openai',    'gpt-4o-mini',            '[{"provider_id":"anthropic","model_id":"claude-haiku-4-5-20251001"}]'),
        ('memory_extract_facts', '*', 'openai',    'gpt-4o-mini',            '[{"provider_id":"anthropic","model_id":"claude-haiku-4-5-20251001"}]'),
        ('tarot_interpret',      '*', 'openai',    'gpt-4o-mini',            '[{"provider_id":"anthropic","model_id":"claude-haiku-4-5-20251001"}]'),
        ('astro_interpret',      '*', 'openai',    'gpt-4o-mini',            '[{"provider_id":"anthropic","model_id":"claude-haiku-4-5-20251001"}]'),
        ('game_narration',       '*', 'openai',    'gpt-4o',                 '[{"provider_id":"anthropic","model_id":"claude-sonnet-4-6"}]'),
        ('proactive_compose',    '*', 'openai',    'gpt-4o-mini',            '[{"provider_id":"anthropic","model_id":"claude-haiku-4-5-20251001"}]'),
        ('persona_evolve',       '*', 'openai',    'gpt-4o-mini',            '[{"provider_id":"anthropic","model_id":"claude-haiku-4-5-20251001"}]'),
        ('embedding',            '*', 'openai',    'text-embedding-3-large', '[]')
    """)


def downgrade() -> None:
    op.drop_table("llm_routing")
    op.drop_table("llm_providers")
