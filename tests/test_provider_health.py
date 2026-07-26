import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

import provider_health as health  # noqa: E402


def test_config_has_unique_candidates_and_deterministic_fallbacks():
    config = health.load_config(ROOT / "config" / "provider-health.json")
    assert [row["provider"] for row in config["candidates"]] == [
        "minimax", "minimax-2", "openai", "anthropic"
    ]
    assert config["probe"]["max_tokens"] == 1
    assert len(config["deterministic_product_fallbacks"]) == 3
    contract = health.load_contract(ROOT / "config" / "cron-schedules.json")
    expected = [row["model"] for row in config["candidates"]]
    for profile in ("brief", "report", "intraday"):
        assert contract["payload_profiles"][profile]["model_candidates"] == expected


def test_rotation_selects_first_healthy_and_omits_dead_entries():
    results = [
        {"model": "primary/model", "healthy": False},
        {"model": "second/model", "healthy": True},
        {"model": "dead/model", "healthy": False},
        {"model": "last/model", "healthy": True},
    ]
    assert health.rotation(results) == ["second/model", "last/model"]


def test_evaluate_skips_probe_for_unconfigured_provider(monkeypatch):
    config = {
        "candidates": [
            {"provider": "ready", "model": "ready/model"},
            {"provider": "missing", "model": "missing/model"},
        ],
        "probe": {"attempts": 2, "initial_backoff_seconds": 1,
                  "timeout_ms": 10, "max_tokens": 1},
    }
    monkeypatch.setattr(
        health,
        "model_status",
        lambda **_kwargs: {
            "auth": {"providers": [{"provider": "ready", "effective": {"kind": "key"}}]}
        },
    )
    calls = []
    monkeypatch.setattr(
        health,
        "probe_one",
        lambda provider, _probe, sleep=None: calls.append(provider) or (True, []),
    )
    rows = health.evaluate(config, sleep=lambda _seconds: None)
    assert calls == ["ready"]
    assert rows[0]["healthy"] is True
    assert rows[1]["status"] == "unconfigured"


def test_probe_retries_with_bounded_exponential_backoff(monkeypatch):
    responses = [
        {"auth": {"probes": {"results": [{"provider": "p", "status": "error"}]}}},
        {"auth": {"probes": {"results": [{"provider": "p", "status": "error"}]}}},
        {"auth": {"probes": {"results": [{"provider": "p", "status": "ok",
                                           "latencyMs": 5}]}}},
    ]
    monkeypatch.setattr(health, "model_status", lambda **_kwargs: responses.pop(0))
    sleeps = []
    probe = {"attempts": 3, "initial_backoff_seconds": 2,
             "timeout_ms": 10, "max_tokens": 1}
    ok, attempts = health.probe_one("p", probe, sleep=sleeps.append)
    assert ok is True
    assert len(attempts) == 3
    assert sleeps == [2, 4]


def test_desired_changes_excludes_memory_and_removes_duplicate_fallback():
    live = [
        {
            "id": "1",
            "name": "market",
            "payload": {
                "model": "minimax/MiniMax-M3",
                "fallbacks": ["minimax/MiniMax-M3", "dead/model"],
            },
        },
        {
            "id": "2",
            "name": "memory",
            "payload": {"model": "minimax/MiniMax-M3", "fallbacks": []},
        },
    ]
    models = ["minimax/MiniMax-M3", "minimax-2/MiniMax-M3"]
    changes = health.desired_changes(live, models, {"market"})
    assert len(changes) == 1
    assert changes[0]["name"] == "market"
    assert changes[0]["to"] == {
        "model": "minimax/MiniMax-M3",
        "fallbacks": ["minimax-2/MiniMax-M3"],
    }


def test_state_file_contains_no_auth_material(tmp_path):
    state = {
        "schema_version": 1,
        "providers": [{"provider": "p", "status": "ok", "healthy": True}],
        "rotation": ["p/model"],
    }
    path = tmp_path / "provider-health.json"
    health._atomic_write(path, state)
    assert json.loads(path.read_text()) == state
    assert "token" not in path.read_text().lower()


def test_failed_alert_is_retried_for_same_failure(monkeypatch):
    state = {
        "unhealthy_fingerprint": "p:probe_failed",
        "providers": [{"provider": "p", "status": "probe_failed", "healthy": False}],
        "rotation": ["ready/model"],
    }
    calls = []
    monkeypatch.setattr(
        health,
        "send_telegram",
        lambda *args: calls.append(args) or (True, None),
    )

    sent = health.maybe_alert(
        state,
        prior_fingerprint="p:probe_failed",
        prior_alert_sent=False,
        no_alert=False,
    )

    assert sent is True
    assert len(calls) == 1
