"""Build the README's two-book P&L card from the published dashboard payload.

    python3 site/tools/build_readme_book_charts.py [--data-plane DIR]   # rewrite the SVG

One figure in the README's two layouts, with the US book on the left and the
Hong Kong book on the right, under the dashboard GIF: `site/assets/books.svg`
on the desktop canvas and `books-narrow.svg` on the single column, chosen by a
`<picture>` like every other figure. It is drawn with the primitives of
`build_readme_diagrams.py` (canvas, glass panes, type scale, inks, the glow of a
pulse), so it reads as one of them. The two books take two of that system's
role colours, blue for US and warm red for HK.

Each pane says three things and no more: which book, its return, and what that
return was divided by. The return is the only large type; the curve is the
second thing seen. Money amounts are not printed: they are in the `<desc>`.

One figure is not one number. USD and HKD are never added, each pane has its
own vertical scale, and the two percentages do not share a denominator, so each
pane prints `÷ <basis>` under its return. With the amounts gone, the payload's
own combined return in the footer is what stops a reader averaging the two; it
carries its basis in the same `÷` form.

Every figure is read from `dashboard.json` on the data plane, so the card
cannot be `--check`ed against a checkout that does not have the payload.
`ops/growth/refresh_readme_metrics.py` calls `render_all()` in the weekly README
refresh.

Where each figure comes from:
  headline % and its basis           `net_principal_return[leg]` (amounts: desc only)
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
FILES = {NAME: True, 'books-narrow.svg': False}     # file -> wide layout
BOOKS = {
    # leg key in the payload -> (kicker, currency prefix, role colour in the house palette)
    'us': ('US BOOK', 'US$', 'blue'),
    'hk': ('HK BOOK', 'HK$', 'warm'),
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


def _book(d, dashboard, leg, x, top, w, height):
    """Draw one book's pane at x; return (one-line summary, first day, last day)."""
    kicker, prefix, role = BOOKS[leg]
    color = house.ROLE[role]
    ret = dashboard['net_principal_return'][leg]
    basis = ret['return_basis']
    points = series(dashboard, leg)
    first, last = points[0][0], points[-1][0]
    headline = percent(ret['return_pct'])
    if d.wide:      # return on the left, curve on the right
        head, left, room = 44, x + 28, 222
        rows = (top + 37, top + 85, top + 111)
        x0, x1, y0, y1 = left + room + 14, x + w - 26, top + 28, top + height - 28
    else:           # return on top, curve underneath
        head, left, room = 38, x + 18, w - 18 - 12
        rows = (top + 30, top + 70, top + 94)
        x0, x1, y0, y1 = left, x + w - 18, top + 114, top + height - 20

    if len(headline) * head * house.TYPE['title'][2] > room:
        house.WARN.append(f'{leg} headline: "{headline}" does not fit {room:.0f}')
    house.fits(f'÷ {basis}', 'code', room, f'{leg} basis')

    d.card(x, top, w, height, role)
    d.text(left, rows[0], kicker, 'kick', fill=color)
    d.add(f'<text x="{left - 1:g}" y="{rows[1]:g}" class="title" style="font-size:{head}px" '
          f'fill="{color}">{escape(headline)}</text>')
    d.text(left, rows[2], f'÷ {basis}', 'code', fill=house.MUT)

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
    # Where the book stands today: the house pulse, standing still and breathing.
    d.add(f'<circle class="breathe" cx="{px(last):.1f}" cy="{end:.1f}" r="13" '
          f'fill="url(#glow-{role})"/>')
    d.add(f'<circle cx="{px(last):.1f}" cy="{end:.1f}" r="4.5" fill="{color}" stroke="#ffffff" '
          f'stroke-width="2"/>')
    amount = f'{money(ret["total_profit"], prefix, signed=True)} on {money(ret[basis], prefix)}'
    return f'{kicker.title()} {headline}, {amount} ({basis})', first, last


def chart(dashboard, wide=True):
    combined = dashboard['net_principal_return']['combined_usd']
    d = house.D('US and Hong Kong books, measured apart', '', wide=wide)
    if wide:
        top, height, w, xs = M, 138, house.CW, (M, M + house.COL2)
    else:
        top, height, w = 20, 176, (W - 2 * M - 12) / 2
        xs = (M, M + w + 12)
    us = _book(d, dashboard, 'us', xs[0], top, w, height)
    hk = _book(d, dashboard, 'hk', xs[1], top, w, height)
    first, last = min(us[1], hk[1]), max(us[2], hk[2])
    # The footer is the quietest line: both books in one figure, then the dates.
    y, inset = top + height + 35, 6
    whole, basis = f'combined {percent(combined["return_pct"])}', f'÷ {combined["return_basis"]}'
    period = f'{_day(first)} – {_day(last)}, {last.year}'
    house.fits(whole + basis + period, 'code', d.pw - 2 * (M + inset) - 40, 'footer')
    d.add(f'<text x="{M + inset:g}" y="{y:g}" class="m" fill="{house.MUT}">{escape(whole)}'
          f'<tspan class="code" dx="9">{escape(basis)}</tspan></text>')
    d.text(d.pw - M - inset, y, period, 'm', anchor='end', fill=house.FAINT)
    d.desc = (f'{us[0]}. {hk[0]}. Combined {percent(combined["return_pct"])} in USD '
              f'({combined["return_basis"]}). Each return is total P&L (realized + unrealized) '
              f'divided by the basis named under it; the bases differ and the currencies are not '
              f'added. Daily total P&L per book from {first.isoformat()} to {last.isoformat()}. '
              f'Source: dashboard.json on the data plane.')
    return d.render(top + height + 56).replace(
        'Generated by site/tools/build_readme_diagrams.py; edit the builder',
        'Generated by site/tools/build_readme_book_charts.py from dashboard.json; edit the builder')


def render_all(dashboard):
    """{file name: svg}, both layouts. Raises rather than drawing a partial card."""
    house.WARN.clear()
    rendered = {name: chart(dashboard, wide) for name, wide in FILES.items()}
    if house.WARN:
        raise ValueError('book chart label overflow: ' + '; '.join(house.WARN))
    return rendered


def write_all(dashboard, assets=ASSETS):
    """Write the layouts that changed; return the names written."""
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
