"""The report core must run without the repository, OpenClaw, or git.

Codex's bar for this slice: a CLI that shells out to
`scripts/harness/report_postflight.py` is a rename, not independence. So the
test forces the ways out to be unavailable and asserts a validated report is
still produced.

Two tests only — these are the two things that would actually make the claim
false.
"""
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CONTEXT = {
    "market": "hk", "phase": "close", "context_id": "hk-close-fixture",
    "title": "港股收盘 08/02",
    "raw_wechat_block": "恒指 25,031 ▲0.27%",
}
PROSE = "▎情绪面\n市场情绪平稳。\n\n▎技术面\n07226 收 4.20。\n\n▎操作建议\n维持观望。\n"


def test_report_runs_with_no_openclaw_no_git_and_no_scripts_directory(tmp_path):
    (tmp_path / "ctx.json").write_text(json.dumps(CONTEXT, ensure_ascii=False))
    (tmp_path / "prose.txt").write_text(PROSE)

    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    env = {
        "PATH": str(empty_bin),          # no openclaw, no git, no gh
        "PYTHONPATH": str(ROOT / "src"),  # the package; `scripts/` is not importable
        "HOME": str(tmp_path),
        "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8",
    }
    done = subprocess.run(
        [sys.executable, "-c",
         "from clawock.cli import main; import sys; sys.exit(main(sys.argv[1:]))",
         "report", "--context", str(tmp_path / "ctx.json"),
         "--prose", str(tmp_path / "prose.txt"), "--json"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=90)

    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert result["status"] == "pass"
    # The delivered body is harness-owned data + model prose, not the prose alone.
    assert CONTEXT["raw_wechat_block"] in result["body"]
    assert "▎操作建议" in result["body"]


def test_the_core_never_re_invokes_the_harness_scripts():
    """The facade this slice exists to avoid. Checked through the AST, because
    both modules legitimately *mention* report_postflight.py in prose."""
    offenders = []
    for name in ("report.py", "cli.py", "validation.py"):
        tree = ast.parse((ROOT / "src" / "clawock" / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"run", "Popen",
                                                                 "check_output"}:
                value = node.value
                if isinstance(value, ast.Name) and value.id == "subprocess":
                    offenders.append(f"{name}:{node.lineno}")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mod = getattr(node, "module", "") or ""
                names = {a.name for a in node.names}
                if mod == "subprocess" or "subprocess" in names:
                    offenders.append(f"{name}:{node.lineno} imports subprocess")

    assert not offenders, (
        "the package core shells out — that is the facade this slice rejects: "
        f"{offenders}")
