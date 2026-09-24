"""WCAG AA contrast for the faded timestamps, resolved through the cascade.

This exists because the fix for it was dead for as long as it had been written.
`.asof-faded { color: #263848 }` sat in the light-theme block with a comment
saying it preserved the quiet hierarchy "without blending below WCAG AA" — and
never applied, because every element carrying it also carries `.muted`, whose
`color` rule is a single class too and lives ~1600 lines further down. Equal
specificity, later in the file, so `.muted` won. Lighthouse measured the result
on the live desktop page at 3.24:1.

A string search for `#263848` would have passed the whole time. So this resolves
the winner the way a browser does — specificity, then source order — applies the
class's own opacity against the surface it sits on, and asserts the ratio.
"""
from pathlib import Path
import re

import pytest

CSS = Path(__file__).resolve().parents[1] / "site" / "assets" / "css" / "dashboard.css"
AA_NORMAL_TEXT = 4.5


def _relative_luminance(rgb):
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _hex(value):
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _blend(foreground, background, alpha):
    return tuple(round(alpha * f + (1 - alpha) * b)
                 for f, b in zip(foreground, background))


def _declarations(css, prop):
    """(selector, value, order) for every rule setting `prop`, in source order.

    Comments are stripped first. Leaving them in makes the text between two
    rules part of the next "selector", which quietly disqualifies exactly the
    rules that carry an explanatory comment — and the rule this file exists to
    protect is one of them.
    """
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    out = []
    for order, match in enumerate(re.finditer(r"([^{}]+)\{([^{}]*)\}", css)):
        selector, body = match.group(1).strip(), match.group(2)
        if selector.startswith("@") or "," in selector:
            continue
        found = re.search(rf"(?:^|;)\s*{prop}\s*:\s*([^;]+)", body)
        if found:
            out.append((selector, found.group(1).strip(), order))
    return out


def _specificity(selector):
    """Enough of the real algorithm for this stylesheet: (#id, .class, element)."""
    ids = len(re.findall(r"#[\w-]+", selector))
    classes = len(re.findall(r"\.[\w-]+", selector)) + len(re.findall(r"\[[^\]]+\]", selector))
    elements = len(re.findall(r"(?:^|[\s>+~])([a-z][\w-]*)", selector))
    return (ids, classes, elements)


def _winner(css, prop, classes):
    """The declaration a browser would apply to an element carrying `classes`."""
    applicable = []
    for selector, value, order in _declarations(css, prop):
        parts = set(re.findall(r"\.([\w-]+)", selector))
        # Only simple class selectors are in play for these two rules; a
        # descendant or element-qualified selector is not a match for a bare
        # element carrying exactly this class set.
        if not parts or not parts <= classes:
            continue
        if re.search(r"[\s>+~#\[]", selector.strip()):
            continue
        applicable.append((_specificity(selector), order, selector, value))
    if not applicable:
        pytest.fail(f"no {prop} declaration matches {sorted(classes)}")
    return max(applicable)


@pytest.mark.parametrize("surface, label", [("#FFFFFF", "card"), ("#F8FAFC", "panel")])
def test_faded_timestamps_meet_aa_against_light_surfaces(surface, label):
    css = CSS.read_text(encoding="utf-8")
    classes = {"muted", "asof-faded"}

    _, _, color_selector, color_value = _winner(css, "color", classes)
    _, _, _, opacity_value = _winner(css, "opacity", classes)
    alpha = float(opacity_value)

    assert color_value.startswith("#"), (
        f"the winning color for .muted.asof-faded is {color_value!r} from "
        f"{color_selector!r} — a variable here means the light-theme override "
        "lost the cascade again")

    effective = _blend(_hex(color_value), _hex(surface), alpha)
    ratio = _contrast(effective, _hex(surface))

    assert ratio >= AA_NORMAL_TEXT, (
        f"faded timestamps render at {ratio:.2f}:1 on the {label} surface "
        f"({color_value} at opacity {alpha} over {surface}); AA needs "
        f"{AA_NORMAL_TEXT}:1. Winning rule was {color_selector!r}.")


def _theme_tokens(css):
    """`--name: #hex` tokens per theme: dark is the first `:root`, light is the
    `prefers-color-scheme: light` override layered on top of it."""
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)

    def tokens(block):
        # Percentages too: the tint strengths are tokens now (`--tint-soft:
        # 15%`), so a chip's background reads `var(--positive) var(--tint-soft)`.
        # Without them `_paint` would leave the `var()` in place and every chip
        # would drop out of the scan — which is a pass on nothing.
        return dict(re.findall(
            r"(--[\w-]+)\s*:\s*(#[0-9A-Fa-f]{3,6}\b|\d+(?:\.\d+)?%)", block))

    def resolve(theme):
        # Aliases like `--card-2: var(--surface-2)` follow whichever theme the
        # target token resolves in, so they are resolved after the merge.
        for name, target in aliases.items():
            if target in theme:
                theme.setdefault(name, theme[target])
        return theme

    root = re.search(r":root\s*\{([^{}]*)\}", css).group(1)
    aliases = dict(re.findall(r"(--[\w-]+)\s*:\s*var\((--[\w-]+)\)\s*;", root))
    dark = tokens(root)
    light_block = re.search(
        r"@media \(prefers-color-scheme: light\)\s*\{\s*:root\s*\{([^{}]*)\}", css)
    return {"dark": resolve(dict(dark)),
            "light": resolve({**dark, **tokens(light_block.group(1))})}


