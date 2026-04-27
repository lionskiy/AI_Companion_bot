"""Stage 2 infrastructure: fact_type expansion, source_mode, llm_routing seed

Revision ID: 020_stage2_infrastructure
Revises: 019_tg_bots
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa

revision = "020_stage2_infrastructure"
down_revision = "019_tg_bots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Expand fact_type CHECK constraint in memory_facts
    op.execute("ALTER TABLE memory_facts DROP CONSTRAINT IF EXISTS memory_facts_fact_type_check")
    op.execute("""
        ALTER TABLE memory_facts ADD CONSTRAINT memory_facts_fact_type_check
        CHECK (fact_type IN (
            'declared','observed','inferred','user_verified','external',
            'dream_pattern','value','life_wheel_score','cbt_pattern',
            'narrative_reframe','numerology','psych_profile'
        ))
    """)

    # 2. Add source_mode to memory_episodes
    op.execute("""
        ALTER TABLE memory_episodes
        ADD COLUMN IF NOT EXISTS source_mode VARCHAR(30) DEFAULT 'chat'
        CHECK (source_mode IN ('chat','dream','journal','journal_reflection','journal_synthesis','ritual'))
    """)

    # 3. Seed new llm_routing rows for Stage 2 task_kinds
    op.execute("""
        INSERT INTO llm_routing (task_kind, provider, model, max_tokens, temperature, fallback_chain)
        VALUES
          ('dream_extract_symbols',    'openai', 'gpt-4o-mini', 500,  0.0, '["gpt-4o-mini"]'),
          ('dream_interpret',          'openai', 'gpt-4o',      1500, 0.8, '["gpt-4o","gpt-4o-mini"]'),
          ('numerology_interpret',     'openai', 'gpt-4o-mini', 1000, 0.7, '["gpt-4o-mini"]'),
          ('psychology_cbt',           'openai', 'gpt-4o',      1500, 0.7, '["gpt-4o","gpt-4o-mini"]'),
          ('psychology_values',        'openai', 'gpt-4o-mini', 1000, 0.7, '["gpt-4o-mini"]'),
          ('psychology_narrative',     'openai', 'gpt-4o',      1500, 0.8, '["gpt-4o","gpt-4o-mini"]'),
          ('life_wheel',               'openai', 'gpt-4o-mini', 1000, 0.6, '["gpt-4o-mini"]'),
          ('journal_analyze',          'openai', 'gpt-4o-mini', 800,  0.5, '["gpt-4o-mini"]'),
          ('journal_monthly_synthesis','openai', 'gpt-4o',      2000, 0.7, '["gpt-4o","gpt-4o-mini"]'),
          ('golden_moment',            'openai', 'gpt-4o',      1500, 0.9, '["gpt-4o","gpt-4o-mini"]'),
          ('onboarding_question',      'openai', 'gpt-4o-mini', 300,  0.7, '["gpt-4o-mini"]'),
          ('rerank',                   'openai', 'gpt-4o-mini', 500,  0.0, '["gpt-4o-mini"]'),
          ('proactive_compose',        'openai', 'gpt-4o-mini', 500,  0.8, '["gpt-4o-mini"]'),
          ('proactive_return',         'openai', 'gpt-4o-mini', 500,  0.8, '["gpt-4o-mini"]')
        ON CONFLICT (task_kind) DO NOTHING
    """)

    # 4. Seed new app_config entries
    op.execute("""
        INSERT INTO app_config (key, value) VALUES
          ('reranker_type',                'disabled'),
          ('max_memory_tokens',            '1500'),
          ('pinned_importance_threshold',  '0.85'),
          ('fact_dedup_threshold',         '0.92'),
          ('proactive_score_threshold',    '0.5'),
          ('proactive_daily_limit',        '2')
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE memory_facts DROP CONSTRAINT IF EXISTS memory_facts_fact_type_check")
    op.execute("""
        ALTER TABLE memory_facts ADD CONSTRAINT memory_facts_fact_type_check
        CHECK (fact_type IN ('declared','observed','inferred','user_verified','external'))
    """)
    op.execute("ALTER TABLE memory_episodes DROP COLUMN IF EXISTS source_mode")
