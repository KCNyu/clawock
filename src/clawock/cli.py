#!/usr/bin/env python3
"""`clawock` — portable decision workflows for external agent runtimes.

An agent-native plugin kit backed by a verifiable execution harness. Existing
external agents call ``clawock run`` to certify inputs and validate/publish their
artifacts; the model, conversation, memory, skills and tool loop stay external.
The package owns lifecycle phases and selects their values/resources through a
declarative profile.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from clawock.tools import ToolError, build_registry
from clawock.tools import describe as describe_tools
from clawock.workspace import ENV_VAR, describe, workspace_root


def _init(args) -> int:
    from clawock.harness.config import initialize

    try:
        root = initialize(args.workspace, workflow=args.workflow)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"initialized clawock workspace: {root}")
    print(f"edit {root / 'clawock.json'} and {root / 'CONTEXT.md'}")
    if args.workflow:
        print(f"workflow: {args.workflow}")
    return 0


def _run_prepare(args) -> int:
    from clawock.harness import AgentRun
    from clawock.harness.config import load_request
    from clawock.publish.store import write_generation

    try:
        request = load_request(args.workspace)
        prepared = AgentRun().prepare(request)
        state = request.workspace / ".clawock" / "work" / prepared.run_id / "request.json"
        payload = prepared.as_dict()
        payload["request_file"] = str(state)
        write_generation({
            str(state): json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        })
        state.chmod(0o600)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _run_publish(args) -> int:
    from clawock.context.assembly import assemble_explicit
    from clawock.harness import AgentRun, PreparedRun
    from clawock.harness.config import load_request
    from clawock.publish import FilesystemStore

    try:
        request = load_request(args.workspace)
        state_path = args.request.expanduser().resolve()
        state_root = (request.workspace / ".clawock" / "work").resolve()
        if not state_path.is_relative_to(state_root):
            # The boundary is deliberate — a request from anywhere else has no
            # provenance — but `relative_to` reports it as a raw ValueError, and
            # "'/x/req.json' is not in the subpath of '/x/.clawock/work'" tells a
            # first-time user nothing about what to do instead.
            raise ValueError(
                f"prepared request must live under {state_root}; `clawock run prepare` "
                f"writes one to {state_root}/<run_id>/request.json — pass that path")
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("prepared request requires schema_version 1")
        run_id = payload.get("run_id")
        generation_id = payload.get("generation_id")
        if not all(
            isinstance(value, str) and len(value) == 32
            and all(char in "0123456789abcdef" for char in value)
            for value in (run_id, generation_id)
        ):
            raise ValueError("prepared request has invalid run/generation IDs")
        if payload.get("task") != request.task:
            raise ValueError("workspace task changed after this run was prepared")
        if payload.get("output_directory") != str(request.output_directory):
            raise ValueError("workspace output directory changed after this run was prepared")
        if payload.get("metadata") != dict(request.metadata):
            raise ValueError("workspace metadata changed after this run was prepared")
        if payload.get("workflow", {}) != dict(request.workflow):
            raise ValueError("workspace workflow changed after this run was prepared")
        context = assemble_explicit(request.workspace, request.context_files)
        supplied_context = payload.get("context")
        if not isinstance(supplied_context, dict) or (
            supplied_context.get("certificate") != context.certificate()
        ):
            raise ValueError("workspace context changed after this run was prepared")

        artifacts: dict[str, str] = {}
        for item in args.artifact:
            name, separator, raw_path = item.partition("=")
            if not separator:
                raise ValueError(f"--artifact must be NAME=PATH, got {item!r}")
            source = Path(raw_path).expanduser()
            if not source.is_absolute():
                source = request.workspace / source
            source = source.resolve()
            if not source.is_relative_to(request.workspace):
                raise ValueError(
                    f"artifact {name!r} is outside the workspace: {source}")
            if name in artifacts:
                raise ValueError(f"duplicate artifact name: {name}")
            artifacts[name] = source.read_text(encoding="utf-8")

        prepared = PreparedRun(request, context, run_id, generation_id)
        receipt = AgentRun().publish(
            prepared,
            artifacts,
            FilesystemStore(request.output_directory / run_id),
        )
        result = receipt.as_dict()
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if receipt.status == "published" else 1


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


def _calendar(args) -> int:
    """Run the package-owned HK/US session guard."""
    from clawock.sessions import main as calendar_main

    forwarded = [args.market]
    if args.date:
        forwarded += ["--date", args.date]
    if args.session != "full":
        forwarded += ["--session", args.session]
    if args.quiet:
        forwarded.append("--quiet")
    return calendar_main(forwarded)


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

    from clawock.harness.report import assemble_message, categorize, validate

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
        ("--date", getattr(args, "date", None)),
    ):
        if value is not None:
            forwarded += [flag, str(value)]
    if getattr(args, "dry_run", False):
        forwarded.append("--dry-run")
    try:
        return run_phase(workflow, phase, forwarded,
                         workspace=getattr(args, "workspace", None),
                         profile=getattr(args, "runtime_profile", None))
    except (AdapterUnavailable, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _profile(args) -> int:
    """Validate and describe the selected declarative product profile."""
    from clawock.config.profiles import describe_profile, load_profile

    root = Path(args.workspace or Path.cwd()).expanduser().resolve()
    try:
        profile = load_profile(root, args.profile)
        payload = describe_profile(profile)
        payload["resolved_resources"] = {
            key: str(profile.resource_path(key)) for key in profile.resources
        }
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _tool(args) -> int:
    """Reach a context tool through the registry instead of a path into scripts/.

    This is what makes the tool layer real (#266). Before it, `clawock.tools` had
    no caller outside its own tests: the skills reached the same data by running
    a source-checkout script, so the registry was an
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
    from clawock.context.assembly import (
        assemble,
        audit,
        audit_all,
        compare_prompt_reports,
        load_prompt_report,
        verify_prompt_report,
    )

    root = workspace_root(getattr(args, "workspace", None) or Path.cwd())
    try:
        if args.context_command == "audit":
            # No --profile means every profile, not the manifest default: the
            # obvious invocation has to be the safe one (#380).
            result = (audit(root, profile=args.profile) if args.profile
                      else audit_all(root))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 1
        if args.context_command == "compare":
            result = compare_prompt_reports(
                load_prompt_report(
                    args.before, session_key=args.before_session_key
                ),
                load_prompt_report(
                    args.after, session_key=args.after_session_key
                ),
                profile=args.profile,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 1
        if args.context_command == "verify":
            result = verify_prompt_report(
                load_prompt_report(args.report, session_key=args.session_key),
                profile=args.profile,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 1
        bundle = assemble(
            root, skills=args.skill or (), profile=args.profile
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(bundle.manifest(), ensure_ascii=False, indent=2))
    else:
        print(bundle.text, end="")
    return 0


def _packaged_utility(args) -> int:
    """Dispatch package-owned ledgers and deterministic output utilities."""
    import importlib

    module = importlib.import_module(PACKAGED_UTILITIES[args.command])
    if (args.command in DOCSTRING_HELP_UTILITIES
            and set(args.utility_args) & {"-h", "--help"}):
        print(f"usage: clawock {args.command} [flags]\n")
        print((module.__doc__ or "no module documentation").strip())
        return 0
    if args.command in HARD_EXIT_UTILITIES:
        module.hard_exit(module.main(args.utility_args))
    return module.main(args.utility_args)

def _workflow(args) -> int:
    """Discover or install portable Agent Skills shipped by clawock."""
    from clawock.publish.store import write_generation
    from clawock.workflows import (
        apply_proposal,
        create_proposal,
        evaluate_files,
        install_workflow,
        list_workflows,
        load_workflow,
        review_proposal,
        render_workflow_schema,
        rollback_change,
    )

    def emit(payload):
        serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        output = getattr(args, "output", None)
        if output is not None:
            write_generation({str(output.expanduser().resolve()): serialized})
        print(serialized, end="")

    def changes():
        parsed = {}
        for item in args.set:
            name, separator, raw = item.partition("=")
            if not separator or not name:
                raise ValueError(f"--set must be NAME=JSON_VALUE, got {item!r}")
            if name in parsed:
                raise ValueError(f"duplicate workflow parameter: {name}")
            try:
                parsed[name] = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"--set value for {name} must be a JSON number"
                ) from exc
        return parsed

    try:
        if args.workflow_command == "list":
            payload = [
                {
                    "id": pack.workflow_id,
                    "version": pack.version,
                    "description": pack.descriptor["description"],
                    "certificate": pack.certificate,
                }
                for pack in list_workflows()
            ]
            emit(payload)
            return 0
        if args.workflow_command == "show":
            emit(load_workflow(args.workflow_id).as_dict())
            return 0
        if args.workflow_command == "schema":
            emit(render_workflow_schema(
                args.workflow_id, args.artifact, dialect=args.dialect
            ))
            return 0
        if args.workflow_command == "evaluate":
            emit(evaluate_files(args.workflow_id, args.decision, args.outcome))
            return 0
        if args.workflow_command == "propose":
            emit(create_proposal(
                args.workspace,
                args.trigger,
                changes(),
                rationale=args.rationale,
                expected_effect=args.expected_effect,
            ))
            return 0
        if args.workflow_command == "review":
            emit(review_proposal(
                args.proposal,
                disposition=args.decision,
                reviewer=args.reviewer,
                note=args.note,
            ))
            return 0
        if args.workflow_command == "apply":
            emit(apply_proposal(args.workspace, args.proposal, args.review))
            return 0
        if args.workflow_command == "rollback":
            emit(rollback_change(args.workspace, args.change_id))
            return 0
        root = args.skill_root
        if root is None:
            root = args.workspace.expanduser().resolve() / ".agents" / "skills"
        destination = install_workflow(
            args.workflow_id, root, force=args.force
        )
        emit({
            "workflow": args.workflow_id,
            "installed": str(destination),
            "skill": str(destination / "SKILL.md"),
        })
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


# The command registry moved to `clawock.utilities` (#814): two harness
# preflights need `PACKAGED_UTILITIES`, and reaching up into the CLI entry point
# for it made `harness` and `cli` mutually dependent. Re-exported here because
# `clawock.cli.PACKAGED_UTILITIES` is referenced by ops/ and by five tests.
from clawock.utilities import (  # noqa: F401  (re-export)
    DOCSTRING_HELP_UTILITIES,
    HARD_EXIT_UTILITIES,
    PACKAGED_UTILITIES,
    UTILITY_HELP,
)


def _editable_drift(distribution) -> str:
    """The checkout an editable install runs, when it no longer declares that version.

    An editable install has two versions: the number pip recorded when it ran,
    and the code the checkout holds now. They separate on the first merge after
    the install, and only the stale one is printed — which is how #745 was
    written. `clawock --version` said 0.1.5 on a host whose checkout was three
    releases further on, so a command that was genuinely broken (`record`, see
    PACKAGED_UTILITIES) was diagnosed as "the installed package is too old", and
    the proposed remedy was a release nobody needed. The desk runs the checkout
    on purpose — docs/operations/release.md § Running the latest code on this
    host — so the honest answer names both numbers and where the code is.

    Returns "" for a normal wheel install, or when the checkout cannot be read.
    """
    import json
    import tomllib
    from urllib.parse import unquote, urlparse

    try:
        raw = distribution.read_text("direct_url.json")
        origin = json.loads(raw) if raw else {}
        if not origin.get("dir_info", {}).get("editable"):
            return ""
        parsed = urlparse(origin.get("url", ""))
        if parsed.scheme != "file":
            return ""
        checkout = Path(unquote(parsed.path))
        declared = tomllib.loads(
            (checkout / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]["version"]
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return ""
    if declared == distribution.version:
        return ""
    return (f" (editable install of {checkout}, which now declares {declared} — "
            "the code that runs is the checkout's; re-run "
            "ops/host/install_clawock_launcher.sh to refresh this metadata)")


def _installed_version() -> str:
    """What pip actually put on this machine, or a sentinel saying it did not.

    A source tree that was never installed has no distribution metadata, and
    inventing a number for it would be the drift this indirection exists to
    avoid — so it says so instead. An editable install is a third case:
    `_editable_drift` above says why it gets a suffix instead of a number.
    """
    from importlib.metadata import PackageNotFoundError, distribution

    try:
        installed = distribution("clawock")
    except PackageNotFoundError:
        return "0+unknown (running from an uninstalled source tree)"
    return installed.version + _editable_drift(installed)


def main(argv=None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv and raw_argv[0] in PACKAGED_UTILITIES:
        return _packaged_utility(argparse.Namespace(
            command=raw_argv[0], utility_args=raw_argv[1:]
        ))

    parser = argparse.ArgumentParser(prog="clawock", description=__doc__)
    # The first command anyone runs after `pip install`, and until now the one
    # command that failed: argparse rejected `--version` as an unknown argument
    # and answered with exit 2 plus the whole 50-subcommand usage block. Someone
    # checking which artifact pip gave them got a wall of text and a failure.
    #
    # Read from installed distribution metadata rather than a literal, for the
    # reason `tests/test_versions_agree.py` records: a restated number survives
    # the bump that was supposed to change it, and the stale copy is the one the
    # user is shown. `clawock.__version__` stays absent on purpose — that file
    # explains why — so this reads the distribution directly.
    parser.add_argument(
        "--version", action="version", version=f"clawock {_installed_version()}")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a standalone clawock workspace")
    init.add_argument("workspace", type=Path)
    init.add_argument("--workflow", help="pin a packaged decision workflow")
    init.set_defaults(func=_init)

    run = sub.add_parser(
        "run", help="certify and publish one external decision-workflow run")
    run_steps = run.add_subparsers(dest="run_command", required=True)
    prepare = run_steps.add_parser("prepare", help="emit certified run input as JSON")
    prepare.add_argument("--workspace", type=Path, default=Path.cwd())
    prepare.set_defaults(func=_run_prepare)
    publish = run_steps.add_parser(
        "publish", help="validate and publish artifacts produced by the calling agent")
    publish.add_argument("--workspace", type=Path, default=Path.cwd())
    publish.add_argument(
        "--request", type=Path, required=True,
        help="the request `clawock run prepare` wrote to "
             ".clawock/work/<run_id>/request.json")
    publish.add_argument("--artifact", action="append", default=[], metavar="NAME=PATH")
    publish.set_defaults(func=_run_publish)

    doctor = sub.add_parser(
        "doctor", help="audit portfolio and registry prerequisites")
    doctor.add_argument("--workspace", type=Path, default=None)
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=_doctor)

    calendar = sub.add_parser(
        "calendar", help="check whether an HK or US market session is open")
    calendar.add_argument("market", choices=("hk", "us"))
    calendar.add_argument("--date", help="YYYY-MM-DD; defaults to today in market TZ")
    calendar.add_argument(
        "--session", choices=("full", "morning", "afternoon"), default="full")
    calendar.add_argument("--quiet", action="store_true")
    calendar.set_defaults(func=_calendar)

    profile = sub.add_parser(
        "profile", help="validate and describe a declarative runtime profile")
    profile.add_argument("profile", help="profile id or workspace-relative JSON path")
    profile.add_argument("--workspace", type=Path, default=None)
    profile.set_defaults(func=_profile)

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
    report.add_argument(
        "--profile", dest="runtime_profile",
        help="declarative product profile id or workspace-relative JSON path")
    report.set_defaults(func=_report)

    for workflow in ("brief", "intraday"):
        harness = sub.add_parser(workflow, help=f"run {workflow} harness in-process")
        # `render` is brief-only: it is the step that turns the model's judgment
        # into the published report, and only the brief has one.
        phases = (("preflight", "postflight", "render") if workflow == "brief"
                  else ("preflight", "postflight"))
        harness.add_argument("harness_phase", choices=phases)
        harness.add_argument("--market", choices=("hk", "us"))
        harness.add_argument("--context-id")
        harness.add_argument("--text-file", type=Path)
        harness.add_argument("--date", help="artifact date (render; default today)")
        harness.add_argument("--dry-run", action="store_true")
        harness.add_argument("--workspace", type=Path, default=None)
        harness.add_argument(
            "--profile", dest="runtime_profile",
            help="declarative product profile id or workspace-relative JSON path")
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

    for name in PACKAGED_UTILITIES:
        utility = sub.add_parser(name, help=UTILITY_HELP[name], add_help=False)
        utility.add_argument("utility_args", nargs=argparse.REMAINDER)
        utility.set_defaults(func=_packaged_utility)

    context = sub.add_parser(
        "context", help="audit or assemble the agent context contract")
    context_sub = context.add_subparsers(dest="context_command", required=True)
    context_audit = context_sub.add_parser(
        "audit", help="verify the OpenClaw context profiles and capability roots")
    context_audit.add_argument("--workspace", type=Path, default=None)
    context_audit.add_argument(
        # No default on purpose. It used to be "isolated-cron", so the bare
        # command silently audited the five-file profile and reported ok while a
        # file only the seven-file interactive profile requires was missing (#380).
        "--profile", default=None,
        help="audit one profile instead of all: interactive, isolated-cron, "
             "heartbeat-full/light, bootstrap-pending or subagent",
    )
    context_audit.set_defaults(func=_context)
    context_assemble = context_sub.add_parser(
        "assemble", help="render the bootstrap and explicitly selected skills")
    context_assemble.add_argument("--workspace", type=Path, default=None)
    context_assemble.add_argument("--profile", default="isolated-cron")
    context_assemble.add_argument("--skill", action="append",
                                  help="load this skill body; repeatable")
    context_assemble.add_argument("--json", action="store_true",
                                  help="print assembly manifest, not prompt text")
    context_assemble.set_defaults(func=_context)
    context_compare = context_sub.add_parser(
        "compare", help="compare before/after OpenClaw system-prompt reports")
    context_compare.add_argument("--profile", required=True)
    context_compare.add_argument("--before", type=Path, required=True)
    context_compare.add_argument("--after", type=Path, required=True)
    context_compare.add_argument("--before-session-key")
    context_compare.add_argument("--after-session-key")
    context_compare.set_defaults(func=_context)
    context_verify = context_sub.add_parser(
        "verify",
        help="check one OpenClaw system-prompt report against its profile")
    context_verify.add_argument("--profile", required=True)
    context_verify.add_argument("--report", type=Path, required=True)
    context_verify.add_argument("--session-key")
    context_verify.set_defaults(func=_context)

    workflow = sub.add_parser(
        "workflow", help="discover or install portable decision-workflow skills")
    workflow_sub = workflow.add_subparsers(dest="workflow_command", required=True)
    workflow_list = workflow_sub.add_parser("list", help="list packaged workflows")
    workflow_list.set_defaults(func=_workflow)
    workflow_show = workflow_sub.add_parser("show", help="print a workflow contract")
    workflow_show.add_argument("workflow_id")
    workflow_show.set_defaults(func=_workflow)
    workflow_schema = workflow_sub.add_parser(
        "schema", help="export an artifact schema for an external runtime")
    workflow_schema.add_argument("workflow_id")
    workflow_schema.add_argument("artifact")
    workflow_schema.add_argument(
        "--dialect", choices=("canonical", "codex"), default="canonical",
        help="canonical validation schema or Codex structured-output subset",
    )
    workflow_schema.add_argument("--output", type=Path)
    workflow_schema.set_defaults(func=_workflow)
    workflow_install = workflow_sub.add_parser(
        "install", help="install a workflow as a standard Agent Skill")
    workflow_install.add_argument("workflow_id")
    workflow_install.add_argument("--workspace", type=Path, default=Path.cwd())
    workflow_install.add_argument("--skill-root", type=Path, default=None)
    workflow_install.add_argument("--force", action="store_true")
    workflow_install.set_defaults(func=_workflow)
    workflow_evaluate = workflow_sub.add_parser(
        "evaluate", help="reconcile a decision with observed price and FX evidence")
    workflow_evaluate.add_argument("workflow_id")
    workflow_evaluate.add_argument("--decision", type=Path, required=True)
    workflow_evaluate.add_argument("--outcome", type=Path, required=True)
    workflow_evaluate.add_argument("--output", type=Path)
    workflow_evaluate.set_defaults(func=_workflow)
    workflow_propose = workflow_sub.add_parser(
        "propose", help="create a bounded parameter proposal from measured evidence")
    workflow_propose.add_argument("--workspace", type=Path, default=Path.cwd())
    workflow_propose.add_argument("--trigger", type=Path, required=True)
    workflow_propose.add_argument("--set", action="append", required=True,
                                  metavar="NAME=JSON_VALUE")
    workflow_propose.add_argument("--rationale", required=True)
    workflow_propose.add_argument("--expected-effect", required=True)
    workflow_propose.add_argument("--output", type=Path)
    workflow_propose.set_defaults(func=_workflow)
    workflow_review = workflow_sub.add_parser(
        "review", help="accept or reject one exact proposal")
    workflow_review.add_argument("--proposal", type=Path, required=True)
    workflow_review.add_argument("--decision", choices=("accepted", "rejected"),
                                 required=True)
    workflow_review.add_argument("--reviewer", required=True)
    workflow_review.add_argument("--note", required=True)
    workflow_review.add_argument("--output", type=Path)
    workflow_review.set_defaults(func=_workflow)
    workflow_apply = workflow_sub.add_parser(
        "apply", help="apply an accepted proposal and write a rollback record")
    workflow_apply.add_argument("--workspace", type=Path, default=Path.cwd())
    workflow_apply.add_argument("--proposal", type=Path, required=True)
    workflow_apply.add_argument("--review", type=Path, required=True)
    workflow_apply.set_defaults(func=_workflow)
    workflow_rollback = workflow_sub.add_parser(
        "rollback", help="restore the parameters recorded before an applied change")
    workflow_rollback.add_argument("--workspace", type=Path, default=Path.cwd())
    workflow_rollback.add_argument("--change-id", required=True)
    workflow_rollback.set_defaults(func=_workflow)

    args = parser.parse_args(raw_argv)
    if args.command == "report" and not args.harness_phase and not args.context:
        parser.error("clawock report requires --context, or preflight/postflight")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
