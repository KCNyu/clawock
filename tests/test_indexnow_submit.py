"""IndexNow submitter: the pieces that have to exist together to be alive.

#592 deleted `ops/growth/indexnow_submit.py`; the host crontab line then failed
daily with `can't open file` until #672/#679 removed the key file, the deploy
contract entries and the crontab line too. Nothing decided whether the feature
should exist — it just stopped, quietly, over three PRs. kcn restored it in
#767.

These tests pin the parts that made it *silently* dead rather than loudly dead:
the script has to be there, and its inspection modes must not reach the network
(a `--help` that POSTs would be discovered only in production).

They deliberately do not assert anything about search-engine outcomes. Measured
2026-07-24: a month of accepted IndexNow pings produced zero Bing coverage, and
2026-08-19 GSC still shows the homepage last crawled 2026-06-22. `HTTP 200` from
IndexNow means received, not crawled, and certainly not indexed.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops/growth/indexnow_submit.py"
KEY = "4fb2df1611ed42e5b67fd6171a237acb"


def _load():
    spec = importlib.util.spec_from_file_location("indexnow_submit", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_script_the_host_cron_calls_actually_exists():
    """The failure mode was a crontab line pointing at a deleted file."""
    assert SCRIPT.is_file()


def test_the_published_key_matches_the_key_file_name():
    """IndexNow validates ownership by fetching {key}.txt and comparing bodies."""
    assert (ROOT / "site" / f"{KEY}.txt").read_text().strip() == KEY
    assert _load().find_key() == KEY


def test_help_never_reaches_the_network():
    """argparse must exit before any HTTP work — including the sitemap fetch."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "--dry-run" in result.stdout


def test_explicit_urls_and_all_are_refused_together():
    module = _load()
    with pytest.raises(SystemExit):
        module.parse_args(["--all", "https://kcnyu.github.io/clawock/"])


def test_dry_run_prints_without_posting(monkeypatch, capsys):
    """The mode kcn is told to verify with must not be able to submit."""
    module = _load()
    monkeypatch.setattr(
        module, "select",
        lambda _args: (["https://kcnyu.github.io/clawock/"], {}),
    )
    monkeypatch.setattr(
        module, "post",
        lambda *_a, **_k: pytest.fail("dry-run must not POST"),
    )
    monkeypatch.setattr(
        module, "find_key",
        lambda: pytest.fail("dry-run must not need the key"),
    )
    module.main(["--dry-run"])
    assert "would submit 1 URL(s)" in capsys.readouterr().out


def test_a_successful_post_is_what_marks_urls_as_done(monkeypatch):
    """Recording before the POST would drop URLs forever on a failed run."""
    module = _load()
    order = []
    monkeypatch.setattr(module, "find_key", lambda: KEY)
    monkeypatch.setattr(module, "select", lambda _a: (["u"], {"u": "etag"}))
    monkeypatch.setattr(
        module, "post", lambda *_a, **_k: order.append("post"))
    monkeypatch.setattr(
        module, "save_seen", lambda _r: order.append("save"))
    module.main([])
    assert order == ["post", "save"]


def test_a_failed_post_does_not_record_the_urls(monkeypatch):
    module = _load()
    saved = []
    monkeypatch.setattr(module, "find_key", lambda: KEY)
    monkeypatch.setattr(module, "select", lambda _a: (["u"], {"u": "etag"}))
    monkeypatch.setattr(
        module, "post",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("502")),
    )
    monkeypatch.setattr(module, "save_seen", lambda _r: saved.append(_r))
    with pytest.raises(RuntimeError):
        module.main([])
    assert saved == []


# --- selection must compare page content, not per-build validators (#975) ---
#
# GitHub Pages rebuilds every page on each push to master and stamps the
# rebuild batch into every ETag prefix, so the old HEAD/ETag ledger saw every
# URL as changed dozens of times a day and re-announced the whole sitemap
# daily. These tests pin that identical bodies are never resubmitted and only
# real changes/new pages are.

import argparse
import hashlib


ARGS = argparse.Namespace(urls=[], all=False)


def test_identical_bodies_across_runs_are_not_resubmitted(monkeypatch):
    module = _load()
    bodies = {"https://x/a": b"same", "https://x/b": b"same"}
    monkeypatch.setattr(module, "sitemap_urls", lambda: list(bodies))
    monkeypatch.setattr(
        module, "load_seen",
        lambda: {u: hashlib.sha256(b).hexdigest() for u, b in bodies.items()})
    monkeypatch.setattr(
        module, "digest",
        lambda u: hashlib.sha256(bodies[u]).hexdigest())
    urls, record = module.select(ARGS)
    assert urls == []
    assert record == {}


def test_changed_and_new_pages_are_submitted_unreachable_are_skipped(monkeypatch):
    module = _load()
    bodies = {"https://x/a": b"unchanged", "https://x/b": b"edited v2"}
    seen = {"https://x/a": hashlib.sha256(b"unchanged").hexdigest(),
            "https://x/b": hashlib.sha256(b"edited v1").hexdigest()}
    monkeypatch.setattr(module, "sitemap_urls", lambda: list(bodies) + ["https://x/c"])
    monkeypatch.setattr(module, "load_seen", lambda: dict(seen))
    monkeypatch.setattr(
        module, "digest",
        lambda u: None if u.endswith("/c") else hashlib.sha256(bodies[u]).hexdigest())
    urls, record = module.select(ARGS)
    assert urls == ["https://x/b"]
    assert record == {"https://x/b": hashlib.sha256(b"edited v2").hexdigest()}


def test_ledger_schema_is_body_digests_not_etags(monkeypatch, tmp_path):
    """The ETag-era ledger key must not be read back: its values change on
    every Pages rebuild, so honoring them resurrects the daily full submit."""
    module = _load()
    (tmp_path / "seen.json").write_text('{"validators": {"u": "\"deadbeef-1\""}}')
    monkeypatch.setattr(module, "STATE", str(tmp_path / "seen.json"))
    assert module.load_seen() == {}

