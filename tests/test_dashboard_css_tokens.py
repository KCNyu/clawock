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
