"""README 分档表 Blocks 行必须与 config/preflight-blocks.json 对死。

#1095:37/16/29 曾经是无人能证伪的手敲数字。现在块清单是注册表,
README 的精确数字由本测试钉住——preflight 增删块而不同步注册表,CI 红。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "preflight-blocks.json"
CADENCES = ("brief", "report", "intraday")


def _registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))["blocks"]


def _blocks_row(path, marker):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith(marker):
            numbers = [int(x) for x in re.findall(r"\d+", line)]
            assert len(numbers) == 3, f"unparseable row in {path}: {line!r}"
            return numbers
    raise AssertionError(f"no {marker!r} row found in {path}")


def test_readme_block_counts_match_registry():
    blocks = _registry()
    counts = [len(blocks[c]) for c in CADENCES]
    en = _blocks_row(ROOT / "README.md", "| **Blocks** |")
    zh = _blocks_row(ROOT / "README.zh.md", "| **块数** |")
    # 列序:盘前深度简报 / 开午收报告 / 盘中盯盘
    assert en == counts, f"README.md Blocks 行 {en} != registry {counts}"
    assert zh == en, f"README.zh.md 块数行 {zh} != README.md {en}"


def test_registry_lists_are_unique_snake_case():
    blocks = _registry()
    assert list(blocks) == list(CADENCES)
    for cadence in CADENCES:
        names = blocks[cadence]
        assert names, cadence
        assert len(set(names)) == len(names), f"{cadence} has duplicates"
        assert all(re.fullmatch(r"[a-z_]+", n) for n in names), cadence
