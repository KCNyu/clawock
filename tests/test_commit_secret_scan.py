"""The CI scan of a range's added lines catches the shapes the 2026-03-11 leak had (#2033).

The leak put three market-data keys into TOOLS.md (a `**Provider**: value` line —
Markdown, which the pre-commit hook skips on purpose) and into scripts as named
assignments, a quoted `api_key = '…'` literal and a `token=` URL. Each shape is
pinned here with a synthetic value built at runtime, so this file never carries
a literal the scan itself would report. The other direction is pinned too: the
identifiers and placeholders that sit next to those names in today's tree must
stay quiet, or the gate is something people learn to route around.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "commit_secret_scan", ROOT / "ops" / "ci" / "commit_secret_scan.py")
scan = importlib.util.module_from_spec(spec)
sys.modules["commit_secret_scan"] = scan
assert spec.loader is not None
spec.loader.exec_module(scan)

KEY40 = "c9a7" * 10
KEY16 = "Q3" * 8
# Built at runtime too: .githooks/pre-commit flags `FINNHUB_API_KEY = <word>` literally.
FH = "FINNHUB" + "_API_KEY"


def _patch(path: str, *added: str) -> str:
    body = "\n".join(f"+{line}" for line in added)
    return f"commit {'a' * 40}\ndiff --git a/{path} b/{path}\n+++ b/{path}\n{body}\n"


@pytest.mark.parametrize("path,line", [
    ("TOOLS.md", f"- **Finnhub**: `{KEY40}`"),
    ("TOOLS.md", f"- **Alpha Vantage**: {KEY16}"),
    ("final_analysis.py", f"{FH} = '{KEY40}'"),
    ("scripts/run.sh", f'export POLYGON_API_KEY="{KEY40}"'),
    (".env.example", f"TAVILY_API_KEY={KEY40}"),
    ("check_ai_stocks.py", f"api_key = '{KEY40}'"),
    ("fetch.py", f"url = f'https://finnhub.io/api/v1/quote?symbol=X&token={KEY40}'"),
    ("notes.md", f"used sk-{KEY40} for the probe"),
    ("bot.py", f'TELEGRAM_BOT_TOKEN = "{str(12345) * 2}:{KEY40}"'),
])
def test_every_shape_the_leak_had_is_reported(path, line):
    findings = scan.scan_diff(_patch(path, line))
    assert len(findings) == 1
    assert findings[0].path == path


@pytest.mark.parametrize("line", [
    "api_key = get_finnhub_key()",
    f"{FH} = os.environ['{FH}']",
    'POLYGON_API_KEY="${POLYGON_API_KEY:-}"',
    f"{FH}=YOUR_{FH}_HERE",
    f"url = f'https://finnhub.io/api/v1/quote?symbol={{t}}&token={{{FH}}}'",
    "- **Finnhub**: set FINNHUB_API_KEY in .api_keys",
    "risk-on-with-trend-conflict",
])
def test_names_identifiers_and_placeholders_stay_quiet(line):
    assert scan.scan_diff(_patch("x.py", line)) == []


def test_only_added_lines_count():
    patch = (f"commit {'b' * 40}\n+++ b/TOOLS.md\n-{FH} = '{KEY40}'\n"
             f"+{FH} is read from .api_keys\n")
    assert scan.scan_diff(patch) == []


def test_the_report_never_contains_the_value():
    finding, = scan.scan_diff(_patch("TOOLS.md", f"- **Polygon.io**: {KEY40}"))
    described = finding.describe()
    assert KEY40 not in described
    assert (finding.path, finding.name) == ("TOOLS.md", "Polygon.io")
    assert described.startswith(f"{'a' * 9} TOOLS.md: ") and "len=40" in described


def test_a_real_commit_range_is_scanned_end_to_end(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    (tmp_path / "README.md").write_text("hello\n")
    git("add", "README.md")
    git("commit", "-qm", "base")
    (tmp_path / "TOOLS.md").write_text(f"### API Keys\n- **Finnhub**: {KEY40}\n")
    git("add", "TOOLS.md")
    git("commit", "-qm", "leak")

    result = subprocess.run(
        ["python3", str(ROOT / "ops" / "ci" / "commit_secret_scan.py"), "--range", "HEAD~1..HEAD"],
        cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 1
    assert "TOOLS.md" in result.stdout and KEY40 not in result.stdout + result.stderr

    clean = subprocess.run(
        ["python3", str(ROOT / "ops" / "ci" / "commit_secret_scan.py"), "--range", "HEAD~1..HEAD~1"],
        cwd=tmp_path, capture_output=True, text=True)
    assert clean.returncode == 0


def test_master_pre_push_scans_a_pure_data_commit(tmp_path):
    """Pure data does not start CI, so the host hook must stop a bad push."""
    import shutil

    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True,
                              capture_output=True, text=True).stdout.strip()

    git("init", "-q")
    git("config", "user.name", "KCNyu")
    git("config", "user.email", "shengyu.li.evgeny@gmail.com")
    (tmp_path / ".githooks").mkdir()
    (tmp_path / "ops/ci").mkdir(parents=True)
    (tmp_path / "ops/publish").mkdir()
    for name in ("pre-push", "_identity_check.sh"):
        shutil.copy2(ROOT / ".githooks" / name, tmp_path / ".githooks" / name)
    shutil.copy2(ROOT / "ops/ci/commit_secret_scan.py",
                 tmp_path / "ops/ci/commit_secret_scan.py")
    (tmp_path / "ops/system_check.py").write_text("import sys\nsys.exit(0)\n")
    (tmp_path / "ops/publish/money_checker.sh").write_text(
        "run_money_check() { return 0; }\n")
    (tmp_path / "README.md").write_text("seed\n")
    git("add", "README.md")
    git("commit", "-qm", "seed")
    base = git("rev-parse", "HEAD")
    (tmp_path / "assets/data").mkdir(parents=True)
    (tmp_path / "assets/data/note.md").write_text(f"- **Finnhub**: {KEY40}\n")
    git("add", "assets/data/note.md")
    git("commit", "-qm", "runtime data")
    head = git("rev-parse", "HEAD")
    result = subprocess.run(
        ["bash", str(tmp_path / ".githooks/pre-push")], cwd=tmp_path,
        capture_output=True, text=True,
        input=f"refs/heads/master {head} refs/heads/master {base}\n")
    assert result.returncode != 0
    assert "master update failed credential scan" in result.stdout
    assert KEY40 not in result.stdout + result.stderr
