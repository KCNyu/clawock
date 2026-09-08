"""Count the delivery legs that can fail on their own (the #1242 criterion).

`check_fallback_chain_shape` asked that question of the model chain and found
three hops behind one credential — one leg wearing three. Nobody had asked it of
the path the reports actually leave on.

2026-09-08 answered both halves of it in one morning:

* WeChat returned `ret=-2 prepare failed` on five consecutive slots and Telegram
  carried every one — a channel failure costs one leg, and the second leg is
  real;
* the 10:34 co-send and the 10:43 watchdog mirror both gave up on the same local
  gateway at its 10s ceiling — a transport failure costs every channel at once,
  and the "backstop" was a second call down the pipe that had just failed.

So the reported number is transports, not channels.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def system_check():
    for path in (ROOT, ROOT / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(
        "kcnyu_system_check_delivery_chain", ROOT / "ops" / "system_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(system_check, monkeypatch, tmp_path, channels_per_slot):
    out = tmp_path / "assets" / "data"
    out.mkdir(parents=True, exist_ok=True)
    (out / "workflow-outcomes.json").write_text(json.dumps({
        "schema_version": 1,
        "records": [{"job": "盘中盯盘", "slot": "2026-09-08T10:00:00+08:00",
                     "stages": {"primary_delivery": {"status": "success",
                                                     **channels_per_slot}}}],
    }), encoding="utf-8")
    monkeypatch.setenv("CLAWOCK_WORKSPACE", str(tmp_path))
    r = system_check.Result()
    system_check.check_delivery_chain_shape(r)
    return [row for row in r.checks if row[0] == "delivery chain"]


def test_two_channels_down_one_pipe_are_one_leg(system_check, monkeypatch, tmp_path):
    rows = _run(system_check, monkeypatch, tmp_path,
                {"wechat_ok": True, "telegram_ok": True})

    assert len(rows) == 1
    _, level, message = rows[0]
    assert level == system_check.WARNING
    assert "2 channel(s)" in message and "1 transport" in message
    # The sentence has to name the backstop, because that is the part that reads
    # as redundancy and is not.
    assert "backstop" in message


def test_a_single_channel_is_not_reported(system_check, monkeypatch, tmp_path):
    """One channel is one leg by construction — saying so adds no information,
    and a warning that fires on a correct configuration trains the reader to
    skip the row."""
    rows = _run(system_check, monkeypatch, tmp_path, {"telegram_ok": True})

    assert rows == []


def test_the_channels_come_from_the_ledger_not_a_hardcoded_pair(
        system_check, monkeypatch, tmp_path):
    """Same reason the rate check reads them there: a third channel must be
    counted the day it starts writing its result, not the day someone edits a
    list."""
    rows = _run(system_check, monkeypatch, tmp_path,
                {"wechat_ok": True, "telegram_ok": True, "signal_ok": False})

    assert "3 channel(s)" in rows[0][2]
    assert "signal" in rows[0][2]


def test_transports_are_asked_of_the_harness_not_assumed(
        system_check, monkeypatch, tmp_path):
    """The count must come from the code that actually sends. If a channel is
    ever routed through a second provider, this check improves on its own —
    and if the provider cannot be resolved at all, it says that instead of
    quietly reporting a number it did not measure.
    """
    from clawock.providers import delivery

    def boom(*a, **k):
        raise RuntimeError('no provider')

    monkeypatch.setattr(delivery, 'default_provider', boom)
    rows = _run(system_check, monkeypatch, tmp_path,
                {"wechat_ok": True, "telegram_ok": True})

    assert rows and 'cannot resolve the delivery provider' in rows[0][2]
