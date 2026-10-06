"""Build the README's two per-book P&L charts from the published dashboard payload.

    python3 site/tools/build_readme_book_charts.py [--data-plane DIR]   # rewrite the SVGs

One chart per book — `site/assets/book-us.svg` (USD) and `site/assets/book-hk.svg`
(HKD) — in the visual system of `build_readme_diagrams.py`. They are two files
with two scales on purpose: USD and HKD are never added, and the two return
percentages do not share a denominator (see below), so nothing here puts them on
one axis.

Unlike the six diagrams these are data, not structure: every figure is read from
`dashboard.json` on the data plane, so they cannot be `--check`ed against a
checkout that does not have the payload. `ops/growth/refresh_readme_metrics.py`
calls `render_all()` in the weekly README refresh, from the same payload it reads
the README placeholders from, so the chart and the sentence under it agree.

Where each figure comes from:
  headline %, total P&L, principal   `net_principal_return[leg]`
  realized / unrealized              `realized_vs_unrealized[leg]`
  the curves                         `snapshots` rows, columns named by
                                     `snapshots_columns` (`<leg>_profit`,
                                     `<leg>_realized`); never by position
The denominator is whatever `return_basis` says for that leg, and the chart
prints it: `true_principal` is the peak net cash put in, `net_principal` is cost
basis minus realized P&L. The plotted quantity is money in the book's own
currency, which needs no denominator at all.
"""
import argparse
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('build_readme_diagrams',
                                               _HERE / 'build_readme_diagrams.py')
house = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(house)

ASSETS = house.ASSETS
BOOKS = {
    # leg key in the payload -> (file, kicker, currency prefix)
    'us': ('book-us.svg', 'US BOOK · USD', 'US$'),
    'hk': ('book-hk.svg', 'HK BOOK · HKD', 'HK$'),
}
BASIS = {
    'true_principal': ('peak net cash put in', 'true_principal'),
    'net_principal': ('net principal', 'net_principal (cost − realized)'),
}
MINUS = '−'
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


def money(value, prefix, signed=False):
    sign = MINUS if value < 0 else ('+' if signed else '')
    return f'{sign}{prefix}{abs(value):,.0f}'


def percent(value):
    if value is None:
        return 'n/a'
    return f'{MINUS if value < 0 else "+"}{abs(value):.2f}%'


def series(dashboard, leg):
    """[(date, total P&L, realized P&L)] for one leg, read by column name."""
    columns = dashboard['snapshots_columns']
    at = {name: columns.index(name) for name in ('date', f'{leg}_profit', f'{leg}_realized')}
    points = {}
    for row in dashboard['snapshots']:
        total, realized = row[at[f'{leg}_profit']], row[at[f'{leg}_realized']]
        if total is None or realized is None:
            continue
        points[date.fromisoformat(row[at['date']])] = (float(total), float(realized))
    if len(points) < 2:
        raise ValueError(f'{leg}: fewer than two snapshot rows carry a P&L')
    return [(day, *points[day]) for day in sorted(points)]


