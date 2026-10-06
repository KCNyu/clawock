"""Build the README's two per-book P&L cards from the published dashboard payload.

    python3 site/tools/build_readme_book_charts.py [--data-plane DIR]   # rewrite the SVGs

One card per book — `site/assets/book-us.svg` (USD) and `site/assets/book-hk.svg`
(HKD). They sit side by side at the top of the README, so they are built to be
read at a glance: a dark canvas, one colour family per book (US blue to cyan, HK
magenta to orange), the return as the headline and one curve. They do not use
the pearl palette of `build_readme_diagrams.py`; those six explain structure,
these two show a result.

They are two files with two scales on purpose: USD and HKD are never added, and
the two return percentages do not share a denominator, so nothing here puts them
on one axis.

Every figure is read from `dashboard.json` on the data plane, so the cards
cannot be `--check`ed against a checkout that does not have the payload.
`ops/growth/refresh_readme_metrics.py` calls `render_all()` in the weekly README
refresh, from the same payload it reads the README placeholders from.

Where each figure comes from:
  headline %, total P&L, principal   `net_principal_return[leg]`
  the curve                          `snapshots` rows, column `<leg>_profit`,
                                     found through `snapshots_columns`; never
                                     by position
The denominator is whatever `return_basis` says for that leg, and the card
prints it twice: in words under the headline and as the field name in the
footer. `true_principal` is the peak net cash put in, `net_principal` is cost
basis minus realized P&L. The plotted quantity is money in the book's own
currency, which needs no denominator at all.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

_HERE = Path(__file__).resolve().parent
ASSETS = _HERE.parent / 'assets'
W, H, M = 520, 372, 30
SANS = ('-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI",Inter,Roboto,'
        '"Helvetica Neue",Arial,sans-serif')
MONO = 'ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace'
BOOKS = {
    # leg key in the payload -> (file, kicker, currency prefix, gradient from, gradient to, kicker ink)
    'us': ('book-us.svg', 'US BOOK · USD', 'US$', '#3b82f6', '#22d3ee', '#7dd3fc'),
    'hk': ('book-hk.svg', 'HK BOOK · HKD', 'HK$', '#ec4899', '#fb923c', '#fdba74'),
}
BASIS = {
    'true_principal': 'peak net cash in',
    'net_principal': 'cost − realized',
}
MINUS = '\u2212'
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
WARN = []


def fits(text, size, room, where, advance=.58):
    """Inter's bold advance plus a margin; the build refuses to write past it."""
    need = len(text) * size * advance
    if need > room:
        WARN.append(f'{where}: "{text}" needs {need:.0f}, has {room:.0f}')


def money(value, prefix, signed=False):
    sign = MINUS if value < 0 else ('+' if signed else '')
    return f'{sign}{prefix}{abs(value):,.0f}'


def percent(value):
    if value is None:
        return 'n/a'
    return f'{MINUS if value < 0 else "+"}{abs(value):.2f}%'


def series(dashboard, leg):
    """[(date, total P&L)] for one leg, read by column name."""
    columns = dashboard['snapshots_columns']
    at = {name: columns.index(name) for name in ('date', f'{leg}_profit')}
    points = {}
    for row in dashboard['snapshots']:
        total = row[at[f'{leg}_profit']]
        if total is None:
            continue
        points[date.fromisoformat(row[at['date']])] = float(total)
    if len(points) < 2:
        raise ValueError(f'{leg}: fewer than two snapshot rows carry a P&L')
    return [(day, points[day]) for day in sorted(points)]


def _day(day):
    return f'{MONTHS[day.month - 1]} {day.day}'


