"""Brief readability is observable, but modest overage is not product failure."""
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
from clawock.harness import brief_postflight as postflight  # noqa: E402


def _write_size(path: Path, size: int) -> Path:
    path.write_bytes(b'x' * size)
    return path


def test_clean_brief_is_within_budget_and_passes(tmp_path):
    path = _write_size(
        tmp_path / 'brief.md', postflight.BRIEF_READABILITY_TARGET_BYTES)

    readability = postflight.assess_brief_readability(path)

    assert readability['status'] == 'within_budget'
    assert readability['bytes'] == postflight.BRIEF_READABILITY_TARGET_BYTES
    assert postflight.readability_issues(readability) == []
    assert postflight.categorize([]) == 'pass'


def test_modest_overage_is_separate_advisory_not_validation_warning(tmp_path):
    size = postflight.BRIEF_READABILITY_TARGET_BYTES + 1_234
    path = _write_size(tmp_path / 'brief.md', size)
    before = path.read_bytes()

    readability = postflight.assess_brief_readability(path)

    assert readability == {
        'status': 'advisory',
        'bytes': size,
        'target_bytes': postflight.BRIEF_READABILITY_TARGET_BYTES,
        'extreme_bytes': postflight.BRIEF_READABILITY_EXTREME_BYTES,
        'over_by_bytes': 1_234,
    }
    assert postflight.readability_issues(readability) == []
    assert postflight.categorize([]) == 'pass'
    assert path.read_bytes() == before, 'readability assessment truncated the brief'


def test_readability_advisory_cannot_hide_substantive_failure(tmp_path):
    path = _write_size(
        tmp_path / 'brief.md', postflight.BRIEF_READABILITY_TARGET_BYTES + 100)
    readability = postflight.assess_brief_readability(path)
    substantive = ['pre-open.md 缺失（critical）']

    issues = substantive + postflight.readability_issues(readability)

    assert readability['status'] == 'advisory'
    assert issues == substantive
    assert postflight.categorize(issues) == 'fail'


def test_extreme_oversize_remains_a_real_degradation(tmp_path):
    path = _write_size(
        tmp_path / 'brief.md', postflight.BRIEF_READABILITY_EXTREME_BYTES)

    readability = postflight.assess_brief_readability(path)
    issues = postflight.readability_issues(readability)

    assert readability['status'] == 'extreme'
    assert len(issues) == 1 and '极端超长' in issues[0]
    assert postflight.categorize(issues) == 'warn'


def test_generation_instructions_hand_the_report_to_the_harness():
    """Size is no longer the model's to manage, because the report is no longer
    the model's to write (2026-08-31).

    The per-section byte budget, the mid-draft `wc -c` and the "do not truncate"
    rule all existed because a model composing markdown could and did overshoot.
    `clawock.harness.brief_render` renders the document from the judgment and the
    context, so the instructions must say that plainly — an instruction sheet
    that still asks for a hand-written report is how the model spends a morning
    producing a file postflight will overwrite.
    """
    skill = (ROOT / 'skills' / 'daily-deep-brief' / 'SKILL.md').read_text(
        encoding='utf-8')
    report = skill.split('#### A. 报告与微信卡', 1)[1].split(
        '#### B. 结构化 plan', 1)[0]

    assert 'brief_render' in report
    assert '不要写这两个文件' in report
    assert 'clawock brief render --dry-run' in report
    # The layout ban is the operative half: it is what keeps a pipe out of a
    # cell the harness is drawing.
    assert '纯文本' in report
    assert '28KB' in report, 'the size ceiling still has to be stated somewhere'


def test_the_size_ceiling_survives_as_a_harness_gate():
    """The readability gate is not retired with the budget instructions: it is
    what would notice a renderer or a book that grew past what a phone reads."""
    assert postflight.BRIEF_READABILITY_TARGET_BYTES == 28_000
    assert postflight.BRIEF_READABILITY_EXTREME_BYTES == 40_000
