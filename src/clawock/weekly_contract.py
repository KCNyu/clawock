"""Headings and coverage requirements for newly generated weekly reviews."""
from clawock.prose_validation import section_prose_lines

WEEKLY_REQUIRED_SECTIONS = ('本周净值', '决策兑现', '风险演变', '下周关注')
WEEKLY_SECTION_HEADINGS = tuple(
    f'## {i}. {name}' for i, name in enumerate(WEEKLY_REQUIRED_SECTIONS, 1))
WEEKLY_EVIDENCE = dict(zip(WEEKLY_SECTION_HEADINGS, (
    ('bundle_evidence', 'snapshots'),
    ('decision_episodes', 'decision_metrics'),
    ('current_risk',),
    ('plans', 'current_risk'),
), strict=True))


def weekly_section_bodies(text):
    bodies = {}
    active = None
    for _, line in section_prose_lines(text):
        stripped = line.lstrip(' ')
        marker = stripped.split(' ', 1)[0]
        if len(line) - len(stripped) <= 3 and marker in ('#', '##'):
            active = stripped.strip()
            if active in WEEKLY_SECTION_HEADINGS:
                bodies.setdefault(active, [])
        elif active in bodies and marker not in ('###', '####', '#####', '######'):
            bodies[active].append(line)
    return {heading: '\n'.join(lines) for heading, lines in bodies.items()}


def weekly_sections(text):
    """Archive fallback after source references have been materialized."""
    bodies = weekly_section_bodies(text)
    filled = {heading for heading, body in bodies.items() if sum(c.isalpha() for c in body) >= 5}
    return set(bodies), filled
