"""`dashboard.hero.js` 与 `dashboard.render.js` 是手工维护的两份实现。

首屏只加载 hero.js（轻量首帧），进详情 tab 才拉 render.js，两边有大量同名
同职责的函数。历史上这条「改了一份忘了另一份」反复出现过：2026-08-24 这轮
里，`renderHeroSpark` 只落进 render.js，于是首屏那条缩略走势线在生产路径上
根本不存在，而页面不报错、测试也不红 —— 典型的「源码里对、生产里死」。

这条闸是**棘轮**：当下已经分叉的函数登记在 ALLOWED_DIVERGENT 里，其余同名
函数必须逐字相同。名单只准变短：某个函数被重新对齐之后，它必须从名单里
删掉，否则这条测试会失败。这样它不会因为历史包袱而失效。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERO = ROOT / "site" / "assets" / "js" / "dashboard.hero.js"
RENDER = ROOT / "site" / "assets" / "js" / "dashboard.render.js"

# 已知分叉（2026-08-24 建闸时的现状）。hero.js 是首帧轻量实现，其中
# render / renderTab / refreshTab 的差异是设计使然；其余五个是历史漂移，
# 修一个删一行。**只准删，不准加** —— 加一行就等于默许了一次新的漂移。
ALLOWED_DIVERGENT = {
    "computeWatchRows",
    "refreshTab",
    "render",
    "renderHonesty",
    "renderRiskGuardrail",
    "renderTab",
    "renderTodayHighlights",
    "syncDeskRail",
}

_DECL = re.compile(r"^  function ([A-Za-z_$][\w$]*)\s*\(")


def _top_level_functions(path: Path) -> dict[str, str]:
    """顶层（两空格缩进）函数声明 -> 函数体文本。

    这两个文件都是没有 IIFE 包裹的经典脚本，顶层函数一律是 `  function x(`
    开头、`  }` 单独一行结尾，缩进本身就是可靠的边界。不引第三方 JS 解析器
    是刻意的：这条闸要能在最小依赖下跑。
    """
    lines = path.read_text(encoding="utf-8").split("\n")
    out: dict[str, str] = {}
    i = 0
    while i < len(lines):
        match = _DECL.match(lines[i])
        if not match:
            i += 1
            continue
        end = i + 1
        while end < len(lines) and lines[end] != "  }":
            end += 1
        out[match.group(1)] = "\n".join(lines[i:end + 1])
        i = end + 1
    return out


@pytest.fixture(scope="module")
def bundles() -> tuple[dict[str, str], dict[str, str]]:
    hero, render = _top_level_functions(HERO), _top_level_functions(RENDER)
    # 解析器本身要能自证：两个文件都必须解出足够多的函数，否则一旦缩进
    # 风格变了，这条闸会静默地什么都不检查。
    assert len(hero) > 20, f"parsed only {len(hero)} functions from {HERO.name}"
    assert len(render) > 40, f"parsed only {len(render)} functions from {RENDER.name}"
    return hero, render


def test_shared_functions_are_byte_identical(bundles):
    hero, render = bundles
    shared = sorted(set(hero) & set(render))
    assert shared, "the two bundles share no function names — did the parser break?"
    drifted = [
        name for name in shared
        if name not in ALLOWED_DIVERGENT and hero[name] != render[name]
    ]
    assert drifted == [], (
        "these functions exist in both dashboard bundles but no longer match: "
        f"{drifted}. 改了一份就要改另一份 —— 首屏走 hero.js，详情 tab 走 "
        "render.js，只改一份的后果是生产路径上功能直接不存在。"
    )


def test_allowlist_only_shrinks(bundles):
    hero, render = bundles
    shared = set(hero) & set(render)
    reconciled = sorted(
        name for name in ALLOWED_DIVERGENT
        if name in shared and hero[name] == render[name]
    )
    assert reconciled == [], (
        f"these are identical again and must be removed from ALLOWED_DIVERGENT: {reconciled}"
    )
    stale = sorted(ALLOWED_DIVERGENT - shared)
    assert stale == [], (
        f"ALLOWED_DIVERGENT names a function that is no longer in both bundles: {stale}"
    )


def test_hero_spark_is_present_in_both(bundles):
    """本轮的具体事故：这两个函数只落进了 render.js。"""
    hero, render = bundles
    for name in ("heroProfitSeries", "renderHeroSpark", "renderCommandDeck"):
        assert name in hero, f"{name} missing from {HERO.name} (first-paint bundle)"
        assert name in render, f"{name} missing from {RENDER.name}"
