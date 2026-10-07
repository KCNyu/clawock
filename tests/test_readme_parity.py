"""EN/ZH README structural parity + house-style guards.

The two READMEs translate meaning, not syntax, so we cannot compare text — but
their skeleton (section count, collapsibles, embedded assets, primary links) must
stay identical so the versions cannot quietly drift. We also lock in the redesign
decisions: no decorative emoji in headings (the "AI-generated README" tell), and no
live/changing numbers hard-coded into evergreen copy.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN = (ROOT / "README.md").read_text(encoding="utf-8")
ZH = (ROOT / "README.zh.md").read_text(encoding="utf-8")
# The detail the READMEs link to instead of carrying (#2707): the layer table, the
# per-run block breakdown and the rules moved here, and their pins moved with them.
DESK_EN = (ROOT / "docs/how-the-desk-works.md").read_text(encoding="utf-8")
DESK_ZH = (ROOT / "docs/how-the-desk-works.zh.md").read_text(encoding="utf-8")
LLMS = (ROOT / "site/llms.txt").read_text(encoding="utf-8")
FAQ = (ROOT / "site/faq.md").read_text(encoding="utf-8")

# Pictographic emoji codepoints (symbols, pictographs, flags, dingbats, variation
# selector), checked as explicit ranges instead of a regex character class — it reads
# clearly and avoids flagging the wide unicode ranges as a suspicious regex range.
# Deliberately excludes the arrow block (←↑→ are legitimate typography used in the
# schedule and repo-layout blocks) and the CJK range (Chinese prose is fine).
_EMOJI_RANGES = (
    (0x1F300, 0x1FAFF), (0x2600, 0x27BF), (0x1F1E6, 0x1F1FF),
    (0x2B00, 0x2BFF), (0xFE0F, 0xFE0F),
)


def _first_emoji(text):
    for ch in text:
        o = ord(ch)
        if any(lo <= o <= hi for lo, hi in _EMOJI_RANGES):
            return ch
    return None

EN_H2 = [
    "What you get", "Information in: sources before opinions",
    "Decision out: both sides read the same evidence",
    "After the close: results feed the next decision",
    "Any harness, one decision contract that accumulates evidence",
    "What the model is not allowed to do", "Try it in five minutes",
    "Harness views and background work", "Under the hood", "Explore",
    "Scope, disclaimer, and license",
]
ZH_H2 = [
    "你能得到什么", "信息进来：先有来源，再有观点", "决策出来：多空同读一份证据",
    "收盘后：结果回到下一次判断", "任何 harness，同一套会积累的决策契约",
    "模型不被允许做的事", "五分钟跑起来", "Harness 界面与后台工作",
    "引擎盖下面", "接着看", "范围、免责与许可",
]


def _h2(md):
    return [ln for ln in md.splitlines() if ln.startswith("## ")]


def _details(md):
    return md.count("<summary>")


def _assets(md):
    return sorted(set(re.findall(r"(?:site/)?assets/[\w./-]+\.(?:svg|png|gif)", md)))


def test_section_count_matches():
    assert len(_h2(EN)) == len(_h2(ZH)) > 0


def test_details_count_matches():
    # The user explicitly wants the original visual forms directly visible.
    # Pin zero collapsibles rather than silently allowing them to return.
    assert _details(EN) == _details(ZH) == 0


def test_embedded_assets_match():
    # Same image assets, in both files, and each one exists on disk.
    assert _assets(EN) == _assets(ZH)
    for rel in _assets(EN):
        assert (ROOT / rel).exists(), f"README references missing asset {rel}"


def test_primary_links_present_in_both():
    for target in (
        "https://kcnyu.github.io/clawock/",
        "https://kcnyu.github.io/clawock/briefs.html",
        "docs/operations/cron-schedules.md",
        "docs/legal/third-party-data.md",
        "LICENSE",
    ):
        assert target in EN and target in ZH, f"{target} missing from a README"


def test_language_switch_links_cross():
    assert "README.zh.md" in EN
    assert "README.md" in ZH


def test_research_surfaces_stay_in_both_languages():
    assert "### Research surfaces" in EN
    assert "### 研究入口" in ZH
    for target in (
        "skills/us-stock-analysis/SKILL.md",
        "skills/hk-stock-analysis/SKILL.md",
        "skills/portfolio-risk-review/SKILL.md",
        "skills/portfolio-swarm-review/SKILL.md",
        "skills/serenity-skill/SKILL.md",
        "skills/earnings-review/SKILL.md",
        "skills/entry-gate/SKILL.md",
    ):
        assert target in EN and target in ZH, f"{target} missing from a README"


def test_per_run_context_layers_documented_in_both_languages():
    """The layered view must stay honest about counts: it claims a block count per
    run, and those come from the preflights' own context dicts.

    #759: the anchor used to be an opening brace with no newline after it, so for two of the three
    preflights it latched onto an unrelated single-line `result = {'rows': rows}`
    hundreds of lines earlier and then counted every quoted key in every nested
    dict until the next dedented brace. It was measuring the wrong object, and
    the README numbers had been calibrated to that wrong measurement (intraday
    read 28 where the context literal has 29 blocks; brief read 39 where it has
    37). Requiring the newline pins each match to the real multi-line payload,
    and an 8-space anchor keeps nested keys out of the count.

    Identifiers assigned after the literal (`context_id`, `generation_id`) are
    deliberately not counted: they name the packet, they are not blocks in it —
    which is why a written artifact carries one key more than this number.
    """
    import re

    assert "### What each run actually receives" in DESK_EN
    assert "### 每种运行实际拿到什么" in DESK_ZH

    root = Path(__file__).resolve().parents[1]
    counts = {}
    for name, path in (
        ("brief", "src/clawock/harness/brief_preflight.py"),
        ("report", "src/clawock/harness/report_preflight.py"),
        ("intraday", "src/clawock/harness/intraday_preflight.py"),
    ):
        source = (root / path).read_text()
        block = re.search(r"\n    (?:context|result) = \{\n(.*?)\n    \}",
                          source, re.S)
        assert block, name
        counts[name] = len(re.findall(r"^        '([a-z_0-9]+)':",
                                      block.group(1), re.M))

    for md, name in ((DESK_EN, "docs/how-the-desk-works.md"),
                     (DESK_ZH, "docs/how-the-desk-works.zh.md")):
        row = next(line for line in md.splitlines()
                   if line.startswith("| **Blocks**") or line.startswith("| **块数**"))
        # split, not a shared-delimiter regex: `| 36 | 15 | 18 |` consumes the
        # middle pipe and silently drops a column
        stated = [int(cell.strip()) for cell in row.split("|")
                  if cell.strip().isdigit()]
        assert stated == [counts["brief"], counts["report"], counts["intraday"]], (
            f"{name} block counts drifted from the preflights: {stated} vs {counts}"
        )


def test_the_information_layer_table_adds_up_in_both_languages():
    """The one structural number in the README that nothing was checking.

    Everything else with a count behind it is pinned — the per-run block counts
    read the preflights' own context dicts, the section and asset lists are
    compared across languages. The information-layer table was prose: a headline
    ("N fetch and compute modules across M layers") sitting above a table whose
    rows carry the per-layer counts, in two languages, with nothing tying the
    four numbers together. Editing one row and forgetting the headline is a
    silent, plausible edit, and so is fixing it in one language only.

    What this does NOT prove, stated so nobody reads more into a green: it does
    not verify the modules exist or that the taxonomy still matches the package.
    When this was written that mapping had no artifact behind it — the layers
    were drawn when these were files under `scripts/data/`, which #429 deleted —
    so a test claiming to check it would have been encoding a guess as truth.
    `config/information-layers.json` is now that artifact and
    `tests/test_information_layer_taxonomy.py` grounds the rows against it
    (#476). This one still only checks that the four numbers agree; the two are
    kept separate so the internal-consistency check survives if the taxonomy is
    ever reshaped.
    """
    seen = {}
    for md, name, pattern in (
        (DESK_EN, "docs/how-the-desk-works.md",
         r"\*\*(\d+) fetch and compute modules across (\d+) layers\*\*"),
        (DESK_ZH, "docs/how-the-desk-works.zh.md", r"\*\*(\d+) 层、(\d+) 个抓取与计算模块\*\*"),
    ):
        headline = re.search(pattern, md)
        assert headline, f"{name}: the information-layer headline changed shape"
        # ZH states layers first, EN states modules first.
        modules, layers = (headline.group(1), headline.group(2))
        if name.endswith("zh.md"):
            layers, modules = modules, layers

        rows = [ln for ln in md.splitlines() if re.match(r"^\| \d+ · ", ln)]
        assert len(rows) == int(layers), (
            f"{name}: headline says {layers} layers, table has {len(rows)} rows")

        per_layer = [int(ln.split("|")[2].strip()) for ln in rows]
        assert sum(per_layer) == int(modules), (
            f"{name}: rows sum to {sum(per_layer)}, headline says {modules}")

        seen[name] = per_layer

    # The rows must also be the same rows in both languages, or the two READMEs
    # describe different systems while each stays internally self-consistent.
    assert seen["docs/how-the-desk-works.md"] == seen["docs/how-the-desk-works.zh.md"], (
        f"layer counts differ between languages: {seen}")


def test_the_two_book_card_sits_in_the_hero_after_the_dashboard_gif():
    """The US/HK card is a result, so it stays above the first section heading;
    it follows the dashboard GIF, which is the page's opening image."""
    for md, name in ((EN, "README.md"), (ZH, "README.zh.md")):
        hero = md.split("\n## ", 1)[0]
        assert "books.svg" in hero, f"{name}: the book card slid below the first section"
        assert hero.index("dashboard.gif") < hero.index("books.svg"), (
            f"{name}: the book card moved ahead of the dashboard GIF")
        # Like every other figure it has a desktop and a single-column layout.
        assert re.search(r'<picture><source media="\(max-width: 700px\)" srcset="[^"]*'
                         r'site/assets/books-narrow\.svg"><img src="[^"]*site/assets/books\.svg"',
                         hero), f"{name}: the book card lost one of its two layouts"


def test_explicit_h2_sequences():
    # Lock both languages' section order (and their 1:1 correspondence by position),
    # not just the count — so a section can't be added/reordered in one language only.
    assert [h[3:].strip() for h in _h2(EN)] == EN_H2
    assert [h[3:].strip() for h in _h2(ZH)] == ZH_H2


def test_hero_is_unchanged_apart_from_weekly_metrics():
    """The confirmed first 33 lines stay byte-identical except refreshed CW_M values."""
    import hashlib

    for md, expected in (
        (EN, "d179668bd8b5d487ef3fbc5c0243aeb6e8f25c3104614a6dc22e6295540058f0"),
        (ZH, "6267f85a944050fdc44c0d309a829d9bff9c66110f71c30bcfc547b76636acd1"),
    ):
        hero = ''.join(md.splitlines(keepends=True)[:33])
        hero = re.sub(r'(<!-- CW_M:\w+ -->).*?(<!-- /CW_M:\w+ -->)', r'\1\2', hero)
        assert hashlib.sha256(hero.encode()).hexdigest() == expected


def test_the_whole_loop_figure_opens_the_first_section():
    """The complete figure leads; a one-paragraph intro is all that precedes it."""
    for md in (EN, ZH):
        first = md.split("\n## ")[1]
        before, _, after = first.partition('<p align="center"><img')
        assert 'rsi-loop.svg' in after.split('\n', 1)[0]
        assert len([ln for ln in before.splitlines()[1:] if ln.strip()]) == 1
        assert '|---' not in first


def test_rsi_artifacts_and_portability_precede_installation():
    """The reader sees inputs, a decision and measurable feedback before setup."""
    for md, setup in ((EN, "## Try it in five minutes"), (ZH, "## 五分钟跑起来")):
        story = md[:md.index(setup)]
        for artifact in ('request.json', 'decision.json', 'plan.json', 'decisions.jsonl',
                         'outcome.json', 'evaluation.json'):
            assert artifact in story, artifact
        for harness in ('Claude Code', 'Codex', 'OpenClaw', 'DeepSeek Harness'):
            assert harness in story, harness
        for diagram in ('rsi-loop', 'information-flow', 'feedback-learning'):
            assert f'{diagram}.svg' in story, diagram
        assert story.index('decision-card-example.png') < story.index('shadow-backtest.png')


def test_emoji_only_in_the_hhi_bucket_row():
    # The single place emoji are allowed is the HHI concentration row, where the
    # ✅🟡🟠🔴 markers mirror the dashboard's actual bucket colors. Nowhere else — no
    # decorative heading emoji, no ⚠️ leaking into prose. Whole-document scan.
    for md, name in ((EN, "README.md"), (ZH, "README.zh.md"),
                     (DESK_EN, "docs/how-the-desk-works.md"),
                     (DESK_ZH, "docs/how-the-desk-works.zh.md")):
        for i, line in enumerate(md.splitlines(), 1):
            if "HHI" in line and "0.15" in line:
                continue  # the allowed bucket legend
            ch = _first_emoji(line)
            assert ch is None, f"emoji outside the HHI row at {name}:{i}: {ch!r}"


def test_zh_uses_benchmark_vendor_not_official_bars():
    # Iron rule: settlement bars come from a canonical VENDOR feed (Tencent/etc.),
    # never an exchange/official feed. ZH must not resurrect the 官方 phrasings.
    for banned in ("官方行情", "官方源", "官方不复权", "官方逐日"):
        assert banned not in ZH, f"disallowed official-market-data claim in ZH: {banned!r}"


def test_no_live_numbers_in_evergreen_copy():
    # Policy constants (35%, -18%, x2/x3, HHI bucket thresholds) are static config and
    # allowed. What must never appear is a hard-coded live result: a win rate, a P&L
    # figure, or a sample size — those drift and go stale. Guard the phrasings that
    # would carry one.
    banned = [
        r"win rate of \d", r"\d+%\s*win", r"n\s*=\s*\d",   # sample sizes / rates
        r"[-+]?\$\d[\d,]*\s*(?:profit|loss|P&L|pnl)",       # money results
        r"胜率\s*\d", r"样本\s*\d", r"n\s*=\s*\d+\s*条",
        # #648: 公开战绩 prose must not re-freeze live results the CW_M
        # placeholders own — the refresh script only rewrites placeholders, so
        # a hard-coded twin on the same page silently drifts (the −15.95%/640
        # twin already did once; this guard pins the phrasings that carry one).
        r"真实账户收益\s*[−-]?\d",   # prose P&L, not the bracketed template
        r"账本在此:\s*\d+",          # frozen ledger row count in prose
        r"别拿\s*\d+",               # frozen figure in a rule-of-thumb sentence
        # Chinese prose can restate a live hit rate without a % sign (#2102).
        r"每\s*[零一二三四五六七八九十百两\d]+\s*次.{0,20}对\s*[零一二三四五六七八九十百两\d]+\s*次(?:半)?",
    ]
    # #670: site/llms.txt and site/faq.md have no CW_M refresh placeholders, so
    # any hard-coded live figure there is stale the day after it lands. Ban the
    # frozen shapes outright: a decimal return %, a "+ days" run length, a
    # "+ records" ledger size, and settled-judgment / active-rate counts.
    site_banned = [
        r"−?\d+\.\d+%",        # frozen account return (the −15.95% that froze)
        r"\d+\+\s*days",       # frozen run length (90+)
        r"\d+\+\s*records",    # frozen ledger size (640+)
        r"\d+\s*judgments",    # frozen settled count (177)
        r"\d+%\s*active",      # frozen active-hit-rate pair (53%)
    ]
    for md, name in (
        (EN, "README.md"), (ZH, "README.zh.md"),
        (LLMS, "site/llms.txt"), (FAQ, "site/faq.md"),
    ):
        patterns = banned + (site_banned if name.startswith("site/") else [])
        for pat in patterns:
            m = re.search(pat, md, re.IGNORECASE)
            assert not m, f"live number in evergreen copy ({name}): {m.group(0)!r}"


def test_the_weekly_metrics_placeholders_survive_a_rewrite():
    """`ops/growth/refresh_readme_metrics.py` rewrites the CW_M placeholders in
    place every Sunday. A README edit that drops one does not fail anything:
    the job just stops updating that number, and the figure left in its place
    goes stale in silence. A key the script does not compute is the other way
    round: it raises KeyError and the weekly job goes red.

    So both are pinned: each README keeps the keys it has, and every key it
    uses is one the script produces. Dropping a number on purpose means
    editing the set below in the same change.
    """
    source = (ROOT / "ops/growth/refresh_readme_metrics.py").read_text(encoding="utf-8")
    block = re.search(r"\n    values = \{\n(.*?)\n    \}", source, re.S)
    assert block, "refresh_readme_metrics.py no longer builds a `values` dict"
    produced = set(re.findall(r'^        "(\w+)":', block.group(1), re.M))
    assert produced, "no keys read from the refresh script: this test would pass vacuously"

    expected = {
        # The per-book and combined returns are printed by site/assets/books.svg,
        # which the same script redraws, so README.md carries no placeholder for them.
        "README.md": {"days", "rows", "settled"},
        "README.zh.md": {
            "as_of", "days", "rows", "settled", "return_pct", "active_pct",
            "active_n", "hold_pct", "hold_n", "hi_pct", "hi_n", "active_ci",
            "hi_ci", "followed", "not_followed", "unknown",
        },
    }
    for md, name in ((EN, "README.md"), (ZH, "README.zh.md")):
        opened = re.findall(r"<!-- CW_M:(\w+) -->", md)
        closed = re.findall(r"<!-- /CW_M:(\w+) -->", md)
        assert sorted(opened) == sorted(closed), f"{name}: an unpaired CW_M placeholder"
        assert set(opened) == expected[name], (
            f"{name}: placeholders {sorted(set(opened))} != {sorted(expected[name])}")
        assert set(opened) <= produced, (
            f"{name}: {sorted(set(opened) - produced)} are not computed by the refresh script")
