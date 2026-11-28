"""Headings and body requirements for newly generated weekly reviews."""
import re

from clawock.prose_validation import section_prose_lines

WEEKLY_REQUIRED_SECTIONS = ('本周净值', '决策兑现', '风险演变', '下周关注')
WEEKLY_SECTION_HEADINGS = tuple(
    f'## {i}. {name}' for i, name in enumerate(WEEKLY_REQUIRED_SECTIONS, 1))


# Shared by generation and Pages. The body must speak to the section's fact
# category, including when the author has to explain an evidence gap.
_COVERAGE = tuple(map(re.compile, (
    r'净值|盈亏|损益|回撤|收益|拖累|拖了后腿|贡献|出入金|账面',
    r'成交|执行|下单|挂单|决策|计划|判断|校准|触发',
    r'风控|风险|回撤|敞口|集中|相关性|杠杆|红线|一起[跌涨]|仓位',
    r'看|跟踪|观察|留意|复查|等到|关注|触发|证伪|确认|如果|条件',
)))


def weekly_sections(text):
    """Return exact section headings found and the ones with prose."""
    found, filled = set(), set()
    heading = None
    for _, line in section_prose_lines(text):
        if re.match(r'^ {0,3}#{1,2} ', line):
            heading = line.strip()
            if heading in WEEKLY_SECTION_HEADINGS:
                found.add(heading)
        elif (heading in found and not re.match(r'^ {0,3}#{3,6} ', line)
              and _COVERAGE[WEEKLY_SECTION_HEADINGS.index(heading)].search(line)):
            filled.add(heading)
    return found, filled
