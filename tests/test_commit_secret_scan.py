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
    assert "TOOLS.md" in described and "Polygon.io" in described and "len=40" in described


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
