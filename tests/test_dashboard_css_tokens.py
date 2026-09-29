"""Every custom property the dashboard stylesheet reads without a fallback exists.

An undefined `var(--x)` is not an error anywhere: the declaration silently
computes to its initial value. `.trace-rows` and the decision-trace timeline dot
read `var(--surface)`, a token the palette never defined (only `--surface-0..3`
and the `--card` alias), so both painted transparent and the rail line ran
through every dot (#1535).
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "site" / "assets" / "css" / "dashboard.css"


def test_every_fallbackless_var_is_defined():
    css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.DOTALL)
    defined = set(re.findall(r"(--[\w-]+)\s*:", css))
    # Properties the page sets at runtime (element.style.setProperty("--x", …)).
    for path in (ROOT / "site").rglob("*.js"):
        defined |= set(re.findall(r"setProperty\(\s*[\"'](--[\w-]+)", path.read_text(encoding="utf-8")))
    missing = sorted({name for name, fallback in re.findall(r"var\(\s*(--[\w-]+)\s*(,)?", css)
                      if not fallback and name not in defined})
    assert missing == [], f"dashboard.css reads undefined custom properties: {missing}"


def test_a_fallback_never_stands_in_for_a_token_nobody_defines():
    """#2145: `var(--hover-bg, rgba(0,0,0,0.03))` read a property the palette
    never defined, so the literal always won — a light-theme 3% black that on
    the dark canvas measured 1.0139:1, i.e. no hover at all. The gate above
    skips any var() with a fallback; this one asks that the name still exists
    (a stylesheet declaration, an inline `style="--x:…"`, or setProperty)."""
    css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.DOTALL)
    defined = set(re.findall(r"(--[\w-]+)\s*:", css))
    for path in [*(ROOT / "site").rglob("*.js"), *(ROOT / "site").rglob("*.html")]:
        text = path.read_text(encoding="utf-8")
        defined |= set(re.findall(r"setProperty\(\s*[\"'](--[\w-]+)", text))
        defined |= set(re.findall(r"(--[\w-]+)\s*:", text))
    orphaned = sorted({name for name, fallback in re.findall(r"var\(\s*(--[\w-]+)\s*(,)?", css)
                       if fallback and name not in defined})
    assert orphaned == [], f"dashboard.css falls back for tokens nothing defines: {orphaned}"


def test_heatmap_direction_colors_follow_theme_tokens():
    css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.DOTALL)
    assert re.search(r"--heat-up\s*:\s*var\(--positive\)", css)
    assert re.search(r"--heat-down\s*:\s*var\(--negative\)", css)
    assert not re.search(r"--heat-(?:up|down)\s*:\s*#[0-9a-fA-F]+", css)
