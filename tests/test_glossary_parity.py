"""Structural and content guards for docs/glossary.md.

The glossary is the source of truth for cross-document terminology: each entry
must keep its EN term, its canonical Chinese rendering, a one-sentence
definition, and a `First defined` pointer to the originating file. The same
one-term-one-Chinese rule the test enforces here is the rule translators
follow when the term appears elsewhere in the project, so the test is not
only a regression gate — it is the contract that prevents the glossary from
drifting into a second glossary that disagrees with the README.

The structural rules are deliberately strict:

1. Every entry row is exactly four columns separated by ` | `.
2. Every EN term is unique.
3. Every Chinese rendering is unique (one EN → one 中文, no alternates).
4. Every `First defined` pointer resolves to an existing path.
5. The term appears in the file it claims to be defined in.
6. No decorative emoji in the heading or in the table cells — see
   `test_readme_parity.py` for the same house rule.

If a term legitimately needs two Chinese renderings, do **not** add an
alternate; fix the original Chinese rendering and update the README at the
same time. Drift between the glossary and the translation site is the
failure mode this test exists to catch.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GLOSSARY = ROOT / "docs" / "glossary.md"


def _parse_table_rows(text):
    """Return list of (en, zh, definition, first_defined) for every body row.

    Skips the header, separator and any blank rows. The glossary uses a fixed
    four-column pipe table; a row that doesn't match that shape is a bug and
    the test should refuse it.
    """
    rows = []
    in_table = False
    for line in text.splitlines():
        if not line.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not in_table:
            in_table = True
            # First table row is always the header — skip the header and the
            # immediately following separator row.
            continue
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            # Markdown table separator.
            continue
        if len(cells) != 4:
            raise AssertionError(
                f"glossary row does not have 4 cells: {line!r}"
            )
        en, zh, definition, first_defined = cells
        rows.append((en, zh, definition, first_defined))
    return rows


def _first_emoji(text):
    for ch in text:
        o = ord(ch)
        # Same ranges as test_readme_parity — arrows and CJK are fine.
        if any(lo <= o <= hi for lo, hi in (
            (0x1F300, 0x1FAFF), (0x2600, 0x27BF),
            (0x1F1E6, 0x1F1FF), (0x2B00, 0x2BFF),
            (0xFE0F, 0xFE0F),
        )):
            return ch
    return None


def test_glossary_exists():
    assert GLOSSARY.exists(), f"{GLOSSARY} must exist; this is the term source of truth"


def test_glossary_has_at_least_one_table():
    text = GLOSSARY.read_text(encoding="utf-8")
    rows = _parse_table_rows(text)
    assert len(rows) >= 20, (
        f"glossary should have at least 20 term rows; got {len(rows)}. "
        "If a smaller glossary is intended, update the floor and the rationale."
    )


def test_each_row_has_four_cells_with_non_empty_fields():
    text = GLOSSARY.read_text(encoding="utf-8")
    rows = _parse_table_rows(text)
    for i, (en, zh, definition, first_defined) in enumerate(rows):
        assert en, f"row {i}: empty EN term"
        assert zh, f"row {i} ({en!r}): empty Chinese rendering"
        assert definition, f"row {i} ({en!r}): empty one-sentence definition"
        assert first_defined, f"row {i} ({en!r}): empty First defined"


def test_en_terms_are_unique():
    text = GLOSSARY.read_text(encoding="utf-8")
    rows = _parse_table_rows(text)
    en_terms = [r[0] for r in rows]
    lower = [t.lower() for t in en_terms]
    dupes = sorted({t for t in lower if lower.count(t) > 1})
    assert not dupes, f"duplicate EN terms (case-insensitive): {dupes}"


def test_chinese_renderings_are_unique():
    """One EN term → one Chinese rendering. Translators do not pick alternates."""
    text = GLOSSARY.read_text(encoding="utf-8")
    rows = _parse_table_rows(text)
    zh_renderings = [r[1] for r in rows]
    dupes = sorted({t for t in zh_renderings if zh_renderings.count(t) > 1})
    assert not dupes, (
        f"duplicate Chinese renderings: {dupes}. "
        "Pick one canonical rendering per EN term; translators must follow."
    )


def test_first_defined_paths_exist():
    text = GLOSSARY.read_text(encoding="utf-8")
    rows = _parse_table_rows(text)
    for en, _, _, first_defined in rows:
        # The pointer may include a backref like `` `module_name` `` or `` PR #1198``.
        # It may also be a comma-separated list — every path must exist.
        raw = first_defined.strip()
        # Drop inline-backticks and split on comma.
        pieces = [p.strip().strip("`") for p in raw.split(",")]
        # Skip PR references (checked by another test).
        pieces = [p for p in pieces if not p.startswith("PR ")]
        if not pieces:
            continue
        for piece in pieces:
            # Strip a `module::name` backref to just the file.
            path_part = piece.split("::")[0].strip()
            if not path_part:
                continue
            candidates_to_check = [path_part]
            if not path_part.startswith(("src/", "docs/", "tests/", "site/")):
                candidates_to_check = [
                    path_part,
                    f"src/clawock/{path_part}",
                    f"docs/{path_part}",
                ]
            assert any(
                (ROOT / p).exists() for p in candidates_to_check
            ), (
                f"row {en!r}: First defined {first_defined!r} — "
                f"no path matches any of {candidates_to_check}"
            )


def test_first_defined_pr_references_exist():
    """If `First defined` points at a PR, that PR must exist in origin/master."""
    text = GLOSSARY.read_text(encoding="utf-8")
    rows = _parse_table_rows(text)
    # Read commit log once
    try:
        commits = (ROOT / ".git").resolve()
    except Exception:
        commits = None
    import subprocess
    for en, _, _, first_defined in rows:
        m = re.match(r"^PR #(\d+)$", first_defined.strip())
        if not m:
            continue
        pr = int(m.group(1))
        result = subprocess.run(
            ["gh", "pr", "view", str(pr), "--repo", "KCNyu/clawock",
             "--json", "number", "--jq", ".number"],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0 and result.stdout.strip() == str(pr), (
            f"row {en!r}: First defined points at PR #{pr}, "
            f"but that PR is not accessible: {result.stderr.strip() or result.stdout.strip()}"
        )


def test_term_appears_in_first_defined_file():
    """The EN term should appear in the file it claims to be defined in.

    This catches stale pointers after a refactor. It's a soft check —
    underscored terms may have moved and we skip the lookup for those.
    """
    text = GLOSSARY.read_text(encoding="utf-8")
    rows = _parse_table_rows(text)
    for en, _, _, first_defined in rows:
        first_defined = first_defined.strip().strip("`")
        if first_defined.startswith("PR "):
            continue
        # Extract the leading path
        m = re.match(r"^([\w./-]+)", first_defined)
        if not m:
            continue
        path_part = m.group(1)
        # Normalize to existing path; pick the **first existing** candidate,
        # not the first one in the list (top-level README.md takes precedence
        # over docs/README.md because `risk budget` was first defined at the
        # project root).
        candidates = [path_part]
        if not path_part.startswith(("src/", "docs/", "tests/", "site/")):
            candidates = [
                path_part,  # top-level first, e.g. README.md
                f"src/clawock/{path_part}",
                f"docs/{path_part}",
            ]
        target = None
        for c in candidates:
            p = ROOT / c
            if p.exists():
                target = p
                break
        if target is None:
            continue  # checked by test_first_defined_paths_exist
        try:
            content = target.read_text(encoding="utf-8").lower()
        except Exception:
            continue
        # Token-based lookup: split the EN term on whitespace and parens,
        # accept the row if any token of length ≥ 6 appears in the target file.
        tokens = re.findall(r"[a-z0-9_]+", en.lower())
        if not tokens:
            continue
        # Skip short tokens like 'IC' that may collide with random text.
        candidates = [t for t in tokens if len(t) >= 6]
        if not candidates:
            continue
        matched = any(t in content for t in candidates)
        assert matched, (
            f"row {en!r}: First defined points at {target.relative_to(ROOT)}, "
            f"but none of {candidates!r} appears in that file. "
            "Stale pointer or a move?"
        )


def test_no_decorative_emoji_in_glossary():
    text = GLOSSARY.read_text(encoding="utf-8")
    bad = _first_emoji(text)
    assert bad is None, (
        f"glossary contains decorative emoji {bad!r}. "
        "House rule: arrows and CJK are fine; decorative pictographs are not."
    )


def test_glossary_link_in_readmes():
    """Both READMEs must reference docs/glossary.md so readers can find it."""
    en = (ROOT / "README.md").read_text(encoding="utf-8")
    zh = (ROOT / "README.zh.md").read_text(encoding="utf-8")
    assert "docs/glossary.md" in en, "README.md must link to docs/glossary.md"
    assert "docs/glossary.md" in zh, "README.zh.md must link to docs/glossary.md"
