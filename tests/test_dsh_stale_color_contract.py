"""One "stale" state, one warning colour in the provider row."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / 'examples/dsh/packages/clawock-dsh/src/styles.module.css').read_text()


def test_stale_uses_the_warning_colour_on_fill_and_value():
    assert '.wb-prov-fill[data-role=stale] { background: var(--wb-warn); }' in CSS
    assert '.wb-prov-primary[data-wb-tone=stale] { color: var(--wb-warn); }' in CSS
    assert '.wb-headline[data-wb-tone=stale] .wb-headline-value { color: var(--wb-warn); }' in CSS
