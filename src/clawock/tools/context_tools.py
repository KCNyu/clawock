"""Package-owned context capabilities exposed to external agent runtimes.

The protocol implementation ships in ``clawock``. The workspace argument points
only at user artifacts and data; it is never searched for executable Python.
"""
from __future__ import annotations

from pathlib import Path

from clawock.context import brief as brief_context
from clawock.decision import packet as brief_decision_packet
from clawock.tools.base import BaseTool, ToolError

# The packet module owns this: it is what builds the rows, and a hand-kept
# second copy here is how `information` (and four others) ended up unqueryable.
SECTIONS = brief_decision_packet.QUERYABLE_SECTIONS


def _manifest(workspace, manifest) -> Path:
    path = Path(manifest)
    if not path.is_absolute():
        path = Path(workspace) / path
    if not path.exists():
        raise ToolError(f"manifest not found: {path}")
    return path


class DecisionPacketSummary(BaseTool):
    name = "decision_packet_summary"
    description = (
        "The brief's resident input: book and concentration, per-ticker "
        "deterministic status, technical and factor availability, risk counts, "
        "allowed actions and evidence IDs. Read this first; query individual "
        "tickers only when analysing them."
    )
    parameters = {
        "type": "object",
        "properties": {
            "manifest": {
                "type": "string",
                "description": "Path to the generation's manifest.json.",
            },
        },
        "required": ["manifest"],
    }

    def execute(self, workspace, *, manifest: str) -> str:
        packet = brief_decision_packet.read_packet(_manifest(workspace, manifest))
        # The summary budget, not the per-query one. #723 raised the ceiling but
        # only on packet.py's own CLI path; this tool is what the brief agent
        # actually calls, and it kept the 24KB default — so the fix was live in
        # the source and still dead in production, which is the exact shape the
        # inert-fix rule exists for. The test below pins this call site.
        return brief_decision_packet.bounded_payload(
            brief_decision_packet.summary_view(packet),
            brief_decision_packet.MAX_SUMMARY_BYTES,
        )


class DecisionPacketQuery(BaseTool):
    name = "decision_packet_query"
    description = (
        "One ticker's slice of the decision packet, optionally narrowed to a "
        "single section. Prefer a section: whole-ticker queries are larger and "
        "the per-query budget is enforced."
    )
    parameters = {
        "type": "object",
        "properties": {
            "manifest": {"type": "string",
                         "description": "Path to the generation's manifest.json."},
            "ticker": {"type": "string", "description": "Ticker, e.g. 00100."},
            "section": {"type": "string", "enum": list(SECTIONS),
                        "description": "Narrow to one dimension."},
        },
        "required": ["manifest", "ticker"],
    }

    def execute(self, workspace, *, manifest: str, ticker: str,
                section: str | None = None) -> str:
        if section is not None and section not in SECTIONS:
            raise ToolError(
                f"unknown section {section!r}; expected one of {', '.join(SECTIONS)}")
        packet = brief_decision_packet.read_packet(_manifest(workspace, manifest))
        value = (packet.get("tickers") or {}).get(str(ticker))
        if value is None:
            raise ToolError(f"unknown ticker: {ticker}")
        # `_meta` carries the generation_id, and a narrowed payload must keep it:
        # the whole protocol is generation-pinned and postflight validates a report
        # against the exact generation the model read. The CLI path has always
        # attached it here; the tool dropped it, so every section query through the
        # registry was silently un-pinned (found by wiring the first real consumer,
        # #266 — nothing else would have shown it).
        payload = value if section is None else {
            "_meta": packet.get("_meta"),
            "ticker": str(ticker),
            section: value.get(section),
        }
        # The budget is applied here, not on a print path — that is the bug this
        # layer exists to close: every non-CLI caller used to bypass the cap.
        return brief_decision_packet.bounded_payload(payload)


class DecisionPacketJudgmentTemplate(BaseTool):
    name = "decision_packet_judgment_template"
    description = (
        "A generation-pinned template containing only the judgment fields the "
        "external agent may fill."
    )
    parameters = {
        "type": "object",
        "properties": {
            "manifest": {"type": "string",
                         "description": "Path to the generation's manifest.json."},
        },
        "required": ["manifest"],
    }

    def execute(self, workspace, *, manifest: str) -> str:
        packet = brief_decision_packet.read_packet(_manifest(workspace, manifest))
        return brief_decision_packet.bounded_payload(
            brief_decision_packet.judgment_template(packet)
        )


class ContextBundle(BaseTool):
    name = "context_bundle"
    description = (
        "An audit bundle from the same generation — deep detail that is not in "
        "the packet. Load at most one per consumer, immediately before use; this "
        "is not default model input."
    )
    parameters = {
        "type": "object",
        "properties": {
            "manifest": {"type": "string",
                         "description": "Path to the generation's manifest.json."},
            "bundle": {"type": "string",
                       "description": "Bundle name as listed in the manifest."},
        },
        "required": ["manifest", "bundle"],
    }

    def execute(self, workspace, *, manifest: str, bundle: str) -> str:
        return brief_context.read_artifact(_manifest(workspace, manifest), bundle)


class ReportContext(BaseTool):
    name = "report_context"
    description = (
        "The deterministic context for one market report slot: the title and the "
        "harness-owned data block that will be prepended to the prose."
    )
    parameters = {
        "type": "object",
        "properties": {
            "market": {"type": "string", "enum": ["hk", "us"]},
            "phase": {"type": "string",
                      "description": "Slot, e.g. open / mid / pm / close."},
            "date": {"type": "string", "description": "YYYY-MM-DD."},
        },
        "required": ["market", "phase", "date"],
    }

    @classmethod
    def check_available(cls, workspace) -> bool:
        return (Path(workspace) / "memory" / ".tmp").exists()

    def execute(self, workspace, *, market: str, phase: str, date: str) -> str:
        path = (Path(workspace) / "memory" / ".tmp"
                / f"report-context-{market}-{phase}-{date}.json")
        if not path.exists():
            raise ToolError(f"no report context for {market}/{phase} on {date}")
        return path.read_text(encoding="utf-8")


TOOLS = (
    DecisionPacketSummary,
    DecisionPacketQuery,
    DecisionPacketJudgmentTemplate,
    ContextBundle,
    ReportContext,
)
