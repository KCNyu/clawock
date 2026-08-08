"""The launcher is host wiring, and host wiring still has to be reproducible.

`clawock` cannot be pip-installed on this box: the system Python is
externally-managed (PEP 668), and --break-system-packages on the machine that
runs the money pipeline trades a tidy install for a risk to the interpreter
every cron depends on. So the entry point is a generated launcher — instance, by
docs/reference/product-vs-instance.md.

What that must not become is host state nobody can rebuild. This pins the
installer: it produces a working launcher against any checkout, and the launcher
points at the checkout rather than copying it, so a git fast-forward changes
behaviour with no reinstall — which is what the live box needs.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "ops" / "host" / "install_clawock_launcher.sh"


@pytest.fixture(scope="module")
def installed_launcher(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("installed-launcher")
    target = tmp_path / "bin" / "clawock"
    venv = tmp_path / "venv"
    done = subprocess.run(["bash", str(INSTALLER), str(ROOT), str(target), str(venv)],
                          capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stderr
    return target, venv, tmp_path


def test_the_installer_produces_a_working_entry_point(installed_launcher):
    target, _venv, tmp_path = installed_launcher
    assert target.exists() and os.access(target, os.X_OK)

    # Run it from a directory that is neither the checkout nor a workspace, to
    # prove it carries its own resolution rather than inheriting a lucky cwd.
    ran = subprocess.run([str(target), "--help"], capture_output=True, text=True,
                         timeout=60, cwd=str(tmp_path))
    assert ran.returncode == 0, f"{ran.stdout}\n{ran.stderr}"
    assert "clawock" in ran.stdout


def test_the_launcher_points_at_the_checkout_rather_than_copying_it(installed_launcher):
    """A fast-forward must change behaviour with no reinstall."""
    target, venv, _tmp_path = installed_launcher
    body = target.read_text()
    assert str(ROOT) in body, "the launcher must name the checkout it serves"
    assert str(venv / "bin" / "clawock") in body
    assert "CLAWOCK_INSTANCE=kcnyu" in body


def test_the_installer_exposes_all_watchdogs_on_the_same_path(installed_launcher):
    target, venv, _tmp_path = installed_launcher
    for name in (
        "clawock-kcnyu-brief-watchdog",
        "clawock-kcnyu-report-watchdog",
        "clawock-kcnyu-intraday-watchdog",
    ):
        launcher = target.parent / name
        assert launcher.exists() and os.access(launcher, os.X_OK)
        body = launcher.read_text()
        assert str(venv / "bin" / name) in body
        assert "CLAWOCK_WORKSPACE=" in body


def test_the_installer_refuses_a_directory_that_is_not_a_checkout(tmp_path):
    done = subprocess.run(["bash", str(INSTALLER), str(tmp_path),
                           str(tmp_path / "clawock"), str(tmp_path / "venv")],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode != 0, "installing against a non-checkout must fail loudly"
    assert "not a clawock checkout" in done.stderr
