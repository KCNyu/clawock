"""The repository source aliases retired after the installed-command cutover."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_source_harness_alias_directory_is_gone():
    assert list((ROOT / "scripts" / "harness").glob("*.py")) == []


def test_runtime_contracts_do_not_reference_source_harness_aliases():
    paths = [ROOT / "config" / "cron-schedules.json"]
    paths.extend((ROOT / "scripts" / "data").glob("*"))
    paths.extend((ROOT / "ops" / "host").glob("*"))
    offenders = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        if "scripts/harness" in text:
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []
