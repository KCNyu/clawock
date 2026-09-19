#!/usr/bin/env python3
"""Generate the command inventory in `docs/reference/commands.md`.

The document the README calls "the full command and provider catalog" was
hand-maintained, so nothing noticed when a command was added, renamed or
removed (#489). The inventory half is now derived from the two command
registries in the single `clawock` distribution that
`config/information-layers.json` partitions:

- `clawock.utilities.PACKAGED_UTILITIES` — the public CLI's own dispatch table;
- `[project.scripts]` in the root `pyproject.toml`.

Both are read from source rather than imported, so the generator works in a
checkout where nothing is installed — the case that hid a missing subpackage
from CI for a week (#270).

The taxonomy supplies the classification and the one-line note; the registries
supply the inventory and the module each command resolves to. Neither half can
be typed here: a command that is in a registry and in no layer or exclusion
list makes this generator fail rather than emit a catalog that silently omits
it, and a taxonomy entry naming a command neither registry exposes fails
the same way.

The lifecycle subcommands `clawock` builds itself (`init`, `run`, `brief`, …)
are in neither registry. They are read from `clawock.cli.build_parser()`, the
parser `clawock --help` prints, so the inventory covers every subcommand the
CLI offers instead of counting a registry and calling it the CLI (#1592, #1627).

Only the block between the two markers is generated. Everything else in the
document is hand-written, because flag tables, SEC's rate limit and which key a
provider needs are not things a registry holds.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# `lifecycle_commands` imports `clawock.cli` from this checkout, never from
# whatever happens to be installed (same bootstrap as ops/system_check.py).
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
OUTPUT = ROOT / "docs" / "reference" / "commands.md"
CONFIG = ROOT / "config" / "information-layers.json"
PUBLIC = "clawock"
SCRIPTS = "standalone"

BEGIN = "<!-- BEGIN GENERATED INVENTORY -->"
END = "<!-- END GENERATED INVENTORY -->"


def packaged_utilities(root: Path = ROOT) -> dict:
    """The public CLI's dispatch table, read from source."""
    source = (root / "src" / PUBLIC / "utilities.py").read_text()
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Assign)
                and getattr(node.targets[0], "id", "") == "PACKAGED_UTILITIES"):
            return ast.literal_eval(node.value)
    raise SystemExit(
        "PACKAGED_UTILITIES is no longer a literal in clawock/utilities.py "
        "(it moved out of cli.py in #814)")


def installed_scripts(root: Path = ROOT) -> dict:
    """Standalone console scripts declared by the clawock distribution."""
    data = tomllib.loads((root / "pyproject.toml").read_text())
    return {
        command: target
        for command, target in data["project"]["scripts"].items()
        if command != "clawock"
    }


def registries(root: Path = ROOT) -> dict:
    return {PUBLIC: packaged_utilities(root), SCRIPTS: installed_scripts(root)}


def lifecycle_commands(root: Path = ROOT) -> dict:
    """`clawock` subcommands the CLI builds itself: name → its `--help` line.

    Imported rather than parsed: the parser is built by code (loops over
    workflows and the utility registry), and `build_parser()` is the one thing
    that knows what `clawock --help` offers. The packaged utilities are left
    out here because the registry tables already list them.
    """
    from clawock.cli import build_parser

    utilities = packaged_utilities(root)
    subparsers = next(action for action in build_parser()._actions
                      if isinstance(action, argparse._SubParsersAction))
    return {choice.dest: choice.help or ""
            for choice in subparsers._choices_actions
            if choice.dest not in utilities}


def _invocation(registry: str, command: str) -> str:
    """How an operator actually types it."""
    return f"`{command}`" if registry == SCRIPTS else f"`clawock {command}`"


def _module(target: str) -> str:
    """The module behind an entry, without the `:main` an entry point carries."""
    return f"`{target.split(':')[0]}`"


def _cell(text: str) -> str:
    """Markdown table cells cannot contain a raw pipe or a newline."""
    return " ".join(str(text).split()).replace("|", "\\|")


