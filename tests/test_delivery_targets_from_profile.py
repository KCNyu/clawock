"""Where the watchdogs deliver is the profile's decision, not the package's (#1632).

`_watchdog_common` used to carry one desk's WeChat conversation, Telegram chat id
and GitHub Pages URL as module constants, so an installed `clawock` would page
that desk from anyone's workspace. The targets now come from the selected
profile's `delivery.targets` and the brief link from the workspace's Pages
contract; a workspace that declares neither gets a failed send that says why.
"""
import json
from pathlib import Path

import pytest

from clawock.config.profiles import load_profile
from clawock.harness import _watchdog_common as common
from clawock.providers.openclaw import CronRead

ROOT = Path(__file__).resolve().parents[1]
MINIMAL = json.loads((ROOT / "examples/profiles/minimal/profile.json").read_text())


def _workspace(tmp_path, monkeypatch, targets, site_url=None):
    profile = dict(MINIMAL, id="desk")
    profile["delivery"] = {"provider": "openclaw", "targets": targets}
    path = tmp_path / "config/profiles/desk/profile.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(profile))
    if site_url is not None:
        (tmp_path / "config/pages-public.json").write_text(
            json.dumps({"site_url": site_url}))
    monkeypatch.setenv("CLAWOCK_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("CLAWOCK_PROFILE", "desk")
    return tmp_path


def test_the_reusable_package_names_no_desk_of_its_own():
    leaked = ("2033937852", "o9cq80-hGTruM-OSs8kNmDOtLVZI", "kcnyu.github.io")
    offenders = [
        f"{path.relative_to(ROOT)}: {needle}"
        for path in (ROOT / "src/clawock").rglob("*.py")
        for needle in leaked
        if needle in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_the_kcnyu_profile_declares_its_own_telegram_chat(monkeypatch):
    monkeypatch.setenv("CLAWOCK_WORKSPACE", str(ROOT))
    monkeypatch.setenv("CLAWOCK_PROFILE", "kcnyu")
    target = load_profile(ROOT, "kcnyu").delivery_targets["telegram"]

    assert target.source == "static"
    assert common.telegram_target() == target.value


def test_telegram_target_reads_the_variable_an_environment_target_names(
        tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch, {
        "telegram": {"source": "environment", "key": "DESK_TG"}})

    monkeypatch.delenv("DESK_TG", raising=False)
    assert common.telegram_target() is None
    monkeypatch.setenv("DESK_TG", "4242")
    assert common.telegram_target() == "4242"


def test_no_telegram_target_is_a_failed_send_with_its_reason(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch, {"telegram": {"source": "disabled"}})
    monkeypatch.setattr(common, "_delivery", lambda *_a: pytest.fail(
        "a send without a target must not reach the transport"))

    assert common.telegram_target() is None
    ok, detail = common.send_telegram(common.telegram_target(), "hello", False)

    assert ok is False
    assert "no Telegram target configured" in detail


def test_wechat_target_comes_from_the_runtime_state_db_first(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch, {"wechat": {"source": "runtime_job"}})
    asked = []

    def read_jobs(source):
        asked.append(source)
        return CronRead([{"name": "x", "delivery": {
            "channel": "openclaw-weixin", "to": "desk@im.wechat",
            "accountId": "bot"}}], source)

    monkeypatch.setattr(common._openclaw, "read_jobs", read_jobs)

    assert common.resolve_wechat_target() == ("openclaw-weixin", "desk@im.wechat", "bot")
    assert asked == ["sqlite"]


def test_an_unresolvable_wechat_target_raises_instead_of_borrowing_one(
        tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch, {"wechat": {"source": "runtime_job"}})
    monkeypatch.setattr(common._openclaw, "read_jobs",
                        lambda source: CronRead([], "empty"))

    with pytest.raises(RuntimeError, match="no WeChat delivery target"):
        common.resolve_wechat_target()


def test_a_disabled_wechat_target_is_never_looked_up(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch, {"wechat": {"source": "disabled"}})
    monkeypatch.setattr(common._openclaw, "read_jobs", lambda source: pytest.fail(
        "a disabled target must not be resolved from the runtime"))

    with pytest.raises(RuntimeError, match="disabled"):
        common.resolve_wechat_target()


def test_the_brief_link_follows_the_workspace_pages_contract(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch, {}, site_url="https://desk.example/site/")
    assert common.brief_url("2026-09-19") == (
        "https://desk.example/site/memory/2026-09-19-pre-open.html")

    (tmp_path / "config/pages-public.json").unlink()
    assert common.brief_url("2026-09-19") == "memory/2026-09-19-pre-open.html"


@pytest.mark.parametrize("target, message", [
    ({"source": "static"}, "value is required for static"),
    ({"source": "static", "value": "1", "key": "X"}, "key is only valid for environment"),
    ({"source": "environment", "key": "X", "value": "1"}, "value is only valid for static"),
])
def test_profile_rejects_a_target_whose_fields_do_not_fit_its_source(
        tmp_path, monkeypatch, target, message):
    _workspace(tmp_path, monkeypatch, {"telegram": target})

    with pytest.raises(ValueError, match=message):
        load_profile(tmp_path, "desk")
