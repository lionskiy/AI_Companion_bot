"""Seed llm_routing for KB enrichment task_kinds + app_config keys for ingest v2

Revision ID: 018_ingest_routing_seed
Revises: 017_ingest_v2
Create Date: 2026-04-24
"""
from alembic import op
from sqlalchemy import text

revision = "018_ingest_routing_seed"
down_revision = "017_ingest_v2"
branch_labels = None
depends_on = None

_ROUTING_ROWS = [
    ("kb_enrich_context",  "*", "openai", "gpt-4o-mini",  300, 0.3),
    ("kb_enrich_metadata", "*", "openai", "gpt-4o-mini", 1000, 0.1),
]

_CONFIG_ROWS = [
    ("kb_enrichment_context",  "true",
     "Enable contextual prefix for KB ingest (prepended to each chunk before embedding)"),
    ("kb_enrichment_metadata", "true",
     "Enable keywords+category extraction for KB ingest payload"),
    ("kb_enrich_concurrency",  "4",
     "Max parallel LLM calls for enrichment stage"),
    ("kb_max_zip_size_mb",     "500",
     "Max ZIP upload size in MB"),
    ("kb_max_file_size_mb",    "100",
     "Max single file size within ZIP in MB"),
    ("kb_max_files_in_zip",    "500",
     "Max number of files per ZIP"),
    ("kb_category_list",
     '["КПТ","психоанализ","травма","отношения","детская_психология",'
     '"саморазвитие","духовность","нарратив","тревога","депрессия","другое"]',
     "JSON array of category labels for enrichment metadata classifier"),
]


def upgrade() -> None:
    conn = op.get_bind()

    for task_kind, tier, provider_id, model_id, max_tokens, temperature in _ROUTING_ROWS:
        conn.execute(
            text(
                "INSERT INTO llm_routing "
                "(task_kind, tier, provider_id, model_id, max_tokens, temperature, fallback_chain) "
                "VALUES (:tk, :t, :p, :m, :mt, :temp, '[]'::jsonb) "
                "ON CONFLICT (task_kind, tier) DO NOTHING"
            ),
            {"tk": task_kind, "t": tier, "p": provider_id,
             "m": model_id, "mt": max_tokens, "temp": temperature},
        )

    for key, value, description in _CONFIG_ROWS:
        conn.execute(
            text(
                "INSERT INTO app_config (key, value, description) "
                "VALUES (:k, :v, :d) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"k": key, "v": value, "d": description},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for task_kind, tier, *_ in _ROUTING_ROWS:
        conn.execute(
            text("DELETE FROM llm_routing WHERE task_kind=:tk AND tier=:t"),
            {"tk": task_kind, "t": tier},
        )
    for key, *_ in _CONFIG_ROWS:
        conn.execute(text("DELETE FROM app_config WHERE key=:k"), {"k": key})
