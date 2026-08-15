"""Process-local JSON read cache keyed by file mtime (#557).

Same mtime ⇒ same bytes, so a cached hit is always current and a producer that
atomically replaces the file bumps mtime and the next read re-parses. The
contract: parse count drops, freshness never does.
"""
import json
import os

from clawock.safe_io import load_json_cached, clear_json_cache


def _write(path, payload):
    path.write_text(json.dumps(payload))


def test_second_read_with_same_mtime_skips_parse(monkeypatch, tmp_path):
    p = tmp_path / "x.json"
    _write(p, {"a": 1})
    calls = {"n": 0}
    real_load = json.load

    def spy(f):
        calls["n"] += 1
        return real_load(f)

    monkeypatch.setattr("clawock.safe_io.json.load", spy)

    assert load_json_cached(p) == {"a": 1}
    assert load_json_cached(p) == {"a": 1}
    assert calls["n"] == 1


def test_mtime_change_reparses(tmp_path):
    p = tmp_path / "x.json"
    _write(p, {"a": 1})
    os.utime(p, (1_000_000_000, 1_000_000_000))
    assert load_json_cached(p) == {"a": 1}

    _write(p, {"a": 2})
    os.utime(p, (2_000_000_000, 2_000_000_000))
    assert load_json_cached(p) == {"a": 2}


def test_clear_cache_forces_reparse(monkeypatch, tmp_path):
    p = tmp_path / "x.json"
    _write(p, {"a": 1})
    calls = {"n": 0}
    real_load = json.load

    def spy(f):
        calls["n"] += 1
        return real_load(f)

    monkeypatch.setattr("clawock.safe_io.json.load", spy)
    load_json_cached(p)
    clear_json_cache()
    load_json_cached(p)
    assert calls["n"] == 2


def test_missing_file_raises_like_a_plain_read(tmp_path):
    try:
        load_json_cached(tmp_path / "nope.json")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("expected FileNotFoundError")
