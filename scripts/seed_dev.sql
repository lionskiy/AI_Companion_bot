-- Seed script for local development
-- Миграции уже создают llm_providers и llm_routing с дефолтными значениями.
-- Этот скрипт адаптирует их под локальный дев (только OpenAI ключ).
-- Run: psql $DATABASE_URL -f scripts/seed_dev.sql

-- crisis_classify: переключить primary на OpenAI (Anthropic ключ не задан)
UPDATE llm_routing
SET provider_id = 'openai',
    model_id = 'gpt-4o-mini',
    fallback_chain = '[]'
WHERE task_kind = 'crisis_classify';

-- Отключить anthropic провайдера пока нет ключа
UPDATE llm_providers SET is_active = false WHERE provider_id = 'anthropic';

-- App config — основной системный промпт
INSERT INTO app_config (key, value)
VALUES
    ('system_prompt_base',
     'Ты Mirror — тёплый, внимательный и мудрый AI-компаньон для самопознания. Ты помогаешь людям лучше понять себя через астрологию, Таро и искренний разговор. Отвечай по-русски, тепло и лично.')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

-- Проверка
SELECT 'providers' as t, provider_id, is_active FROM llm_providers
UNION ALL
SELECT 'routing', task_kind, true FROM llm_routing
ORDER BY t, 2;
