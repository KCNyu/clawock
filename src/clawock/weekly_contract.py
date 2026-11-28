"""Headings and body requirements for newly generated weekly reviews."""
import re

from clawock.prose_validation import section_prose_lines

WEEKLY_REQUIRED_SECTIONS = ('本周净值', '决策兑现', '风险演变', '下周关注')
WEEKLY_SECTION_HEADINGS = tuple(
    f'## {i}. {name}' for i, name in enumerate(WEEKLY_REQUIRED_SECTIONS, 1))


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
              and re.search(r'[^\W\d_]', line)):
            filled.add(heading)
    return found, filled
