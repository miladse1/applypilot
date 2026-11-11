"""Security controls: host checking, headers, sign-in limits, sessions, AI limits, data location."""

import hashlib
from datetime import datetime, timezone

import pytest

from app.core.config import Settings, data_home
from app.core.database import SessionLocal
from app.models import AIUsage, SessionToken
from app.services.ai import AIRateLimited, BudgetExceeded, ai_scope, enforce_ai_limits

PASSWORD = "correct-horse"


def _register(client, email="sam@example.com", password=PASSWORD):
    return client.post("/api/v1/auth/register", json={"email": email, "password": password, "full_name": "Sam Rivera"})


# ------------------------------------------------------------------ transport

def test_unknown_host_is_refused(client):
    # A web page that rebinds its own domain to 127.0.0.1 still sends its own Host header.
    response = client.get("/api/v1/health", headers={"host": "attacker.example"})
    assert response.status_code == 400


def test_api_responses_carry_security_headers(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in response.headers["content-security-policy"]


def test_cors_rejects_other_origins(client):
    response = client.options(
        "/api/v1/auth/me",
        headers={"origin": "https://attacker.example", "access-control-request-method": "GET"},
    )
    assert "access-control-allow-origin" not in response.headers


# ------------------------------------------------------------------ accounts and sessions

def test_session_tokens_are_stored_hashed(client):
    token = _register(client).json()["session_token"]
    with SessionLocal() as db:
        stored = db.query(SessionToken).one()
    assert stored.token_hash != token
    assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()


def test_registration_is_rate_limited(client):
    statuses = [_register(client, email=f"user{i}@example.com").status_code for i in range(11)]
    assert statuses[:10] == [201] * 10
    assert statuses[10] == 429


def test_registration_closes_after_the_first_account(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "allow_registration", False)
    assert _register(client, email="owner@example.com").status_code == 201
    second = _register(client, email="someone@example.com")
    assert second.status_code == 403
    assert second.json()["detail"]["code"] == "registration_closed"
    # The owner can still sign in.
    assert client.post("/api/v1/auth/login", json={"email": "owner@example.com", "password": PASSWORD}).status_code == 200


def test_failed_sign_ins_are_rate_limited(client):
    _register(client)
    for _ in range(20):
        assert client.post("/api/v1/auth/login", json={"email": "sam@example.com", "password": "wrong-password"}).status_code == 401
    # Even the right password waits out the lockout window.
    assert client.post("/api/v1/auth/login", json={"email": "sam@example.com", "password": PASSWORD}).status_code == 429


def test_unknown_email_and_wrong_password_look_the_same(client):
    _register(client)
    unknown = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever-123"})
    wrong = client.post("/api/v1/auth/login", json={"email": "sam@example.com", "password": "whatever-123"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_oversized_password_is_refused_before_hashing(client):
    response = client.post("/api/v1/auth/login", json={"email": "sam@example.com", "password": "x" * 10_000})
    assert response.status_code == 422


def test_password_change_signs_out_other_sessions(client):
    first = _register(client).json()["session_token"]
    second = client.post("/api/v1/auth/login", json={"email": "sam@example.com", "password": PASSWORD}).json()["session_token"]
    changed = client.post(
        "/api/v1/auth/password-change",
        json={"current_password": PASSWORD, "new_password": "a-new-long-password"},
        headers={"Authorization": f"Bearer {second}"},
    )
    assert changed.status_code == 200
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {first}"}).status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {second}"}).status_code == 200


def test_session_token_is_not_returned_to_other_endpoints(client):
    token = _register(client).json()["session_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert token not in str(me)
    assert "password_hash" not in str(me)


# ------------------------------------------------------------------ AI cost and abuse limits

def _settings(**overrides):
    return Settings(_env_file=None, ai_provider="none", **overrides)


def test_ai_requests_are_rate_limited_per_user(client):
    settings = _settings(ai_requests_per_minute=3, ai_requests_per_hour=100)
    with ai_scope("user-1", "test"):
        for _ in range(3):
            enforce_ai_limits(settings)
        with pytest.raises(AIRateLimited):
            enforce_ai_limits(settings)
    # Another user has their own allowance.
    with ai_scope("user-2", "test"):
        enforce_ai_limits(settings)


def test_background_ai_work_is_rate_limited_too(client):
    settings = _settings(ai_requests_per_minute=2, ai_requests_per_hour=100)
    enforce_ai_limits(settings)
    enforce_ai_limits(settings)
    with pytest.raises(AIRateLimited):
        enforce_ai_limits(settings)


def test_monthly_ceiling_covers_all_users_and_background_work(client):
    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        db.add(AIUsage(user_id=None, feature="posting_extraction", model="claude-haiku-5-5", cost_usd=6.0, created_at=now))
        db.add(AIUsage(user_id="user-1", feature="resume_tailoring", model="claude-sonnet-5-5", cost_usd=5.0, created_at=now))
        db.commit()
    with ai_scope("user-2", "test"), pytest.raises(BudgetExceeded):
        enforce_ai_limits(_settings(ai_monthly_limit_usd=10.0))
    enforce_ai_limits(_settings(ai_monthly_limit_usd=20.0))


# ------------------------------------------------------------------ private data location

def test_private_data_defaults_to_the_data_folder(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("STORAGE_DIR", raising=False)
    settings = Settings(_env_file=None)
    home = str(data_home())
    assert settings.database_url == f"sqlite:///{home}/applypilot.db"
    assert settings.storage_dir == f"{home}/storage"
    # Never inside the repository.
    repo = str(__import__("pathlib").Path(__file__).resolve().parents[3])
    assert not settings.database_url.removeprefix("sqlite:///").startswith(repo)
