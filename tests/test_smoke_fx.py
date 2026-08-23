"""The FX smoke probe must fail loudly on an unusable answer, quietly pass on
a good one — its job is continue-on-error, but a probe that cannot assert is
worth nothing."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops" / "ci"))
import smoke_fx  # noqa: E402


def _runner(payload: str):
    def fake(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=payload, stderr="")
    return fake


def test_a_good_answer_names_the_source(capsys):
    payload = json.dumps({"rate": 7.82, "source": "exdev"})
    assert smoke_fx.check(runner=_runner(payload)) == "exdev"


@pytest.mark.parametrize("payload", [
    json.dumps({"rate": 12.0, "source": "bad"}),
    json.dumps({"source": "no-rate"}),
    "not json",
])
def test_an_unusable_answer_exits_nonzero(payload):
    with pytest.raises((AssertionError, KeyError, json.JSONDecodeError)):
        smoke_fx.check(runner=_runner(payload))


def test_main_reports_failure_without_a_traceback(monkeypatch, capsys):
    monkeypatch.setattr(
        smoke_fx, "check", lambda runner=None: (_ for _ in ()).throw(AssertionError("rate out of range")))
    assert smoke_fx.main() == 1
    assert "FX smoke FAILED" in capsys.readouterr().err


def test_main_reports_the_source(monkeypatch, capsys):
    monkeypatch.setattr(smoke_fx, "check", lambda runner=None: "tencent")
    assert smoke_fx.main() == 0
    assert "FX OK: tencent" in capsys.readouterr().out
