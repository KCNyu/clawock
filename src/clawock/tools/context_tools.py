"""The four capabilities the brief skill already drives, given a schema.

Each one delegates to the code that implements it today — `read_packet`,
`summary_view`, `bounded_payload` in `brief_decision_packet.py`. Nothing here
reimplements the protocol; it exposes it. That is deliberate: the generation
pin, the hash check and the per-query byte budget are load-bearing and already
tested, and a second copy of them would be a second thing to get wrong.

The workspace is passed in rather than resolved from `__file__`, because these
tools have to work against a foreign workspace — that is the whole point.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from clawock.tools import BaseTool, ToolError

SECTIONS = ("facts", "technical", "quant", "sentiment", "evidence", "risk",
            "constraints")


def _load(workspace, module: str):
    """Import a workspace's own data module.

    Not a subprocess, and not a copy: these tools read *that workspace's*
    protocol, so importing that workspace's implementation is the honest
    resolution. A wheel installed elsewhere still works — it just needs a
    workspace to point at, exactly like `portfolio.json`.
    """
    path = Path(workspace) / "scripts" / "data" / f"{module}.py"
    if not path.exists():
        raise ToolError(f"{module}.py not found in workspace {workspace}")
    data_dir = str(path.parent)
    if data_dir not in sys.path:
        sys.path.insert(0, data_dir)
    spec = importlib.util.spec_from_file_location(module, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def _manifest(workspace, manifest) -> Path:
    path = Path(manifest)
    if not path.is_absolute():
        path = Path(workspace) / path
    if not path.exists():
        raise ToolError(f"manifest not found: {path}")
    return path


class _PacketTool(BaseTool):
    @classmethod
    def check_available(cls, workspace) -> bool:
        return (Path(workspace) / "scripts" / "data"
                / "brief_decision_packet.py").exists()


class DecisionPacketSummary(_PacketTool):
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
        packet_module = _load(workspace, "brief_decision_packet")
        packet = packet_module.read_packet(_manifest(workspace, manifest))
        return packet_module.bounded_payload(packet_module.summary_view(packet))


class DecisionPacketQuery(_PacketTool):
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
        packet_module = _load(workspace, "brief_decision_packet")
        packet = packet_module.read_packet(_manifest(workspace, manifest))
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
        return packet_module.bounded_payload(payload)


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

    @classmethod
    def check_available(cls, workspace) -> bool:
        return (Path(workspace) / "scripts" / "data" / "brief_context.py").exists()

    def execute(self, workspace, *, manifest: str, bundle: str) -> str:
        path = _manifest(workspace, manifest)
        entry = ((json.loads(path.read_text(encoding="utf-8")).get("artifacts") or {})
                 .get(bundle))
        if not entry:
            available = sorted(
                (json.loads(path.read_text(encoding="utf-8")).get("artifacts") or {}))
            raise ToolError(
                f"unknown bundle {bundle!r}; manifest lists: {', '.join(available)}")
        target = Path(entry.get("path") or "")
        if not target.exists():
            raise ToolError(f"bundle {bundle!r} is listed but missing: {target}")
        return target.read_text(encoding="utf-8")


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


TOOLS = (DecisionPacketSummary, DecisionPacketQuery, ContextBundle, ReportContext)