def _rule_value(css, selector, prop):
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        if re.sub(r"\s+", " ", match.group(1).strip()) == selector:
            found = re.search(rf"(?:^|;)\s*{prop}\s*:\s*([^;]+)", match.group(2))
            if found:
                return found.group(1).strip()
    pytest.fail(f"no {prop} on {selector!r}")


def _paint(value, tokens, surface):
    """(rgb over `surface`) for the colour forms the regime badges use."""
    value = re.sub(r"var\((--[\w-]+)\)", lambda m: tokens[m.group(1)], value)
    if value.startswith("#"):
        return _hex(value)
    rgba = re.fullmatch(r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)", value)
    if rgba:
        return _blend(tuple(int(c) for c in rgba.groups()[:3]), surface, float(rgba.group(4)))
    mix = re.fullmatch(r"color-mix\(in srgb, (#[0-9A-Fa-f]{3,6}) ([\d.]+)%, transparent\)", value)
    if mix:
        return _blend(_hex(mix.group(1)), surface, float(mix.group(2)) / 100)
    mix = re.fullmatch(r"color-mix\(in srgb, (#[0-9A-Fa-f]{3,6}) ([\d.]+)%, (#[0-9A-Fa-f]{3,6})\)", value)
    if mix:
        return _blend(_hex(mix.group(1)), _hex(mix.group(3)), float(mix.group(2)) / 100)
    pytest.fail(f"unhandled colour {value!r}")


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_neutral_regime_badge_label_meets_aa_in_both_themes(theme):
    """#1580: the NEUTRAL label was a fixed `#94a3b8` — 6.55:1 on the dark card
    but 2.37:1 on the light one, on the badge's own tint. The ratio is taken
    against that tint over the card, which is what the text actually sits on."""
    css = CSS.read_text(encoding="utf-8")
    tokens = _theme_tokens(css)[theme]
    card = _hex(tokens["--surface-1"])
    badge = _paint(_rule_value(css, ".regime-badge.neutral", "background"), tokens, card)
    label = _rule_value(css, ".regime-badge.neutral .rg-label", "color")

    ratio = _contrast(_paint(label, tokens, badge), badge)

    assert ratio >= AA_NORMAL_TEXT, (
        f"{theme} NEUTRAL regime label {label} renders at {ratio:.2f}:1 on its "
        f"badge; AA needs {AA_NORMAL_TEXT}:1")


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("chip, row", [
    (".infl-who.musk", ".infl-row"),
    (".drv-chip.drv-peer", ".plan-action"),
])
def test_hardcoded_source_chips_meet_aa_in_both_themes(chip, row, theme):
    """#1583: the Musk author badge (`#3b82f6`) and the 同行 driver chip
    (`#2dd4bf`) had fixed text colours. On their own tint over the `--card-2`
    row they sit in, that was 2.83:1 / 1.55:1 in light and 3.72:1 for Musk in
    dark. The hued tokens their siblings use don't clear AA on that row in
    light either (`--accent` 3.91, `--positive` 4.28), so the text follows
    #1580 onto `--text-secondary` and the tint keeps the hue."""
    css = CSS.read_text(encoding="utf-8")
    tokens = _theme_tokens(css)[theme]
    row_bg = _paint(_rule_value(css, row, "background"), tokens, None)
    badge = _paint(_rule_value(css, chip, "background"), tokens, row_bg)
    label = _rule_value(css, chip, "color")

    ratio = _contrast(_paint(label, tokens, badge), badge)

    assert ratio >= AA_NORMAL_TEXT, (
        f"{theme} {chip} text {label} renders at {ratio:.2f}:1 on its tint over "
        f"{row}; AA needs {AA_NORMAL_TEXT}:1")


# A tint is what makes a chip a chip: the badge's own hue at low alpha, laid
# over whatever surface the row happens to be. Opaque fills don't depend on the
# surface and aren't this pattern.
_TINT = re.compile(
    r"color-mix\(in srgb, [^,]+ (?:[\d.]+%|var\(--tint-[\w-]+\)), transparent\)"
    r"|rgba\(\s*\d+,\s*\d+,\s*\d+,\s*0?\.\d+\s*\)")
