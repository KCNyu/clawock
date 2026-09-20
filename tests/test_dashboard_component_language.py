"""One visual language for the dashboard's widgets, checked instead of hoped for.

`refactor(site)` #1706 made the *shell* one source of truth. Inside it, every
card and control had drifted into its own dialect, and the drift was invisible
to every existing test because each rule is individually valid CSS:

* The same layer had four spellings. `--card`/`--card-2` are aliases of
  `--surface-1`/`--surface-2`, and "a block inside a card" was written as
  `--card-2` (28 rules), `--card`/`--surface-1` (~10) and `--surface-3` (3).
* Worse, it was not a layer at all: `--surface-1` #131E2C against `--surface-2`
  #141E2A measured **1.001:1**. Every one of those 28 blocks, plus the holdings
  table's sticky header, was painted the exact colour of the thing it sat on.
* One "press" gesture had four scales (.92 / .97 / .98 on buttons), one focus
  ring had two colours and five offsets, 150ms was written both as
  `var(--duration-fast)` and `0.15s`, and `ease` appeared bare 23 times next to
  the `--ease-out` the palette's own comment says is mandatory.
* One "this is a warning" tint had six strengths (7/12/15/16/30/40%).

None of that is a bug in any single rule, which is why it has to be checked as
a property of the whole sheet.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CSS_PATH = ROOT / "site" / "assets" / "css" / "dashboard.css"
RAW = CSS_PATH.read_text(encoding="utf-8")
CSS = re.sub(r"/\*.*?\*/", " ", RAW, flags=re.DOTALL)

RULES = [(re.sub(r"\s+", " ", m.group(1).strip()), m.group(2))
         for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", CSS)]


def _hex(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _luminance(rgb) -> float:
    def channel(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _themes() -> dict[str, dict[str, str]]:
    root = re.search(r":root\s*\{([^{}]*)\}", CSS).group(1)
    light = re.search(
        r"@media \(prefers-color-scheme: light\)\s*\{\s*:root\s*\{([^{}]*)\}", CSS).group(1)

    def hexes(block):
        return dict(re.findall(r"(--[\w-]+)\s*:\s*(#[0-9A-Fa-f]{3,6})\b", block))
    dark = hexes(root)
    return {"dark": dark, "light": {**dark, **hexes(light)}}


# ── the palette has to have rungs, not repeats ─────────────────────────────

@pytest.mark.parametrize("theme", ["dark", "light"])
def test_every_surface_step_is_a_step_a_reader_can_see(theme):
    """A palette rung that equals the one below it is a rung nobody can use.

    `--surface-2` sat at 1.001:1 from `--surface-1` in dark for as long as both
    existed. Rules kept choosing it for "a block on a card" and got a block the
    exact colour of the card — and the holdings table's sticky header, which is
    also `--surface-2`, covered the rows it scrolled over with their own colour.
    """
    tokens = _themes()[theme]
    ladder = ["--bg", "--surface-0", "--surface-1", "--surface-2", "--surface-3", "--overlay"]
    flat = []
    for lower, upper in zip(ladder, ladder[1:]):
        ratio = _contrast(_hex(tokens[lower]), _hex(tokens[upper]))
        if ratio < 1.02:
            flat.append(f"{theme} {lower}({tokens[lower]}) vs {upper}({tokens[upper]}): {ratio:.3f}")
    assert flat == [], (
        "these palette steps are the same colour, so any component that picks "
        "the upper one to sit on the lower one is invisible:\n  " + "\n  ".join(flat))


# ── one name per role ──────────────────────────────────────────────────────

def test_a_block_inside_a_card_names_its_role_not_a_grey():
    """`--card-2` is retired: it was an alias of a rung that did not exist.

    The roles are `--fill-card` / `--fill-inset` / `--fill-inset-2`, so a rule
    says which layer it is rather than which grey it liked.
    """
    for role in ("--fill-card", "--fill-inset", "--fill-inset-2"):
        assert f"{role}:" in CSS, (
            f"{role} is gone; a component is back to picking a grey")
        assert f"var({role})" in CSS, f"{role} is defined but nothing uses it"
    users = [sel for sel, body in RULES if "var(--card-2" in body]
    assert users == [], (
        "these rules still read the retired `--card-2` alias: " + ", ".join(users))
    assert "var(--card-2" not in (ROOT / "site/assets/js/dashboard.render.js").read_text(
        encoding="utf-8"), "an inline style in the renderer still reads --card-2"


def test_status_colours_have_one_name_each():
    """`--amber` and `--warning` are the same colour; using both is how "the
    same warning is orange here and red there" happens. The aliases stay
    defined for anything outside this sheet, but nothing here may read them."""
    retired = ("--green", "--red", "--amber", "--gray", "--pos", "--neg", "--warn", "--muted")
    offenders = sorted({f"{name} in {sel}"
                        for sel, body in RULES
                        for name in retired
                        if re.search(rf"var\(\s*{name}\s*[,)]", body)})
    assert offenders == [], (
        "use the semantic name (--positive / --negative / --warning / --neutral "
        "/ --text-secondary), not the legacy alias:\n  " + "\n  ".join(offenders))


def test_status_tints_come_off_the_tint_scale():
    """Six strengths of "warning" is one decision written six times."""
    semantic = ("positive", "negative", "warning", "accent", "neutral")
    strays = sorted({
        f"--{token} {pct}%"
        for token, pct in re.findall(
            r"color-mix\(in srgb,\s*var\(--([\w-]+)\)\s*(\d+)%,\s*transparent\)", CSS)
        if token in semantic and 5 <= int(pct) <= 40})
    assert strays == [], (
        "use var(--tint-wash) / var(--tint-soft) / var(--tint-strong) / "
        "var(--tint-edge): " + ", ".join(strays))


# ── one interaction language ───────────────────────────────────────────────

#: `:active` scales that are deliberately off the shared value, with the reason.
PRESS_EXCEPTIONS: dict[str, str] = {}


def test_pressing_anything_feels_the_same():
    strays = []
    for sel, body in RULES:
        if ":active" not in sel:
            continue
        for value in re.findall(r"transform:\s*(scale\([^)]*\))", body):
            if "var(--press-scale)" in value or value in PRESS_EXCEPTIONS:
                continue
            strays.append(f"{sel} -> {value}")
    assert strays == [], (
        "press feedback must be var(--press-scale), or listed in "
        "PRESS_EXCEPTIONS with the reason:\n  " + "\n  ".join(strays))


def test_one_focus_ring():
    """#1706 gave the shell one ring; the widgets kept two colours and five
    offsets. `outline: none` is allowed only where the rule replaces the ring
    with something else and says so."""
    wrong = []
    for sel, body in RULES:
        if ":focus-visible" not in sel:
            continue
        outline = re.search(r"(?:^|;)\s*outline\s*:\s*([^;]+)", body)
        if outline and outline.group(1).strip() not in ("var(--focus-ring)", "none"):
            wrong.append(f"{sel} -> outline: {outline.group(1).strip()}")
        offset = re.search(r"outline-offset\s*:\s*([^;]+)", body)
        if offset and offset.group(1).strip() not in ("2px", "-2px", "3px"):
            wrong.append(f"{sel} -> outline-offset: {offset.group(1).strip()}")
    assert wrong == [], (
        "the ring is `var(--focus-ring)` at 2px (outside) or -2px (drawn inside "
        "a clipping box); 3px only clears a dot:\n  " + "\n  ".join(wrong))


def test_no_transition_or_entrance_invents_its_own_timing():
    """The palette's own comment says "全站 transition 只引用这四个，禁裸曲线".
    It was true of 22 declarations and false of 23."""
    strays = []
    for match in re.finditer(r"(transition(?:-duration|-timing-function)?|animation)\s*:\s*([^;{}]+);", CSS):
        prop, value = match.group(1), match.group(2)
        if prop == "animation" and ("infinite" in value or re.search(r"\b\d\d+s\b", value)):
            continue  # spinners and marquees are not interaction timing
        if "!important" in value:
            continue  # the prefers-reduced-motion kill switch is `0.01ms !important`
        if re.search(r"(?<![-\w])ease(?![-\w(])", value):
            strays.append(f"{prop}: {value.strip()[:70]} (bare `ease`)")
        # Only the first time value in a shorthand is the duration; a second one
        # is a delay, and a stagger delay is a per-item decision, not a scale.
        head = value.split("var(--ease")[0]
        if re.search(r"(?<![\d.\w])0?\.\d+s\b", head) or re.search(r"(?<![\w-])\d{1,4}ms\b", head):
            strays.append(f"{prop}: {value.strip()[:70]} (literal duration)")
        if "cubic-bezier" in value:
            strays.append(f"{prop}: {value.strip()[:70]} (bare curve)")
    assert strays == [], (
        "use var(--duration-fast|--duration-standard) and "
        "var(--ease-out|--ease-in-out):\n  " + "\n  ".join(sorted(set(strays))))


def test_container_corners_come_off_the_corner_scale():
    """Four corner tokens exist; a literal that equals one of them is a value
    the next component can copy without knowing which rung it is on."""
    named = {"6px": "--radius-sm", "10px": "--radius", "12px": "--radius-float",
             "16px": "--radius-lg"}
    strays = sorted({f"border-radius: {v} (use var({named[v]}))"
                     for v in re.findall(r"border-radius:\s*([^;]+);", CSS)
                     if v.strip() in named})
    assert strays == [], "\n  ".join(strays)
