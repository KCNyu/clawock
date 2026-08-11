"""The information-layer table describes the package, or it describes nothing.

`test_the_information_layer_table_adds_up_in_both_languages` checks the four
numbers in the README agree with each other and across both languages. It says
in its own docstring that it cannot check they describe the system, because the
taxonomy had no artifact behind it: the layers were drawn when these were files
under `scripts/data/`, and #429 deleted that directory without the count moving
(#476).

`config/information-layers.json` is that artifact. Every packaged command
appears in it exactly once — inside a layer, or in `excluded` with the reason it
is not information collection — so adding a command to the CLI forces a
classification instead of silently diluting a number. This file checks three
things the parity test cannot:

1. the partition is total and disjoint against `PACKAGED_UTILITIES` itself;
2. every module named in it resolves to a real module;
3. the README's rows, in both languages, are the config's own counts.

What it still does not prove: that the *editorial* judgement is right — that
`regime` is quant and `thesis` is not. That is a boundary someone chose, which
is why the rule is written down in `inclusion_rule` and each exclusion carries
its reason. A test can keep the boundary visible and consistent; it cannot make
it true.
"""
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "information-layers.json").read_text())
EN = (ROOT / "README.md").read_text()
ZH = (ROOT / "README.zh.md").read_text()

INSTANCE_SRC = ROOT / "instances" / "kcnyu" / "src"


def _packaged_utilities():
    """The CLI's own registry, read from source.

    Importing `clawock.cli` would work here, but reading the mapping keeps this
    test meaningful in a checkout where the package is not installed — the case
    that hid a missing subpackage from CI for a week (#270).
    """
    import ast

    source = (ROOT / "src" / "clawock" / "cli.py").read_text()
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Assign)
                and getattr(node.targets[0], "id", "") == "PACKAGED_UTILITIES"):
            return ast.literal_eval(node.value)
    raise AssertionError("PACKAGED_UTILITIES is no longer a literal in clawock/cli.py")


def _entries():
    for layer in CONFIG["layers"]:
        for module in layer["modules"]:
            yield layer, module


def test_every_packaged_command_is_classified_exactly_once():
    """The property that makes the count self-maintaining.

    A new `clawock <thing>` cannot be added without deciding whether it collects
    information, and a deleted one cannot leave a stale row behind. Without this
    the config is just a second place to type 26.
    """
    registry = _packaged_utilities()
    assert len(registry) > 40, "the CLI registry shrank unexpectedly — check the parse"

    classified = []
    for _, module in _entries():
        if "command" in module:
            classified.append(module["command"])
    classified.extend(CONFIG["excluded"])

    duplicates = {name for name in classified if classified.count(name) > 1}
    assert not duplicates, f"classified in two places at once: {sorted(duplicates)}"

    missing = sorted(set(registry) - set(classified))
    assert not missing, (
        f"{len(missing)} packaged command(s) are in no layer and on no exclusion "
        f"list: {missing}. Put each in the layer it feeds, or in `excluded` with "
        "the reason it is not information collection.")

    unknown = sorted(set(classified) - set(registry))
    assert not unknown, (
        f"config/information-layers.json names command(s) the CLI does not "
        f"expose: {unknown}")


def test_every_module_in_the_taxonomy_resolves():
    """Names, not just numbers. The taxonomy's failure mode was surviving a
    refactor that moved every module it counted, which a count cannot notice
    and a resolved import can."""
    registry = _packaged_utilities()

    for layer, module in _entries():
        where = f"layer {layer['id']} · {layer['name']['en']}"
        if "command" in module:
            dotted = registry[module["command"]]
            path = ROOT / "src" / Path(dotted.replace(".", "/")).with_suffix(".py")
            assert path.exists(), f"{where}: {module['command']} → {dotted} is gone"
        else:
            dotted = module["module"]
            assert module.get("distribution") == "clawock-kcnyu", (
                f"{where}: a non-command entry must say which distribution ships it")
            path = INSTANCE_SRC / Path(dotted.replace(".", "/")).with_suffix(".py")
            assert path.exists(), f"{where}: {dotted} is gone"
        assert module.get("note"), f"{where}: {dotted} has no note saying what it does"


def test_the_packaged_modules_are_importable_from_the_package():
    """A path on disk is not a module. `src/` layout plus a subpackage missing
    from the wheel's `packages` list is exactly how `clawock.providers` shipped
    unimportable (#270), so resolve through the import system too."""
    registry = _packaged_utilities()
    dotted = [registry[m["command"]] for _, m in _entries() if "command" in m]

    if importlib.util.find_spec("clawock") is None:
        pytest.skip("clawock is not installed in this environment")

    unresolvable = [name for name in dotted if importlib.util.find_spec(name) is None]
    assert not unresolvable, (
        f"named in the taxonomy but not importable from the installed package: "
        f"{unresolvable}")


def _rows(markdown):
    return [line for line in markdown.splitlines() if re.match(r"^\| \d+ · ", line)]


def test_the_readme_layer_table_is_generated_from_the_config():
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
    for command, reason in CONFIG["excluded"].items():
        assert len(reason.split()) >= 4, (
            f"{command}: '{reason}' does not say why it is not information "
            "collection")
    assert CONFIG["inclusion_rule"].strip(), "the boundary must be stated, not implied"
