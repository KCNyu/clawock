"""One loss prints one way on the dashboard.

`fmtMoney` wrote a negative as `$-7,269` and the command deck's `heroMoney`
wrote the same `realized_vs_unrealized` value as `−$7,269`, a few cards apart on
one page (#2672). The sign's position now has one owner, `fmtMoney`, and
`heroMoney` only adds the plus.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / "site" / "assets" / "js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required to run the bundle")
def test_the_command_deck_and_the_cards_print_a_loss_the_same_way():
    core = (JS / "dashboard.core.js").read_text(encoding="utf-8")
    hero = (JS / "dashboard.hero.js").read_text(encoding="utf-8")
    fmt = re.search(r"^  const fmtMoney = \(v, ccy\) => \{.*?^  \};$", core, re.M | re.S).group(0)
    deck = re.search(r"^  function heroMoney\(v, ccy\) \{.*?^  \}$", hero, re.M | re.S).group(0)
    script = ('const DASH = "—";\n' + fmt + "\n" + deck + "\n"
              "process.stdout.write(JSON.stringify(["
              "fmtMoney(-7269.43, 'USD'), heroMoney(-7269.43, 'USD'), fmtMoney(-99.99, 'HKD'),"
              "fmtMoney(3301.01, 'USD'), heroMoney(3301.01, 'USD'), heroMoney(0, 'USD')]));\n")
    out = subprocess.run([shutil.which("node"), "-e", script], check=True,
                         capture_output=True, text=True).stdout
    assert json.loads(out) == ["−$7,269", "−$7,269", "−HK$99.99", "$3,301", "+$3,301", "$0"]
