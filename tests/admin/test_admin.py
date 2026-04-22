from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.asyncio(loop_scope="session")

VALID_TOKEN = "test-admin-token"


def _make_app():
    import os
    os.environ.setdefault("ADMIN_TOKEN", VALID_TOKEN)

    from fastapi import FastAPI
    from mirror.admin.router import router
    app = FastAPI()
    app.include_router(router)
    return app


# ── auth ──────────────────────────────────────────────────────────────────────

def test_missing_token_returns_422():
    app = _make_app()
    with TestClient(app) as client:
        resp = client.get("/admin/config")
    assert resp.status_code == 422


def test_wrong_token_returns_403():
    app = _make_app()
    with TestClient(app) as client:
        with patch("mirror.admin.router.settings") as mock_settings:
            mock_settings.admin_token.get_secret_value.return_value = VALID_TOKEN
            resp = client.get("/admin/config", headers={"x-admin-token": "wrong"})
    assert resp.status_code == 403


# ── schemas ───────────────────────────────────────────────────────────────────

def test_app_config_entry_schema():
    from mirror.admin.schemas import AppConfigEntry
    entry = AppConfigEntry(key="system_prompt", value="Hello")
    assert entry.key == "system_prompt"
    assert entry.value == "Hello"


def test_quota_config_view_schema():
    from mirror.admin.schemas import QuotaConfigView
    view = QuotaConfigView(tier="free", daily_messages=20, tarot_per_day=3, astrology_per_day=3)
    assert view.tier == "free"
    assert view.daily_messages == 20


def test_llm_routing_view_schema():
    from mirror.admin.schemas import LLMRoutingView
    view = LLMRoutingView(
        task_kind="main_chat",
        tier="*",
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
        fallback_chain=["gpt-4o"],
        max_tokens=1000,
        temperature=0.7,
    )
    assert view.task_kind == "main_chat"
    assert view.provider_id == "anthropic"


def test_quota_config_update_partial():
    from mirror.admin.schemas import QuotaConfigUpdate
    upd = QuotaConfigUpdate(daily_messages=50)
    assert upd.daily_messages == 50
    assert upd.tarot_per_day is None


def test_llm_routing_update_partial():
    from mirror.admin.schemas import LLMRoutingUpdate
    upd = LLMRoutingUpdate(model_id="gpt-4o-mini")
    assert upd.model_id == "gpt-4o-mini"
    assert upd.provider_id is None


def test_stats_view_schema():
    from mirror.admin.schemas import StatsView
    stats = StatsView(total_users=100, active_today=10, messages_today=500, rituals_sent_today=80)
    assert stats.total_users == 100
    assert stats.rituals_sent_today == 80


def test_user_admin_view_schema():
    from uuid import uuid4
    from mirror.admin.schemas import UserAdminView
    view = UserAdminView(
        user_id=uuid4(),
        username="test_user",
        tier="free",
        daily_ritual_enabled=True,
        created_at="2026-04-21T00:00:00+00:00",
    )
    assert view.tier == "free"
    assert view.daily_ritual_enabled is True


# ── router import ─────────────────────────────────────────────────────────────

def test_admin_router_prefix():
    from mirror.admin.router import router
    assert router.prefix == "/admin"


def test_admin_router_has_expected_routes():
    from mirror.admin.router import router
    paths = [r.path for r in router.routes]
    assert "/admin/config" in paths
    assert "/admin/quota" in paths
    assert "/admin/routing" in paths
    assert "/admin/users" in paths
    assert "/admin/stats" in paths