def _classify(config: dict, available: dict) -> tuple[list, list]:
    """Resolve every taxonomy entry against the registries.

    Fails on either half of the partition being wrong, because a catalog that
    quietly drops an unclassified command is the failure this generator exists
    to prevent.
    """
    seen = set()
    layers, excluded = [], []

    for layer in config["layers"]:
        rows = []
        for module in layer["modules"]:
            registry = module.get("registry", PUBLIC)
            key = (registry, module["command"])
            rows.append((key, module.get("note", "")))
            seen.add(key)
        layers.append((layer, rows))

    for command, spec in config["excluded"].items():
        key = (spec.get("registry", PUBLIC), command)
        excluded.append((key, spec.get("reason", "")))
        seen.add(key)

    declared = {(registry_name, command)
                for registry_name, commands in available.items()
                for command in commands}

    missing = sorted(declared - seen)
    if missing:
        raise SystemExit(
            f"{len(missing)} installed command(s) are in no layer and on no "
            f"exclusion list: {missing}. Classify each in "
            "config/information-layers.json before regenerating the catalog.")

    unknown = sorted(seen - declared)
    if unknown:
        raise SystemExit(
            f"config/information-layers.json names command(s) no registry "
            f"exposes: {unknown}")

    return layers, excluded


def _table(rows, available, note_header: str) -> list[str]:
    lines = [f"| Command | Module | {note_header} |", "|---|---|---|"]
    for (registry, command), note in rows:
        target = available[registry][command]
        lines.append(
            f"| {_invocation(registry, command)} | {_module(target)} | "
            f"{_cell(note)} |")
    return lines


def render(config: dict, available: dict, lifecycle: dict | None = None) -> str:
    layers, excluded = _classify(config, available)
    lifecycle = lifecycle_commands() if lifecycle is None else lifecycle
    counted = sum(len(rows) for _, rows in layers)
    total = sum(len(registry) for registry in available.values()) + len(lifecycle)

    lines = [
        BEGIN,
        "",
        "<!-- Generated by ops/ci/generate_tool_reference.py; DO NOT EDIT."
        " Run the generator after changing a registry or the taxonomy. -->",
        "",
        "## Installed commands / 已安装命令",
        "",
        f"**{total} commands** are installed by the single `{PUBLIC}` distribution: "
        f"{len(lifecycle)} lifecycle subcommands built in `src/clawock/cli.py`, "
        f"{len(available[PUBLIC])} packaged `clawock <utility>` subcommands and "
        f"{len(available[SCRIPTS])} standalone scripts. "
        f"`clawock --help` offers the first two groups "
        f"({len(lifecycle) + len(available[PUBLIC])} subcommands). "
        f"{counted} of the registry commands collect or compute information and "
        f"appear under the layer they feed; the remaining {len(excluded)} publish, "
        "gate, record or schedule, and are listed with the reason they are not "
        "collection.",
        "",
        "本节由生成器从 `clawock.cli.build_parser()`、两份 registry 与 "
        "`config/information-layers.json` 推导，不手写；新增或删除一条命令，"
        "这张表自己会变。",
        "",
        "### Lifecycle subcommands / 生命周期子命令",
        "",
        "Workspace, run and harness lifecycle commands; details are in the "
        "hand-written sections below.",
        "",
        "| Command | What it does |",
        "|---|---|",
        *(f"| `{PUBLIC} {name}` | {_cell(help_text)} |"
          for name, help_text in lifecycle.items()),
        "",
    ]

    for layer, rows in layers:
        lines.extend([
            f"### Layer {layer['id']} · {layer['name']['en']} / "
            f"{layer['name']['zh']}",
            "",
            f"Sources: {layer['sources']['en']}",
            "",
            *_table(rows, available, "What it collects or computes"),
            "",
        ])

    lines.extend([
        "### Not information collection / 不属于信息收集",
        "",
        "These are installed commands too. They are listed here so the catalog "
        "is the whole installation rather than the interesting part of it.",
        "",
        *_table(excluded, available, "Why it is not collection"),
        "",
        END,
    ])
    return "\n".join(lines)


def _split(document: str) -> tuple[str, str]:
    """The hand-written text before and after the generated block."""
    if document.count(BEGIN) != 1 or document.count(END) != 1:
        raise SystemExit(
            f"{OUTPUT} must contain exactly one {BEGIN} and one {END}")
    head, rest = document.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    return head, tail


def build(document: str, config: dict, available: dict,
          lifecycle: dict | None = None) -> str:
    head, tail = _split(document)
    return head + render(config, available, lifecycle) + tail


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    config = json.loads(CONFIG.read_text())
    available = registries()
    current = OUTPUT.read_text()
    content = build(current, config, available)

    if args.check:
        if current != content:
            print("docs/reference/commands.md inventory is stale; run "
                  "ops/ci/generate_tool_reference.py")
            return 1
        print("docs/reference/commands.md matches the registries and taxonomy")
        return 0

    OUTPUT.write_text(content)
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
