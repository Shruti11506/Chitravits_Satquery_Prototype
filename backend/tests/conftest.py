import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.fakes import FakeSupabaseClient


@pytest.fixture(autouse=True)
def _agent_disabled_by_default(monkeypatch):
    """Force the agent bridge OFF for the existing suite.

    These tests assert the agent-OFF contract (a created job stays "queued"
    until a future AI layer picks it up). The `AGENT_ENABLED` flag defaults
    false in code, but a developer's local ``backend/.env`` may turn it on for
    manual end-to-end testing; without this, that local setting would leak into
    the test process (config reads backend/.env) and make these contract tests
    non-deterministic. Tests that exercise the agent-ON path set the flag
    explicitly (see tests/test_agent_bridge.py).
    """
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "AGENT_ENABLED", False, raising=False)


@pytest.fixture
def fake_supabase(monkeypatch):
    fake = FakeSupabaseClient()

    monkeypatch.setattr("app.api.routes.health.get_supabase", lambda: fake)
    monkeypatch.setattr("app.api.routes.imagery.get_supabase", lambda: fake)
    monkeypatch.setattr("app.services.imagery_service.get_supabase", lambda: fake)
    monkeypatch.setattr("app.services.job_service.get_supabase", lambda: fake)
    monkeypatch.setattr("app.services.conversation_service.get_supabase", lambda: fake)
    monkeypatch.setattr("app.services.result_service.get_supabase", lambda: fake)
    monkeypatch.setattr("app.services.profile_service.get_supabase", lambda: fake)
    monkeypatch.setattr("app.services.settings_service.get_supabase", lambda: fake)
    monkeypatch.setattr("app.services.project_service.get_supabase", lambda: fake)
    monkeypatch.setattr("app.services.report_service.get_supabase", lambda: fake)

    return fake


@pytest.fixture
def client(fake_supabase):
    return TestClient(app)
