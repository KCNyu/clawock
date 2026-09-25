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


def slice_reference(value, *, ticker=None, since=None):
    """One ticker's rows, or the rows at/after HH:MM, of a reference entry.

    Shapes in the intraday context: a list of rows (`signals_detail`), a dict
    with `rows` (radar, setups), a dict keyed by ticker (`peer_scan`,
    `t0_setups.rows`), or a list of text lines (`headline_feed`). Anything
    else is returned whole.
    """
    import re  # noqa: PLC0415

    def hit(row):
        if ticker is not None:
            if isinstance(row, dict):
                ok = (ticker in (str(row.get('ticker')), str(row.get('label')),
                                 str(row.get('issuer')))
                      or ticker in (row.get('holdings') or []))
            else:
                ok = ticker in str(row)
            if not ok:
                return False
        if since is not None:
            stamp = row if not isinstance(row, dict) else ' '.join(
                str(row.get(key) or '') for key in ('time', 'published_at', 'date', 'as_of'))
            times = re.findall(r'(\d{2}:\d{2})', str(stamp))
            if times and times[0] < since:
                return False
        return True

    if isinstance(value, list):
        return [row for row in value if hit(row)]
    if isinstance(value, dict):
        if ticker is not None and ticker in value:
            return {ticker: value[ticker]}
        out = {}
        for key, item in value.items():
            if isinstance(item, list):
                out[key] = [row for row in item if hit(row)]
            elif isinstance(item, dict) and ticker is not None and ticker in item:
                out[key] = {ticker: item[ticker]}
            elif ticker is None:
                out[key] = item
        return out
    return value


class IntradayReference(BaseTool):
    name = "intraday_reference"
    description = (
        "One reference-layer entry of an intraday slot's context (the core packet's "
        "index lists them), pinned to that slot's context_id; optionally one "
        "ticker's rows or the rows since HH:MM."
    )
    parameters = {
        "type": "object",
        "properties": {
            "market": {"type": "string", "enum": ["hk", "us"]},
            "context_id": {"type": "string",
                           "description": "context_id from the core packet."},
            "entry": {"type": "string",
                      "description": "Entry name from index.references."},
            "ticker": {"type": "string", "description": "Only this ticker's rows."},
            "since": {"type": "string", "description": "Only rows at/after HH:MM."},
        },
        "required": ["market", "context_id", "entry"],
    }

    @classmethod
    def check_available(cls, workspace) -> bool:
        return (Path(workspace) / "memory" / ".tmp").exists()

    def execute(self, workspace, *, market: str, context_id: str, entry: str,
                ticker: str | None = None, since: str | None = None) -> str:
        # `entry`, not `name`: ToolRegistry.call takes the tool name positionally.
        name = entry
        import json  # noqa: PLC0415

        from clawock.context.intraday_layers import REFERENCE_ENTRIES  # noqa: PLC0415

        if name not in REFERENCE_ENTRIES:
            raise ToolError(f"{name!r} is not a reference entry; the core packet has "
                            "every other field")
        tmp = Path(workspace) / "memory" / ".tmp"
        candidates = [tmp / f"intraday-context-{market}-latest.json",
                      *sorted(tmp.glob(f"intraday-context-{market}-*.json"), reverse=True)[:40]]
        for path in candidates:
            try:
                ctx = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if ctx.get("context_id") == context_id:
                break
        else:
            raise ToolError(f"no {market} intraday context with context_id {context_id}")
        if name not in ctx:
            raise ToolError(f"{name!r} is not in context {context_id}")
        value = ctx[name]
        if ticker is not None or since is not None:
            value = slice_reference(value, ticker=ticker, since=since)
        return json.dumps(value, ensure_ascii=False, indent=2)


TOOLS = (
    DecisionPacketSummary,
    DecisionPacketQuery,
    DecisionPacketJudgmentTemplate,
    ContextBundle,
    ReportContext,
    IntradayReference,
)
