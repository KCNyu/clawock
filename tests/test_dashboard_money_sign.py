"""One loss prints one way on the dashboard.

`fmtMoney` wrote a negative as `$-7,269` and the command deck's `heroMoney`
wrote the same `realized_vs_unrealized` value as `−$7,269`, a few cards apart on
one page (#2672). The sign's position now has one owner, `fmtMoney`, and
`heroMoney` only adds the plus.

The rate printed under that amount is the same loss, and until #2957 it was
written with the other glyph: `−$7,269` over `-7.27%`. The glyph has one owner
too (`MINUS` / `fixed` in `dashboard.core.js`), and every formatter here is
evaluated on top of it.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / "site" / "assets" / "js"


def _sign_owner():
    """`MINUS` and `fixed` as the page defines them, ahead of any formatter."""
    core = (JS / "dashboard.core.js").read_text(encoding="utf-8")
    return ('const DASH = "—";\n'
            + re.search(r'^  const MINUS = .*$', core, re.M).group(0) + "\n"
            + re.search(r'^  const fixed = .*$', core, re.M).group(0) + "\n")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required to run the bundle")
def test_the_command_deck_and_the_cards_print_a_loss_the_same_way():
    core = (JS / "dashboard.core.js").read_text(encoding="utf-8")
    hero = (JS / "dashboard.hero.js").read_text(encoding="utf-8")
    fmt = re.search(r"^  const fmtMoney = \(v, ccy\) => \{.*?^  \};$", core, re.M | re.S).group(0)
    deck = re.search(r"^  function heroMoney\(v, ccy\) \{.*?^  \}$", hero, re.M | re.S).group(0)
    script = (_sign_owner() + fmt + "\n" + deck + "\n"
              "process.stdout.write(JSON.stringify(["
              "fmtMoney(-7269.43, 'USD'), heroMoney(-7269.43, 'USD'), fmtMoney(-99.99, 'HKD'),"
              "fmtMoney(3301.01, 'USD'), heroMoney(3301.01, 'USD'), heroMoney(0, 'USD')]));\n")
    out = subprocess.run([shutil.which("node"), "-e", script], check=True,
                         capture_output=True, text=True).stdout
    assert json.loads(out) == ["−$7,269", "−$7,269", "−HK$99.99", "$3,301", "+$3,301", "$0"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required to run the bundle")
def test_the_gold_card_prints_a_loss_with_the_minus_outside_the_symbol():
    """The gold card had its own formatter and printed `¥-2,766` while the cards
    around it printed `−$7,269` (#2713)."""
    hero = (JS / "dashboard.hero.js").read_text(encoding="utf-8")
    num = re.search(r"^    const num = \(v, d = 0\) => .*$", hero, re.M).group(0)
    signed = re.search(r"^    const signedCny = \(v\) => .*$", hero, re.M).group(0)
    script = (_sign_owner() + num + "\n" + signed + "\n"
              "process.stdout.write(JSON.stringify("
              "[signedCny(-2766.1), signedCny(1204.6), signedCny(0), signedCny(null)]));\n")
    out = subprocess.run([shutil.which("node"), "-e", script], check=True,
                         capture_output=True, text=True).stdout
    assert json.loads(out) == ["−¥2,766", "+¥1,205", "+¥0", "—"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required to run the bundle")
def test_a_rate_and_a_bare_number_print_a_loss_with_the_amounts_minus():
    """`−$7,269` sat directly above `-7.27%` on the float-rate card (#2957)."""
    core = (JS / "dashboard.core.js").read_text(encoding="utf-8")
    money = re.search(r"^  const fmtMoney = \(v, ccy\) => \{.*?^  \};$", core, re.M | re.S).group(0)
    pct = re.search(r"^  const fmtPct = \(v, digits = 2\) => \{.*?^  \};$", core, re.M | re.S).group(0)
    num = re.search(r"^  const fmtNum = \(v, digits = 2\) => \{.*?^  \};$", core, re.M | re.S).group(0)
    raw = re.search(r"^  const numText = \(v\) => .*?;$", core, re.M | re.S).group(0)
    script = (_sign_owner() + "\n".join([money, pct, num, raw]) + "\n"
              "const out = [fmtMoney(-7269.43, 'USD'), fmtPct(-7.269), fmtPct(-7.26, 1),"
              " fmtNum(-2.571), fixed(-0.39, 2), numText(-246.28), numText('-n/a'),"
              " fmtPct(7.269), fmtPct(null), numText(null), fixed(12.5, 1)];\n"
              "process.stdout.write(JSON.stringify("
              "{out, signs: out.slice(0, 6).map(s => s.codePointAt(0).toString(16))}));\n")
    got = json.loads(subprocess.run([shutil.which("node"), "-e", script], check=True,
                                    capture_output=True, text=True).stdout)
    assert got["out"] == ["−$7,269", "−7.27%", "−7.3%", "−2.57", "−0.39", "−246.28",
                          # a string the producer wrote is quoted, not reformatted
                          "-n/a", "+7.27%", "—", "—", "12.5"]
    assert set(got["signs"]) == {"2212"}
