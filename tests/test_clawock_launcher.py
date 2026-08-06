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

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "ops" / "install_clawock_launcher.sh"


def test_the_installer_produces_a_working_entry_point(tmp_path):
    target = tmp_path / "bin" / "clawock"
    done = subprocess.run(["bash", str(INSTALLER), str(ROOT), str(target)],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert target.exists() and os.access(target, os.X_OK)

    # Run it from a directory that is neither the checkout nor a workspace, to
    # prove it carries its own resolution rather than inheriting a lucky cwd.
    ran = subprocess.run([str(target), "--help"], capture_output=True, text=True,
                         timeout=60, cwd=str(tmp_path))
    assert ran.returncode == 0, f"{ran.stdout}\n{ran.stderr}"
    assert "clawock" in ran.stdout


def test_the_launcher_points_at_the_checkout_rather_than_copying_it(tmp_path):
    """A fast-forward must change behaviour with no reinstall."""
    target = tmp_path / "clawock"
    subprocess.run(["bash", str(INSTALLER), str(ROOT), str(target)],
                   capture_output=True, text=True, timeout=60, check=True)
    body = target.read_text()
    assert str(ROOT) in body, "the launcher must name the checkout it serves"
    assert "clawock.cli" in body


def test_the_installer_refuses_a_directory_that_is_not_a_checkout(tmp_path):
    done = subprocess.run(["bash", str(INSTALLER), str(tmp_path),
                           str(tmp_path / "clawock")],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode != 0, "installing against a non-checkout must fail loudly"
    assert "not a clawock checkout" in done.stderr
