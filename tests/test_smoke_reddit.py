"""The Reddit reachability probe must not redden a commit for a source that
blocks the runner's datacenter range — but it must still fail on an answer that
is not an answer. These tests pin both sides of that line."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops" / "ci"))
import smoke_reddit  # noqa: E402

FEED_XML = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><title>MSFT one</title></entry>
  <entry><title>MSFT two</title></entry>
</feed>"""
EMPTY_FEED_XML = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'


class _Response:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def _respond(monkeypatch, response):
    monkeypatch.setattr(smoke_reddit.requests, "get", lambda *a, **k: response)


def test_a_reachable_feed_passes(monkeypatch, capsys):
    _respond(monkeypatch, _Response(200, FEED_XML))

    assert smoke_reddit.main() == 0
    out = capsys.readouterr().out
    assert "reachable (2 entries)" in out
    assert "::warning::" not in out


@pytest.mark.parametrize("status, verdict", [(403, "blocked"), (429, "throttled")])
def test_blocked_or_throttled_is_a_visible_warning_not_a_failure(
        monkeypatch, capsys, status, verdict):
    _respond(monkeypatch, _Response(status))

    assert smoke_reddit.main() == 0
    out = capsys.readouterr().out
    assert f"{verdict} (HTTP {status})" in out
    assert "not reachable from this runner" in out
    assert "::warning::" in out


@pytest.mark.parametrize("error", [
    requests.exceptions.Timeout("read timed out"),
    requests.exceptions.ConnectionError("network unreachable"),
])
def test_a_network_failure_is_a_visible_warning_not_a_failure(
        monkeypatch, capsys, error):
    def boom(*args, **kwargs):
        raise error

    monkeypatch.setattr(smoke_reddit.requests, "get", boom)

    assert smoke_reddit.main() == 0
    out = capsys.readouterr().out
    assert f"unreachable ({type(error).__name__})" in out
    assert "::warning::" in out


@pytest.mark.parametrize("response", [
    _Response(404),
    _Response(500),
    _Response(200, "this is not xml"),
    _Response(200, EMPTY_FEED_XML),
])
def test_a_real_failure_still_exits_nonzero(monkeypatch, capsys, response):
    _respond(monkeypatch, response)

    assert smoke_reddit.main() == 1
    out = capsys.readouterr().out
    assert "::error::reddit search feed probe failed:" in out


def test_check_names_the_verdict_and_count(monkeypatch):
    _respond(monkeypatch, _Response(200, FEED_XML))

    assert smoke_reddit.check() == ("reachable", 2)


def test_check_raises_unreachable_for_a_block(monkeypatch):
    _respond(monkeypatch, _Response(403))

    with pytest.raises(smoke_reddit.Unreachable, match="blocked"):
        smoke_reddit.check()
