"""Build the README's two-book P&L card from the published dashboard payload.

    python3 site/tools/build_readme_book_charts.py [--data-plane DIR]   # rewrite the SVG

One card, `site/assets/books.svg`, with the US book (USD) on the left and the
Hong Kong book (HKD) on the right. It sits under the dashboard GIF in the README
and is built to be read at a glance: a dark canvas, one colour family per book
(US blue to cyan, HK magenta to orange), each return as a headline over its own
curve. It does not use the pearl palette of `build_readme_diagrams.py`; those
six explain structure, this one shows a result.

One card is not one number. USD and HKD are never added, each half has its own
vertical scale, and the two return percentages do not share a denominator, so
each half prints the basis it was divided by. The only figure that spans both
books is the payload's own combined return, in the footer with its basis.

Every figure is read from `dashboard.json` on the data plane, so the card
cannot be `--check`ed against a checkout that does not have the payload.
`ops/growth/refresh_readme_metrics.py` calls `render_all()` in the weekly README
refresh.

Where each figure comes from:
  headline %, total P&L, principal   `net_principal_return[leg]`
  combined % and its basis           `net_principal_return.combined_usd`
  the curves                         `snapshots` rows, column `<leg>_profit`,
                                     found through `snapshots_columns`; never
                                     by position
`true_principal` is the peak net cash put in, `net_principal` is cost basis
minus realized P&L. The plotted quantity is money in the book's own currency,
which needs no denominator at all.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

_HERE = Path(__file__).resolve().parent
ASSETS = _HERE.parent / 'assets'
NAME = 'books.svg'
W, H, M = 640, 252, 28
HALF = W // 2
SANS = ('-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI",Inter,Roboto,'
        '"Helvetica Neue",Arial,sans-serif')
MONO = 'ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace'
BOOKS = {
    # leg key in the payload -> (kicker, currency prefix, gradient from, gradient to, kicker ink)
    'us': ('US BOOK · USD', 'US$', '#3b82f6', '#22d3ee', '#7dd3fc'),
    'hk': ('HK BOOK · HKD', 'HK$', '#ec4899', '#fb923c', '#fdba74'),
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


def _half(dashboard, leg, ox):
    """(defs, marks, one-line summary, first day, last day) for one book at x offset ox."""
    kicker, prefix, c0, c1, ink = BOOKS[leg]
    ret = dashboard['net_principal_return'][leg]
    basis = ret['return_basis']
    points = series(dashboard, leg)
    first, last = points[0][0], points[-1][0]
    room = HALF - 2 * M

    headline = percent(ret['return_pct'])
    amount = f'{money(ret["total_profit"], prefix, signed=True)} on {money(ret[basis], prefix)}'
    fits(headline, 46, room, f'{leg} headline')
    fits(amount, 15, room, f'{leg} amount', advance=.56)
    fits(f'÷ {basis}', 12, room, f'{leg} basis', advance=.62)

    x0, x1, y0, y1 = ox + M, ox + HALF - M, 150, 204
    values = [total for _, total in points]
    lo, hi = min(values + [0.0]), max(values + [0.0])
    span_days = (last - first).days or 1

    def px(day):
        return x0 + (day - first).days / span_days * (x1 - x0)

    def py(value):
        return y1 - (value - lo) / ((hi - lo) or 1.0) * (y1 - y0)

    line = ' '.join(f'{"M" if i == 0 else "L"}{px(day):.1f} {py(total):.1f}'
                    for i, (day, total) in enumerate(points))
    zero, end = py(0), py(points[-1][1])
    # The fill is strongest under the curve and fades toward the zero line.
    up = zero > (y0 + y1) / 2
    defs = (
        f'<radialGradient id="glow-{leg}" cx="{ox + HALF - 30}" cy="20" r="{HALF}" '
        f'gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="{c1}" stop-opacity=".30"/>'
        f'<stop offset="1" stop-color="{c0}" stop-opacity="0"/></radialGradient>'
        f'<linearGradient id="ink-{leg}" x1="{x0}" y1="0" x2="{x0 + 190}" y2="0" '
        f'gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="{c0}"/>'
        f'<stop offset="1" stop-color="{c1}"/></linearGradient>'
        f'<linearGradient id="stroke-{leg}" x1="{x0}" y1="0" x2="{x1}" y2="0" '
        f'gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="{c0}"/>'
        f'<stop offset="1" stop-color="{c1}"/></linearGradient>'
        f'<linearGradient id="area-{leg}" x1="0" y1="{y0}" x2="0" y2="{y1}" '
        f'gradientUnits="userSpaceOnUse">'
        f'<stop offset="0" stop-color="{c1}" stop-opacity="{.42 if up else .02}"/>'
        f'<stop offset="1" stop-color="{c0}" stop-opacity="{.02 if up else .42}"/></linearGradient>'
    )
    marks = [
        f'<rect width="{W}" height="{H}" fill="url(#glow-{leg})"/>',
        f'<text x="{x0}" y="42" class="kick" fill="{ink}">{escape(kicker)}</text>',
        f'<text x="{x0 - 2}" y="90" class="head" fill="url(#ink-{leg})">{escape(headline)}</text>',
        f'<text x="{x0}" y="114" class="amt">{escape(amount)}</text>',
        f'<text x="{x0}" y="133" class="mono">÷ {escape(basis)}</text>',
        f'<path d="{line} L{px(last):.1f} {zero:.1f} L{px(first):.1f} {zero:.1f}Z" '
        f'fill="url(#area-{leg})"/>',
        f'<path d="M{x0} {zero:.1f}H{x1}" stroke="#e2e8f0" stroke-opacity=".38" stroke-dasharray="2 5"/>',
        f'<path d="{line}" fill="none" stroke="url(#stroke-{leg})" stroke-width="2.6" '
        f'stroke-linejoin="round" stroke-linecap="round"/>',
        f'<circle cx="{px(last):.1f}" cy="{end:.1f}" r="9" fill="{c1}" fill-opacity=".22"/>',
        f'<circle cx="{px(last):.1f}" cy="{end:.1f}" r="4.2" fill="{c1}" stroke="#0b1020" stroke-width="2"/>',
    ]
    return defs, marks, f'{kicker.split(" · ")[0].title()} {headline}, {amount} ({basis})', first, last


def chart(dashboard):
    us = _half(dashboard, 'us', 0)
    hk = _half(dashboard, 'hk', HALF)
    combined = dashboard['net_principal_return']['combined_usd']
    first, last = min(us[3], hk[3]), max(us[4], hk[4])
    footer = (f'combined {percent(combined["return_pct"])} in USD ({combined["return_basis"]})'
              f'  ·  {_day(first)} – {_day(last)}, {last.year}')
    fits(footer, 12, W - 2 * M, 'footer', advance=.62)
    marks = us[1] + hk[1] + [
        f'<path d="M{HALF} 26V{H - 44}" stroke="#e2e8f0" stroke-opacity=".14"/>',
        f'<text x="{W / 2:g}" y="{H - 20}" class="mono" text-anchor="middle">{escape(footer)}</text>',
    ]
    desc = (f'{us[2]}. {hk[2]}. Each return is total P&L (realized + unrealized) divided by the '
            f'basis named beside it; the two bases differ and the currencies are not added. '
            f'Daily total P&L per book from {first.isoformat()} to {last.isoformat()}. '
            f'Source: dashboard.json on the data plane.')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'role="img" aria-labelledby="title desc">\n'
        f'  <title id="title">US and Hong Kong books, measured apart</title>\n'
        f'  <desc id="desc">{escape(desc)}</desc>\n'
        '  <!-- Generated by site/tools/build_readme_book_charts.py from dashboard.json; '
        'edit the builder, not this file. -->\n'
        '  <defs><clipPath id="card"><rect width="{W}" height="{H}" rx="22"/></clipPath>'
        '<linearGradient id="page" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#0b1020"/><stop offset="1" stop-color="#151b3a"/></linearGradient>'
        .replace('{W}', str(W)).replace('{H}', str(H))
        + us[0] + hk[0]
        + f'<style>text{{font-family:{SANS}}}'
        '.kick{font-size:12.5px;font-weight:700;letter-spacing:1.6px}'
        '.head{font-size:46px;font-weight:800;letter-spacing:-1.5px}'
        '.amt{font-size:15px;font-weight:600;fill:#f8fafc}'
        f'.mono{{font-size:12px;font-family:{MONO};fill:#94a3b8}}</style></defs>\n'
        f'  <rect width="{W}" height="{H}" rx="22" fill="url(#page)"/>\n'
        '  <g clip-path="url(#card)">\n'
        + '\n'.join('    ' + mark for mark in marks) + '\n  </g>\n'
        f'  <rect x=".75" y=".75" width="{W - 1.5}" height="{H - 1.5}" rx="21.25" fill="none" '
        f'stroke="#94a3b8" stroke-opacity=".28" stroke-width="1.5"/>\n</svg>\n')


def render_all(dashboard):
    """{file name: svg}. Raises rather than drawing a partial card."""
    WARN.clear()
    rendered = {NAME: chart(dashboard)}
    if WARN:
        raise ValueError('book chart label overflow: ' + '; '.join(WARN))
    return rendered


def write_all(dashboard, assets=ASSETS):
    """Write the card if it changed; return the names written."""
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
