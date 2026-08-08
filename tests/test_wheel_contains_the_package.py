"""What we ship must contain what we claim to ship.

`packages = ["clawock"]` is an exact list in setuptools, so `clawock.providers`
and `clawock.tools` were absent from every wheel built after they were added.
`pip install clawock` followed by `import clawock.providers.openclaw` raised
ModuleNotFoundError, and `scripts/harness/_watchdog_common.py` — imported by all
three watchdogs — imports exactly that.

Nothing caught it, for three separate reasons, and each one is a lesson about
where to point a test:

* every workflow installs with `pip install -e .`, and an editable install leaves
  the source tree on `sys.path`, so the wheel's contents never matter in CI;
* the live host does not install the package at all — it reaches the source
  through `sys.path` inserts;
* `test_package_surface.py` reads `clawock/*.py` in the source tree, and
  `test_report_core_is_independent.py` proves independence with
  `PYTHONPATH=<repo root>` — also the source tree. Both assert things about code
  we did not ship.

So this test builds the artifact and imports out of it. Nothing that reads the
source tree can replace it, because the source tree is the thing that lied.

Mutation check: pin the declaration back to `packages = ["clawock"]` and this
goes red on the first subpackage.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Everything the wheel build reads. Copied to a clean directory first, because a
# leftover `clawock.egg-info` in the checkout makes setuptools reuse the previous
# build's package list — which masks a wrong declaration completely. That is how
# this test passed under mutation the first time it was written.
BUILD_INPUTS = ("pyproject.toml", "README.md", "LICENSE", "NOTICE")


def _modules_in_source() -> set[str]:
    """Importable dotted names for every module under clawock/ in the checkout."""
    names = set()
    for path in sorted((ROOT / "clawock").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(ROOT).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts.pop()
        names.add(".".join(parts))
    return names


def test_every_module_imports_from_a_non_editable_install(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    shutil.copytree(ROOT / "clawock", source / "clawock",
                    ignore=shutil.ignore_patterns("__pycache__"))
    for name in BUILD_INPUTS:
        origin = ROOT / name
        assert origin.exists(), f"{name} is declared as a build input but is missing"
        shutil.copy2(origin, source / name)

    build = tmp_path / "wheel"
    done = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-cache-dir",
         "-w", str(build), str(source)],
        capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, f"wheel build failed:\n{done.stderr[-2000:]}"

    wheels = list(build.glob("clawock-*.whl"))
    assert len(wheels) == 1, f"expected one wheel, got {wheels}"

    site = tmp_path / "site"
    done = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--no-index",
         "--target", str(site), str(wheels[0])],
        capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, f"install failed:\n{done.stderr[-2000:]}"

    modules = sorted(_modules_in_source())
    assert "clawock.providers.openclaw" in modules, (
        "the module the watchdogs import went missing from the source tree — "
        "fix this test's expectations deliberately, not reflexively")

    # cwd is tmp_path and PYTHONPATH is the install target only: the checkout is
    # not reachable, so an import can only succeed out of the installed artifact.
    done = subprocess.run(
        [sys.executable, "-c",
         "import importlib, sys\n"
         "for name in sys.argv[1:]:\n"
         "    importlib.import_module(name)\n"
         "print('ok')"] + modules,
        cwd=tmp_path,
        env={"PYTHONPATH": str(site), "PATH": "/usr/bin:/bin",
             "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8"},
        capture_output=True, text=True, timeout=120)

    assert done.returncode == 0, (
        "a module in the source tree is not importable from the built wheel — "
        "the shipped package is not the package:\n" + done.stderr[-2000:])

    # Importable was never the claim. `OpenClawRuns` used to import
    # `_watchdog_common` — which lives in scripts/harness and is not shipped —
    # *inside* the method, so it imported cleanly from an installation and
    # raised ModuleNotFoundError the first time anyone called it. The chain has
    # no runtime to talk to here, so the answer is an empty history; that it
    # answers at all is the point.
    done = subprocess.run(
        [sys.executable, "-c",
         "from clawock.providers.runs import OpenClawRuns\n"
         "runs = OpenClawRuns().history('any-job')\n"
         "assert isinstance(runs, list), runs\n"
         "print('ok')"],
        cwd=tmp_path,
        env={"PYTHONPATH": str(site), "PATH": "/usr/bin:/bin",
             "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8"},
        capture_output=True, text=True, timeout=120)

    assert done.returncode == 0, (
        "the run-history provider is importable from the wheel but not callable "
        "there, so it is a provider only where the checkout happens to be:\n"
        + done.stderr[-2000:])

    # Importability still is not the product claim. Drive the complete portable
    # lifecycle exactly as an external agent does from the installed wheel:
    # init -> certified prepare -> agent-owned output -> validate/publication.
    workspace = tmp_path / "book"
    clean_env = {
        "PYTHONPATH": str(site), "PATH": "/usr/bin:/bin",
        "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8",
    }
    discovered = subprocess.run(
        [sys.executable, "-m", "clawock", "workflow", "list"],
        cwd=tmp_path, env=clean_env, capture_output=True, text=True, timeout=120)
    assert discovered.returncode == 0, discovered.stderr
    assert {item["id"] for item in json.loads(discovered.stdout)} == {
        "investment-decision"}

    installed = subprocess.run(
        [sys.executable, "-m", "clawock", "workflow", "install",
         "investment-decision", "--workspace", str(workspace)],
        cwd=tmp_path, env=clean_env, capture_output=True, text=True, timeout=120)
    assert installed.returncode == 0, installed.stderr
    skill = workspace / ".agents/skills/investment-decision"
    assert (skill / "SKILL.md").read_text().startswith(
        "---\nname: investment-decision\n")

    initialized = subprocess.run(
        [sys.executable, "-m", "clawock", "init", str(workspace),
         "--workflow", "investment-decision"],
        cwd=tmp_path, env=clean_env, capture_output=True, text=True, timeout=120)
    assert initialized.returncode == 0, initialized.stderr

    prepared = subprocess.run(
        [sys.executable, "-m", "clawock", "run", "prepare",
         "--workspace", str(workspace)],
        cwd=tmp_path, env=clean_env, capture_output=True, text=True, timeout=120)
    assert prepared.returncode == 0, prepared.stderr
    request = json.loads(prepared.stdout)
    assert request["context"]["documents"][0]["sha256"]
    assert request["workflow"]["id"] == "investment-decision"
    assert len(request["workflow"]["certificate"]) == 64

    # This copy stands in for decision.json produced by OpenClaw, Hermes, Claude
    # Code, Codex or another caller. clawock does not start that agent.
    decision = workspace / "decision.json"
    decision.write_text((skill / "assets/decision.example.json").read_text())
    completed = subprocess.run(
        [sys.executable, "-m", "clawock", "run", "publish",
         "--workspace", str(workspace), "--request", request["request_file"],
         "--artifact", "decision.json=decision.json"],
        cwd=tmp_path, env=clean_env, capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(completed.stdout)
    assert receipt["status"] == "published"
    published = Path(receipt["publish"]["receipt"])
    manifest = json.loads((published / "manifest.json").read_text())
    assert json.loads((published / "decision.json").read_text())["decision"][
        "action"] == "watch"
    assert manifest["generation_id"] == receipt["generation_id"]
    assert manifest["workflow"] == request["workflow"]
    assert {item["generation_id"] for item in receipt["artifacts"]} == {
        receipt["generation_id"]}
