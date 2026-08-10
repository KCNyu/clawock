"""The runtime must be launchable from a job that has a bare PATH.

The delivery backstop is the thing that notices a report never arrived. It runs
from the user crontab, where `PATH=/usr/bin:/bin`, and on 2026-08-10 it failed
twice — 10:40 and 11:40, two intraday slots — with `openclaw is not installed`.
The runtime was installed. `shutil.which` answering None means "not on this
PATH", and the adapter was reading it as "absent".

Its last successful send was 2026-08-06 23:10, and the first two attempts after
that both failed, so the migration behind `runtime_paths()` broke it and nothing
noticed for four days: a backstop only sends when something else already went
wrong, so its own failure is invisible on every healthy day.

Resolving the launcher is only half. The pnpm launcher is a shell script whose
last line is `exec node …`, so a bare PATH turns `openclaw is not installed`
into `exec: node: not found` — same undelivered report, different message.

Third in the family, after #438 (the money checker) and #444 (the gold refresh):
`command -v X` is not the same question as "is X installed".
"""
import os
import stat

import pytest

from clawock.providers.openclaw import _resolve_binary, runtime_env, runtime_paths


CRON_PATH = "/usr/bin:/bin"


def _executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def host(tmp_path):
    """A home laid out the way this one is: pnpm launcher, nvm node."""
    home = tmp_path / "home"
    _executable(home / ".local" / "share" / "pnpm" / "openclaw")
    _executable(home / ".nvm" / "versions" / "node" / "v22.23.1" / "bin" / "node")
    return home


def test_a_bare_cron_path_still_finds_the_installed_runtime(host):
    env = {"PATH": CRON_PATH, "HOME": str(host)}

    resolved = _resolve_binary(env)

    assert resolved == str(host / ".local" / "share" / "pnpm" / "openclaw")
    # The bare name is what produced "is not installed": it reaches subprocess,
    # raises FileNotFoundError, and the delivery result says the runtime is absent.
    assert resolved != "openclaw"


def test_the_runtime_can_actually_exec_node_from_that_job(host):
    """Half a fix is a different error message for the same undelivered report."""
    env = {"PATH": CRON_PATH, "HOME": str(host)}

    path = runtime_env(env)["PATH"].split(os.pathsep)

    assert str(host / ".nvm" / "versions" / "node" / "v22.23.1" / "bin") in path
    # The caller's own PATH keeps priority — an operator who selected a runtime
    # must not have this quietly reorder it underneath them.
    assert path[:2] == CRON_PATH.split(":")


def test_a_path_that_already_works_is_left_alone(host):
    """No reordering, no duplicates, on the healthy path this runs on every day."""
    own = host / "chosen"
    _executable(own / "openclaw")
    env = {"PATH": f"{own}:{CRON_PATH}", "HOME": str(host)}

    assert _resolve_binary(env) == str(own / "openclaw")
    resolved = runtime_env(env)["PATH"].split(os.pathsep)
    assert resolved[0] == str(own)
    assert len(resolved) == len(set(resolved))


def test_directories_that_hold_nothing_runnable_are_not_added(tmp_path):
    """Otherwise PATH grows with entries that only cost stat calls."""
    home = tmp_path / "empty-home"
    (home / ".local" / "share" / "pnpm").mkdir(parents=True)
    (home / ".local" / "share" / "pnpm" / "README").write_text("not executable")

    path = runtime_env({"PATH": CRON_PATH, "HOME": str(home)})["PATH"].split(os.pathsep)

    # Asserted against this directory rather than against the whole PATH: a
    # system-wide entry such as /usr/local/bin may legitimately exist and hold
    # executables on the machine running the tests.
    assert str(home / ".local" / "share" / "pnpm") not in path
    assert CRON_PATH.split(":") == path[:2]


def test_an_absent_runtime_still_reports_itself_absent(tmp_path):
    """The fallback must not invent a path, or 'not installed' becomes a
    confusing ENOENT on a file that was never there."""
    env = {"PATH": CRON_PATH, "HOME": str(tmp_path / "nothing")}

    assert _resolve_binary(env) == "openclaw"


def test_an_explicit_override_is_still_obeyed(host):
    env = {"PATH": CRON_PATH, "HOME": str(host),
           "CLAWOCK_OPENCLAW_BIN": "/opt/custom/openclaw"}

    assert runtime_paths(env).binary == "/opt/custom/openclaw"


def test_the_environment_is_carried_through_not_replaced(host):
    """Spawning with a rebuilt env must not drop what the runtime needs to
    authenticate — only PATH is meant to change."""
    env = {"PATH": CRON_PATH, "HOME": str(host), "OPENCLAW_TOKEN": "keep-me"}

    resolved = runtime_env(env)

    assert resolved["OPENCLAW_TOKEN"] == "keep-me"
    assert resolved["HOME"] == str(host)
