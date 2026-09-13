"""A failed daily-bar update must retain the last complete settlement input."""
import errno
import io
import json

import pytest

from clawock.market_data import bars


def test_interrupted_bar_write_retains_previous_store(tmp_path, monkeypatch):
    monkeypatch.setattr(bars, "BARS_DIR", tmp_path)
    old = {"ticker": "TEST", "bars": {"2026-09-10": {"close": 10}}}
    bars.write_bars("TEST", old)
    before = bars.bars_path("TEST").read_bytes()
    real_open = io.open

    class InterruptedWriter:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def write(self, text):
            self.handle.write(text[:len(text) // 2])
            self.handle.flush()
            raise OSError(errno.ENOSPC, "injected disk full after partial write")

    def interrupted_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        return InterruptedWriter(handle) if "w" in mode else handle

    # io.open is shared by Path.write_text and os.fdopen: inject the same real
    # partial-write failure regardless of whether the writer stages its bytes.
    monkeypatch.setattr(io, "open", interrupted_open)
    with pytest.raises(OSError, match="injected disk full"):
        bars.write_bars("TEST", {"ticker": "TEST", "bars": {
            **old["bars"], "2026-09-11": {"close": 11}}})
    assert bars.bars_path("TEST").read_bytes() == before
    assert bars.load_bars("TEST") == old
    assert list(tmp_path.iterdir()) == [bars.bars_path("TEST")]


def test_successful_bar_write_preserves_sorted_storage_format(tmp_path, monkeypatch):
    monkeypatch.setattr(bars, "BARS_DIR", tmp_path)
    doc = {"ticker": "TEST", "bars": {
        "2026-09-11": {"close": 11}, "2026-09-10": {"close": 10}}}
    bars.write_bars("TEST", doc)
    assert list(bars.load_bars("TEST")["bars"]) == ["2026-09-10", "2026-09-11"]
    assert bars.bars_path("TEST").read_text() == json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
