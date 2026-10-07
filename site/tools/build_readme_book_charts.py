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

The figure moves the way the others do, and a little more, because it is the
one result in the hero. Per pane, on one `CYCLE`: the house pulse runs the
curve with a streak of light behind it, a ring opens where it lands on today's
value, and a glint crosses the glass. Behind the panes two colour fields drift,
which is what the translucent glass is there to show. The two books run half a
cycle apart so something is always moving. Both layouts call the same `_motion`
and `_book`, so they carry the same definitions and differ only in distances.
Everything that moves stops under `prefers-reduced-motion`: SMIL carries the
class `pulse`, which the house style removes, and each CSS animation is
switched off in the same media query. The first frame is complete without any
of it. Still no `<filter>`: light is gradients and clip paths.

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
CYCLE = 8                      # seconds: run the curve, land, ring, glint, rest
RUN = .45                      # the share of a cycle the pulse spends on the curve
EASE = '.45 0 .55 1'           # the house pulse's spline
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


def _motion(d, panes, top, height):
    """Shared light: definitions, the drifting fields behind the glass, the styles.

    `panes` is [(leg, x, width)]. Distances are the only thing that differs
    between the two layouts.
    """
    w = panes[0][2]
    reach, band = w + 150, 64                  # how far a glint travels; its width
    orb = min(150, w * .48)
    slide = w * .16
    d.add('<defs><linearGradient id="glint"><stop offset="0" stop-color="#ffffff" stop-opacity="0"/>'
          '<stop offset=".5" stop-color="#ffffff" stop-opacity=".5"/>'
          '<stop offset="1" stop-color="#ffffff" stop-opacity="0"/></linearGradient>'
          + ''.join(f'<clipPath id="pane-{leg}"><rect x="{x:g}" y="{top:g}" width="{pw:g}" '
                    f'height="{height:g}" rx="14"/></clipPath>' for leg, x, pw in panes)
          + '</defs>')
    d.add('<style>'
          f'.glint{{animation:glint {CYCLE}s cubic-bezier(.4,0,.2,1) infinite}}'
          f'@keyframes glint{{0%,{RUN * 100 + 8:g}%{{transform:translateX(0)}}'
          f'{RUN * 100 + 36:g}%,100%{{transform:translateX({reach:g}px)}}}}'
          f'.drift{{animation:drift {CYCLE * 2}s ease-in-out infinite alternate}}'
          f'@keyframes drift{{to{{transform:translate({slide:g}px,{height * .14:g}px)}}}}'
          f'.late{{animation-delay:-{CYCLE / 2:g}s}}'
          '@media (prefers-reduced-motion:reduce){.glint,.drift{animation:none}}</style>')
    for i, (leg, x, pw) in enumerate(panes):
        role = BOOKS[leg][2]
        # Start on the outer side and drift inward, so the two fields approach and part.
        cx = x + pw * (.34 if i == 0 else .66) - (0 if i == 0 else slide)
        d.add(f'<circle class="drift{" late" if i else ""}" cx="{cx:g}" cy="{top + height * .62:g}" '
              f'r="{orb:g}" fill="url(#glow-{role})" fill-opacity=".8"/>')
    return reach, band


def _book(d, dashboard, leg, x, top, w, height, glint, begin):
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
    ex = f'cx="{px(last):.1f}" cy="{end:.1f}"'
    # The fill is densest far from zero and thins to nothing at the zero line.
    at_zero = (zero - y0) / (y1 - y0)
    d.add(f'<defs><linearGradient id="area-{leg}" x1="0" y1="{y0:g}" x2="0" y2="{y1:g}" '
          f'gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="{color}" stop-opacity=".3"/>'
          f'<stop offset="{at_zero:.3f}" stop-color="{color}" stop-opacity=".03"/>'
          f'<stop offset="1" stop-color="{color}" stop-opacity=".3"/></linearGradient></defs>')
    d.add(f'<path d="{line} L{px(last):.1f} {zero:.1f} L{px(first):.1f} {zero:.1f}Z" '
          f'fill="url(#area-{leg})"/>')
    d.add(f'<path d="M{x0:g} {zero:.1f}H{x1:g}" stroke="{house.LINE}" stroke-dasharray="2 4"/>')
    d.add(f'<path id="curve-{leg}" class="curve" d="{line}" fill="none" stroke="{color}" '
          f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')

    # One cycle: run the curve, land on today, rest. `pulse` is the house class
    # that prefers-reduced-motion removes, so every SMIL element carries it.
    timing = (f'dur="{CYCLE}s" begin="{begin:g}s" repeatCount="indefinite" calcMode="spline" '
              f'keyTimes="0;{RUN:g};{RUN + .07:g};1" keySplines="{EASE};0 0 1 1;0 0 1 1"')
    # The streak is a wide, faint copy of the line: white would read as a gap in it.
    tail = 16                                  # of a path length normalised to 100
    d.add(f'<path class="pulse" d="{line}" pathLength="100" fill="none" stroke="{color}" '
          f'stroke-opacity=".3" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" '
          f'stroke-dasharray="{tail} 200" stroke-dashoffset="{tail}">'
          f'<animate attributeName="stroke-dashoffset" values="{tail};{tail - 100};-100;-100" '
          f'{timing}/></path>')
    for r, fill in ((9, f'url(#glow-{role})'), (3.4, color)):
        d.add(f'<circle class="pulse" r="{r}" fill="{fill}"><animateMotion keyPoints="0;1;1;1" '
              f'{timing}><mpath href="#curve-{leg}" xlink:href="#curve-{leg}"/></animateMotion>'
              f'</circle>')
    ring = (f'dur="{CYCLE}s" begin="{begin:g}s" repeatCount="indefinite" '
            f'keyTimes="0;{RUN - .03:g};{RUN + .3:g};1"')
    d.add(f'<circle class="pulse" {ex} r="4.5" fill="none" stroke="{color}" stroke-width="1.5" '
          f'opacity="0"><animate attributeName="r" values="4.5;4.5;20;20" {ring}/>'
          f'<animate attributeName="opacity" values="0;.75;0;0" {ring}/></circle>')
    # Where the book stands today: the house pulse, standing still and breathing.
    d.add(f'<circle class="breathe" {ex} r="13" fill="url(#glow-{role})"/>')
    d.add(f'<circle {ex} r="4.5" fill="{color}" stroke="#ffffff" stroke-width="2"/>')

    # The glint is on top of everything in the pane, as light on glass is, and
    # is parked outside the pane's clip for most of the cycle.
    reach, band = glint
    gx, lean = x - band - 50, height * .42
    d.add(f'<g clip-path="url(#pane-{leg})"><path class="glint{" late" if begin else ""}" '
          f'd="M{gx + lean:g} {top:g}h{band}l{-lean:g} {height:g}h{-band}Z" fill="url(#glint)"/></g>')
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
    glint = _motion(d, [('us', xs[0], w), ('hk', xs[1], w)], top, height)
    us = _book(d, dashboard, 'us', xs[0], top, w, height, glint, 0)
    hk = _book(d, dashboard, 'hk', xs[1], top, w, height, glint, -CYCLE / 2)
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
