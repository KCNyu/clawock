"""How many places know which agent runtime we are on.

The goal is a standard, migratable harness — not something parasitic on one
runtime. That is either a fact or a wish, and the difference is countable: if
every module knows it is on OpenClaw, "it happens to run on OpenClaw" is
marketing; if only the adapter knows, it is architecture.

This is a ratchet, not a rewrite. Rewriting all the sites at once would touch
the watchdogs and system_check — the parts that tell us the live system is
healthy — which is a bad trade on a money system. So: record the count, fail if
it rises, lower it as consumers move behind `clawock.providers`.

Counting rule, and it matters
-----------------------------
A *label* naming `openclaw` as one source among several is the pattern we want,
not debt: `cron_timeline.py` already takes `--source gha|openclaw|crontab` and
treats all three as peers. A text matcher would punish that file and reward
deleting the wrong thing. So the classifier walks the AST and only counts a site
where the name is used to *invoke the binary or read its state*.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Where knowing about OpenClaw is correct: that is what an adapter is for.
ADAPTER = ROOT / "clawock" / "providers"

# Lower this as consumers move behind clawock.providers. It must never rise.
#
#   scripts/system_check.py                 7
#   scripts/data/sync_cron_payloads.py      1
#
# _watchdog_common reached 0 when delivery and the cron CLI moved behind
# clawock/providers/ (its 6 were the largest single block).
BASELINE = 8


def _is_invocation(source_lines: list[str], node: ast.AST, lineno: int) -> bool:
    """Whether this use of the name drives the binary rather than labels a source."""
    line = source_lines[lineno - 1] if lineno <= len(source_lines) else ""
    return any(marker in line for marker in ("subprocess", "cmd", "BIN", "run("))


def coupling_sites() -> dict[str, list[int]]:
    """Files outside the adapter that invoke OpenClaw or read its state."""
    sites: dict[str, list[int]] = {}
    for path in sorted(ROOT.glob("scripts/**/*.py")) + sorted(ROOT.glob("clawock/**/*.py")):
        if ADAPTER in path.parents:
            continue
        try:
            source = path.read_text()
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            continue
        lines = source.splitlines()
        # Docstrings are ast.Constant too. A docstring that *describes* an
        # OpenClaw call is documentation, not a call — counting it punishes
        # writing the comment, and the cheapest way to go green is deleting the
        # explanation. Collect their node ids and skip them.
        docstrings = set()
        for holder in ast.walk(tree):
            if isinstance(holder, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                   ast.AsyncFunctionDef)):
                body = getattr(holder, "body", None)
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    docstrings.add(id(body[0].value))
        found: list[int] = []
        for node in ast.walk(tree):
            # `OPENCLAW_BIN` is unambiguous: it exists to be executed.
            if isinstance(node, ast.Name) and node.id == "OPENCLAW_BIN":
                found.append(node.lineno)
                continue
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in docstrings:
                continue
            value = node.value.strip()
            # `"openclaw cron runs …"` is a command however it is assembled.
            if value.startswith("openclaw "):
                found.append(node.lineno)
            elif value == "openclaw" and _is_invocation(lines, node, node.lineno):
                found.append(node.lineno)
        if found:
            sites[path.relative_to(ROOT).as_posix()] = sorted(set(found))
    return sites


def test_the_runtime_coupling_count_never_rises():
    sites = coupling_sites()
    total = sum(len(lines) for lines in sites.values())

    detail = "\n".join(f"  {name}: {len(lines)} — lines {lines}"
                       for name, lines in sorted(sites.items()))
    assert total <= BASELINE, (
        f"runtime coupling rose to {total} (baseline {BASELINE}). New code must "
        f"go through clawock.providers, not call OpenClaw directly:\n{detail}")

    # A drop is the point of the exercise; make the reminder to lower the
    # baseline impossible to miss, so the ratchet cannot silently go slack.
    assert total >= BASELINE, (
        f"runtime coupling fell to {total} — lower BASELINE to {total} in this "
        "file so the gain is locked in")


def test_a_multi_source_label_is_not_counted_as_coupling():
    """`--source gha|openclaw|crontab` is the design we want. If the counter
    punished it, the cheapest way to go green would be to delete the wrong
    thing."""
    sites = coupling_sites()

    assert "scripts/data/cron_timeline.py" not in sites, (
        "cron_timeline treats openclaw as one source among three — counting it "
        "would reward removing multi-source support")


def test_the_adapter_is_exempt_because_that_is_what_an_adapter_is_for():
    sites = coupling_sites()

    assert not [name for name in sites if name.startswith("clawock/providers/")]
    # And the adapter must actually exist, or the exemption is hiding nothing.
    assert (ADAPTER / "delivery.py").exists()
