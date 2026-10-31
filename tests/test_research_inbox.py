"""Queue persistence, explicit dispositions and brief retry semantics."""
import json

import pytest

from clawock.decision import research_inbox as I
from clawock.market_data import stock_discovery as D

DAY = "2026-10-31"
CANDIDATE = {"market": "US", "ticker": "TEST", "name": "Test", "sector_label": "科技"}


def test_disposition_survives_rediscovery_and_due_rows_survive_source_failure(tmp_path):
    I.ingest(tmp_path, [CANDIDATE], today=DAY)
    first = I.view(tmp_path, today=DAY, highlights_only=True)
    assert first["total"] == 1 and first["rows"][0]["new"]
    I.set_status(tmp_path, "US", "TEST", "deferred", reason="wait for filing", review_on="2026-11-02")
    I.ingest(tmp_path, [CANDIDATE], today="2026-11-01")
    assert I.view(tmp_path, today="2026-11-01", highlights_only=True)["rows"] == []
    result = I.attach(tmp_path, D.unavailable("timeout"), today="2026-11-02")
    row = result["inbox"]["rows"][0]
    assert row["due"] and row["status"] == "deferred"
    assert row["reason"] == "wait for filing" and row["last_seen"] == "2026-11-01"
    lines = "\n".join(D.candidate_lines(result))
    assert "未取到" in lines and "到期复查" in lines and "TEST" in lines
    assert result["candidates"] == []


def test_retry_stable_new_items_next_day_suppressed_rejected_stays_rejected(tmp_path):
    first = I.attach(tmp_path, {"candidates": [CANDIDATE]}, today=DAY)
    second = I.attach(tmp_path, {"candidates": [CANDIDATE]}, today=DAY)
    assert first == second
    assert not I.view(tmp_path, today="2026-11-01", highlights_only=True)["rows"]
    I.set_status(tmp_path, "US", "TEST", "rejected", reason="business model")
    I.ingest(tmp_path, [CANDIDATE], today="2026-11-02")
    assert not I.view(tmp_path, today="2026-11-02", highlights_only=True)["rows"]
    assert I.view(tmp_path, today=DAY)["rows"][0]["status"] == "rejected"


def test_bad_state_is_not_overwritten_and_fresh_candidates_remain_visible(tmp_path):
    path = I._path(tmp_path)
    path.parent.mkdir()
    path.write_text("{broken")
    result = I.attach(tmp_path, {"status": "ok", "candidates": [CANDIDATE]}, today=DAY)
    assert result["inbox"]["status"] == "unavailable"
    assert "TEST" in "\n".join(D.candidate_lines(result))
    assert path.read_text() == "{broken"


def test_transition_validation_and_market_keys(tmp_path):
    I.ingest(tmp_path, [CANDIDATE, {**CANDIDATE, "market": "HK", "ticker": "00700"}], today=DAY)
    for kwargs in (dict(status="deferred", reason="wait"),
                   dict(status="pending", reason=""),
                   dict(status="researching", reason="ok", review_on="not-a-date")):
        with pytest.raises(ValueError):
            I.set_status(tmp_path, "US", "TEST", **kwargs)
    assert I.view(tmp_path, today=DAY)["total"] == 2
    for state in I.STATES:
        result = I.set_status(tmp_path, "US", "TEST", state, reason="reviewed", review_on="2026-11-02")
        assert result["status"] == state
    with pytest.raises(ValueError):
        I.set_status(tmp_path, "US", "../x", "pending", reason="x")


def test_latest_gate_links_are_informational_not_a_queue_authorization(tmp_path, monkeypatch):
    from clawock.decision import entry
    gates = tmp_path / "memory/entry-gates"
    gates.mkdir(parents=True)
    (gates / "test.json").write_text(json.dumps({"ticker": "TEST", "gate_id": "g1"}))
    monkeypatch.setattr(entry, "proposal_authorizations",
                        lambda *a, **kw: {"TEST": {"gate_id": "g1", "cleared": False}})
    result = I.attach(tmp_path, {"status": "ok", "candidates": [CANDIDATE]}, today=DAY)
    row = result["inbox"]["rows"][0]
    assert row["gate_artifact"] == "memory/entry-gates/test.json"
    assert row["status"] == "pending"
    text = "\n".join(D.candidate_lines(result))
    assert "尚未通过或已过期" in text and "memory/entry-gates/test.json" in text


def test_hk_missing_inputs_do_not_fetch(tmp_path):
    result = D.collect(tmp_path, market="HK", fetcher=lambda: pytest.fail("must not fetch HK"))
    assert result["status"] == "incomplete"
    assert result["reason_code"] == "invalid_discovery_inputs"
    assert result["candidates"] == []
    combined = D.collect(tmp_path, market="all")
    assert combined["markets"]["HK"]["reason_code"] == result["reason_code"]
    assert combined["status"] == "incomplete"


def test_concurrent_ingest_preserves_both_candidates(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda ticker: I.ingest(tmp_path, [{**CANDIDATE, "ticker": ticker}], today=DAY),
                      ["AAA", "BBB"]))
    assert {row["ticker"] for row in I.view(tmp_path, today=DAY)["rows"]} == {"AAA", "BBB"}


def test_noncanonical_review_dates_rejected(tmp_path):
    I.ingest(tmp_path, [CANDIDATE], today=DAY)
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        I.set_status(tmp_path, "US", "TEST", "deferred", reason="wait", review_on="20261102")



def test_structurally_corrupt_inbox_still_preserves_fresh_discovery(tmp_path):
    path = I._path(tmp_path)
    path.parent.mkdir()
    content = json.dumps({"schema_version": 1, "rows": {"US:TEST": {"market": [], "ticker": "TEST"}}})
    path.write_text(content)
    result = I.attach(tmp_path, {"status": "ok", "candidates": [CANDIDATE]}, today=DAY)
    assert result["inbox"]["status"] == "unavailable"
    assert result["candidates"] == [CANDIDATE]
    assert path.read_text() == content


def test_public_gate_link_is_pinned_and_disappears_after_local_edit(tmp_path):
    import subprocess
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args],
                                       text=True, stderr=subprocess.DEVNULL).strip()
    git("init")
    git("config", "user.email", "fixture@example.test")
    git("config", "user.name", "Fixture")
    artifact = tmp_path / "memory/entry-gates/test.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}")
    git("add", "memory/entry-gates/test.json")
    git("commit", "-m", "fixture")
    git("remote", "add", "origin", "https://github.com/KCNyu/clawock.git")
    commit = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/master", commit)
    path = "memory/entry-gates/test.json"
    assert I._published_gates(tmp_path)[path] == f"https://github.com/KCNyu/clawock/blob/{commit}/{path}"
    artifact.write_text('{"changed": true}')
    assert path not in I._published_gates(tmp_path)
