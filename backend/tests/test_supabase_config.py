"""A fresh clone's usual setup mistakes must fail loudly, never as an empty history."""
import base64
import json

import pytest

from app.core.config import Settings
from app.db import supabase as supabase_module
from app.db.supabase import NOT_CONFIGURED_MESSAGE, WRONG_KEY_MESSAGE, secret_key_kind, supabase_config_problem


def _jwt(role: str) -> str:
    def part(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{part({'alg': 'HS256'})}.{part({'role': role, 'iss': 'supabase'})}.signature"


@pytest.mark.parametrize(
    "key, kind",
    [
        ("sb_secret_abc123", "secret"),
        ("sb_publishable_abc123", "publishable"),
        (_jwt("service_role"), "service_role"),
        (_jwt("anon"), "anon"),
        ("not-a-key", "unknown"),
    ],
)
def test_secret_key_kind(key, kind):
    assert secret_key_kind(key) == kind


def _settings(url="https://example.supabase.co", key="sb_secret_x"):
    return Settings(_env_file=None, SUPABASE_URL=url, SUPABASE_SECRET_KEY=key)


@pytest.mark.parametrize(
    "url, key, problem",
    [
        ("", "", NOT_CONFIGURED_MESSAGE),
        ("YOUR_SUPABASE_PROJECT_URL", "YOUR_SUPABASE_SECRET_KEY", NOT_CONFIGURED_MESSAGE),  # copied template
        ("https://example.supabase.co", "sb_publishable_x", WRONG_KEY_MESSAGE),
        ("https://example.supabase.co", _jwt("anon"), WRONG_KEY_MESSAGE),
        ("https://example.supabase.co", "sb_secret_x", None),
        ("https://example.supabase.co", _jwt("service_role"), None),
    ],
)
def test_supabase_config_problem(url, key, problem):
    assert supabase_config_problem(_settings(url, key)) == problem


@pytest.fixture
def real_get_supabase(monkeypatch):
    """Undo conftest's fake client for one test, with the given settings."""

    def use(settings):
        monkeypatch.setattr(supabase_module, "get_settings", lambda: settings)
        supabase_module.get_supabase.cache_clear()
        return supabase_module.get_supabase

    yield use
    supabase_module.get_supabase.cache_clear()


def test_publishable_key_is_refused_not_read_as_empty(real_get_supabase):
    get_supabase = real_get_supabase(_settings(key="sb_publishable_x"))
    with pytest.raises(supabase_module.SupabaseNotConfiguredError) as raised:
        get_supabase()
    assert raised.value.status_code == 503 and raised.value.code == "SUPABASE_NOT_CONFIGURED"


def test_health_reports_not_configured(client, monkeypatch):
    def not_configured():
        raise supabase_module.SupabaseNotConfiguredError(NOT_CONFIGURED_MESSAGE)

    monkeypatch.setattr("app.api.routes.health.get_supabase", not_configured)
    body = client.get("/api/v1/health/supabase").json()
    assert body["success"] is False
    assert body["data"]["supabase"] == "not_configured"
    assert body["error"] == {"code": "SUPABASE_NOT_CONFIGURED", "message": NOT_CONFIGURED_MESSAGE, "details": None}
