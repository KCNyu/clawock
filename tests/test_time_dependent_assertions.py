"""闸：读实时时钟的测试，不许和日期字面量对断言。

2026-08-26 00:00 HKT，master 的 CI 自己变红了 —— 没有人改任何代码：

    assert h["prev_close_date"] != "2026-08-25"

写这条的时候 "2026-08-25" 是「今天」，断言的意思是「前收日不能是今天」。
第二天同一个字面量变成了「上一个交易日」，而被测代码算出来的正是它，于是
断言的意思翻了个面。测试里的日期字面量与文案里的实时数字是同一类东西：
都会过期，而且过期的时候**看起来仍然像在守规矩**。

规则不是「测试里不许写日期」——夹具里当然要写。规则是：**同一个测试里，
不能一边让被测代码读真实时钟，一边拿字面量当期望值**。要么冻住时钟（把
now 传进去 / monkeypatch），要么从同一个时钟推出期望值。
"""
import ast
import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
LIVE_CLOCK = ("datetime.now(", "date.today(")
DATE_LITERAL = re.compile(r"assert[^\n]*[\"']20\d\d-\d\d-\d\d")


def _offenders():
    found = []
    for path in sorted(TESTS.glob("*.py")):
        # 本文件里那段样本是字符串常量，不是断言 —— 扫描自己会把它读成违例。
        if path.name == Path(__file__).name:
            continue
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test"):
                continue
            body = "\n".join(lines[node.lineno - 1:node.end_lineno])
            if any(call in body for call in LIVE_CLOCK) and DATE_LITERAL.search(body):
                found.append(f"{path.name}::{node.name}")
    return found


def test_no_test_compares_a_live_clock_against_a_date_literal():
    assert _offenders() == [], (
        "这些测试同时读了真实时钟并对日期字面量断言，它们会在某个午夜自己变红："
        f"{_offenders()}。修法：冻住时钟，或者用同一个时钟推出期望值。")


def test_the_scanner_can_actually_see_an_offender():
    """反空转：上面那条闸必须真的能抓到东西，否则它就是一条恒真断言。"""
    sample = (
        "def test_sample():\n"
        "    now = datetime.now(timezone.utc)\n"
        "    assert row['session'] == \"2026-08-25\"\n"
    )
    lines = sample.splitlines()
    node = ast.parse(sample).body[0]
    body = "\n".join(lines[node.lineno - 1:node.end_lineno])
    assert any(call in body for call in LIVE_CLOCK)
    assert DATE_LITERAL.search(body)
