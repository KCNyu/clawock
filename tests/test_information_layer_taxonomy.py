"""The information-layer table describes the package, or it describes nothing.

`test_the_information_layer_table_adds_up_in_both_languages` checks the four
numbers in the README agree with each other and across both languages. It says
in its own docstring that it cannot check they describe the system, because the
taxonomy had no artifact behind it: the layers were drawn when these were files
under `scripts/data/`, and #429 deleted that directory without the count moving
(#476).

`config/information-layers.json` is that artifact. Every command the single
distribution exposes through either registry appears in it exactly once — inside a layer, or in
`excluded` with the reason it is not information collection — so adding a
command forces a classification instead of silently diluting a number. This file
checks three things the parity test cannot:

1. the partition is total and disjoint against the two script registries;
2. every module named in it resolves to a real module;
3. the README's rows, in both languages, are the config's own counts.

Every counted entry has to be a key of a registry, and that is the load-bearing
part. The first draft of this file let a layer name a bare module path, which
meant a hand-picked entry could be added, or duplicated, without any registry
disagreeing — the total was 36 derived numbers plus 2 free ones. A number is
only self-maintaining if nothing in it can be typed.

What it still does not prove: that the *editorial* judgement is right — that
`regime` is quant and `thesis` is not. That is a boundary someone chose, which
is why the rule is written down in `inclusion_rule` and each exclusion carries
its reason. A test can keep the boundary visible and consistent; it cannot make
it true.
"""
import ast
import importlib.util
import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "information-layers.json").read_text())
EN = (ROOT / "README.md").read_text()
ZH = (ROOT / "README.zh.md").read_text()

PUBLIC = "clawock"
SCRIPTS = "standalone"


def _packaged_utilities():
    """The public CLI's own registry, read from source.

    Importing `clawock.cli` would work here, but reading the mapping keeps this
    test meaningful in a checkout where the package is not installed — the case
    that hid a missing subpackage from CI for a week (#270).
    """
    source = (ROOT / "src" / PUBLIC / "utilities.py").read_text()
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Assign)
                and getattr(node.targets[0], "id", "") == "PACKAGED_UTILITIES"):
            return ast.literal_eval(node.value)
    raise AssertionError(
        "PACKAGED_UTILITIES is no longer a literal in clawock/utilities.py "
        "(it moved out of cli.py in #814 so the harness could stop importing "
        "the CLI entry point)")


def _installed_scripts():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return {key: value for key, value in data["project"]["scripts"].items()
            if key != "clawock"}


def _registries():
    return {PUBLIC: _packaged_utilities(), SCRIPTS: _installed_scripts()}


def _key(entry):
    """(registry, command) — the identity a counted entry must have."""
    return (entry.get("registry", PUBLIC), entry["command"])


def _entries():
    for layer in CONFIG["layers"]:
        for module in layer["modules"]:
            yield layer, module


def _counted_keys():
    return [_key(module) for _, module in _entries()]


def _excluded_keys():
    return [(spec.get("registry", PUBLIC), command)
            for command, spec in CONFIG["excluded"].items()]


def test_every_installed_command_is_classified_exactly_once():
    """The property that makes the count self-maintaining.

    A new command in either registry cannot be added without deciding
    whether it collects information, and a deleted one cannot leave a stale row
    behind. Without this the config is just a second place to type a number.
    """
    registries = _registries()
    assert len(registries[PUBLIC]) > 40, "the public CLI registry shrank — check the parse"
    assert len(registries[SCRIPTS]) > 8, "the script registry shrank — check the parse"

    classified = _counted_keys() + _excluded_keys()

    duplicates = {key for key in classified if classified.count(key) > 1}
    assert not duplicates, f"classified in two places at once: {sorted(duplicates)}"

    declared = {(registry_name, command)
                for registry_name, commands in registries.items()
                for command in commands}

    missing = sorted(declared - set(classified))
    assert not missing, (
        f"{len(missing)} installed command(s) are in no layer and on no exclusion "
        f"list: {missing}. Put each in the layer it feeds, or in `excluded` with "
        "the reason it is not information collection.")

    unknown = sorted(set(classified) - declared)
    assert not unknown, (
        f"config/information-layers.json names command(s) no registry exposes: "
        f"{unknown}")


