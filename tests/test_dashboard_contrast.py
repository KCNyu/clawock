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
        return dict(re.findall(r"(--[\w-]+)\s*:\s*(#[0-9A-Fa-f]{3,6})\b", block))

    dark = tokens(re.search(r":root\s*\{([^{}]*)\}", css).group(1))
    light_block = re.search(
        r"@media \(prefers-color-scheme: light\)\s*\{\s*:root\s*\{([^{}]*)\}", css)
    return {"dark": dark, "light": {**dark, **tokens(light_block.group(1))}}


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