def chart(dashboard, leg):
    name, kicker, prefix, c0, c1, ink = BOOKS[leg]
    ret = dashboard['net_principal_return'][leg]
    basis = ret['return_basis']
    principal = ret[basis]
    points = series(dashboard, leg)
    first, last = points[0][0], points[-1][0]

    headline = percent(ret['return_pct'])
    basis_words = BASIS.get(basis, basis)
    amount = f'{money(ret["total_profit"], prefix, signed=True)} on {money(principal, prefix)}'
    footer = f'total P&L ÷ {basis}  ·  {_day(first)} – {_day(last)}, {last.year}'
    fits(headline, 62, W - 2 * M, f'{leg} headline')
    fits(f'{amount} {basis_words}', 17, W - 2 * M, f'{leg} amount', advance=.54)
    fits(footer, 12.5, W - 2 * M, f'{leg} footer', advance=.62)

    # --- plot ---------------------------------------------------------------
    x0, x1, y0, y1 = M, W - M, 182, 296
    values = [total for _, total in points]
    lo, hi = min(values + [0.0]), max(values + [0.0])
    span_days = (last - first).days or 1

    def px(day):
        return x0 + (day - first).days / span_days * (x1 - x0)

    def py(value):
        return y1 - (value - lo) / ((hi - lo) or 1.0) * (y1 - y0)

    line = ' '.join(f'{"M" if i == 0 else "L"}{px(day):.1f} {py(total):.1f}'
                    for i, (day, total) in enumerate(points))
    zero = py(0)
    # The fill is strongest under the curve and fades toward the zero line.
    up = zero > (y0 + y1) / 2
    parts = [
        f'<text x="{M}" y="50" class="kick" fill="{ink}">{escape(kicker)}</text>',
        f'<text x="{M - 3}" y="112" class="head" fill="url(#ink)">{escape(headline)}</text>',
        f'<text x="{M}" y="144" class="amt"><tspan fill="#f8fafc">{escape(amount)}</tspan>'
        f'<tspan fill="#94a3b8"> {escape(basis_words)}</tspan></text>',
        f'<path d="{line} L{px(last):.1f} {zero:.1f} L{px(first):.1f} {zero:.1f}Z" fill="url(#area)"/>',
        f'<path d="M{x0} {zero:.1f}H{x1}" stroke="#e2e8f0" stroke-opacity=".38" stroke-dasharray="2 5"/>',
        f'<text x="{x0}" y="{zero + (15 if up else -7):.1f}" class="tick">0</text>',
        f'<path d="{line}" fill="none" stroke="url(#stroke)" stroke-width="3" '
        f'stroke-linejoin="round" stroke-linecap="round"/>',
        f'<circle cx="{px(last):.1f}" cy="{py(points[-1][1]):.1f}" r="11" fill="{c1}" fill-opacity=".22"/>',
        f'<circle cx="{px(last):.1f}" cy="{py(points[-1][1]):.1f}" r="5" fill="{c1}" '
        f'stroke="#0b1020" stroke-width="2"/>',
    ]
    month = date(first.year, first.month, 1)
    while month <= last:
        if month >= first and 16 < px(month) - x0 and x1 - px(month) > 16:
            parts.append(f'<text x="{px(month):.1f}" y="{y1 + 24}" class="tick" text-anchor="middle">'
                         f'{MONTHS[month.month - 1]}</text>')
        month = date(month.year + month.month // 12, month.month % 12 + 1, 1)
    parts.append(f'<text x="{M}" y="{H - 24}" class="foot">{escape(footer)}</text>')

    title = f'{kicker.split(" · ")[0].title()}: {headline}, {amount} {basis_words}'
    desc = (f'Total P&L (realized + unrealized) divided by {basis}. Daily total P&L in '
            f'{prefix.rstrip("$")}D from {first.isoformat()} to {last.isoformat()}, '
            f'{len(points)} daily snapshots. Source: dashboard.json on the data plane.')
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'role="img" aria-labelledby="title desc">\n'
        f'  <title id="title">{escape(title)}</title>\n'
        f'  <desc id="desc">{escape(desc)}</desc>\n'
        '  <!-- Generated by site/tools/build_readme_book_charts.py from dashboard.json; '
        'edit the builder, not this file. -->\n'
        '  <defs>'
        '<linearGradient id="page" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#0b1020"/><stop offset="1" stop-color="#151b3a"/></linearGradient>'
        f'<radialGradient id="glow" cx="{W - 40}" cy="30" r="{W * .75:g}" gradientUnits="userSpaceOnUse">'
        f'<stop offset="0" stop-color="{c1}" stop-opacity=".30"/>'
        f'<stop offset="1" stop-color="{c0}" stop-opacity="0"/></radialGradient>'
        f'<linearGradient id="ink" x1="{M}" y1="0" x2="{W * .62:g}" y2="0" gradientUnits="userSpaceOnUse">'
        f'<stop offset="0" stop-color="{c0}"/><stop offset="1" stop-color="{c1}"/></linearGradient>'
        f'<linearGradient id="stroke" x1="{x0}" y1="0" x2="{x1}" y2="0" gradientUnits="userSpaceOnUse">'
        f'<stop offset="0" stop-color="{c0}"/><stop offset="1" stop-color="{c1}"/></linearGradient>'
        f'<linearGradient id="area" x1="0" y1="{y0}" x2="0" y2="{y1}" gradientUnits="userSpaceOnUse">'
        f'<stop offset="0" stop-color="{c1}" stop-opacity="{.42 if up else .02}"/>'
        f'<stop offset="1" stop-color="{c0}" stop-opacity="{.02 if up else .42}"/></linearGradient>'
        f'<style>text{{font-family:{SANS}}}'
        '.kick{font-size:13px;font-weight:700;letter-spacing:1.6px}'
        '.head{font-size:62px;font-weight:800;letter-spacing:-2px}'
        '.amt{font-size:17px;font-weight:600}'
        '.tick{font-size:12.5px;font-weight:500;fill:#94a3b8}'
        f'.foot{{font-size:12.5px;font-family:{MONO};fill:#94a3b8}}</style></defs>\n'
        f'  <rect width="{W}" height="{H}" rx="24" fill="url(#page)"/>\n'
        f'  <rect width="{W}" height="{H}" rx="24" fill="url(#glow)"/>\n'
        f'  <rect x=".75" y=".75" width="{W - 1.5}" height="{H - 1.5}" rx="23.25" fill="none" '
        f'stroke="{c1}" stroke-opacity=".35" stroke-width="1.5"/>\n'
        + '\n'.join('  ' + part for part in parts) + '\n</svg>\n')
    return name, svg


def render_all(dashboard):
    """{file name: svg} for every book. Raises rather than drawing a partial chart."""
    WARN.clear()
    rendered = dict(chart(dashboard, leg) for leg in BOOKS)
    if WARN:
        raise ValueError('book chart label overflow: ' + '; '.join(WARN))
    return rendered


def write_all(dashboard, assets=ASSETS):
    """Write the charts that changed; return their names."""
    changed = []
    for name, svg in render_all(dashboard).items():
        path = Path(assets) / name
        if not path.exists() or path.read_text(encoding='utf-8') != svg:
            path.write_text(svg, encoding='utf-8')
            changed.append(name)
    return changed


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--data-plane', default=str(_HERE.parents[1] / 'assets' / 'data'),
                        help='directory holding dashboard.json')
    args = parser.parse_args(argv)
    dashboard = json.loads((Path(args.data_plane) / 'dashboard.json').read_text(encoding='utf-8'))
    for name in write_all(dashboard):
        print(f'wrote site/assets/{name}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