def test_the_harness_phases_are_out_of_scope_on_purpose_and_not_by_omission():
    """The one registry the partition deliberately skips.

    The preflight/postflight phases assemble the blocks the layers produce, so
    counting them would count the reader as one of the things read. That is a
    defensible line only while it is a stated one — and only while the phases
    are really in a different registry, not quietly missing from both.
    """
    assert "not_classified" in CONFIG["registries"], (
        "the skipped registries must be named in the artifact, not just here")
    note = CONFIG["registries"]["not_classified"]
    from clawock.harness.runner import PHASE_MODULES
    # Named, not counted: a bare count treats a new phase (`brief render`,
    # 2026-08-31) as the same event as a deleted one, and only the second is a
    # regression. These six are the assemble/deliver pairs the exclusion is
    # about; anything added beside them is free to exist.
    for workflow in ("brief", "report", "intraday"):
        for phase in ("preflight", "postflight"):
            assert (workflow, phase) in PHASE_MODULES, (
                f"the lifecycle registry lost {workflow} {phase}")
    assert "phase" in note.lower() or "lifecycle" in note.lower(), (
        "the lifecycle registry is excluded but the artifact does not say so")


def test_every_module_in_the_taxonomy_resolves():
    """Names, not just numbers. The taxonomy's failure mode was surviving a
    refactor that moved every module it counted, which a count cannot notice
    and a resolved module can."""
    registries = _registries()

    for layer, module in _entries():
        registry_name, command = _key(module)
        where = f"layer {layer['id']} · {layer['name']['en']}"
        target = registries[registry_name][command]
        dotted = target.split(":")[0]
        path = ROOT / "src" / Path(dotted.replace(".", "/")).with_suffix(".py")
        assert path.exists(), f"{where}: {command} → {target} is gone"
        assert module.get("note"), f"{where}: {command} has no note saying what it does"


def test_the_packaged_modules_are_importable_from_the_package():
    """A path on disk is not a module. `src/` layout plus a subpackage missing
    from the wheel's `packages` list is exactly how `clawock.providers` shipped
    unimportable (#270), so resolve through the import system too."""
    registry = _packaged_utilities()
    dotted = [registry[command] for registry_name, command in _counted_keys()
              if registry_name == PUBLIC]

    if importlib.util.find_spec(PUBLIC) is None:
        pytest.skip("clawock is not installed in this environment")

    unresolvable = [name for name in dotted if importlib.util.find_spec(name) is None]
    assert not unresolvable, (
        f"named in the taxonomy but not importable from the installed package: "
        f"{unresolvable}")


def _rows(markdown):
    return [line for line in markdown.splitlines() if re.match(r"^\| \d+ · ", line)]


def test_the_readme_layer_table_matches_the_config():
    """Both languages, cell by cell.

    The parity test pins the four numbers to each other; this pins them to the
    artifact. Layer names and source lists are compared too — a row whose count
    is right while its name drifted describes a layer that no longer exists.
    """
    layers = CONFIG["layers"]

    for markdown, name, language in ((EN, "README.md", "en"), (ZH, "README.zh.md", "zh")):
        rows = _rows(markdown)
        assert len(rows) == len(layers), (
            f"{name}: {len(rows)} table rows, {len(layers)} layers in the config")

        for row, layer in zip(rows, layers):
            cells = [cell.strip() for cell in row.split("|")[1:-1]]
            expected = (
                f"{layer['id']} · {layer['name'][language]}",
                str(len(layer["modules"])),
                layer["sources"][language],
            )
            assert tuple(cells) == expected, (
                f"{name}: row {layer['id']} is {tuple(cells)}, the config says "
                f"{expected}")


def test_the_headline_totals_come_from_the_config():
    layers = CONFIG["layers"]
    modules = sum(len(layer["modules"]) for layer in layers)

    for markdown, name, pattern, order in (
        (EN, "README.md",
         r"\*\*(\d+) fetch and compute modules across (\d+) layers\*\*", "ml"),
        (ZH, "README.zh.md",
         r"\*\*(\d+) 层、(\d+) 个抓取与计算模块\*\*", "lm"),
    ):
        headline = re.search(pattern, markdown)
        assert headline, f"{name}: the information-layer headline changed shape"
        stated = dict(zip(order, (int(headline.group(1)), int(headline.group(2)))))
        assert stated["m"] == modules, (
            f"{name}: headline claims {stated['m']} modules, the config has {modules}")
        assert stated["l"] == len(layers), (
            f"{name}: headline claims {stated['l']} layers, the config has {len(layers)}")


def test_the_exclusions_carry_a_reason_rather_than_a_bare_name():
    """An exclusion list without reasons is a way to make any number come out
    right. The reason is what a reader can disagree with."""
    for command, spec in CONFIG["excluded"].items():
        assert len(spec["reason"].split()) >= 4, (
            f"{command}: '{spec['reason']}' does not say why it is not "
            "information collection")
    assert CONFIG["inclusion_rule"].strip(), "the boundary must be stated, not implied"
    for name in (PUBLIC, SCRIPTS):
        assert name in CONFIG["registries"], (
            f"{name}'s registry must be named in the artifact, so a reader can "
            "check the partition covers what they think it covers")
