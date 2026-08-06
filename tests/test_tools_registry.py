"""Three things that would make the tool layer worse than no tool layer.

1. A schema that lies about what `execute` accepts — a model calling it gets a
   TypeError inside its own turn, which is strictly worse than prose.
2. The per-query byte budget bypassed. It used to live only on the CLI print
   path, so every non-CLI caller silently skipped it; that is the bug this layer
   exists to close.
3. A missing dependency exploding instead of excluding the tool.
"""
import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clawock.tools import BaseTool, ToolError, build_registry  # noqa: E402
from clawock.tools import context_tools  # noqa: E402


def test_every_declared_schema_matches_what_execute_accepts():
    """A schema is a promise to the model. Drift here is invisible until a run
    fails mid-turn."""
    problems = []
    for tool_cls in context_tools.TOOLS:
        tool = tool_cls()
        signature = inspect.signature(tool.execute)
        accepted = {name for name, p in signature.parameters.items()
                    if p.kind is inspect.Parameter.KEYWORD_ONLY}
        declared = set((tool.parameters or {}).get("properties", {}))
        required = set((tool.parameters or {}).get("required", []))

        if declared - accepted:
            problems.append(f"{tool.name}: declares {sorted(declared - accepted)} "
                            "which execute() does not accept")
        if accepted - declared:
            problems.append(f"{tool.name}: execute() takes {sorted(accepted - declared)} "
                            "which the schema never mentions")
        missing_default = {
            name for name in accepted - required
            if signature.parameters[name].default is inspect.Parameter.empty}
        if missing_default:
            problems.append(f"{tool.name}: {sorted(missing_default)} is optional in the "
                            "schema but has no default in execute()")

    assert not problems, problems


def test_the_query_budget_is_enforced_through_the_tool(tmp_path, monkeypatch):
    """The cap lived only in the CLI's print path. Any caller using
    read_packet()/summary_view() directly — i.e. every non-CLI consumer —
    bypassed it."""
    packet_module = type(sys)("brief_decision_packet")
    packet_module.MAX_QUERY_BYTES = 24 * 1024

    def bounded_payload(value):
        text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        if len(text.encode()) > packet_module.MAX_QUERY_BYTES:
            raise ValueError("decision packet query exceeds")
        return text

    packet_module.bounded_payload = bounded_payload
    packet_module.read_packet = lambda path: {
        "tickers": {"00100": {"technical": {"blob": "x" * 40_000}}}}
    monkeypatch.setattr(context_tools, "_load", lambda ws, mod: packet_module)

    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    tool = context_tools.DecisionPacketQuery()

    with pytest.raises(ValueError, match="exceeds"):
        tool.execute(tmp_path, manifest=str(manifest), ticker="00100",
                     section="technical")


def test_a_tool_whose_dependency_is_missing_is_excluded_not_raised(tmp_path):
    """`check_available` is the difference between a shorter tool list and a
    traceback in the middle of a model turn."""
    registry = build_registry(tmp_path)          # empty dir: no scripts/, no memory/

    assert registry.names() == []
    with pytest.raises(ToolError, match="unknown tool"):
        registry.call("decision_packet_summary", manifest="x")


def test_schemas_render_for_both_dialects():
    class Fake(BaseTool):
        name = "fake"
        description = "  spaced  "
        parameters = {"type": "object", "properties": {"a": {"type": "string"}},
                      "required": ["a"]}

    assert Fake().to_openai_schema()["function"]["name"] == "fake"
    assert Fake().to_anthropic_schema()["input_schema"]["required"] == ["a"]
    # Descriptions are what the model reads; leading whitespace is noise.
    assert Fake().to_anthropic_schema()["description"] == "spaced"


def test_the_cli_consumer_refuses_an_over_budget_query_instead_of_crashing(
        tmp_path, monkeypatch, capsys):
    """The budget must hold for the consumer that actually reads context (#266).

    The sibling test above proves `execute` enforces the cap by raising. That is
    only half the guarantee once a real caller exists: `bounded_payload` raises
    ValueError, not ToolError, so a CLI that caught only ToolError would turn the
    single most likely refusal on this path into a traceback printed into the
    middle of a model turn — the exact failure the tool layer exists to prevent.
    """
    from clawock import cli

    packet_module = type(sys)("brief_decision_packet")
    packet_module.MAX_QUERY_BYTES = 24 * 1024

    def bounded_payload(value):
        text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        if len(text.encode()) > packet_module.MAX_QUERY_BYTES:
            raise ValueError("decision packet query exceeds")
        return text

    packet_module.bounded_payload = bounded_payload
    packet_module.read_packet = lambda path: {
        "_meta": {"generation_id": "gen"},
        "tickers": {"00100": {"technical": {"blob": "x" * 40_000}}}}
    monkeypatch.setattr(context_tools, "_load", lambda ws, mod: packet_module)
    monkeypatch.setattr(
        context_tools.DecisionPacketQuery, "check_available",
        classmethod(lambda cls, ws: True))

    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")

    code = cli.main(["tool", "decision_packet_query", "--workspace", str(tmp_path),
                     "--arg", f"manifest={manifest}", "--arg", "ticker=00100",
                     "--arg", "section=technical"])

    captured = capsys.readouterr()
    assert code == 1, "an over-budget query must fail, not print a giant payload"
    assert "exceeds" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out.strip() == ""


def test_a_narrowed_query_keeps_the_generation_pin(tmp_path, monkeypatch):
    """A section query must carry `_meta` (#266).

    The protocol is generation-pinned and postflight validates a report against
    the generation the model actually read. The CLI path always attached `_meta`
    here; the tool dropped it, so every narrowed query through the registry was
    silently un-pinned — invisible until a real consumer compared the two.
    """
    packet_module = type(sys)("brief_decision_packet")
    packet_module.bounded_payload = lambda value: json.dumps(value)
    packet_module.read_packet = lambda path: {
        "_meta": {"generation_id": "gen-abc"},
        "tickers": {"00100": {"technical": {"tag": "trend-off"}}}}
    monkeypatch.setattr(context_tools, "_load", lambda ws, mod: packet_module)

    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    payload = json.loads(context_tools.DecisionPacketQuery().execute(
        tmp_path, manifest=str(manifest), ticker="00100", section="technical"))

    assert payload["_meta"]["generation_id"] == "gen-abc"
