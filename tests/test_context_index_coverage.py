"""Whatever context the agent is given must actually index the tools.

A skill or research script that exists but appears in no index is unreachable: a
cron session reads `BOOTSTRAP.md` (force-injected) and the `CLAUDE.md`/`AGENTS.md`
required reads, and finds tools through `TOOLS.md`. Five skill directories —
including the 08:00 brief's own — were absent from `TOOLS.md` when these tests were
written, and none of the research-lifecycle scripts were mentioned anywhere in it.

The index also has a budget: openclaw injects the bootstrap file under
`bootstrapMaxChars` (16000 at the time of writing), and `TOOLS.md` is kept inside
the same budget so the index cannot be truncated halfway.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = (ROOT / "TOOLS.md").read_text(encoding="utf-8")
BOOTSTRAP = (ROOT / "BOOTSTRAP.md").read_text(encoding="utf-8")
CLAUDE_MD = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
AGENTS_MD = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
INJECTION_BUDGET_CHARS = 16000

RESEARCH_SCRIPTS = (
    "entry_gate.py", "earnings_review.py", "thesis_registry.py",
    "research_provenance.py", "research_surface.py",
)
RESEARCH_LOCATIONS = {
    name: (ROOT / "src" / "clawock" / name
           if name == "research_provenance.py"
           else ROOT / "scripts" / "data" / name)
    for name in RESEARCH_SCRIPTS
}
ARTIFACT_DIRS = ("memory/entry-gates", "memory/earnings", "memory/theses")


def skill_names():
    return sorted(
        path.parent.name for path in (ROOT / "skills").glob("*/SKILL.md")
    )


def test_every_skill_is_indexed_in_tools_md():
    # Backticked, the way the index actually names a skill. A bare substring test
    # passes on accidents: `github` "appeared" four times in TOOLS.md purely
    # through `github.com` and `kcnyu.github.io` URLs while the skill itself was
    # unindexed.
    missing = [name for name in skill_names() if f"`{name}`" not in TOOLS]
    assert missing == [], f"skills unreachable from TOOLS.md: {missing}"


def test_shared_skill_fragments_are_explained_rather_than_left_dangling():
    # skills/_shared carries no SKILL.md, so the coverage test above skips it; it
    # still has to be findable, or an agent edits one leg's copy of a shared rule.
    assert (ROOT / "skills" / "_shared").is_dir()
    assert "skills/_shared/" in TOOLS


def test_every_research_script_is_indexed_in_tools_md():
    missing = [name for name in RESEARCH_SCRIPTS if f"`{name}`" not in TOOLS]
    assert missing == [], f"research scripts unreachable from TOOLS.md: {missing}"
    for path in RESEARCH_LOCATIONS.values():
        assert path.exists()


def test_bootstrap_states_the_research_lifecycle_rules():
    # The injected file, not just the optional read, has to carry the rules that
    # decide whether a session may open exposure or restate a thesis.
    for token in ("entry_gate.py", "earnings-review", "thesis_registry.py",
                  "research_provenance.py", "research_surface"):
        assert token in BOOTSTRAP, f"BOOTSTRAP.md never mentions {token}"
    assert "gray_needs_evidence" in BOOTSTRAP


def test_artifact_directories_are_discoverable_from_the_entry_pointers():
    for directory in ARTIFACT_DIRS:
        assert (ROOT / directory).is_dir()
        assert (ROOT / directory / "README.md").exists()
        assert directory in TOOLS or directory in BOOTSTRAP, (
            f"{directory} is not reachable from the injected context"
        )


def test_required_reads_still_point_at_the_index():
    for text in (CLAUDE_MD, AGENTS_MD):
        assert "TOOLS.md" in text


def test_injected_context_stays_inside_the_budget():
    assert len(BOOTSTRAP) <= INJECTION_BUDGET_CHARS, len(BOOTSTRAP)
    assert len(TOOLS) <= INJECTION_BUDGET_CHARS, len(TOOLS)
    # Leave real headroom rather than sitting on the cap: the index grows every
    # time a tool is added, and a truncated index is worse than a missing one.
    assert len(TOOLS) <= INJECTION_BUDGET_CHARS * 0.9, len(TOOLS)


def test_cadence_decisions_are_written_down_and_linked():
    cadence = ROOT / "docs" / "operations" / "research-cadence.md"
    assert cadence.exists()
    text = cadence.read_text(encoding="utf-8")
    for row in ("every push", "daily", "on new evidence", "on the report"):
        assert row in text
    assert "research-cadence.md" in TOOLS
    assert "research-cadence.md" in (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
