"""Per-ticker episode facts in model prose, shared by packet and harness."""
import re

_EPISODE_CLAIM = re.compile(
    r'(\d+)\s*个[^。；;\n%]{0,12}?episode[^。；;\n%]{0,12}?胜率\s*(\d+(?:\.\d+)?)\s*%')


def episode_claim_mismatches(text, reflections, *, subject=None):
    """「N 个 episode 胜率 P%」 must be the pair of the ticker it is said about.

    The percent pool is one flat table over the whole context, so another
    ticker's 62% authorizes itself anywhere: RKLX's verdict shipped 07226's
    「13 个 episode 胜率 62%」 (its own record was 11 / 45%) and the gate said
    nothing (#2307). Structured row or brief heading owns its prose. Otherwise
    the last reflection ticker named before the claim owns it; with none
    named, any ticker's own pair will do.
    """
    reflections = {
        str(ticker): row for ticker, row in (reflections or {}).items()
        if isinstance(row, dict) and isinstance(row.get('n'), int)
        and isinstance(row.get('win_rate'), (int, float))
    }
    if not reflections:
        return []

    def states(row, n, pct):
        return row['n'] == n and abs(row['win_rate'] * 100 - pct) <= 1.0

    out = []
    for match in _EPISODE_CLAIM.finditer(text):
        n, pct = int(match.group(1)), float(match.group(2))
        # Structured rows own their prose, even if a peer is mentioned inline.
        # The rendered brief uses bullet headings; generic report prose keeps
        # its explicit last-named subject (including legitimate comparisons).
        headings = list(re.finditer(r'^- \*\*([^*\n]+)\*\*\s*·',
                                    text[:match.start()], re.M))
        owner = subject or (headings[-1].group(1) if headings else None)
        if owner not in reflections:
            owner, at = None, -1
            for ticker in reflections:
                found = text.rfind(ticker, 0, match.start())
                if found > at:
                    owner, at = ticker, found
        if owner is not None:
            if states(reflections[owner], n, pct):
                continue
            row = reflections[owner]
            label = (f'{n} 个 episode 胜率 {match.group(2)}%'
                     f'（{owner} 自己是 {row["n"]} 个 / {row["win_rate"]:.0%}）')
        elif any(states(row, n, pct) for row in reflections.values()):
            continue
        else:
            label = f'{n} 个 episode 胜率 {match.group(2)}%'
        if label not in out:
            out.append(label)
    return out