def _ticks(lo, hi):
    """About five round gridlines covering [lo, hi]; zero is always one of them."""
    span = (hi - lo) or 1.0
    raw = span / 5
    magnitude = 10 ** (len(str(int(raw))) - 1) if raw >= 1 else 1
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    first = int(lo // step) * step
    out, value = [], first
    while value < hi + step:
        out.append(value)
        if value >= hi:
            break
        value += step
    return out


def chart(dashboard, leg):
    name, kicker, prefix = BOOKS[leg]
    ret = dashboard['net_principal_return'][leg]
    split = dashboard['realized_vs_unrealized'][leg]
    basis = ret['return_basis']
    principal = ret[basis]
    points = series(dashboard, leg)
    first, last = points[0][0], points[-1][0]
    role = 'blue'
    W, M, CW = house.W, house.M, house.CW

    headline = percent(ret['return_pct'])
    basis_words, basis_formula = BASIS.get(basis, (basis, basis))
    line1 = f'{money(ret["total_profit"], prefix, signed=True)} total P&L on {money(principal, prefix)}'
    line2 = (f'realized {money(split["realized"], prefix, signed=True)}  ·  '
             f'unrealized {money(split["unrealized"], prefix, signed=True)}')
    d = house.D(
        f'{kicker.split(" · ")[0].title()}: {headline} on {money(principal, prefix)} {basis_words}',
        f'{line1} {basis_words}; {line2}. Daily total and realized P&L in {prefix.rstrip("$")}D '
        f'from {first.isoformat()} to {last.isoformat()}, {len(points)} daily snapshots. '
        'Source: dashboard.json on the data plane.')

    d.text(M, 46, kicker, 'kick', fill=house.ROLE[role])
    d.text(M, 82, headline, 'title')
    house.fits(line1 + ' ' + basis_words, 'sub', CW, f'{leg} headline')
    d.text(M, 108, [(line1 + ' ', house.INK), (basis_words, house.MUT)], 'sub')
    house.fits(line2, 'sub', CW, f'{leg} split')
    d.text(M, 130, line2, 'sub', fill=house.MUT)

    # --- plot ---------------------------------------------------------------
    top, card_h = 150, 268
    d.card(M, top, CW, card_h, role)
    values = [v for _, total, realized in points for v in (total, realized)] + [0.0]
    ticks = _ticks(min(values), max(values))
    lo, hi = ticks[0], ticks[-1]
    # The kicker names the currency; the axis repeats only the sign and the amount.
    labels = [money(t, '', signed=True) if t else '0' for t in ticks]
    gutter = max(house.width(label, 'm') for label in labels) + 12
    x0, x1 = M + 22 + gutter, W - M - 18
    y0, y1 = top + 26, top + card_h - 74
    span_days = (last - first).days or 1

    def px(day):
        return x0 + (day - first).days / span_days * (x1 - x0)

    def py(value):
        return y1 - (value - lo) / (hi - lo) * (y1 - y0)

    for tick, label in zip(ticks, labels):
        zero = tick == 0
        d.add(f'<path d="M{x0:g} {py(tick):.1f}H{x1:g}" stroke="{house.LINE if zero else house.CARD_STROKE}" '
              f'stroke-width="{1.2 if zero else 1}"/>')
        d.text(x0 - 10, py(tick) + 5, label, 'm', anchor='end', fill=house.MUT)
    month = date(first.year, first.month, 1)
    while month <= last:
        if month >= first:
            d.add(f'<path d="M{px(month):.1f} {y1:g}v5" stroke="{house.LINE}"/>')
            if x1 - px(month) > 24:
                d.text(px(month), y1 + 21, MONTHS[month.month - 1], 'm', anchor='middle',
                       fill=house.MUT)
        month = date(month.year + month.month // 12, month.month % 12 + 1, 1)

    total_path = ' '.join(f'{"M" if i == 0 else "L"}{px(day):.1f} {py(total):.1f}'
                          for i, (day, total, _) in enumerate(points))
    realized_path = f'M{px(first):.1f} {py(points[0][2]):.1f}' + ''.join(
        f'H{px(day):.1f}V{py(realized):.1f}' for day, _, realized in points[1:])
    d.add(f'<path d="{total_path} L{px(last):.1f} {py(0):.1f} L{px(first):.1f} {py(0):.1f}Z" '
          f'fill="{house.ROLE[role]}" fill-opacity=".10"/>')
    d.add(f'<path d="{realized_path}" fill="none" stroke="{house.ROLE["slate"]}" stroke-width="1.5" '
          f'stroke-dasharray="4 4"/>')
    d.add(f'<path d="{total_path}" fill="none" stroke="{house.ROLE[role]}" stroke-width="2" '
          f'stroke-linejoin="round" stroke-linecap="round"/>')
    d.add(f'<circle cx="{px(last):.1f}" cy="{py(points[-1][1]):.1f}" r="4.5" fill="{house.ROLE[role]}" '
          f'stroke="#ffffff" stroke-width="2"/>')

    ly = top + card_h - 22
    d.add(f'<path d="M{M + 18} {ly - 5}h22" stroke="{house.ROLE[role]}" stroke-width="2" stroke-linecap="round"/>')
    d.text(M + 48, ly, 'total P&L (realized + unrealized)', 'm', fill=house.MUT)
    rx = M + 48 + house.width('total P&L (realized + unrealized)', 'm') + 18
    d.add(f'<path d="M{rx:g} {ly - 5}h22" stroke="{house.ROLE["slate"]}" stroke-width="1.5" '
          f'stroke-dasharray="4 4"/>')
    d.text(rx + 30, ly, 'realized only', 'm', fill=house.MUT)
    house.fits('realized only', 'm', W - M - 14 - (rx + 30), f'{leg} legend')

    foot = top + card_h + 30
    note = f'{len(points)} daily snapshots  ·  {first.isoformat()} → {last.isoformat()}'
    house.fits(note, 'm', CW, f'{leg} footer')
    d.text(M, foot, note, 'm', fill=house.FAINT)
    formula = f'return = total P&L ÷ {basis_formula}'
    house.fits(formula, 'code', CW, f'{leg} formula')
    d.text(M, foot + 22, formula, 'code', fill=house.FAINT)
    svg = d.render(foot + 44)
    return name, svg.replace('Generated by site/tools/build_readme_diagrams.py; edit the builder',
                             'Generated by site/tools/build_readme_book_charts.py from dashboard.json; '
                             'edit the builder')


def render_all(dashboard):
    """{file name: svg} for every book. Raises rather than drawing a partial chart."""
    house.WARN.clear()
    rendered = dict(chart(dashboard, leg) for leg in BOOKS)
    if house.WARN:
        raise ValueError('book chart label overflow: ' + '; '.join(house.WARN))
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
