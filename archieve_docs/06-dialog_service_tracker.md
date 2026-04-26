# Module 06: Dialog Service — Tracker

**Спека:** `06-dialog_service_spec.md` · **Зависимости:** Modules 01–05 выполнены

---

| ID | Задача | Файлы | Верификация |
|----|--------|-------|------------|
| D-01 | `DialogState` TypedDict + `IntentResult` dataclass | `mirror/services/dialog_state.py`, `mirror/services/intent_router.py` | `python -m py_compile` |
| D-02 | `IntentRouter.classify(text)` → `IntentResult` (task_kind="intent_classify") | `mirror/services/intent_router.py` | `python -m py_compile` |
| D-03 | Реализовать узлы LangGraph: `classify_intent_node`, `check_policy_node`, `route_mode_node`, `generate_response_node` | `mirror/services/dialog_graph.py` | `python -m py_compile` |
| D-04 | Собрать граф `build_dialog_graph()` с conditional edge на `blocked` | `mirror/services/dialog_graph.py` | `python -m py_compile` |
| D-05 | `DialogService.handle(msg: UnifiedMessage) → UnifiedResponse` | `mirror/services/dialog.py` | `python -m py_compile` |
| D-06 | NATS publisher: `mirror.dialog.session.closed` | `mirror/events/publishers/dialog.py` | `python -m py_compile` |
| D-07 | Сборка контекста промпта: mem_L1 + mem_L2 + mem_L3 + system prompt | `mirror/services/dialog.py` | `python -m py_compile` |
| D-08 | `build_system_prompt()` + `get_app_config()` с кэшированием из `app_config` | `mirror/services/dialog.py` | `python -m py_compile`; `app_config['system_prompt_base']` читается из БД |
| D-08b | Вызвать `load_app_config_cache()` в lifespan FastAPI после `init_db_pool()` | `mirror/main.py` | после старта `get_app_config('system_prompt_base')` возвращает не пустую строку |
| D-09 | Тесты: intent classify, crisis block, astrology/tarot/chat routing, quota exceeded, graph exception → fallback | `tests/dialog/test_dialog.py` | `pytest tests/dialog/ -v` → PASSED |

🛑 **CHECKPOINT:** кризисный сценарий блокирует generate_response, intent routing работает для всех режимов.
