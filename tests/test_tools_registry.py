"""Three things that would make the tool layer worse than no tool layer.

1. A schema that lies about what `execute` accepts — a model calling it gets a
   TypeError inside its own turn, which is strictly worse than prose.
2. The per-query byte budget bypassed. It used to live only on the CLI print
   path, so every non-CLI caller silently skipped it; that is the bug this layer
   exists to close.
3. A package-owned tool disappearing just because a workspace has no source tree.
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
    def bounded_payload(value):
        text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        if len(text.encode()) > 24 * 1024:
            raise ValueError("decision packet query exceeds")
        return text

    monkeypatch.setattr(context_tools.brief_decision_packet,
                        "bounded_payload", bounded_payload)
    monkeypatch.setattr(context_tools.brief_decision_packet, "read_packet", lambda path: {
        "tickers": {"00100": {"technical": {"blob": "x" * 40_000}}}}
    )

    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    tool = context_tools.DecisionPacketQuery()

    with pytest.raises(ValueError, match="exceeds"):
        tool.execute(tmp_path, manifest=str(manifest), ticker="00100",
                     section="technical")


def test_package_tools_exist_without_python_source_in_the_workspace(tmp_path):
    """A wheel supplies behavior; a user's workspace supplies only artifacts."""
    registry = build_registry(tmp_path)  # empty dir: no scripts/, no memory/

    assert registry.names() == [
        "context_bundle",
        "decision_packet_judgment_template",
        "decision_packet_query",
        "decision_packet_summary",
    ]
    with pytest.raises(ToolError, match="manifest not found"):
        registry.call("decision_packet_summary", manifest="x")


def test_package_tools_read_a_real_generation_without_workspace_code(tmp_path):
    source = {"date": "2026-08-08", "quant_signals": {"signal": "verified"}}
    generation_id = context_tools.brief_context.compute_generation_id(source)
    packet = {
        "_meta": {"schema_version": 1, "kind": "brief_decision_packet",
                  "generation_id": generation_id},
        "tickers": {"TEST": {}},
    }
    _, manifest = context_tools.brief_context.write_run_bundle(
        source,
        tmp_path / "brief-context.json",
        tool_artifacts={"decision_packet": packet},
    )
    registry = build_registry(tmp_path)

    bundle = json.loads(registry.call(
        "context_bundle", manifest=manifest["manifest_path"], bundle="research"
    ))
    template = json.loads(registry.call(
        "decision_packet_judgment_template", manifest=manifest["manifest_path"]
    ))

    assert bundle["_meta"]["generation_id"] == generation_id
    assert bundle["quant_signals"] == {"signal": "verified"}
    assert template["context_generation_id"] == generation_id
    assert template["ticker_judgments"][0]["ticker"] == "TEST"


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

    def bounded_payload(value):
        text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        if len(text.encode()) > 24 * 1024:
            raise ValueError("decision packet query exceeds")
        return text

    monkeypatch.setattr(context_tools.brief_decision_packet,
                        "bounded_payload", bounded_payload)
    monkeypatch.setattr(context_tools.brief_decision_packet, "read_packet", lambda path: {
        "_meta": {"generation_id": "gen"},
        "tickers": {"00100": {"technical": {"blob": "x" * 40_000}}}}
    )

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
    monkeypatch.setattr(
        context_tools.brief_decision_packet,
        "bounded_payload",
        lambda value: json.dumps(value),
    )
    monkeypatch.setattr(context_tools.brief_decision_packet, "read_packet", lambda path: {
        "_meta": {"generation_id": "gen-abc"},
        "tickers": {"00100": {"technical": {"tag": "trend-off"}}}}
    )

    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    payload = json.loads(context_tools.DecisionPacketQuery().execute(
        tmp_path, manifest=str(manifest), ticker="00100", section="technical"))

    assert payload["_meta"]["generation_id"] == "gen-abc"


def test_the_summary_tool_uses_the_summary_budget_not_the_query_budget(tmp_path, monkeypatch):
    """The brief agent calls this tool, not packet.py's CLI.

    #723 gave the whole-book summary its own 48KB budget, but only on the CLI
    path in packet.py. `DecisionPacketSummary.execute` kept `bounded_payload`'s
    24KB default, so the live `clawock tool decision_packet_summary` still died
    with `exceeds 24576 bytes: 33543` on a merged fix — right in source, dead in
    production. This pins the call site that actually matters.
    """
    seen = {}

    def bounded_payload(value, limit=context_tools.brief_decision_packet.MAX_QUERY_BYTES):
        seen["limit"] = limit
        return json.dumps(value, ensure_ascii=False)

    monkeypatch.setattr(context_tools.brief_decision_packet, "bounded_payload", bounded_payload)
    monkeypatch.setattr(context_tools.brief_decision_packet, "read_packet", lambda path: {"tickers": {}})
    monkeypatch.setattr(context_tools.brief_decision_packet, "summary_view", lambda packet: {"ok": True})

    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    context_tools.DecisionPacketSummary().execute(tmp_path, manifest=str(manifest))

    assert seen["limit"] == context_tools.brief_decision_packet.MAX_SUMMARY_BYTES, (
        "the summary must be serialised against MAX_SUMMARY_BYTES; the per-query "
        "default is what took the 盘前简报 down on 2026-08-17"
    )


def test_a_real_sized_summary_survives_the_tool_layer(tmp_path, monkeypatch):
    """End-to-end through the tool, at the size that actually broke: a summary
    over the 24KB query cap must come back rather than raise."""
    big = {"tickers": [{"ticker": f"TK{i:02d}", "blob": "x" * 2_600} for i in range(11)]}

    monkeypatch.setattr(context_tools.brief_decision_packet, "read_packet", lambda path: {"tickers": {}})
    monkeypatch.setattr(context_tools.brief_decision_packet, "summary_view", lambda packet: big)

    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")

    out = context_tools.DecisionPacketSummary().execute(tmp_path, manifest=str(manifest))
    size = len(out.encode())
    assert size > context_tools.brief_decision_packet.MAX_QUERY_BYTES, (
        "the fixture has to be past the old cap or this proves nothing"
    )
    assert size < context_tools.brief_decision_packet.MAX_SUMMARY_BYTES
