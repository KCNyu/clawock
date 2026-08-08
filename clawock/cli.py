#!/usr/bin/env python3
"""`clawock` — the entry point a stranger reaches for first.

Today the only honest thing it can do is answer "could this run against my
book?", which is precisely the question nobody could previously ask: without
package metadata or a workspace override, the code only ever operated on the
tree it lived in.

    clawock doctor                      # this checkout
    clawock doctor --workspace ~/mybook # someone else's
    CLAWOCK_WORKSPACE=~/mybook clawock doctor
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from clawock.tools import ToolError, build_registry
from clawock.tools import describe as describe_tools
from clawock.workspace import ENV_VAR, describe, workspace_root


def _doctor(args) -> int:
    default = args.workspace or Path.cwd()
    root = workspace_root(default)
    report = describe(root)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report["problems"] else 1

    print(f"workspace: {report['workspace']}")
    if report["holdings"] is not None:
        print(f"holdings:  {report['holdings']}")
    if not report["problems"]:
        # Deliberately narrow wording. This checks that a portfolio and an
        # instrument registry are present and structurally sane — nothing else.
        # It does not verify provider credentials, market-data reachability,
        # publisher configuration, scheduling or delivery, and a label that
        # implied otherwise would be the same overclaim this project keeps
        # correcting elsewhere.
        print("✅ portfolio and registry are readable and structurally sane")
        print("   not checked: credentials, market data, publisher, schedule, delivery")
        return 0
    print(f"❌ not runnable — {len(report['problems'])} problem(s):")
    for problem in report["problems"]:
        print(f"   · {problem}")
    print(f"\nPoint at another workspace with --workspace or ${ENV_VAR}.")
    return 1



def _report(args) -> int:
    """Assemble and judge a market report, in-process.

    Deliberately does NOT invoke scripts/harness/report_postflight.py. A CLI that
    re-executes the same scripts is a rename, not independence — so this calls the
    extracted core directly and works from an installed wheel with no repository
    checkout, no `openclaw`, no `git`.

    Delivery and publication are not done here: those are capability providers,
    and a report you can render without them is exactly the point of the split.
    """
    if args.harness_phase:
        return _harness(args, "report")

    from clawock.report import assemble_message, categorize, validate

    context = json.loads(Path(args.context).read_text())
    prose = Path(args.prose).read_text() if args.prose else sys.stdin.read()

    body = assemble_message(context, prose)
    issues = validate(body, context, prose_only=True, model_text=prose)
    verdict = categorize(issues)

    result = {
        "market": context.get("market"),
        "phase": context.get("phase"),
        "context_id": context.get("context_id"),
        "chars": len(body),
        "status": verdict,
        "issues": issues,
        "body": body,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(body)
        if issues:
            print(f"\n--- {verdict}: {len(issues)} issue(s) ---", file=sys.stderr)
            for issue in issues:
                print(f"  · {issue}", file=sys.stderr)
    return 0 if verdict == "pass" else 1


def _harness(args, workflow=None) -> int:
    """Drive the live instance through the package lifecycle, in-process."""
    from clawock.harness.runner import AdapterUnavailable, run_phase

    workflow = workflow or args.command
    phase = args.harness_phase
    forwarded = []
    for flag, value in (
        ("--market", getattr(args, "market", None)),
        ("--phase", getattr(args, "market_phase", None)),
        ("--context-id", getattr(args, "context_id", None)),
        ("--text-file", getattr(args, "text_file", None)),
    ):
        if value is not None:
            forwarded += [flag, str(value)]
    if getattr(args, "dry_run", False):
        forwarded.append("--dry-run")
    try:
        return run_phase(workflow, phase, forwarded,
                         workspace=getattr(args, "workspace", None))
    except AdapterUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _tool(args) -> int:
    """Reach a context tool through the registry instead of a path into scripts/.

    This is what makes the tool layer real (#266). Before it, `clawock.tools` had
    no caller outside its own tests: the skills reached the same data by running
    `python3 .../scripts/data/brief_decision_packet.py`, so the registry was an
    executable design document and the per-query byte budget — the hole #258
    actually closed — protected a path nobody took, because the callers that read
    context ARE the skills.

    `--list` prints the contract as JSON, so a non-OpenClaw runner can discover
    the tools instead of re-deriving them from Chinese prose in a SKILL.md.
    """
    root = workspace_root(args.workspace or Path.cwd())
    registry = build_registry(root)
    if args.list:
        print(describe_tools(root, args.dialect))
        return 0
    if not args.name:
        print("a tool name is required (or --list)", file=sys.stderr)
        return 2
    params: dict[str, str] = {}
    for item in args.arg or []:
        key, sep, value = item.partition("=")
        if not sep:
            print(f"--arg must be key=value, got {item!r}", file=sys.stderr)
            return 2
        params[key] = value
    try:
        print(registry.call(args.name, **params))
    except (ToolError, ValueError) as exc:
        # A refusal is the tool working, not the CLI failing: report it on stderr
        # with a non-zero exit so a caller can tell it apart from real output,
        # and never print a traceback into the middle of a model turn.
        # ValueError is in here for one specific reason: the 24 KiB budget raises
        # it from bounded_payload, so the single most likely refusal on this path
        # would otherwise be the one thing that crashes instead of refusing.
        print(f"{args.name}: {exc}", file=sys.stderr)
        return 1
    return 0


def _context(args) -> int:
    """Audit or assemble the runtime-neutral context contract (#366)."""
    from clawock.context import assemble, audit

    root = workspace_root(args.workspace or Path.cwd())
    if args.context_command == "audit":
        result = audit(root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1

    try:
        bundle = assemble(root, skills=args.skill or ())
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(bundle.manifest(), ensure_ascii=False, indent=2))
    else:
        print(bundle.text, end="")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="clawock", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="can this workspace run the loop?")
    doctor.add_argument("--workspace", type=Path, default=None)
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=_doctor)

    report = sub.add_parser(
        "report", help="assemble and validate a market report from a context file")
    report.add_argument("harness_phase", nargs="?", choices=("preflight", "postflight"),
                        help="run the live harness phase in-process")
    report.add_argument("--context", type=Path,
                        help="preflight context JSON")
    report.add_argument("--prose", type=Path, default=None,
                        help="model prose; reads stdin when omitted")
    report.add_argument("--json", action="store_true")
    report.add_argument("--market", choices=("hk", "us"))
    report.add_argument("--phase", dest="market_phase",
                        choices=("open", "mid", "pm", "close"))
    report.add_argument("--context-id")
    report.add_argument("--text-file", type=Path)
    report.add_argument("--workspace", type=Path, default=None)
    report.set_defaults(func=_report)

    for workflow in ("brief", "intraday"):
        harness = sub.add_parser(workflow, help=f"run {workflow} harness in-process")
        harness.add_argument("harness_phase", choices=("preflight", "postflight"))
        harness.add_argument("--market", choices=("hk", "us"))
        harness.add_argument("--context-id")
        harness.add_argument("--text-file", type=Path)
        harness.add_argument("--dry-run", action="store_true")
        harness.add_argument("--workspace", type=Path, default=None)
        harness.set_defaults(func=_harness)

    tool = sub.add_parser(
        "tool", help="call a context tool through the registry")
    tool.add_argument("name", nargs="?", help="tool name, e.g. decision_packet_query")
    tool.add_argument("--arg", action="append", metavar="KEY=VALUE",
                      help="tool argument; repeatable")
    tool.add_argument("--list", action="store_true",
                      help="print the tool contract as JSON and exit")
    tool.add_argument("--dialect", choices=("openai", "anthropic"), default="openai")
    tool.add_argument("--workspace", type=Path, default=None)
    tool.set_defaults(func=_tool)

    context = sub.add_parser(
        "context", help="audit or assemble the agent context contract")
    context_sub = context.add_subparsers(dest="context_command", required=True)
    context_audit = context_sub.add_parser(
        "audit", help="verify OpenClaw bootstrap files without loading exclusions")
    context_audit.add_argument("--workspace", type=Path, default=None)
    context_audit.set_defaults(func=_context)
    context_assemble = context_sub.add_parser(
        "assemble", help="render the bootstrap and explicitly selected skills")
    context_assemble.add_argument("--workspace", type=Path, default=None)
    context_assemble.add_argument("--skill", action="append",
                                  help="load this skill body; repeatable")
    context_assemble.add_argument("--json", action="store_true",
                                  help="print assembly manifest, not prompt text")
    context_assemble.set_defaults(func=_context)

    args = parser.parse_args(argv)
    if args.command == "report" and not args.harness_phase and not args.context:
        parser.error("clawock report requires --context, or preflight/postflight")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
