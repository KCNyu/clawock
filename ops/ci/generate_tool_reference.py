#!/usr/bin/env python3
"""Generate the command inventory in `docs/reference/commands.md`.

The document the README calls "the full command and provider catalog" was
hand-maintained, so nothing noticed when a command was added, renamed or
removed (#489). The inventory half of it is now derived from the same two
registries `config/information-layers.json` partitions:

- `clawock.cli.PACKAGED_UTILITIES` — the public CLI's own dispatch table;
- `[project.scripts]` in `instances/kcnyu/pyproject.toml`.

Both are read from source rather than imported, so the generator works in a
checkout where nothing is installed — the case that hid a missing subpackage
from CI for a week (#270).

The taxonomy supplies the classification and the one-line note; the registries
supply the inventory and the module each command resolves to. Neither half can
be typed here: a command that is in a registry and in no layer or exclusion
list makes this generator fail rather than emit a catalog that silently omits
it, and a taxonomy entry naming a command neither distribution installs fails
the same way.

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
OUTPUT = ROOT / "docs" / "reference" / "commands.md"
CONFIG = ROOT / "config" / "information-layers.json"
INSTANCE_ROOT = ROOT / "instances" / "kcnyu"

PUBLIC = "clawock"
INSTANCE = "clawock-kcnyu"

BEGIN = "<!-- BEGIN GENERATED INVENTORY -->"
END = "<!-- END GENERATED INVENTORY -->"


def packaged_utilities(root: Path = ROOT) -> dict:
    """The public CLI's dispatch table, read from source."""
    source = (root / "src" / PUBLIC / "cli.py").read_text()
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Assign)
                and getattr(node.targets[0], "id", "") == "PACKAGED_UTILITIES"):
            return ast.literal_eval(node.value)
    raise SystemExit("PACKAGED_UTILITIES is no longer a literal in clawock/cli.py")


def instance_scripts(root: Path = ROOT) -> dict:
    """The instance distribution's console scripts, as declared for install."""
    data = tomllib.loads((root / "instances" / "kcnyu" / "pyproject.toml").read_text())
    return data["project"]["scripts"]


def registries(root: Path = ROOT) -> dict:
    return {PUBLIC: packaged_utilities(root), INSTANCE: instance_scripts(root)}


def _invocation(distribution: str, command: str) -> str:
    """How an operator actually types it."""
    return f"`{command}`" if distribution == INSTANCE else f"`clawock {command}`"


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
            distribution = module.get("distribution", PUBLIC)
            key = (distribution, module["command"])
            rows.append((key, module.get("note", "")))
            seen.add(key)
        layers.append((layer, rows))

    for command, spec in config["excluded"].items():
        key = (spec.get("distribution", PUBLIC), command)
        excluded.append((key, spec.get("reason", "")))
        seen.add(key)

    declared = {(distribution, command)
                for distribution, registry in available.items()
                for command in registry}

    missing = sorted(declared - seen)
    if missing:
        raise SystemExit(
            f"{len(missing)} installed command(s) are in no layer and on no "
            f"exclusion list: {missing}. Classify each in "
            "config/information-layers.json before regenerating the catalog.")

    unknown = sorted(seen - declared)
    if unknown:
        raise SystemExit(
            f"config/information-layers.json names command(s) neither "
            f"distribution installs: {unknown}")

    return layers, excluded


def _table(rows, available, note_header: str) -> list[str]:
    lines = [f"| Command | Module | {note_header} |", "|---|---|---|"]
    for (distribution, command), note in rows:
        target = available[distribution][command]
        lines.append(
            f"| {_invocation(distribution, command)} | {_module(target)} | "
            f"{_cell(note)} |")
    return lines


def render(config: dict, available: dict) -> str:
    layers, excluded = _classify(config, available)
    counted = sum(len(rows) for _, rows in layers)
    total = sum(len(registry) for registry in available.values())

    lines = [
        BEGIN,
        "",
        "<!-- Generated by ops/ci/generate_tool_reference.py; DO NOT EDIT."
        " Run the generator after changing a registry or the taxonomy. -->",
        "",
        "## Installed commands / 已安装命令",
        "",
        f"**{total} commands** are installed: {len(available[PUBLIC])} from "
        f"`{PUBLIC}` and {len(available[INSTANCE])} from `{INSTANCE}`. "
        f"{counted} of them collect or compute information and appear under the "
        f"layer they feed; the remaining {len(excluded)} publish, gate, record "
        "or schedule, and are listed with the reason they are not collection.",
        "",
        "本节由生成器从两份 registry 与 `config/information-layers.json` 推导，"
        "不手写；新增或删除一条命令，这张表自己会变。",
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


def build(document: str, config: dict, available: dict) -> str:
    head, tail = _split(document)
    return head + render(config, available) + tail


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
