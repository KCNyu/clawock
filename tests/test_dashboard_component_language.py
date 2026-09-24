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

# The reading pages' own layer. #1706 moved the shell into the shared sheet and
# left `<style>` in the layout holding what only a long-form page has — so the
# rules that are about the whole site's language (the ring, the corner scale,
# a hover that must not stick on a touch screen) have to be checked here too,
# or half the site is unchecked by construction.
LAYOUT_CSS = re.sub(
    r"/\*.*?\*/", " ",
    re.search(r"<style>(.*?)</style>",
              (ROOT / "site" / "_layouts" / "default.html").read_text(encoding="utf-8"),
              re.DOTALL).group(1),
    flags=re.DOTALL)
LAYOUT_RULES = [(re.sub(r"\s+", " ", m.group(1).strip()), m.group(2))
                for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", LAYOUT_CSS)]


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


def test_nothing_rounded_is_painted_the_colour_of_the_card_it_sits_on():
    """A rounded box filled with its own parent's colour is a box nobody sees.

    This is the shape #1707 fixed forty times over. It kept coming back because
    `--card`, `--fill-card` and `--surface-1` are the same colour under three
    names, and a rule that says `background: var(--surface-1)` looks like it
    decided something. A block that means to be a block says `--fill-inset`.

    Rules with a `border-radius: 0` (grid cells that tile a card's interior and
    are divided by hairlines) and pills/circles are not this pattern, and a
    `background: opaque; background: glass;` pair is a fallback, not a fill.
    """
    card_colours = ("var(--surface-1)", "var(--fill-card)", "var(--card)")
    offenders = []
    for selector, body in RULES:
        if re.search(r":(hover|active|focus|checked|disabled)", selector):
            continue
        backgrounds = re.findall(r"(?:^|;)\s*background(?:-color)?\s*:\s*([^;]+)", body)
        radius = re.search(r"border-radius\s*:\s*([^;]+)", body)
        if not backgrounds or not radius or len(backgrounds) > 1:
            continue
        if (backgrounds[0].strip() in card_colours
                and radius.group(1).strip() not in ("0", "50%", "999px", "inherit")):
            offenders.append(f"{selector} -> {backgrounds[0].strip()}")
    assert offenders == [], (
        "these rounded blocks are filled with the colour of the surface they "
        "sit on; use var(--fill-inset):\n  " + "\n  ".join(offenders))


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

#: The markup the shell actually ships: the two documents, plus the renderers
#: that build controls client-side (the holdings row is a `<tr role="button">`
#: that only exists in `dashboard.render.js`; deck dots and the panel retry are
#: buttons created with the DOM API). A class is pressable when it sits on a
#: `<button>`, a `<summary>` or a `role="button"` element in one of these.
PRESS_MARKUP = (
    ROOT / "site" / "index.html",
    ROOT / "site" / "_layouts" / "default.html",
    *sorted((ROOT / "site" / "assets" / "js").glob("dashboard.*.js")),
)
_PRESSABLE_TAG = re.compile(
    r"""<(?:button|summary)\b([^<>]*)>"""
    r"""|<\w+\b([^<>]*role=["']button["'][^<>]*)>""",
    re.DOTALL,
)
_DOM_PRESSABLE_CLASS = re.compile(
    r"""(?:const|let|var)\s+(\w+)\s*=\s*document\.createElement\(\s*"""
    r"""["'](?:button|summary)["']\s*\)\s*;"""
    r"""(?:(?!\b(?:const|let|var)\b)[\s\S])*?\b\1\.className\s*=\s*["']([^"']*)["']"""
)


def _pressable_classes() -> set[str]:
    names: set[str] = set()
    for path in PRESS_MARKUP:
        source = path.read_text(encoding="utf-8")
        for match in _PRESSABLE_TAG.finditer(source):
            attrs = match.group(1) or match.group(2) or ""
            for value in re.findall(r"""class=["']([^"']*)["']""", attrs):
                # A `${...}` hole carries state classes, not selectors.
                names.update(
                    token for token in
                    re.split(r"\s+", re.sub(r"\$\{[^}]*\}", " ", value)) if token)
        for _, value in _DOM_PRESSABLE_CLASS.findall(source):
            names.update(token for token in re.split(r"\s+", value) if token)
    return names


def _press_opt_out_classes() -> set[str]:
    """Controls whose press is deliberately not a scale, read the same way the
    browser contract reads it: `:active { transform: none }`. `td.dm-cell` is
    the only one — scaling a cell drags its column's width with it."""
    names: set[str] = set()
    for sel, body in RULES:
        if ":active" not in sel:
            continue
        if not re.search(r"(?<![-\w])transform\s*:\s*none", body):
            continue
        for part in sel.split(","):
            if ":active" in part:
                names.update(re.findall(r"\.([\w-]+)", part))
    return names


PRESSABLE_CLASSES = _pressable_classes()
PRESS_OPT_OUT_CLASSES = _press_opt_out_classes()

# A 1px offset keeps the 2px ring visible around the small circular refresh
# control without making it read as a second, detached halo beside the as-of
# text. The component-specific browser contract pins the same exception.
FOCUS_OFFSET_EXCEPTIONS = {".refresh-btn:focus-visible": "1px"}


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


def test_the_rings_own_corner_comes_off_the_corner_scale():
    """A focus ring drawn round a transparent control needs its own radius, and
    those were written as literals nowhere else on the scale: 2px on the
    holdings sort headers, 3px on the Overview jump links. Three near-identical
    corners on three rings is the same drift as three press scales."""
    named = {"6px": "--radius-sm", "10px": "--radius",
             "12px": "--radius-float", "16px": "--radius-lg"}
    strays = []
    for sel, body in RULES + LAYOUT_RULES:
        if ":focus-visible" not in sel:
            continue
        radius = re.search(r"border-radius\s*:\s*([^;]+)", body)
        if not radius:
            continue
        value = radius.group(1).strip()
        if value.startswith("var(--radius") or value in ("50%", "999px", "inherit"):
            continue
        hint = f" (use var({named[value]}))" if value in named else ""
        strays.append(f"{sel} -> border-radius: {value}{hint}")
    assert strays == [], (
        "the ring's corner is a corner: use the scale, a pill or a circle:\n  "
        + "\n  ".join(strays))


def test_every_control_a_finger_can_reach_can_also_be_pressed():
    """The press baseline, checked the way #1453's focus baseline is.

    `--press-scale`'s own comment says a press has to feel the same everywhere
    or some buttons read as softer than others. Seven components wrote it;
    everything else — the sort headers, every fold and toggle, the jump links,
    the retry, the decision-map controls — did not move at all. Naming them one
    by one is what let new ones keep skipping it, so the rule is written on the
    element and this asserts the element form, not a list of classes.
    """
    baseline = [body for sel, body in RULES
                if sel == 'button:active, summary:active, [role="button"]:active']
    assert baseline, (
        "the press baseline is gone: every pressable element form has to carry "
        "`transform: scale(var(--press-scale))` on :active, or each new control "
        "is back to remembering it on its own")
    assert "scale(var(--press-scale))" in baseline[0]

    transition = [body for sel, body in RULES
                  if sel == 'button, summary, [role="button"]']
    assert transition and "transform" in transition[0], (
        "without the matching transition the press snaps in and out; the seven "
        "components that pressed before this baseline all eased")


def test_a_control_that_writes_its_own_transition_still_names_transform():
    """The press baseline is written on the element form, and so is its easing —
    but `transition` is one property. Any component rule that writes its own
    shorthand replaces the baseline's whole list, not just the parts it repeats,
    so a control naming background and colour and not transform keeps the scale
    and loses the easing: it snaps, which is the one thing the baseline existed
    to remove. The test above asserts the baseline exists; nothing asserted that
    a component could not silently take it back.

    #1752 found this on `.site-menu-btn` by reading the sheet and fixed that one
    rule. Three more were in the sheet at the time, and reading is how they were
    missed: the desktop tab bar's `.tab-btn` override (the base rule names
    transform, the `min-width: 1024px` one did not), the data-health lane (a
    `<button>` whose own press was a tint, so the scale it snapped was purely the
    baseline's; its successor is `.dh-job-row`) and the holdings `tr.book-row`,
    which carries `role="button"`.
    #1758 closes the scanner's blind spot for DOM-created `.deck-dot` and
    `.panel-load-retry` buttons.
    """
    assert {"site-menu-btn", "tab-btn", "dh-job-row", "book-row", "deck-dot",
            "panel-load-retry"} <= PRESSABLE_CLASSES, (
        "the pressable-class scan stopped seeing the controls it was written "
        "for, so this gate would now pass by discovering nothing")

    strays = []
    for sel, body in RULES + LAYOUT_RULES:
        declared = re.search(r"(?<![-\w])transition\s*:\s*([^;}]+)", body)
        if not declared:
            continue
        value = re.sub(r"\s+", " ", declared.group(1).strip())
        # `none` turns the property off on purpose (reduced motion, the deck's
        # pre-enter freeze). What this catches is a *list* that forgot
        # transform, not a deliberate opt-out of transitioning at all.
        if value == "none" or value.startswith("all") or "transform" in value:
            continue
        for part in (p.strip() for p in sel.split(",")):
            # The subject of the selector is its last compound: `.dh-fold i`
            # transitions the glyph, not the control, and a pseudo-element is
            # not the control either.
            if "::" in part:
                continue
            named = set(re.findall(r"\.([\w-]+)", re.split(r"[ >+~]", part)[-1]))
            if named & PRESSABLE_CLASSES and not named & PRESS_OPT_OUT_CLASSES:
                strays.append(f"{part} -> transition: {value}")
    assert strays == [], (
        "a pressable control's own `transition` shorthand overrides the press "
        "baseline's; name `transform` in it too, or the press snaps:\n  "
        + "\n  ".join(strays))


def test_hover_is_never_left_stuck_on_a_touch_screen():
    """`:hover` sticks after a tap on a touch screen, so every hover state is
    supposed to sit inside `(hover: hover) and (pointer: fine)` — which #1707
    did for the three controls it touched and for nothing else. The site menu,
    the retry, the sort headers, every fold toggle and the whole decision map
    stayed outside it, which is why the decision map also carried a coarse-
    pointer rule whose only job was to undo its own hover."""
    def walk(text, guarded):
        stray, i, n = [], 0, len(text)
        while i < n:
            open_at = text.find("{", i)
            if open_at < 0:
                break
            head = text[i:open_at].strip()
            depth, cursor = 1, open_at + 1
            while cursor < n and depth:
                depth += (text[cursor] == "{") - (text[cursor] == "}")
                cursor += 1
            body = text[open_at + 1:cursor - 1]
            if head.startswith("@"):
                stray += walk(body, guarded or "hover: hover" in head)
            else:
                selector = re.sub(r"\s+", " ", head)
                if ":hover" in selector and not guarded:
                    stray.append(selector)
                stray += walk(body, guarded)
            i = cursor
        return stray

    stray = walk(CSS, False) + walk(LAYOUT_CSS, False)
    assert stray == [], (
        "wrap these in @media (hover: hover) and (pointer: fine):\n  "
        + "\n  ".join(stray))


def test_one_focus_ring():
    """#1706 gave the shell one ring; the widgets kept two colours and five
    offsets. `outline: none` is allowed only where the rule replaces the ring
    with something else and says so."""
    wrong = []
    for sel, body in RULES + LAYOUT_RULES:
        if ":focus-visible" not in sel:
            continue
        outline = re.search(r"(?:^|;)\s*outline\s*:\s*([^;]+)", body)
        if outline and outline.group(1).strip() not in ("var(--focus-ring)", "none"):
            wrong.append(f"{sel} -> outline: {outline.group(1).strip()}")
        offset = re.search(r"outline-offset\s*:\s*([^;]+)", body)
        allowed_offsets = ("2px", "-2px", "3px", FOCUS_OFFSET_EXCEPTIONS.get(sel))
        if offset and offset.group(1).strip() not in allowed_offsets:
            wrong.append(f"{sel} -> outline-offset: {offset.group(1).strip()}")
    assert wrong == [], (
        "the ring is `var(--focus-ring)` at 2px (outside) or -2px (drawn inside "
        "a clipping box); 3px only clears a dot; documented component exceptions "
        "stay in FOCUS_OFFSET_EXCEPTIONS:\n  " + "\n  ".join(wrong))


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


def test_market_age_stays_in_the_market_heading_flow():
    """The age is heading metadata, not a fixed overlay on its title."""
    match = re.search(r"\.overview-asof\s*\{([^}]*)\}", RAW)
    assert match, "the market snapshot age label lost its rule"
    rule = match.group(1)
    assert "var(--font)" in rule and "var(--mono)" not in rule, rule
    assert "font-variant-numeric: tabular-nums" in rule, rule
    assert "white-space: nowrap" in rule, rule
    assert "position: absolute" not in rule, rule

    heading = re.search(
        r'<span class="overview-strip-heading">(.*?)</span>\s*'
        r'<span aria-hidden="true">盘面 →</span>',
        (ROOT / "site" / "index.html").read_text(),
        re.DOTALL,
    )
    assert heading, "market title and age must share the button heading group"
    assert 'id="market-asof"' in heading.group(1)
