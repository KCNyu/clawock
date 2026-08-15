"""Process-local JSON read cache keyed by file mtime (#557).

Same mtime + an atomic writer ⇒ same bytes, so a cached hit is current for
producers that replace the file (bumping mtime). The contract: parse count
drops, freshness never does — for atomic writers. In-place writers that
restore mtime and coarse-mtime filesystems are out of contract (documented
failure mode, pinned by a test below so it cannot silently become a promise).

The cache is bounded (LRU-style eviction past _MAX_JSON_CACHE_ENTRIES) and the
returned object is shared across callers — read-only contract.
"""
import json
import os

from clawock.safe_io import (
    load_json_cached, clear_json_cache, _MAX_JSON_CACHE_ENTRIES,
)


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


def test_cache_is_bounded_and_evicts_oldest(monkeypatch, tmp_path):
    """#623: the cache must not grow without bound; eviction only costs a
    re-parse. A pure-LRU reading of the dict: the first inserted entry is the
    first evicted once the cap is exceeded."""
    files = []
    for i in range(_MAX_JSON_CACHE_ENTRIES + 10):
        p = tmp_path / f"f{i}.json"
        _write(p, {"i": i})
        files.append(p)
    calls = {"n": 0}
    real_load = json.load

    def spy(f):
        calls["n"] += 1
        return real_load(f)

    monkeypatch.setattr("clawock.safe_io.json.load", spy)

    for p in files:
        load_json_cached(p)
    assert calls["n"] == len(files)

    # The ten oldest entries were evicted: re-reading them parses again.
    for i in range(10):
        load_json_cached(files[i])
    assert calls["n"] == len(files) + 10

    # A recently inserted entry is still cached.
    load_json_cached(files[-1])
    assert calls["n"] == len(files) + 10


def test_json_decode_error_is_not_cached(monkeypatch, tmp_path):
    """A failed parse must not poison the cache: fix the file (mtime bumps),
    and the next read succeeds."""
    p = tmp_path / "broken.json"
    p.write_text("{not json")
    try:
        load_json_cached(p)
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("expected JSONDecodeError")

    _write(p, {"ok": 1})
    assert load_json_cached(p) == {"ok": 1}


def test_returned_object_is_shared_read_only_contract(monkeypatch, tmp_path):
    """#623: the same mutable object is returned on cache hits — callers must
    treat it as read-only. Pinned so a future deep-copy refactor is deliberate
    (it would also give up most of the parse-count win)."""
    p = tmp_path / "shared.json"
    _write(p, {"a": [1]})
    first = load_json_cached(p)
    second = load_json_cached(p)
    assert first is second


def test_same_mtime_different_bytes_returns_stale(monkeypatch, tmp_path):
    """Documented failure mode, pinned as behavior: an in-place writer that
    restores the mtime hands the cache an unchanged key, so the stale object is
    returned. This is why the docstring limits the freshness promise to atomic
    writers — the test exists to keep that limitation visible."""
    p = tmp_path / "inplace.json"
    _write(p, {"v": 1})
    os.utime(p, (1_000_000_000, 1_000_000_000))
    assert load_json_cached(p) == {"v": 1}

    # In-place rewrite that restores the exact same mtime.
    with open(p, "w") as f:
        f.write('{"v": 2}')
    os.utime(p, (1_000_000_000, 1_000_000_000))

    assert load_json_cached(p) == {"v": 1}, (
        "in-place writer with restored mtime is out of contract; a cached hit "
        "may be stale — switch the producer to safe_write_json to opt in to "
        "freshness")
