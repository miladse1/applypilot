"""Model routing, cost estimates, spending limits, and result caching. No network calls."""

from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.core.database import SessionLocal
from app.models import AIUsage, User
from app.services import ai
from app.services.ai import AnthropicProvider, BudgetExceeded, ai_scope, estimate_cost, get_provider


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, ai_provider="anthropic", anthropic_api_key="sk-test", **overrides)


class FakeMessages:
    def __init__(self, log: list, text: str = '{"ok": true}'):
        self.log = log
        self.text = text

    def create(self, **kwargs):
        self.log.append(kwargs)
        usage = SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        return SimpleNamespace(
            model=kwargs["model"],
            stop_reason="end_turn",
            usage=usage,
            content=[SimpleNamespace(type="text", text=self.text)],
            _request_id="req_test",
        )


def _fake_client(provider: AnthropicProvider) -> dict:
    calls = {"plain": [], "beta": []}
    provider.client = SimpleNamespace(messages=FakeMessages(calls["plain"]), beta=SimpleNamespace(messages=FakeMessages(calls["beta"])))
    return calls


def _user_id(client, auth_header) -> str:
    return client.get("/api/v1/auth/me", headers=auth_header).json()["id"]


def test_cost_estimates_use_published_prices():
    assert estimate_cost("claude-sonnet-5-5", 1_000_000, 0) == pytest.approx(2.00)
    assert estimate_cost("claude-sonnet-5-5", 0, 1_000_000) == pytest.approx(10.00)
    assert estimate_cost("claude-haiku-5-5", 10_000, 2_000) == pytest.approx(0.002)
    assert estimate_cost("claude-opus-5-5", 10_000, 2_000) == pytest.approx(0.08)
    # Cache reads cost a tenth of input; writes cost 1.25x.
    assert estimate_cost("claude-sonnet-5-5", 0, 0, cache_read=1_000_000) == pytest.approx(0.20)
    assert estimate_cost("claude-sonnet-5-5", 0, 0, cache_write=1_000_000) == pytest.approx(2.50)
    # Haiku prompts over 100K tokens are billed at the higher tier.
    assert estimate_cost("claude-haiku-5-5", 200_000, 0) == pytest.approx(0.10)


def test_models_are_routed_by_tier_and_preference(client, auth_header):
    settings = _settings()
    assert get_provider(settings, tier="fast").model == "claude-haiku-5-5"
    assert get_provider(settings).model == "claude-sonnet-5-5"
    user_id = _user_id(client, auth_header)
    client.put("/api/v1/ai/settings", headers=auth_header, json={"quality_model": "opus"})
    with ai_scope(user_id, "resume_tailoring"):
        assert get_provider(settings).model == "claude-opus-5-5"
        assert get_provider(settings, tier="fast").model == "claude-haiku-5-5"


def test_haiku_skips_fallbacks_and_usage_is_recorded(client, auth_header):
    user_id = _user_id(client, auth_header)
    settings = _settings()
    with ai_scope(user_id, "resume_extraction"):
        fast = get_provider(settings, tier="fast")
        calls = _fake_client(fast)
        fast.structured(system="s", user="u", schema={"type": "object"})
    assert len(calls["plain"]) == 1 and not calls["beta"]
    with ai_scope(user_id, "resume_tailoring"):
        quality = get_provider(settings)
        calls = _fake_client(quality)
        quality.structured(system="s", user="u", schema={"type": "object"})
    assert len(calls["beta"]) == 1 and calls["beta"][0]["fallbacks"] == "default"
    with SessionLocal() as db:
        rows = db.query(AIUsage).filter(AIUsage.user_id == user_id).all()
    assert {(row.feature, row.model) for row in rows} == {("resume_extraction", "claude-haiku-5-5"), ("resume_tailoring", "claude-sonnet-5-5")}
    usage = client.get("/api/v1/ai/usage", headers=auth_header).json()
    expected = estimate_cost("claude-haiku-5-5", 1000, 200) + estimate_cost("claude-sonnet-5-5", 1000, 200)
    assert usage["totals"]["all_time"]["requests"] == 2
    assert usage["totals"]["all_time"]["cost_usd"] == pytest.approx(round(expected, 6))
    assert {item["feature"] for item in usage["by_feature"]} == {"resume_extraction", "resume_tailoring"}


def test_spending_limit_blocks_requests(client, auth_header):
    user_id = _user_id(client, auth_header)
    assert client.put("/api/v1/ai/settings", headers=auth_header, json={"spend_limit_usd": 0.01}).json()["spend_limit_usd"] == 0.01
    with SessionLocal() as db:
        db.add(AIUsage(user_id=user_id, feature="assistant", model="claude-sonnet-5-5", cost_usd=0.02, ok=True, created_at=ai.datetime.now(ai.timezone.utc)))
        db.commit()
    with ai_scope(user_id, "assistant"):
        provider = get_provider(_settings())
        calls = _fake_client(provider)
        with pytest.raises(BudgetExceeded):
            provider.structured(system="s", user="u", schema={"type": "object"})
    assert not calls["plain"] and not calls["beta"]
    usage = client.get("/api/v1/ai/usage", headers=auth_header).json()
    assert usage["limit_reached"] and usage["remaining_usd"] == 0
    assert client.put("/api/v1/ai/settings", headers=auth_header, json={"quality_model": "gpt"}).status_code == 400


def test_identical_requests_reuse_cached_result(client, auth_header):
    user_id = _user_id(client, auth_header)
    with ai_scope(user_id, "cover_letter"):
        provider = get_provider(_settings())
        calls = _fake_client(provider)
        first = provider.structured(system="s", user="same", schema={"type": "object"}, cache=True)
        second = provider.structured(system="s", user="same", schema={"type": "object"}, cache=True)
        provider.structured(system="s", user="same", schema={"type": "object"}, cache=False)
        provider.structured(system="s", user="different", schema={"type": "object"}, cache=True)
    assert first == second
    assert len(calls["beta"]) == 3
    assert client.get("/api/v1/ai/usage", headers=auth_header).json()["cache_hits"] == 1


def test_usage_is_written_through_the_callers_session(client, auth_header):
    """A request that already holds SQLite's write lock must still record usage."""
    user_id = _user_id(client, auth_header)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        user.full_name = "Pending write"
        db.flush()
        with ai_scope(user_id, "assistant", db):
            provider = get_provider(_settings())
            _fake_client(provider)
            provider.structured(system="s", user="u", schema={"type": "object"})
        assert db.query(AIUsage).filter(AIUsage.user_id == user_id).count() == 1
        db.commit()
