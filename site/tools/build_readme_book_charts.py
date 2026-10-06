"""Build the README's two-book P&L card from the published dashboard payload.

    python3 site/tools/build_readme_book_charts.py [--data-plane DIR]   # rewrite the SVG

One card, `site/assets/books.svg`, with the US book (USD) on the left and the
Hong Kong book (HKD) on the right, under the dashboard GIF in the README. It is
drawn with the primitives of `build_readme_diagrams.py` so it reads as one of
the README's figures: the same pearl canvas, white cards with an accent bar,
type scale and inks. The two books take two of that system's role colours, blue
for US and warm red for HK, and each return is set in its book's colour.

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
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('build_readme_diagrams',
                                               _HERE / 'build_readme_diagrams.py')
house = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(house)

ASSETS = house.ASSETS
NAME = 'books.svg'
W, M = house.W, house.M
GAP = 12
CARD_W = (W - 2 * M - GAP) / 2
HALF = W / 2
HEAD = 38                      # the return, larger than any step of the diagram scale
BOOKS = {
    # leg key in the payload -> (kicker, currency prefix, role colour in the house palette)
    'us': ('US BOOK · USD', 'US$', 'blue'),
    'hk': ('HK BOOK · HKD', 'HK$', 'warm'),
}
MINUS = '\u2212'
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


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


def _book(d, dashboard, leg, x, top, height):
    """Draw one book's card at x; return (one-line summary, first day, last day)."""
    kicker, prefix, role = BOOKS[leg]
    color = house.ROLE[role]
    ret = dashboard['net_principal_return'][leg]
    basis = ret['return_basis']
    points = series(dashboard, leg)
    first, last = points[0][0], points[-1][0]
    left, room = x + 18, CARD_W - 18 - 12

    headline = percent(ret['return_pct'])
    amount = f'{money(ret["total_profit"], prefix, signed=True)} on {money(ret[basis], prefix)}'
    if len(headline) * HEAD * house.TYPE['title'][2] > room:
        house.WARN.append(f'{leg} headline: "{headline}" does not fit {room:.0f}')
    house.fits(amount, 'm', room, f'{leg} amount')
    house.fits(f'÷ {basis}', 'code', room, f'{leg} basis')

    d.card(x, top, CARD_W, height, role)
    d.text(left, top + 28, kicker, 'kick', fill=color)
    d.add(f'<text x="{left - 1:g}" y="{top + 68:g}" class="title" style="font-size:{HEAD}px" '
          f'fill="{color}">{escape(headline)}</text>')
    d.text(left, top + 92, amount, 'm')
    d.text(left, top + 112, f'÷ {basis}', 'code', fill=house.MUT)

    x0, x1, y0, y1 = left, x + CARD_W - 16, top + 128, top + height - 18
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
    d.add(f'<path d="{line} L{px(last):.1f} {zero:.1f} L{px(first):.1f} {zero:.1f}Z" '
          f'fill="{color}" fill-opacity=".13"/>')
    d.add(f'<path d="M{x0:g} {zero:.1f}H{x1:g}" stroke="{house.LINE}" stroke-dasharray="2 4"/>')
    d.add(f'<path class="curve" d="{line}" fill="none" stroke="{color}" stroke-width="2" '
          f'stroke-linejoin="round" stroke-linecap="round"/>')
    d.add(f'<circle cx="{px(last):.1f}" cy="{end:.1f}" r="4.5" fill="{color}" stroke="#ffffff" '
          f'stroke-width="2"/>')
    return f'{kicker.split(" · ")[0].title()} {headline}, {amount} ({basis})', first, last


def chart(dashboard):
    top, height = 20, 196
    xs = (M, M + CARD_W + GAP)
    combined = dashboard['net_principal_return']['combined_usd']
    d = house.D('US and Hong Kong books, measured apart', '')
    us = _book(d, dashboard, 'us', xs[0], top, height)
    hk = _book(d, dashboard, 'hk', xs[1], top, height)
    first, last = min(us[1], hk[1]), max(us[2], hk[2])
    footer = (f'combined {percent(combined["return_pct"])} in USD ({combined["return_basis"]})'
              f'  ·  {_day(first)} – {_day(last)}, {last.year}')
    house.fits(footer, 'code', W - 2 * M, 'footer')
    d.text(W / 2, top + height + 32, footer, 'code', anchor='middle', fill=house.MUT)
    d.desc = (f'{us[0]}. {hk[0]}. Each return is total P&L (realized + unrealized) divided by the '
              f'basis named beside it; the two bases differ and the currencies are not added. '
              f'Daily total P&L per book from {first.isoformat()} to {last.isoformat()}. '
              f'Source: dashboard.json on the data plane.')
    return d.render(top + height + 52).replace(
        'Generated by site/tools/build_readme_diagrams.py; edit the builder',
        'Generated by site/tools/build_readme_book_charts.py from dashboard.json; edit the builder')


def render_all(dashboard):
    """{file name: svg}. Raises rather than drawing a partial card."""
    house.WARN.clear()
    rendered = {NAME: chart(dashboard)}
    if house.WARN:
        raise ValueError('book chart label overflow: ' + '; '.join(house.WARN))
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
