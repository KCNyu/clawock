"""A failed evidence rebuild must leave the last complete ledger in place (#1579)."""
import errno
import io
import json

import pytest

from clawock.evidence import build_evidence as ev


def test_interrupted_evidence_write_retains_previous_artifact(tmp_path, monkeypatch):
    artifact = tmp_path / "evidence.json"
    monkeypatch.setattr(ev, "ARTIFACT", artifact)
    monkeypatch.setattr(ev, "_sections", lambda: [])
    monkeypatch.setattr(ev, "_generated_at", lambda: "2026-09-17")
    ev.write_all()
    before = artifact.read_bytes()
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

    # io.open is shared by Path.write_text and os.fdopen: the same partial-write
    # failure lands whether or not the writer stages its bytes elsewhere first.
    monkeypatch.setattr(ev, "_generated_at", lambda: "2026-09-18")
    monkeypatch.setattr(io, "open", interrupted_open)
    with pytest.raises(OSError, match="injected disk full"):
        ev.write_all()
    monkeypatch.undo()

    assert artifact.read_bytes() == before
    assert json.loads(before)["generated_at"] == "2026-09-17"
    assert list(tmp_path.iterdir()) == [artifact]


def test_successful_evidence_write_keeps_storage_format(tmp_path, monkeypatch):
    artifact = tmp_path / "evidence.json"
    monkeypatch.setattr(ev, "ARTIFACT", artifact)
    monkeypatch.setattr(ev, "_sections", lambda: [])
    monkeypatch.setattr(ev, "_generated_at", lambda: "2026-09-18")
    ev.write_all()
    expected = ev.payload([], "2026-09-18")
    assert artifact.read_text(encoding="utf-8") == (
        json.dumps(expected, ensure_ascii=False, indent=2) + "\n")
