"""Brief readability is observable, but modest overage is not product failure."""
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
from clawock_kcnyu.harness import brief_postflight as postflight  # noqa: E402


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


def test_generation_instructions_budget_sections_before_postflight():
    skill = (ROOT / 'skills' / 'daily-deep-brief' / 'SKILL.md').read_text(
        encoding='utf-8')
    report = skill.split('#### A. Markdown 报告', 1)[1].split(
        '#### B. 结构化 plan', 1)[0]

    assert '28KB' in report
    assert '40KB' in report
    assert 'wc -c' in report
    assert '分段预算' in report
    assert '禁止' in report and '截断' in report
    assert '同行明细不是压缩对象' in report
    assert '同行枚举、相对涨跌、持仓位置和归因必须保留' in report
