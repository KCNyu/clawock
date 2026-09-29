"""The npm readback must wait out a slow registry and still fail a real miss.

0.3.0 (2026-09-29): npm accepted the publish at 01:08:21Z but only served the
version from 01:10:59Z. The readback gave up after 41s and went red, and its
retries never reached the network anyway — the first miss sat in npm's HTTP
cache (`max-age=300`) and pacote does not revalidate on ETARGET. The fake npm
below models exactly those two registry behaviours; everything else in the
script (build, pack listing, tarball comparison) runs for real against it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "publish" / "publish_dsh_plugin.sh"
PKG = ROOT / "examples" / "dsh" / "packages" / "clawock-dsh"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="the script needs node")

FAKE_NPM = r"""#!/usr/bin/env bash
# A registry that serves a version only after FAKE_VISIBLE_AFTER lookups, behind
# an HTTP cache that answers repeat lookups locally unless --prefer-online.
set -u
state="$FAKE_STATE"
echo "$*" >> "$state/calls"
case "$1" in
  --version) echo 10.9.8; exit 0 ;;
  config) echo https://registry.example/; exit 0 ;;
  install|run) exit 0 ;;
  publish) touch "$state/published"; exit 0 ;;
  view)
    if [ -f "$state/published" ] && [ "$FAKE_VISIBLE_AFTER" -eq 0 ]; then
      echo "${2#*@}"; exit 0
    fi
    echo "npm error code E404" >&2; exit 1 ;;
  pack)
    if [ "$2" = "--dry-run" ]; then
      case " $* " in *" --json "*) echo '[{"files":[{"path":"package.json"},{"path":"lib/typert.remote-client.js"}]}]' ;; esac
      exit 0
    fi
    spec="$2"; dest="$4"
    online=0; case " $* " in *" --prefer-online "*) online=1 ;; esac
    if [ "$online" -eq 0 ] && [ -f "$state/cached-miss" ]; then
      echo "npm error code ETARGET" >&2
      echo "npm error notarget No matching version found for $spec." >&2
      exit 1
    fi
    n=$(( $(cat "$state/lookups" 2>/dev/null || echo 0) + 1 ))
    echo "$n" > "$state/lookups"
    if [ ! -f "$state/published" ] || [ "$n" -le "$FAKE_VISIBLE_AFTER" ]; then
      touch "$state/cached-miss"
      echo "npm error code ETARGET" >&2
      echo "npm error notarget No matching version found for $spec." >&2
      exit 1
    fi
    version="${spec#*@}"
    mkdir -p "$dest/package/lib"
    cp "$FAKE_PKG/package.json" "$dest/package/package.json"
    echo "// registry copy" > "$dest/package/lib/typert.remote-client.js"
    tar -czf "$dest/clawock-dsh-$version.tgz" -C "$dest" package
    rm -rf "$dest/package"
    echo "clawock-dsh-$version.tgz"
    exit 0 ;;
esac
echo "fake npm: unexpected $*" >&2
exit 2
"""


def run(tmp_path: Path, *args: str, visible_after: int, already_published: bool = False,
        timeout_s: int = 60) -> tuple[subprocess.CompletedProcess, list[str]]:
    bin_dir = tmp_path / "bin"
    state = tmp_path / "state"
    bin_dir.mkdir()
    state.mkdir()
    npm = bin_dir / "npm"
    npm.write_text(FAKE_NPM)
    npm.chmod(0o755)
    if already_published:
        (state / "published").touch()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "FAKE_STATE": str(state),
        "FAKE_PKG": str(PKG),
        "FAKE_VISIBLE_AFTER": str(visible_after),
        "DSH_READBACK_TIMEOUT_S": str(timeout_s),
        "DSH_READBACK_INTERVAL_S": "0",
    }
    env.pop("GITHUB_ACTIONS", None)
    result = subprocess.run(["bash", str(SCRIPT), *args], env=env, text=True,
                            capture_output=True, timeout=120)
    calls = (state / "calls").read_text().splitlines()
    return result, calls


def published(calls: list[str]) -> int:
    return sum(1 for call in calls if call.startswith("publish"))


def test_a_registry_that_serves_the_version_late_is_waited_out(tmp_path):
    result, calls = run(tmp_path, visible_after=3)

    assert result.returncode == 0, result.stdout + result.stderr
    assert published(calls) == 1
    assert "ok: 2 files, version" in result.stdout
    # Each retry was a real lookup, not a replay of the first cached miss, and
    # the log says why each one missed.
    assert "ETARGET" in result.stderr


def test_a_version_the_registry_never_serves_fails_red_with_npms_reason(tmp_path):
    result, calls = run(tmp_path, "--verify-only", visible_after=10**6, already_published=True,
                        timeout_s=0)

    assert result.returncode != 0
    assert "::error::the registry still does not serve clawock-dsh@" in result.stdout
    assert "ETARGET" in result.stdout
    assert published(calls) == 0, "--verify-only must never publish"


def test_a_rerun_does_not_publish_over_a_version_the_registry_holds(tmp_path):
    result, calls = run(tmp_path, visible_after=0, already_published=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert published(calls) == 0
    assert "already on the registry — skipping npm publish" in result.stdout
    assert "ok: 2 files, version" in result.stdout


def test_no_verify_publishes_and_leaves_the_readback_to_its_own_job(tmp_path):
    result, calls = run(tmp_path, "--no-verify", visible_after=10**6)

    assert result.returncode == 0, result.stdout + result.stderr
    assert published(calls) == 1
    assert not any(call.startswith("pack clawock-dsh@") for call in calls)


def test_the_release_is_not_held_hostage_by_the_readback():
    """github-release waits for both publishers to accept, not for the registry
    to finish processing: the 0.3.0 readback false-red skipped it."""
    import yaml

    jobs = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text())["jobs"]
    assert jobs["github-release"]["needs"] == ["publish", "npm"]
    assert jobs["npm-readback"]["needs"] == "npm"
    publish_step = json.dumps(jobs["npm"]["steps"])
    readback_step = json.dumps(jobs["npm-readback"]["steps"])
    assert "publish_dsh_plugin.sh --no-verify" in publish_step
    assert "publish_dsh_plugin.sh --verify-only" in readback_step
    # The job must outlast the script's own wait, or the timeout reports the wait.
    assert jobs["npm-readback"]["timeout-minutes"] * 60 > 900
