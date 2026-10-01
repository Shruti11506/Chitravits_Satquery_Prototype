import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.fakes import FakeSupabaseClient


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
