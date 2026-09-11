"""Tencent's ~10-per-inbound WeChat allowance: count it, and ask to renew it in time.

kcn 2026-09-12:「提醒我刷新」. Replayed on the 2026-09-11 11:14 inbound: nine pushes
landed and the tenth failed, so the note has to ride on pushes 7, 8 and 9 — the
last ones that can still reach him.
"""
import json
import os

from clawock.harness import _watchdog_common as common
from clawock.providers import wechat_allowance as allowance

KCN = "o9cq80-hGTruM-OSs8kNmDOtLVZI@im.wechat"
INBOUND = 1_789_100_000.0


def _inbound(tmp_path, at=INBOUND, target=KCN):
    accounts = tmp_path / "accounts"
    accounts.mkdir(exist_ok=True)
    path = accounts / "bot.context-tokens.json"
    path.write_text(json.dumps({target: "token-value-not-read"}))
    os.utime(path, (at, at))
    return accounts


def _push(tmp_path, accounts, n, message="盘中盯盘"):
    out = []
    for i in range(n):
        text, remaining = allowance.annotate(KCN, message, ledger=tmp_path / "sends.json",
                                             accounts_dir=accounts)
        allowance.record(KCN, text, True, ledger=tmp_path / "sends.json", now=INBOUND + 60 * (i + 1))
        out.append((remaining, "📮" in text))
    return out


def test_the_last_three_pushes_that_can_land_carry_the_note(tmp_path):
    accounts = _inbound(tmp_path)
    pushes = _push(tmp_path, accounts, 9)
    assert [r for r, _ in pushes] == [8, 7, 6, 5, 4, 3, 2, 1, 0]
    assert [noted for _, noted in pushes] == [False] * 6 + [True] * 3


def test_a_new_inbound_resets_the_count(tmp_path):
    accounts = _inbound(tmp_path)
    _push(tmp_path, accounts, 9)
    accounts = _inbound(tmp_path, at=INBOUND + 3600)
    text, remaining = allowance.annotate(KCN, "x", ledger=tmp_path / "sends.json", accounts_dir=accounts)
    assert remaining == 8 and "📮" not in text


def test_failed_sends_spend_nothing_and_long_messages_spend_per_chunk(tmp_path):
    accounts = _inbound(tmp_path)
    allowance.record(KCN, "x", False, ledger=tmp_path / "sends.json", now=INBOUND + 10)
    allowance.record(KCN, "长" * 8001, True, ledger=tmp_path / "sends.json", now=INBOUND + 20)
    assert allowance.used_since(KCN, INBOUND, ledger=tmp_path / "sends.json") == 3


def test_an_unknown_count_is_not_guessed(tmp_path):
    empty = tmp_path / "accounts"
    empty.mkdir()
    text, remaining = allowance.annotate(KCN, "简报", ledger=tmp_path / "sends.json", accounts_dir=empty)
    assert remaining is None and text == "简报"
    other = _inbound(tmp_path, target="someone-else@im.wechat")
    assert allowance.annotate(KCN, "简报", ledger=tmp_path / "sends.json", accounts_dir=other)[1] is None


def test_the_last_one_says_it_is_the_last_and_how_to_renew():
    assert "最后一条" in allowance.note(0) and "回我任意一个字" in allowance.note(0)
    assert "还能再推 2 条" in allowance.note(2)
    assert allowance.note(3) == "" and allowance.note(None) == ""


def test_send_wechat_annotates_and_records_but_a_dry_run_records_nothing(tmp_path, monkeypatch):
    sent = []

    class Result:
        status, detail = "unknown", "ok"

    class Provider:
        def send(self, channel, to, message, dry_run=False):
            sent.append(message)
            return Result()

    accounts = _inbound(tmp_path)
    monkeypatch.setattr(common, "_delivery", lambda account=None: Provider())
    monkeypatch.setattr(allowance, "_accounts_dir", lambda: accounts)
    monkeypatch.setattr(common, "wechat_sends_ledger", lambda: tmp_path / "sends.json")
    for _ in range(7):
        common.send_wechat("openclaw-weixin", KCN, None, "报告", dry_run=False)
    assert "📮" in sent[-1] and "📮" not in sent[-2]

    before = (tmp_path / "sends.json").read_text()
    common.send_wechat("openclaw-weixin", KCN, None, "报告", dry_run=True)
    assert (tmp_path / "sends.json").read_text() == before


def test_the_provider_does_not_know_the_workspace_layout():
    """Decoupled on purpose (kcn 2026-09-12:「注意我们是好不容易解耦的」): the
    delivery provider is handed its ledger; it imports no workspace module."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(allowance))
    imported = {node.module for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module}
    imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                 for alias in node.names}
    assert not {m for m in imported if m.startswith("clawock.workspace")}


def test_a_counting_failure_never_costs_the_send(monkeypatch):
    sent = []

    class Result:
        status, detail = "unknown", "ok"

    class Provider:
        def send(self, channel, to, message, dry_run=False):
            sent.append(message)
            return Result()

    def broken(*a, **k):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(common, "_delivery", lambda account=None: Provider())
    monkeypatch.setattr(allowance, "annotate", broken)
    monkeypatch.setattr(allowance, "record", lambda *a, **k: None)
    assert common.send_wechat("openclaw-weixin", KCN, None, "简报", dry_run=False)[0]
    assert sent == ["简报"]