# Every opaque surface a chip can land on, in either theme. --surface-3 is the
# hover row and the lightest/darkest of them, so it bounds the glass panels too.
_SURFACES = ("--bg", "--surface-0", "--surface-1", "--surface-2", "--surface-3")


def _tinted_chips(css):
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        body = match.group(2)
        background = re.search(r"(?:^|;)\s*background(?:-color)?\s*:\s*([^;]+)", body)
        color = re.search(r"(?:^|;)\s*color\s*:\s*([^;]+)", body)
        if background and color and _TINT.fullmatch(background.group(1).strip()):
            yield (re.sub(r"\s+", " ", match.group(1).strip()),
                   background.group(1).strip(), color.group(1).strip())


def test_every_tinted_chip_meets_aa_on_every_surface_in_both_themes():
    """#1585: #1580 and #1583 each pinned the selectors their issue named, so
    the next sibling on the same pattern went unchecked — and there were 34 of
    them. The cause was never one chip: a hued token clears AA on a bare
    surface (light `--negative` is 4.55 on card-2) and a 10–18% tint of itself
    costs 0.4–0.9, so every "same-hue tint + same-hue text" chip fell under,
    Trump in dark too. Chip text now uses the `--*-ink` step of its hue.

    So this doesn't list chips. It finds every rule that paints a translucent
    tint behind its own text colour and checks it on every surface, in both
    themes; a new chip is covered the day it's written."""
    css = CSS.read_text(encoding="utf-8")
    themes = _theme_tokens(css)
    chips = list(_tinted_chips(css))
    selectors = {selector for selector, _, _ in chips}
    # The parser finding nothing would pass vacuously; the chips #1585 was
    # opened for must be among what it found.
    assert {".infl-who.trump", ".drv-chip.drv-catalyst", ".drv-chip.drv-macro",
            ".infl-who.duan, .infl-who.honghao"} <= selectors, sorted(selectors)
    assert len(chips) >= 40, f"only {len(chips)} tinted chips found; the parser broke"

    failures = []
    for selector, background, color in chips:
        for theme, tokens in themes.items():
            for surface in _SURFACES:
                badge = _paint(background, tokens, _hex(tokens[surface]))
                ratio = _contrast(_paint(color, tokens, badge), badge)
                if ratio < AA_NORMAL_TEXT:
                    failures.append(f"{theme} {selector} {color} on {surface}: {ratio:.2f}")

    assert not failures, (
        f"tinted chip text below AA {AA_NORMAL_TEXT}:1 — use the hue's --*-ink "
        "token (or --text-secondary) for the text:\n" + "\n".join(failures))


def test_plain_negative_text_meets_aa_on_the_light_inset_layers():
    """A semantic token can pass on white and still fail where it is used.

    The widget audit checked tinted chips, but ordinary ``.neg`` text is also
    printed on ``--surface-3``.  The former light ``--negative`` was 4.26:1
    there even though the chip-only guard stayed green.
    """
    tokens = _theme_tokens(CSS.read_text(encoding="utf-8"))["light"]
    foreground = _hex(tokens["--negative"])
    failures = []
    for surface in ("--surface-1", "--surface-2", "--surface-3", "--overlay"):
        ratio = _contrast(foreground, _hex(tokens[surface]))
        if ratio < AA_NORMAL_TEXT:
            failures.append(f"{surface}: {ratio:.2f}")
    assert not failures, "light --negative is below AA on " + ", ".join(failures)


def test_informational_rows_and_badges_are_not_dimmed_below_aa():
    """Low sample/idle are states, not disabled controls.

    Parent opacity compounds every otherwise-valid child colour.  It reduced
    the low-sample badge to 1.62:1 and the idle cron row to 2.54:1 in the real
    DOM, outside the tint scanner's model.  The data-health board keeps its
    quiet rows quiet with a text step on the name, never with opacity.
    """
    css = re.sub(r"/\*.*?\*/", " ", CSS.read_text(encoding="utf-8"), flags=re.S)
    for selector in (".bucket-wr.wr-lown", ".dh-job-name"):
        match = next((m for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
                      if re.sub(r"\s+", " ", m.group(1).strip()) == selector), None)
        assert match, f"missing {selector}"
        assert not re.search(r"(?:^|;)\s*opacity\s*:", match.group(2)), (
            f"{selector} dims readable information with parent opacity")


def test_heatmap_and_drawdown_small_text_use_readable_text_steps():
    css = CSS.read_text(encoding="utf-8")
    assert _rule_value(css, ".dm-cell .dm-m", "color") == "var(--text)"
    assert _rule_value(css, ".ext-region .ext-dd .k", "color") == "var(--text)"
    assert _rule_value(css, ".ext-region .ext-dd .span", "color") == "var(--text)"
