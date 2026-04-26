# Этап 2 — Обзор и состав

**Статус:** Ready for development  
**Этап:** 2  
**Ссылка на POD:** §3.4, §3.5, §3.6, §3.7, §6, §8.3, §8.5, §9  
**Дата:** 2026-04-26

---

## Цель этапа

Расширить продукт новыми режимами диалога, улучшить качество персонализации и добавить проактивное поведение бота. После этапа 2 Mirror превращается из реактивного ассистента в живого компаньона, который помнит, замечает паттерны и сам выходит на связь.

Монетизация (Basic/Plus/Pro, приём оплаты) и новые каналы (VK/MAX) — **не входят** в этот этап, перенесены на этап 2.1 / этап 3.

---

## Состав этапа 2

| № ТЗ | Модуль | Файл спеки |
|-------|--------|-----------|
| 13 | Онбординг «Золотой момент» | 13-onboarding_golden_moment_spec.md |
| 14 | Сонник | 14-dreams_spec.md |
| 15 | Нумерология | 15-numerology_spec.md |
| 16 | Психологические режимы и дневник | 16-psychology_journal_spec.md |
| 17 | Глубокий retrieval (rerank + приоритеты памяти) | 17-deep_retrieval_spec.md |
| 18 | Проактивность (бот пишет первым) | 18-proactive_spec.md |

---

## Порядок реализации (рекомендованный)

1. **17 — Глубокий retrieval** — фундамент для всего остального; улучшает качество ответов во всех режимах
2. **16 — Дневник** — добавляет новый source_mode для памяти, нужен для сонника
3. **14 — Сонник** — использует дневник как хранилище снов
4. **15 — Нумерология** — независимый режим, можно параллельно с 14
5. **13 — Золотой момент** — требует накопленной памяти (L2/L3) и psych_profile
6. **18 — Проактивность** — требует всей инфраструктуры выше

---

## Что остаётся неизменным

- Архитектура каналов (только Telegram)
- Биллинг (только Free тариф, лимит N/день)
- Policy и кризисный протокол §3.8 — обязателен во всех новых режимах
- LLM Router — расширяется новыми task_kinds, не переписывается
- Memory Service API — расширяется, контракт не меняется

---

## Сквозные технические решения (обязательны для всех модулей)

### Расширение fact_type (миграция 020)
`memory_facts` имеет CHECK constraint: `'declared','observed','inferred','user_verified','external'`.  
Миграция 020 (первая в этапе 2) **расширяет constraint**, добавляя новые типы:
```sql
ALTER TABLE memory_facts DROP CONSTRAINT memory_facts_fact_type_check;
ALTER TABLE memory_facts ADD CONSTRAINT memory_facts_fact_type_check
  CHECK (fact_type IN (
    'declared','observed','inferred','user_verified','external',
    'dream_pattern','value','life_wheel_score','cbt_pattern','narrative_reframe','numerology'
  ));
```

### source_mode в memory_episodes (миграция 020)
Таблица `memory_episodes` не имеет поля `source_mode`. Миграция 020 добавляет его:
```sql
ALTER TABLE memory_episodes ADD COLUMN source_mode VARCHAR(30) DEFAULT 'chat';
```
Допустимые значения: `chat`, `dream`, `journal`, `journal_synthesis`, `ritual`.

### Обновление IntentRouter (миграция 020 / seed)
Новые intents: `dream`, `numerology`, `psychology`, `journal`, `reflection`.  
При обновлении — добавить в classify-промпт примеры для каждого нового intent.

### Celery Beat — динамические расписания
Для задач с индивидуальным временем пользователей (вечерняя рефлексия, daily ritual) **НЕ** использовать статический Celery Beat schedule.  
Подход: единый polling task каждые 15 минут → выбирает пользователей у которых `journal_evening_time` попадает в окно ±15 мин с учётом timezone.

### Redis key namespace (единый для всего этапа 2)
```
practice_state:{user_id}               # многошаговые практики
proactive:last_sent:{user_id}:{type}   # cooldown проактивности
proactive:daily_count:{user_id}:{date} # лимит в сутки
proactive:ignored_streak:{user_id}     # счётчик игнорирований
busy_pending:{user_id}                 # отложенное сообщение "занят"
golden_moment:score:{user_id}          # кэш readiness_score
```

### Policy §3.8 в многошаговых практиках
Если в ходе CBT/дневника/нарративной практики PolicyEngine возвращает `risk_level=crisis`:
1. Практика прерывается немедленно
2. Промежуточное Redis-состояние удаляется
3. Бот переключается на кризисный ответ (§3.8)
4. Запись в `safety_log`

---

## Acceptance Criteria этапа 2 (DoD)

- [ ] Все 6 модулей реализованы и покрыты smoke-тестами
- [ ] Каждый новый режим обрабатывает кризисные сигналы через Policy §3.8
- [ ] Новые task_kinds добавлены в таблицу `llm_routing` через миграцию/seed
- [ ] Все Alembic-миграции (020-025) созданы и применены
- [ ] Проактивность управляется командами /quiet и /active
- [ ] KB-коллекции knowledge_dreams и knowledge_numerology созданы в Qdrant и заполнены
- [ ] Золотой момент срабатывает не более 1 раза на пользователя
- [ ] memory_episodes.source_mode заполняется корректно во всех новых режимах
- [ ] fact_type CHECK constraint расширен и не блокирует запись новых типов фактов
