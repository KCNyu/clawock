"""Build the README diagrams in site/assets/ as one visual system.

    python3 site/tools/build_readme_diagrams.py            # rewrite the SVGs
    python3 site/tools/build_readme_diagrams.py --check    # exit 1 if any differs

The system: a pearl canvas washed with four soft colour fields, translucent
glass cards with a thin role-coloured accent bar, system sans type on a fixed
scale, graphite ink with blue kept for data and dispatch flow, green for code
gates and warm red for isolation / arbitration.

Every diagram is built twice from one description. `<name>.svg` is the desktop
layout: two 472-unit columns on a 1016-unit canvas, read down the left and then
down the right, so a figure that was three screens tall in a README column is
about one. `<name>-narrow.svg` is the same content in one 520-unit column for a
phone. The README picks between them with `<picture>`. A diagram function draws
in column coordinates either way and says where the wide layout turns
(`D.turn`, `D.place`); it never positions a second copy of anything.

The glass is drawn, not filtered: an image has no backdrop to blur. A card is a
white fill at partial opacity over the colour fields, a sheen that fades down
its top third, a rim that is bright where the light lands (top) and darker
underneath, a one-unit highlight inside the top edge, and a soft shadow wider
than the card. A sparse dot pattern over the canvas gives the surface grain.
All of it lives in the shared primitives, so every diagram changes together.

Motion is SMIL <animateMotion> pulses along the connectors plus a few CSS
keyframes. Repository screenshots are embedded as PNG data URIs at their original
aspect ratio. No script, no external font or image, no filter (a filter rasterises
the text beneath it, and feTurbulence grain costs far more bytes than a pattern)
— so the diagrams animate inside the README's <img>, stop under
prefers-reduced-motion, and the first frame is already complete.

Every label is sourced from the code or docs it names; change the wording here,
not in the SVG. `fits()` warns when a label would overflow its box, and the
build refuses to write while it does.
"""
import base64
import struct
import sys
from functools import partial
from pathlib import Path
from xml.sax.saxutils import escape

ASSETS = Path(__file__).resolve().parents[1] / 'assets'
W, M = 520, 24          # one column's width, outer margin
CW = W - 2 * M          # content width of a column
GUTTER = 24             # between the two columns of the wide layout
COL2 = CW + GUTTER      # x offset of the second column
WIDE = W + COL2         # canvas width of the wide layout

SANS = ('-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Inter,Roboto,'
        '"Helvetica Neue",Arial,sans-serif')
MONO = 'ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace'

INK, MUT, FAINT = '#151a21', '#5b6875', '#8794a1'
LINE, CARD_STROKE, CHIP = '#a9b6c2', '#dde4eb', '#f2f5f8'
ROLE = {
    'blue': '#3f82b5',    # data and dispatch flow
    'green': '#13865f',   # deterministic code, the merge gate
    'warm': '#b8524a',    # isolation, arbitration, bear case
    'slate': '#5d7487',   # agents and harnesses (LLM)
    'violet': '#6f64a8',  # shared context
}
TINT = {'blue': '#e8f1f8', 'green': '#e6f4ee', 'warm': '#fbecea',
        'slate': '#eaeef2', 'violet': '#efedf7'}

# type scale: (size, weight, advance per char used by fits()). The advances are
# Inter's measured mean (.51 regular, .52 bold — the widest face in SANS) plus ~5%;
# caps with tracking for kickers and tags.
TYPE = {
    'kick': (12.5, 700, .74), 'title': (25, 750, .55), 'sub': (15, 450, .53),
    'h': (17.5, 700, .55), 'b': (15, 450, .53), 'm': (14.5, 450, .53),
    'code': (13.5, 500, .62), 'tag': (11.5, 700, .78),
}
GLOW = {color: role for role, color in ROLE.items()}   # pulse colour -> halo gradient id
WARN = []


def fits(text, cls, room, where):
    size, _, adv = TYPE[cls]
    need = len(text) * size * adv
    if need > room:
        WARN.append(f'{where}: "{text}" needs {need:.0f}, has {room:.0f}')


def width(text, cls):
    size, _, adv = TYPE[cls]
    return len(text) * size * adv


class D:
    """One diagram: collects SVG fragments on a fixed-width canvas."""

    def __init__(self, title, desc, wide=False):
        self.title, self.desc, self.wide = title, desc, wide
        self.pw = WIDE if wide else W          # page width
        self.parts, self.n, self.h = [], 0, 0
        # Wide layout: drawing happens in column coordinates and each run of it
        # is a group translated into place. `dx, dy` is the current group's
        # offset; `bottoms` collects where each closed group ended on the page.
        self.dx = self.dy = 0
        self.group, self.bottoms = None, []

    def add(self, s):
        (self.parts if self.group is None else self.group).append(s)

    # --- wide layout -------------------------------------------------------
    def at(self, x, y):
        """Page coordinates of a point given in the current column's coordinates."""
        return x + self.dx, y + self.dy

    def _close(self):
        if self.group is not None:
            self.parts.append(f'<g transform="translate({self.dx:g} {self.dy:g})">\n    '
                              + '\n    '.join(self.group) + '\n  </g>')
        self.group = None
        self.dx = self.dy = 0

    def flow(self, y):
        """Start the first column; `y` is where its content begins."""
        self.top = y
        if self.wide:
            self.group = []

    def place(self, col, first, page_y, bottom):
        """Wide only: continue in column `col`, with column-y `first` at `page_y`.

        `bottom` is where the content drawn so far ends, in its own coordinates.
        """
        self.bottoms.append(bottom + self.dy + M)
        self._close()
        self.dx, self.dy, self.group = col * COL2, page_y - first, []

    def page_wire(self, d, **kw):
        """A connector in page coordinates, drawn outside the column groups."""
        group, dx, dy = self.group, self.dx, self.dy
        self.group, self.dx, self.dy = None, 0, 0
        self.wire(d, **kw)
        self.group, self.dx, self.dy = group, dx, dy

    def turn(self, x, top, end, *, first, enter, reach=M, leave=None, tail=26, **kw):
        """The connector between two consecutive blocks, and the wide layout's turn.

        Narrow: a plain `down(x, top, end)`. Wide: the first column ends at
        `top`; the flow leaves it, runs up the gutter and enters the second
        column from the left at column-y `enter`, stopping at column-x `reach`.
        `first` is the column-y that lines up with the top of the first column,
        `leave` an exit point on a node's right edge instead of straight down,
        and `tail` how far below `top` the first column still draws.
        """
        if not self.wide:
            return self.down(x, top, end, **kw)
        x0, y0 = self.at(*(leave or (x, top)))
        self.place(1, first, self.top, top + tail)
        lane = COL2 + M - GUTTER / 2
        ex, ey = self.at(reach, enter)
        start = f'M{x0:g} {y0:g}' + ('' if leave else f'V{y0 + 16:g}')
        kw.setdefault('dur', 3.2)
        self.page_wire(f'{start}H{lane:g}V{ey:g}H{ex - 2:g}', **kw)

    def text(self, x, y, segs, cls='b', anchor='start', fill=INK):
        if isinstance(segs, str):
            segs = [(segs, fill)]
        spans = ''.join(f'<tspan fill="{c}">{escape(t)}</tspan>' for t, c in segs)
        a = f' text-anchor="{anchor}"' if anchor != 'start' else ''
        self.add(f'<text x="{x:g}" y="{y:g}" class="{cls}"{a}>{spans}</text>')

    # --- building blocks -------------------------------------------------
    def header(self, kicker, title, sub, legend, title_lh=30):
        room = self.pw - 2 * M
        if self.wide:           # one line each: the canvas is wide enough
            title, sub = [' '.join(title)], [' '.join(sub)]
        self.text(M, 46, kicker, 'kick', fill=ROLE['blue'])
        y = 80
        for line in title:
            fits(line, 'title', room, 'title')
            self.text(M, y, line, 'title')
            y += title_lh
        y += 2
        for line in sub:
            fits(line, 'sub', room, 'sub')
            self.text(M, y, line, 'sub', fill=MUT)
            y += 21
        x, y = M, y + 10
        for label, role in legend:
            w = width(label, 'm') + 22
            if x + w > self.pw - M:
                x, y = M, y + 22
            self.add(f'<circle cx="{x + 5}" cy="{y - 4.5}" r="4.5" fill="{ROLE[role]}"/>')
            self.text(x + 15, y, label, 'm', fill=MUT)
            x += w + 14
        self.add(f'<path d="M{M} {y + 20}H{self.pw - M}" stroke="url(#rule)"/>')
        return y + 20

    def section(self, y, label):
        self.text(M, y, label, 'kick', fill=FAINT)

    def card(self, x, y, w, h, role, tint=False):
        """A pane of glass: shadow, translucent body, sheen, rim, top highlight."""
        body = f'url(#glass-{role})' if tint else 'url(#glass)'
        # A shadow wider and softer than the pane: thick material sits off the page.
        # It starts at the pane's lower edge: glass would show a shadow drawn under it.
        self.add(f'<path d="M{x + 10:g} {y + h - 1:g}H{x + w - 10:g}L{x + w - 2:g} {y + h + 15:g}'
                 f'H{x + 2:g}Z" fill="url(#lift)"/>')
        self.add(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="14" fill="{body}" '
                 f'stroke="url(#rim)" stroke-width="1.2"/>')
        # Sheen over the top third, and the line of light just inside the top edge.
        self.add(f'<rect class="sheen" x="{x + 1:g}" y="{y + 1:g}" width="{w - 2:g}" '
                 f'height="{min(h - 2, 64):g}" rx="13" fill="url(#sheen)"/>')
        self.add(f'<path d="M{x + 14:g} {y + 1.4:g}H{x + w - 14:g}" stroke="#ffffff" '
                 f'stroke-opacity=".95" stroke-linecap="round"/>')
        self.add(f'<path d="M{x + 1.5:g} {y + 14:g}V{y + h - 14:g}" stroke="{ROLE[role]}" '
                 f'stroke-width="4" stroke-linecap="round"/>')

    def tag(self, x, y, label, role, anchor='start'):
        w = width(label, 'tag') + 16
        if anchor == 'end':
            x -= w
        self.add(f'<rect x="{x:g}" y="{y - 14:g}" width="{w:g}" height="20" rx="10" fill="{TINT[role]}" '
                 f'stroke="{ROLE[role]}" stroke-opacity=".16"/>')
        self.text(x + w / 2, y, [(label, ROLE[role])], 'tag', anchor='middle')
        return w

    def chip(self, x, y, w, label, cls='m', fill=INK, bg=CHIP, icon=None, role='slate', h=30):
        fits(label, cls, w - (42 if icon else 12), f'chip {label}')
        self.add(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h}" rx="9" fill="{bg}" '
                 f'fill-opacity=".62" stroke="url(#rim)"/>')
        if icon:
            self.icon(icon, x + 10, y + (h - 18) / 2, role, size=18)
            self.text(x + 36, y + h / 2 + 5, [(label, fill)], cls)
        else:
            self.text(x + w / 2, y + h / 2 + 5, [(label, fill)], cls, anchor='middle')

    def lines(self, x, y, room, rows, cls='b', lh=21, where='lines'):
        for i, row in enumerate(rows):
            segs = [(row, INK if cls == 'b' else MUT)] if isinstance(row, str) else row
            fits(''.join(s[0] for s in segs), cls, room, where)
            self.text(x, y + i * lh, segs, cls)
        return y + len(rows) * lh

    def bullets(self, x, y, room, rows, role='warm', lh=22):
        for i, row in enumerate(rows):
            yy = y + i * lh
            self.add(f'<rect x="{x:g}" y="{yy - 8.5:g}" width="7" height="7" rx="1" '
                     f'transform="rotate(45 {x + 3.5:g} {yy - 5:g})" fill="{ROLE[role]}"/>')
            fits(row, 'b', room - 18, 'bullet')
            self.text(x + 18, yy, row, 'b')
        return y + len(rows) * lh

    def kv(self, x, y, keyw, room, rows, lh=21):
        """Two-column rows: a muted key, then one or more value lines under each other."""
        for key, values in rows:
            if key:
                self.text(x, y, key, 'm', fill=MUT)
            for v in values:
                segs = [(v, INK)] if isinstance(v, str) else v
                fits(''.join(s[0] for s in segs), 'm', room - keyw, f'kv {key}')
                self.text(x + keyw, y, segs, 'm')
                y += lh
        return y

    def logo(self, name, x, y, size=34):
        """Inline a README harness logo (an <img> SVG cannot load another file).

        Tile, geometry and attribution comment come verbatim from
        site/assets/harness/<name>.svg; only the outer <svg> and <title> go.
        """
        if name == 'clawock':
            inner = ('<rect x="1" y="1" width="94" height="94" rx="22" fill="#ffffff" stroke="#d8dde3" stroke-width="2"/>'
                     '<linearGradient id="mark-bull" x1="14" y1="50" x2="51" y2="31" gradientUnits="userSpaceOnUse">'
                     '<stop offset="0" stop-color="#245574"/><stop offset="1" stop-color="#559ed1"/></linearGradient>'
                     '<g transform="translate(16 16)"><path fill="#10141a" d="M8 13C22 9 40 16 55 28C42 24 28 25 17 32C12 27 9 21 8 13Z"/>'
                     '<path fill="url(#mark-bull)" d="M56 51C42 55 24 48 9 36C22 40 36 39 47 32C52 37 55 43 56 51Z"/></g>')
        else:
            text = (ASSETS / 'harness' / f'{name}.svg').read_text(encoding='utf-8')
            inner = text[text.index('>') + 1:text.rindex('</svg>')]
            a, b = inner.find('<title>'), inner.find('</title>')
            if a >= 0:
                inner = inner[:a] + inner[b + len('</title>'):]
        self.add(f'<svg x="{x:g}" y="{y:g}" width="{size}" height="{size}" viewBox="0 0 96 96">{inner.strip()}</svg>')

    def wordmark_tile(self, x, y, size, left, right):
        """A harness with no logo in this repository: its name, set as text on a tile."""
        self.add(f'<rect x="{x + .5:g}" y="{y + .5:g}" width="{size - 1}" height="{size - 1}" rx="{size * .23:g}" '
                 f'fill="#ffffff" stroke="#d8dde3"/>')
        self.add(f'<text x="{x + size / 2:g}" y="{y + size / 2 + 4:g}" class="code" text-anchor="middle" '
                 f'style="font-size:{size * .3:g}px;font-weight:700"><tspan fill="{FAINT}">{left}</tspan>'
                 f'<tspan fill="{INK}">{right}</tspan></text>')

    def icon(self, name, x, y, role='blue', size=22):
        """Original outline glyphs drawn for clawock (MIT), not provider logos.

        Inline geometry keeps the hero self-contained in GitHub/PyPI <img>s.
        Markets, sources and tools retain their written names beside the glyphs.
        """
        shapes = {
            'lens': '<circle cx="10" cy="10" r="6"/><path d="M14 14l7 7M7 10h6m-3-3v6"/>',
            'sector': '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
            'balance': '<path d="M12 3v17M5 21h14M4 7h16M6 7l-4 7h8Zm12 0-4 7h8Z"/>',
            'judge': '<path d="M8 4l5-2 5 10-5 2ZM11 10l-6 9M12 21h9"/>',
            'publish': '<path d="M12 15V3M7 8l5-5 5 5M4 14v7h16v-7"/>',
            'commit': '<circle cx="12" cy="12" r="5"/><path d="M2 12h5m10 0h5"/>',
            'replay': '<path d="M4 8a9 9 0 1 1-1 8M4 3v6h6"/><path d="M10 8l6 4-6 4Z"/>',
            'book': '<path d="M3 4h7l2 2 2-2h7v16h-7l-2 2-2-2H3ZM12 6v16M6 8h3m-3 4h3m6-4h3m-3 4h3"/>',
            'market': '<path d="M3 9L12 3l9 6M4 21h16M6 10v8m6-8v8m6-8v8"/>',
            'fx': '<path d="M4 8h15l-4-4M20 16H5l4 4M20 8v4M4 16v-4"/>',
            'filing': '<path d="M6 3h8l4 4v14H6ZM14 3v5h4M9 12h6m-6 4h6"/>',
            'bars': '<path d="M3 21h18M6 17V9h3v8m3 0V4h3v13m3 0v-6h3v6"/>',
            'news': '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 8h10M7 12h4v4H7Zm7 0h3m-3 4h3"/>',
            'chat': '<path d="M4 4h13a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3H9l-5 4v-4a3 3 0 0 1-2-3V7a3 3 0 0 1 2-3Z"/><path d="M7 10h.01m5 0h.01m5 0h.01"/>',
            'calendar': '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 10h18M7 14h3m4 0h3m-10 4h3"/>',
            'factor': '<path d="M3 20h18M5 16l4-5 4 3 6-9"/><circle cx="9" cy="11" r="1.5"/><circle cx="13" cy="14" r="1.5"/>',
            'gate': '<path d="M4 21V4h16v17M8 4v17m8-17v17M4 12h16M10 8l2 2 3-3"/>',
            'shield': '<path d="M12 2l8 4v6c0 5-5 8-8 10-3-2-8-5-8-10V6ZM8 12l3 3 5-6"/>',
            'debate': '<path d="M2 4h12v9H8l-4 3v-3H2ZM17 8h5v11h-2v3l-4-3h-5v-3"/>',
            'up': '<path d="M4 19L19 4M10 4h9v9"/>',
            'down': '<path d="M4 5l15 15M10 20h9v-9"/>',
            'plane': '<path d="M2 11L22 3l-7 19-4-8ZM11 14L22 3"/>',
            'dashboard': '<rect x="2" y="3" width="20" height="18" rx="2"/><path d="M2 8h20M7 3v5M6 17l4-4 4 2 4-4"/>',
            'branch': '<circle cx="6" cy="4" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="6" cy="20" r="2"/><path d="M6 6v12m0-4c8 0 12-2 12-6"/>',
            'checks': '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M7 8l2 2 3-4m2 3h3M7 16l2 2 3-4m2 3h3"/>',
            'clock': '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
            'terminal': '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 9l3 3-3 3m6 0h5"/>',
        }
        self.add(f'<g class="hero-icon" data-icon="{name}" transform="translate({x:g} {y:g}) scale({size / 24:g})" '
                 f'fill="none" stroke="{ROLE[role]}" stroke-width="1.7" stroke-linecap="round" '
                 f'stroke-linejoin="round" aria-hidden="true">{shapes[name]}</g>')

    def screenshot(self, name, x, y, w):
        """An existing, full-frame repo capture; never a simulated product screen."""
        raw = (ASSETS / name).read_bytes()
        iw, ih = struct.unpack('>II', raw[16:24])
        h = w * ih / iw
        uri = 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')
        self.add(f'<image x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" '
                 f'preserveAspectRatio="xMidYMid meet" href="{uri}">'
                 f'<title>Existing live-host capture: {escape(name)}</title></image>')
        return h

    def mini_charts(self, x, y, w):
        """Schematic price, factor-rank and risk views; never plotted results."""
        self.text(x, y, 'price · factor ranks · risk  /  schematic', 'm', fill=MUT)
        xs, cw = columns(3, gap=10, x0=x, w=w)
        for left, role in zip(xs, ('blue', 'green', 'warm')):
            self.add(f'<rect x="{left:g}" y="{y + 10:g}" width="{cw:g}" height="42" rx="7" '
                     f'fill="{TINT[role]}"/>')
            self.add(f'<path d="M{left + 10:g} {y + 42:g}H{left + cw - 10:g}" '
                     f'stroke="{CARD_STROKE}"/>')
        # Each panel uses its own scale. Geometry is illustrative, with no axes or values.
        points = [(0, 28), (.16, 21), (.32, 25), (.5, 11), (.65, 17), (.8, 8), (1, 12)]
        path = ' '.join(f'{"M" if i == 0 else "L"}{xs[0] + 10 + t * (cw - 20):g} {y + 12 + v:g}'
                        for i, (t, v) in enumerate(points))
        self.add(f'<path d="{path}" fill="none" stroke="{ROLE["blue"]}" stroke-width="2"/>')
        for i, height in enumerate((10, 18, 26, 14, 22)):
            left = xs[1] + 13 + i * (cw - 26) / 5
            self.add(f'<rect x="{left:g}" y="{y + 42 - height:g}" width="{(cw - 36) / 5:g}" '
                     f'height="{height}" rx="2" fill="{ROLE["green"]}" fill-opacity=".7"/>')
        for i, (role, fraction) in enumerate((('green', .8), ('blue', .55), ('warm', .3))):
            self.add(f'<rect x="{xs[2] + 10:g}" y="{y + 18 + i * 9:g}" width="{(cw - 20) * fraction:g}" '
                     f'height="5" rx="2.5" fill="{ROLE[role]}" fill-opacity=".7"/>')

    # --- connectors --------------------------------------------------------
    def wire(self, d, pulses=(0,), dur=2.2, arrow=True, color=LINE, pulse=None, dash=False):
        self.n += 1
        pid = f'w{self.n}'
        mk = ' marker-end="url(#arr)"' if arrow else ''
        ds = ' stroke-dasharray="3 5"' if dash else ''
        self.add(f'<path id="{pid}" d="{d}" fill="none" stroke="{color}" stroke-width="1.5"{ds}{mk}/>')
        for b in pulses:
            c = pulse or ROLE['blue']
            for r, fill in ((7, f'url(#glow-{GLOW[c]})'), (3.4, c)):
                self.add(f'<circle class="pulse" r="{r}" fill="{fill}">'
                         f'<animateMotion dur="{dur}s" begin="{-b:.2f}s" repeatCount="indefinite" '
                         f'keyPoints="0;1" keyTimes="0;1" calcMode="spline" keySplines=".45 0 .55 1">'
                         f'<mpath href="#{pid}" xlink:href="#{pid}"/></animateMotion></circle>')

    def down(self, x, y1, y2, **kw):
        self.wire(f'M{x:g} {y1:g}V{y2 - 2:g}', **kw)

    def curve(self, x1, y1, x2, y2, **kw):
        ym = (y1 + y2) / 2
        self.wire(f'M{x1:g} {y1:g}C{x1:g} {ym:g} {x2:g} {ym:g} {x2:g} {y2 - 10:g}', **kw)

    def render(self, h):
        style = (
            f'text{{font-family:{SANS}}}'
            + ''.join(f'.{k}{{font-size:{s}px;font-weight:{w}}}' for k, (s, w, _) in TYPE.items())
            + '.kick{letter-spacing:1.1px}.title{letter-spacing:-.5px}.h{letter-spacing:-.2px}'
            '.tag{letter-spacing:.9px}'
            f'.code{{font-family:{MONO}}}'
            '.breathe{animation:breathe 2.4s ease-in-out infinite}'
            '@keyframes breathe{50%{opacity:.35}}'
            '@media (prefers-reduced-motion:reduce){.pulse{display:none}.breathe,.sweep{animation:none}}'
        )
        if self.group is not None:
            self.bottoms.append(h + self.dy)
            self._close()
            h = max(self.bottoms)
        pw = self.pw
        # Deterministic grain: a 96-unit tile of sparse dots, light and dark.
        seed, dots = 20260930, []
        for _ in range(46):
            seed = (seed * 1103515245 + 12345) % 2 ** 31
            gx = seed % 9600 / 100
            seed = (seed * 1103515245 + 12345) % 2 ** 31
            gy = seed % 9600 / 100
            dots.append(f'<circle cx="{gx:g}" cy="{gy:g}" r=".55" fill="{"#ffffff" if seed % 3 else "#22303c"}" '
                        f'fill-opacity="{".5" if seed % 3 else ".16"}"/>')
        fields = (('blue', 0, 0, .30), ('violet', pw, 0, .22),
                  ('green', pw * .92, h, .20), ('warm', 0, h * .96, .16))
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                f'width="{pw}" height="{h:g}" viewBox="0 0 {pw} {h:g}" role="img" aria-labelledby="title desc">\n'
                f'  <title id="title">{escape(self.title)}</title>\n'
                f'  <desc id="desc">{escape(self.desc)}</desc>\n'
                '  <!-- Generated by site/tools/build_readme_diagrams.py; edit the builder, not this file. -->\n'
                '  <defs><linearGradient id="page" x1="0" y1="0" x2="1" y2="1">'
                '<stop offset="0" stop-color="#f7f9fc"/><stop offset=".6" stop-color="#eef2f7"/>'
                '<stop offset="1" stop-color="#e6ecf3"/></linearGradient>'
                + ''.join(
                    f'<radialGradient id="field-{role}" cx="{cx:g}" cy="{cy:g}" r="{max(pw, 520) * .62:g}" '
                    f'gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="{ROLE[role]}" '
                    f'stop-opacity="{alpha:g}"/><stop offset="1" stop-color="{ROLE[role]}" stop-opacity="0"/>'
                    f'</radialGradient>' for role, cx, cy, alpha in fields)
                + '<pattern id="grain" width="96" height="96" patternUnits="userSpaceOnUse">'
                + ''.join(dots) + '</pattern>'
                '<linearGradient id="glass" x1="0" y1="0" x2="0" y2="1">'
                '<stop offset="0" stop-color="#ffffff" stop-opacity=".74"/>'
                '<stop offset="1" stop-color="#ffffff" stop-opacity=".48"/></linearGradient>'
                + ''.join(
                    f'<linearGradient id="glass-{role}" x1="0" y1="0" x2="0" y2="1">'
                    f'<stop offset="0" stop-color="{tint}" stop-opacity=".88"/>'
                    f'<stop offset="1" stop-color="{tint}" stop-opacity=".60"/></linearGradient>'
                    for role, tint in TINT.items())
                + '<linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1">'
                '<stop offset="0" stop-color="#ffffff" stop-opacity=".55"/>'
                '<stop offset="1" stop-color="#ffffff" stop-opacity="0"/></linearGradient>'
                '<linearGradient id="rim" x1="0" y1="0" x2="0" y2="1">'
                '<stop offset="0" stop-color="#ffffff" stop-opacity=".95"/>'
                '<stop offset=".5" stop-color="#dfe7ef" stop-opacity=".9"/>'
                '<stop offset="1" stop-color="#9fb0c0" stop-opacity=".75"/></linearGradient>'
                '<linearGradient id="lift" x1="0" y1="0" x2="0" y2="1">'
                '<stop offset="0" stop-color="#1c2b3a" stop-opacity=".17"/>'
                '<stop offset="1" stop-color="#1c2b3a" stop-opacity="0"/></linearGradient>'
                f'<linearGradient id="rule" x1="{M}" y1="0" x2="{pw - M}" y2="0" gradientUnits="userSpaceOnUse">'
                f'<stop offset=".5" stop-color="{CARD_STROKE}"/>'
                f'<stop offset="1" stop-color="{CARD_STROKE}" stop-opacity="0"/></linearGradient>'
                + ''.join(f'<radialGradient id="glow-{role}"><stop offset=".4" stop-color="{color}" stop-opacity=".36"/>'
                          f'<stop offset=".72" stop-color="{color}" stop-opacity=".14"/>'
                          f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></radialGradient>'
                          for role, color in ROLE.items())
                + f'<marker id="arr" markerWidth="10" markerHeight="10" refX="6" refY="5" orient="auto" '
                f'markerUnits="userSpaceOnUse"><path d="M1 1.5L6.5 5L1 8.5" fill="none" stroke="{LINE}" '
                f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></marker>'
                f'<style>{style}</style></defs>\n'
                f'  <rect x=".5" y=".5" width="{pw - 1}" height="{h - 1:g}" rx="22" fill="url(#page)"/>\n'
                + ''.join(f'  <rect x=".5" y=".5" width="{pw - 1}" height="{h - 1:g}" rx="22" '
                          f'fill="url(#field-{role})"/>\n' for role, *_ in fields)
                + f'  <rect x=".5" y=".5" width="{pw - 1}" height="{h - 1:g}" rx="22" fill="url(#grain)" '
                f'stroke="#d5dde6"/>\n')
        return head + '\n'.join('  ' + p for p in self.parts) + '\n</svg>\n'


def columns(n, gap=16, x0=M, w=CW):
    cw = (w - gap * (n - 1)) / n
    return [x0 + i * (cw + gap) for i in range(n)], cw


def sweep(d, x, y, w, rows, lh=22, period=None):
    """A soft highlight that steps down a list, one row at a time."""
    period = period or rows * 1.5
    d.n += 1
    name = f'sw{d.n}'
    steps = ''.join(f'{i * 100 / rows:.2f}%{{transform:translateY({i * lh}px)}}' for i in range(rows))
    d.add(f'<style>.{name}{{animation:{name} {period:g}s steps(1) infinite}}@keyframes {name}{{{steps}}}'
          f'@media (prefers-reduced-motion:reduce){{.{name}{{animation:none}}}}</style>')
    d.add(f'<rect class="{name} sweep" x="{x:g}" y="{y:g}" width="{w:g}" height="{lh}" rx="6" fill="#000" fill-opacity=".035"/>')


# ---------------------------------------------------------------------------
def harnesses(wide=False):
    """site/assets/harnesses.svg — dsh user story, from delegation to a delivered result."""
    d = D('The clawock-dsh plugin — delegate, watch, steer, ship, hear back',
          'On a host configured with agent-dispatch, a user can ask in dsh chat to delegate '
          'repository work to Claude Code, Codex or OpenCode. The runner starts a background '
          'systemd task that outlives the conversation. The plugin shows provider allowances, '
          'each agent queue, running tasks, recent results and notification receipts. Its '
          'controls reorder waiting work, change the next attempt model where allowed, adjust '
          'budgets, retry an ended unfinished session or cancel a task through the audited ops '
          'entry. The repository task pictured requests an isolated branch, a PR, required CI, '
          'squash merge and host refresh; these are its delivery instructions, not automatic '
          'plugin actions. The runner records the report and sends best-effort WeChat and '
          'Telegram notifications, with delivery receipts visible in the panel. The queue '
          'image is an existing full-frame capture from a live host, not an example result.',
          wide=wide)
    d.logo('deepseek-harness', d.pw - M - 34, 26)
    y = d.header('CLAWOCK-DSH · YOUR BACKGROUND TEAM',
                 ['Delegate the work.', 'Keep the controls.'],
                 ['Leave the conversation. Your task keeps running.',
                  'Come back to the queue, the report and the receipts.'],
                 [('request · result', 'blue'), ('background agents', 'slate'),
                  ('checks · live', 'green'), ('quota · control', 'warm')], title_lh=34)

    y += 34
    d.flow(y - 12)
    d.section(y, '01 · ASK IN DSH CHAT')
    y += 14
    h = 156
    d.card(M, y, CW, h, 'blue')
    d.logo('deepseek-harness', M + 20, y + 16)
    d.text(M + 66, y + 38, 'You → your agent', 'h')
    d.tag(W - M - 16, y + 36, 'EXAMPLE REQUEST', 'blue', anchor='end')
    d.lines(M + 20, y + 73, CW - 40,
            ['“Have Codex improve my README.',
             'Open a PR; merge after required checks pass,',
             'refresh the live checkout and send me the result.”'], where='request')
    top = y + h
    y = top + 76
    d.section(y - 14, '02 · THE RUNNER TAKES IT FROM HERE')
    d.down(W / 2, top, y - 38, pulses=(0, 1.1))
    h = 94
    runner = y + h / 2
    d.card(M, y, CW, h, 'blue')
    d.icon('terminal', M + 20, y + 16, size=28)
    d.text(M + 62, y + 36, 'agent-dispatch', 'h')
    d.tag(W - M - 16, y + 34, 'HOST REQUIRED', 'blue', anchor='end')
    d.lines(M + 20, y + 61, CW - 40,
            ['One systemd task per request; independent of chat.'], cls='m', where='runner')
    top = y + h
    y = top + 56
    xs, cw = columns(3)
    h = 122
    for i, (x, (logo, name)) in enumerate(zip(xs, (
            ('claude-code', 'Claude Code'), ('codex', 'Codex'), (None, 'OpenCode')))):
        d.curve(W / 2, top, x + cw / 2, y, pulses=(i * .6,), pulse=ROLE['slate'])
        d.card(x, y, cw, h, 'slate')
        if logo:
            d.logo(logo, x + cw / 2 - 20, y + 14, size=40)
        else:
            d.wordmark_tile(x + cw / 2 - 20, y + 14, 40, '[', ']')
        d.text(x + cw / 2, y + 80, name, 'h', anchor='middle')
        d.text(x + cw / 2, y + 104, 'own task unit', 'm', anchor='middle', fill=MUT)
        fits('own task unit', 'm', cw - 12, 'worker')
    top = y + h
    y = top + 72
    for i, x in enumerate(xs):
        d.curve(x + cw / 2, top, W / 2, y - 38, pulses=(i * .6,), pulse=ROLE['slate'])

    if d.wide:
        # The panel watches the work while it runs, so on a wide canvas it
        # stands beside the story instead of interrupting it.
        merge = d.at(W / 2, y - 38)[1]
        side = d.at(W - M, runner)
        d.place(1, y - 26, d.top, y - 38)
        d.page_wire(f'M{side[0]:g} {side[1]:g}H{COL2 + M - 2:g}', pulses=(.3,), dur=1.4,
                    pulse=ROLE['violet'])
    d.section(y - 12, '03 · WATCH AND STEER FROM THE SIDEBAR')
    shot_w = 224
    shot_iw, shot_ih = struct.unpack('>II', (ASSETS / 'dsh-dispatch-queue.png').read_bytes()[16:24])
    shot_h = shot_w * shot_ih / shot_iw
    h = shot_h + 92
    d.card(M, y, CW, h, 'violet')
    d.icon('dashboard', M + 20, y + 14, 'violet')
    d.text(M + 50, y + 32, 'Your team, at a glance', 'h')
    d.tag(W - M - 16, y + 30, 'LIVE-HOST CAPTURE', 'violet', anchor='end')
    d.screenshot('dsh-dispatch-queue.png', M + 12, y + 48, shot_w)
    tx, room = M + 254, CW - 270
    facts = [
        ('clock', 'Allowances', ['5h + weekly use', 'and reset times.'], 'warm'),
        ('terminal', 'Real queue order', ['Running, queued,', 'or waiting for quota.'], 'blue'),
        ('branch', 'Steer the task', ['Move waiting work;', 'change the next model', 'where allowed.'], 'violet'),
        ('clock', 'Set its budgets', ['Deadline, retries', 'and quota resumes.'], 'warm'),
        ('filing', 'Open the brief', ['Read the task and', 'appended instructions.'], 'slate'),
        ('checks', 'See the receipts', ['Report status and', 'notification delivery', 'shown separately.'], 'green'),
    ]
    for i, (icon, title, rows, role) in enumerate(facts):
        yy = y + 68 + i * 112
        d.icon(icon, tx, yy, role, size=24)
        d.text(tx, yy + 44, title, 'b')
        fits(title, 'b', room, 'queue title')
        d.lines(tx, yy + 65, room, rows, cls='m', lh=19, where='queue detail')
    d.text(M + 20, y + h - 20, 'Existing screenshot · open the full-size capture below', 'm', fill=MUT)
    top = y + h
    y = top + 76
    if d.wide:
        d.place(0, y - 26, merge + 12, top)
    else:
        d.down(W / 2, top, y - 38, pulses=(0, 1.1), pulse=ROLE['green'])

    d.section(y - 12, '04 · THE REPO TASK SHIPS WHAT YOU REQUESTED')
    h = 138
    d.card(M, y, CW, h, 'green')
    xs, cw = columns(3, gap=18, x0=M + 16, w=CW - 32)
    for i, (x, (icon, name, sub)) in enumerate(zip(xs, (
            ('branch', 'Branch + PR', 'isolated worktree'),
            ('checks', 'Required CI', 'all gates pass'),
            ('commit', 'Squash merge', 'review the diff')))):
        d.icon(icon, x + cw / 2 - 16, y + 18, 'green', size=32)
        d.text(x + cw / 2, y + 77, name, 'b', anchor='middle')
        d.text(x + cw / 2, y + 100, sub, 'm', anchor='middle', fill=MUT)
        fits(name, 'b', cw, 'repo step')
        fits(sub, 'm', cw, 'repo sub')
        if i:
            d.wire(f'M{x - 16:g} {y + 34:g}H{x - 3:g}', pulses=(i * .4,), dur=1.2,
                   pulse=ROLE['green'])
    top = y + h
    y = top + 54
    d.down(W / 2, top, y, pulses=(0,), pulse=ROLE['green'])
    h = 92
    d.card(M, y, CW, h, 'green', tint=True)
    d.logo('clawock', M + 20, y + 18, size=40)
    d.text(M + 74, y + 38, 'Merged → live on your host', 'h')
    d.text(M + 74, y + 63, 'refresh_live.sh applies the checked change', 'm', fill=MUT)
    fits('refresh_live.sh applies the checked change', 'm', CW - 94, 'live')
    top = y + h
    y = top + 76
    d.down(W / 2, top, y - 38, pulses=(0, 1.1))

    d.section(y - 12, '05 · HEAR BACK, EVEN AFTER YOU LEAVE')
    h = 160
    d.card(M, y, CW, h, 'blue')
    d.icon('chat', M + 20, y + 16, size=30)
    d.icon('plane', M + 58, y + 16, size=30)
    d.text(M + 104, y + 38, 'WeChat + Telegram', 'h')
    d.lines(M + 20, y + 74, CW - 40,
            ['Final report: what changed, what passed, what is live.',
             'Best-effort sends; the panel shows each receipt.',
             'If unfinished, inspect the log or retry its session.'], cls='m', where='result')
    d.text(M + 20, y + 144, 'Task outcome ≠ message delivery', 'm', fill=ROLE['warm'])
    return d.render(y + h + M)


# ---------------------------------------------------------------------------
def information_flow(wide=False):
    """site/assets/information-flow.svg — the live desk's data flow, end to end."""
    d = D('clawock data flow — sources, fetch fallback, portfolio and risk, three cadences, '
          'agent, postflight, data plane and delivery',
          'Eight information layers feed ordered fetch-fallback routes (HK quotes Tencent plus '
          'Eastmoney HK, then stooq, then yfinance; US quotes Nasdaq, Eastmoney, Finnhub, Yahoo, '
          'yfinance, Alpha Vantage, Polygon; USDHKD Frankfurter, exchangerate.host, Yahoo; every '
          'live Eastmoney call through one throttled gateway; an empty fetch keeps the prior value). '
          'Python reconciles the book, runs the integrity gate and builds risk. The pre-open brief, '
          'session reports and intraday check-ins each run a preflight that assembles only the '
          'blocks that run can use; the agent reads those files and never fetches; a Python '
          'postflight validates and publishes to master, to the data-plane branch the dashboard '
          'polls, and to WeChat and Telegram. An LLM-free crontab watchdog checks every slot and '
          'mirrors to Telegram when the send is not confirmed.',
          wide=wide)
    y = d.header('DATA FLOW · HK + US',
                 ['From eight source layers', 'to a delivered card'],
                 ['Python fetches, computes and settles; the model', 'only reads the files a run assembles.'],
                 [('source · fetch', 'blue'), ('python', 'green'), ('agent · LLM', 'slate'),
                  ('gate · watchdog', 'warm')], title_lh=34)

    y += 30
    d.flow(y - 12)
    d.section(y, '1 · SOURCES')
    y += 14
    h = 262
    d.card(M, y, CW, h, 'blue')
    d.text(M + 20, y + 32, '8 information layers', 'h')
    d.tag(W - M - 16, y + 30, 'HK + US', 'blue', anchor='end')
    xs, cw = columns(2, gap=12, x0=M + 16, w=CW - 32)
    layers = ['L1 market', 'L2 SEC · HKEX', 'L3 capital flow', 'L4 news', 'L5 macro · mood',
              'L6 quant · risk', 'L7 book · FX', 'L8 backtest']
    for i, name in enumerate(layers):
        col, row = i % 2, i // 2
        d.chip(xs[col], y + 54 + row * 52, cw, name, h=36, role='blue',
               icon=('market', 'filing', 'bars', 'news', 'calendar', 'shield', 'fx', 'replay')[i])
    top = y + h
    y = top + 44
    d.down(W / 2, top, y, pulses=(0, 1.1))

    h = 312
    d.card(M, y, CW, h, 'blue')
    d.icon('market', M + 20, y + 14)
    d.text(M + 50, y + 32, 'Fetch with fallback', 'h')
    d.tag(W - M - 16, y + 30, 'ORDERED ROUTES', 'blue', anchor='end')
    yy = y + 66
    routes = [
        ('HK quotes', [[('Tencent + Eastmoney HK', INK)], [('→ stooq → yfinance', MUT)]], 'market'),
        ('US quotes', [[('Nasdaq', INK), (' → Eastmoney → Finnhub', MUT)],
                       [('→ Yahoo → yfinance', MUT)], [('→ Alpha Vantage → Polygon', MUT)]], 'market'),
        ('USD/HKD', [[('Frankfurter', INK), (' → exchangerate.host', MUT)], [('→ Yahoo', MUT)]], 'fx'),
    ]
    for key, values, icon in routes:
        d.icon(icon, M + 20, yy - 15, size=18)
        yy = d.kv(M + 48, yy, 100, CW - 64, [(key, values)], lh=22) + 12
    d.add(f'<path d="M{M + 20:g} {yy - 6:g}H{W - M - 16:g}" stroke="{CARD_STROKE}"/>')
    d.lines(M + 20, yy + 14, CW - 36, [[('One throttled gateway for every live Eastmoney', MUT)],
                                       [('call; an empty fetch keeps the prior value.', MUT)]],
            cls='m', lh=19, where='fetch note')
    top = y + h
    y = top + 44
    d.down(W / 2, top, y, pulses=(.4, 1.5))

    h = 150
    d.card(M, y, CW, h, 'green')
    d.icon('shield', M + 20, y + 14, 'green')
    d.text(M + 50, y + 32, 'Portfolio + risk', 'h')
    d.tag(W - M - 16, y + 30, 'PYTHON', 'green', anchor='end')
    d.kv(M + 20, y + 60, 84, CW - 36, [
        ('reconcile', ['recompute every money field']),
        ('integrity', ['data-health gate on the book']),
        ('fx', ['HK + US sum only through it']),
        ('risk', ['β · vol · drawdown → risk.json']),
    ])
    top = y + h
    y = top + 30
    label = 'preflight · only the blocks this run can use'
    d.turn(W / 2, top, y - 22, first=y - 14, enter=y - 3, reach=W / 2 - width(label, 'm') / 2 - 6,
           pulses=(0,), pulse=ROLE['green'], arrow=False)
    d.text(W / 2, y + 2, [('preflight', ROLE['green']), (' · only the blocks this run can use', MUT)],
           'm', anchor='middle')
    fits(label, 'm', CW, 'preflight label')
    y += 50
    xs, cw = columns(3)
    cad = [('Brief', ['pre-open', '08:03 HKT', 'weekdays', '→ plan.json']),
           ('Report', ['HK open, mid,', 'pm, close', 'US open, close', 'fresh quotes']),
           ('Intraday', ['every 30 min', 'while a market', 'is open', 'judgment packet'])]
    h = 150
    for i, (x, (name, body)) in enumerate(zip(xs, cad)):
        d.curve(W / 2, y - 26, x + cw / 2, y, pulses=(i * .5,), dur=1.6)
        d.card(x, y, cw, h, 'green')
        d.text(x + 16, y + 30, name, 'h')
        d.lines(x + 16, y + 56, cw - 24, body, cls='m', lh=20, where='cadence')
    top = y + h
    y = top + 50
    for i, x in enumerate(xs):
        d.curve(x + cw / 2, top, W / 2, y, pulses=(i * .5 + .3,), dur=1.8, pulse=ROLE['slate'])

    h = 96
    d.card(M, y, CW, h, 'slate')
    d.icon('debate', M + 20, y + 14, 'slate')
    d.text(M + 50, y + 32, 'Agent', 'h')
    d.tag(W - M - 16, y + 30, 'LLM', 'slate', anchor='end')
    d.lines(M + 20, y + 58, CW - 36, ['Reads the context files, never fetches;',
                                      'the brief also writes plan.json.'], lh=21, where='agent')
    top = y + h
    y = top + 40
    d.down(W / 2, top, y, pulses=(0, 1.1), pulse=ROLE['green'])
    h = 96
    d.card(M, y, CW, h, 'green')
    d.icon('checks', M + 20, y + 14, 'green')
    d.text(M + 50, y + 32, 'Postflight', 'h')
    d.tag(W - M - 16, y + 30, 'PYTHON', 'green', anchor='end')
    d.lines(M + 20, y + 58, CW - 36, ['Validates the output, then publishes;',
                                      'sends WeChat and co-sends Telegram.'], lh=21, where='postflight')
    top = y + h
    y = top + 50
    outs = [('Deliver', ['WeChat +', 'Telegram']),
            ('data-plane', ['7 files, one', 'generation']),
            ('master', ['ledger +', 'pre-push gate'])]
    h = 132
    for i, (x, (name, body)) in enumerate(zip(xs, outs)):
        d.curve(W / 2, top, x + cw / 2, y, pulses=(i * .5,), dur=1.8)
        d.card(x, y, cw, h, 'blue')
        d.text(x + 16, y + 30, name, 'h')
        d.lines(x + 16, y + 56, cw - 24, body, cls='m', lh=20, where='outputs')
        d.icon(('plane', 'publish', 'commit')[i], x + 16, y + 96, size=22)
    top = deliver_bottom = y + h
    d.lines(xs[1], top + 24, W - M - xs[1], [[('WeChat cannot confirm a send;', FAINT)],
                                            [('Telegram can. The dashboard polls', FAINT)],
                                            [('data-plane every 60 s; master', FAINT)],
                                            [('takes only a reconciled book.', FAINT)]], cls='m', lh=19,
            where='outputs note')
    top += 16
    top += 70
    y = top + 40
    d.wire(f'M{xs[0] + cw / 2:g} {y - 2:g}V{deliver_bottom + 4:g}', pulses=(0, 1.2), dur=2.4, dash=True,
           color='#d9a8a3', pulse=ROLE['warm'])
    h = 136
    d.card(M, y, CW, h, 'warm')
    d.icon('clock', M + 20, y + 14, 'warm')
    d.text(M + 50, y + 32, 'Watchdog', 'h')
    d.tag(W - M - 16, y + 30, 'CRONTAB · NO LLM', 'warm', anchor='end')
    yy = d.kv(M + 20, y + 60, 84, CW - 36, [
        ('brief', [[('08:36', INK), (' · miss check 09:05', MUT)]]),
        ('report', ['10–20 min after its slot']),
        ('intraday', [':13 and :43']),
    ])
    d.text(M + 20, yy + 2, 'Unconfirmed send → mirror to Telegram', 'm', fill=ROLE['warm'])
    return d.render(y + h + M)


# ---------------------------------------------------------------------------
def architecture(wide=False):
    """site/assets/architecture.svg — the KCNyu live desk: argue, gate, publish, settle, loop."""
    d = D('KCNyu live investment instance built with clawock contracts',
          'This is the KCNyu deployment, not the reusable clawock product architecture. Python '
          'assembles one immutable evidence pack. OpenClaw agents run four analyst lenses, a bull '
          'case, a bear case and three risk voices, and a judge names the strategy frame and writes '
          'plan.json. A Python decision contract validates plan.json and the brief sections, and '
          'flags any risk breach the plan ignores, before the ledger, brief and dashboard publish '
          'it. On the return path code triggers each call against canonical unadjusted daily bars, '
          'groups repeated calls into episodes, grades them against a directional baseline and '
          'publishes the scorecard, which feeds the next brief.',
          wide=wide)
    y = d.header('KCNYU LIVE DESK · HK + US',
                 ['How this deployment turns', 'a claim into a public record'],
                 ['OpenClaw argues the call. Code gates it, the', 'bars settle it, and the score feeds tomorrow.'],
                 [('python', 'green'), ('agent · LLM', 'slate'), ('settle · grade', 'blue'),
                  ('gate', 'warm')], title_lh=34)
    RAIL = W - M - 18          # the return loop runs up the right edge
    IW = CW - 42              # inner column, leaving room for the loop
    y += 30
    d.flow(y - 12)
    d.section(y, '01 · EVIDENCE')
    y += 14
    ey = y
    h = 118
    d.card(M, y, IW, h, 'green')
    d.icon('book', M + 20, y + 14, 'green')
    d.text(M + 50, y + 32, 'Evidence pack', 'h')
    d.tag(M + IW - 16, y + 30, 'PYTHON', 'green', anchor='end')
    d.text(M + 20, y + 54, [('context.json', INK), (' — reconciled, immutable', MUT)], 'm')
    xs, cw = columns(4, gap=6, x0=M + 16, w=IW - 32)
    for x, label in zip(xs, ('book', 'market', 'risk', 'events')):
        d.chip(x, y + 72, cw, label)
    top = y + h
    y = top + 44
    d.section(y - 12, '02 · DECISION ROOM')
    d.down(M + IW / 2, top, y, pulses=(0,), pulse=ROLE['slate'])
    h = 74
    d.card(M, y, IW, h, 'slate')
    d.icon('lens', M + 20, y + 12, 'slate')
    d.text(M + 50, y + 30, 'Four analyst lenses', 'h')
    d.tag(M + IW - 16, y + 28, 'LLM', 'slate', anchor='end')
    d.text(M + 20, y + 54, 'fundamental · technical · sentiment · sector', 'm', fill=MUT)
    fits('fundamental · technical · sentiment · sector', 'm', IW - 36, 'lenses')
    top = y + h
    y = top + 44
    xs, cw = columns(3, gap=10, x0=M, w=IW)
    fork = [('Bull case', 'hold / add', 'green'), ('Bear case', 'trim / cut', 'warm'),
            ('Risk voices', 'three of them', 'slate')]
    h = 112
    for i, (x, (name, body, role)) in enumerate(zip(xs, fork)):
        d.curve(M + IW / 2, top, x + cw / 2, y, pulses=(i * .5,), dur=1.8, pulse=ROLE['slate'])
        d.card(x, y, cw, h, role)
        fits(name, 'h', cw - 24, 'fork')
        d.icon({'Bull case': 'up', 'Bear case': 'down', 'Risk voices': 'shield'}[name], x + 16, y + 14, role)
        d.text(x + 16, y + 64, name, 'h')
        d.text(x + 16, y + 88, body, 'm', fill=MUT)
    top = y + h
    y = top + 48
    for i, x in enumerate(xs):
        d.curve(x + cw / 2, top, M + IW / 2, y, pulses=(i * .5 + .3,), dur=1.8, pulse=ROLE['slate'])
    h = 96
    d.card(M, y, IW, h, 'slate')
    d.icon('judge', M + 20, y + 14, 'slate')
    d.text(M + 50, y + 32, 'Judge', 'h')
    d.tag(M + IW - 16, y + 30, 'LLM', 'slate', anchor='end')
    d.lines(M + 20, y + 58, IW - 36, ['Names the strategy frame of each call:',
                                      [('action · trigger · confidence → plan.json', MUT)]], lh=21, where='judge')
    top = y + h
    y = top + 50
    d.turn(M + IW / 2, top, y, first=y - 26, enter=y + 28, pulses=(0, 1.6), pulse=ROLE['green'])
    d.section(y - 14, '03 · DECISION CONTRACT')
    h = 134
    d.card(M, y, IW, h, 'green')
    d.icon('checks', M + 20, y + 14, 'green')
    d.text(M + 50, y + 32, 'Code gate', 'h')
    d.tag(M + IW - 16, y + 30, 'PYTHON', 'green', anchor='end')
    d.bullets(M + 22, y + 62, IW - 40, ['plan.json schema: fields, enums, confidence',
                                        'Brief sections: tiers, judge, next session',
                                        'A risk breach the plan ignores is flagged'], role='green')
    top = y + h
    y = top + 48
    xs, cw = columns(3, gap=10, x0=M, w=IW)
    pubs = [('Ledger', 'decisions.jsonl'), ('Brief', 'the chat card'), ('Dashboard', 'data-plane')]
    h = 106
    for i, (x, (name, body)) in enumerate(zip(xs, pubs)):
        d.curve(M + IW / 2, top, x + cw / 2, y, pulses=(i * .5,), dur=1.8)
        d.card(x, y, cw, h, 'blue')
        d.icon(('filing', 'chat', 'dashboard')[i], x + 16, y + 12)
        d.text(x + 16, y + 60, name, 'h')
        fits(body, 'm', cw - 20, 'pub')
        d.text(x + 12, y + 84, body, 'm', fill=MUT)
    top = y + h
    y = top + 48
    d.text(xs[0] + cw / 2 + 14, y - 14, '04 · SETTLE IN THE OPEN', 'kick', fill=FAINT)
    d.down(xs[0] + cw / 2, top, y, pulses=(0,))
    steps = [('Record', 'the model submits; it never grades itself'),
             ('Trigger', 'canonical unadjusted daily bars, per market'),
             ('Group', 'repeat calls of one strategy = one episode'),
             ('Grade', 'code scores it against a directional baseline'),
             ('Public scorecard', 'ungradeable calls stay visible in coverage')]
    h = 30 + len(steps) * 46
    d.card(M, y, IW, h, 'blue')
    for i, (name, body) in enumerate(steps):
        yy = y + 34 + i * 46
        d.icon(('filing', 'market', 'sector', 'checks', 'dashboard')[i], M + 20, yy - 16, size=20)
        d.text(M + 52, yy, name, 'b')
        fits(body, 'm', IW - 70, 'settle')
        d.text(M + 52, yy + 20, body, 'm', fill=MUT)
        if i:
            d.add(f'<path d="M{M + 30:g} {yy - 30:g}V{yy - 18:g}" stroke="{LINE}" stroke-width="1.5"/>')
    bottom = y + h
    # the loop: the scorecard feeds the next brief's evidence
    if d.wide:
        # Up the second column's rail, over both columns, down the first one's.
        x1, yb = d.at(M + IW, bottom - 30)
        r1, over = d.at(RAIL, 0)[0], d.top - 12
        d.page_wire(f'M{x1:g} {yb:g}H{r1 - 8:g}Q{r1:g} {yb:g} {r1:g} {yb - 8:g}V{over + 8:g}'
                    f'Q{r1:g} {over:g} {r1 - 8:g} {over:g}H{RAIL + 8:g}Q{RAIL:g} {over:g} {RAIL:g} {over + 8:g}'
                    f'V{ey + 24:g}Q{RAIL:g} {ey + 32:g} {RAIL - 8:g} {ey + 32:g}H{M + IW + 4:g}',
                    pulses=(0, 3.5), dur=7, color='#b8c9d8')
        ty = d.top + (yb - d.top) / 2 - d.dy
    else:
        d.wire(f'M{M + IW:g} {bottom - 30:g}H{RAIL - 8:g}Q{RAIL:g} {bottom - 30:g} {RAIL:g} {bottom - 38:g}'
               f'V{ey + 40:g}Q{RAIL:g} {ey + 32:g} {RAIL - 8:g} {ey + 32:g}H{M + IW + 4:g}',
               pulses=(0, 2.5), dur=5, color='#b8c9d8')
        ty = (ey + bottom) / 2
    d.add(f'<text x="{W - M - 2:g}" y="{ty:g}" class="kick" fill="{ROLE["blue"]}" '
          f'transform="rotate(90 {W - M - 2:g} {ty:g})" text-anchor="middle">FEEDS THE NEXT BRIEF</text>')
    return d.render(bottom + M)


# ---------------------------------------------------------------------------
def product_architecture(wide=False):
    """site/assets/product-architecture.svg — runtime / package / instance ownership."""
    d = D('clawock product architecture',
          'External agent runtimes own the model, conversation, memory, planning, tools, permissions '
          'and credentials. They install a standard skill and call the clawock CLI using JSON. The '
          'clawock package owns portable decision workflows, certified inputs, artifact contracts, '
          'deterministic money and foreign-exchange reconciliation, outcome evaluation, receipts, '
          'and bounded proposal review and rollback. User instances own strategy, evidence, ledgers, '
          'schedules, delivery and user interfaces. Every harness drives the same three steps: '
          'clawock run prepare, the agent writes decision.json, clawock run publish.',
          wide=wide)
    y = d.header('PRODUCT ARCHITECTURE · RUNTIME NEUTRAL',
                 ['The runtime thinks.', 'clawock keeps it reconciled.'],
                 ['Three owners, one contract between them:', 'skill + CLI + JSON in, adapter-owned I/O out.'],
                 [('external runtime', 'slate'), ('clawock package', 'green'), ('user instance', 'violet')], title_lh=34)
    y += 30
    d.flow(y - 12)
    d.section(y, 'OWNED BY THE EXTERNAL RUNTIME')
    y += 14
    h = 124
    d.card(M, y, CW, h, 'slate')
    for i, name in enumerate(('openclaw', 'claude-code', 'codex', 'deepseek-harness', 'any-cli')):
        d.logo(name, M + 20 + i * 42, y + 16)
    d.lines(M + 20, y + 78, CW - 36, ['OpenClaw · Claude Code · Codex · DeepSeek Harness',
                                      [('or your own CLI — each owns model, memory, tools', MUT)]], lh=21, where='runtime')
    top = y + h
    y = top + 54
    d.wire(f'M{W / 2 - 12:g} {top:g}V{y - 2:g}', pulses=(0, 1.2), pulse=ROLE['slate'])
    d.wire(f'M{W / 2 + 12:g} {y:g}V{top + 2:g}', pulses=(.6, 1.8), pulse=ROLE['green'])
    d.text(W / 2 - 24, top + 32, 'install skill · call CLI', 'm', anchor='end', fill=MUT)
    d.text(W / 2 + 24, top + 32, 'JSON back', 'm', fill=MUT)
    stages = [('Workflow', 'evidence + opposition, bounded', 'workflow install'),
              ('Certify', 'pinned input · context hashes', 'run prepare'),
              ('Reconcile', 'order · cash · FX · validation', 'run publish'),
              ('Evaluate', 'observed price + FX · receipt', 'workflow evaluate'),
              ('Improve', 'bounded proposal, exact diff', 'review · apply · rollback')]
    h = 70 + len(stages) * 52 + 10
    d.card(M, y, CW, h, 'green')
    d.logo('clawock', M + 20, y + 16, size=30)
    d.text(M + 60, y + 37, 'clawock package', 'h')
    d.tag(W - M - 16, y + 36, 'SRC/CLAWOCK', 'green', anchor='end')
    sweep(d, M + 12, y + 60, CW - 24, len(stages), lh=52, period=10)
    for i, (name, what, cmd) in enumerate(stages):
        yy = y + 86 + i * 52
        d.add(f'<circle cx="{M + 32:g}" cy="{yy - 5:g}" r="11" fill="{TINT["green"]}"/>')
        d.text(M + 32, yy, f'0{i + 1}', 'tag', anchor='middle', fill=ROLE['green'])
        d.icon(('debate', 'checks', 'balance', 'dashboard', 'replay')[i], M + 52, yy - 15, 'green', size=18)
        d.text(M + 78, yy, [(name, INK), (' · ', FAINT), (what, MUT)], 'm')
        fits(name + ' · ' + what, 'm', CW - 94, 'stage')
        d.text(M + 78, yy + 20, cmd, 'code', fill=ROLE['green'])
    top = y + h
    y = top + 44
    d.text(W / 2 + 14, top + (40 if d.wide else 26), 'adapter-owned I/O', 'm', fill=MUT)
    d.turn(W / 2, top, y, first=y - 26, enter=y + 28, tail=48, pulses=(0,), pulse=ROLE['violet'])
    h = 118
    d.card(M, y, CW, h, 'violet')
    d.icon('book', M + 20, y + 14, 'violet')
    d.text(M + 50, y + 32, 'Your instance', 'h')
    d.tag(W - M - 16, y + 30, 'NOT IN THE WHEEL', 'violet', anchor='end')
    d.lines(M + 20, y + 58, CW - 36, ['strategy, evidence, ledger, schedules, delivery, UI',
                                      [('default store: FilesystemStore. KCNyu is one live', MUT)],
                                      [('proof, not the product.', MUT)]], lh=20, where='instance')
    top = y + h
    y = top + 36
    d.section(y, 'EVERY HARNESS, THE SAME THREE STEPS')
    y += 16
    xs, cw = columns(3, gap=18)
    stepsb = [('run prepare', '→ request.json', 'green'), ('agent writes', 'decision.json', 'slate'),
              ('run publish', '→ published', 'green')]
    h = 110
    for i, (x, (name, body, role)) in enumerate(zip(xs, stepsb)):
        d.card(x, y, cw, h, role)
        d.icon(('checks', 'filing', 'publish')[i], x + 16, y + 12, role)
        d.text(x + 16, y + 64, name, 'b')
        fits(body, 'm', cw - 24, 'steps')
        d.text(x + 16, y + 88, body, 'm', fill=MUT)
        if i:
            d.wire(f'M{x - 17:g} {y + h / 2:g}H{x - 3:g}', pulses=(i * .4,), dur=1.2)
    y += h + 26
    d.lines(M, y, CW, ['Drop the opposing evidence from decision.json and',
                       'publish refuses it with exit code 1.'], cls='m', lh=19, where='steps note')
    return d.render(y + 20 + M)


# ---------------------------------------------------------------------------
def debate_flow(wide=False):
    """site/assets/debate-flow.svg — the three-tier debate inside the pre-open brief."""
    d = D('Inside the clawock multi-agent debate',
          "A pipeline. One shared evidence pack feeds four analyst lenses that merge into a single "
          "table. Two researchers are asked to argue opposing bull and bear cases and to record where "
          "they disagree, so unanimous agreement reads as a flag. Three risk voices then stress every "
          "call and a judge names the strategy frame driving each decision, resolving the argument "
          "into plan.json — which enters the next session's grading pipeline, where code, not the "
          "model, settles the score.",
          wide=wide)
    y = d.header('THE DEBATE · HK + US',
                 ['Disagreement is required.', 'The resolution is attributed.'],
                 ['Protocol rules set in the brief prompt; code only', 'checks that each tier was written.'],
                 [('evidence · python', 'green'), ('agents · LLM', 'slate'), ('opposing case', 'warm'),
                  ('grading', 'blue')], title_lh=34)
    y += 30
    d.flow(y - 12)
    d.section(y, 'SHARED INPUT')
    y += 14
    h = 76
    d.card(M, y, CW, h, 'green')
    d.icon('book', M + 20, y + 12, 'green')
    d.text(M + 50, y + 30, [('context.json', INK)], 'h')
    d.text(M + 20, y + 54, 'one immutable evidence pack; every claim cites it', 'm', fill=MUT)
    top = y + h
    d.section(top + 34, 'TIER 1 · ANALYST LENSES')
    y = top + 48
    d.down(W / 2, top, y, pulses=(0,), pulse=ROLE['slate'])
    h = 176
    d.card(M, y, CW, h, 'slate')
    d.text(M + 20, y + 32, 'Four analyst lenses', 'h')
    d.tag(W - M - 16, y + 30, 'LLM', 'slate', anchor='end')
    xs, cw = columns(2, gap=12, x0=M + 16, w=CW - 32)
    for i, name in enumerate(['Fundamental', 'Technical', 'Sentiment', 'Sector rotation']):
        d.chip(xs[i % 2], y + 50 + (i // 2) * 48, cw, name, h=36,
               icon=('lens', 'factor', 'chat', 'sector')[i])
    d.text(M + 20, y + h - 14, 'same context → one merged table', 'm', fill=MUT)
    top = y + h
    d.section(top + 34, 'TIER 2 · RESEARCHERS')
    y = top + 48
    d.down(W / 2, top, y, pulses=(0,), pulse=ROLE['slate'])
    h = 112
    xs, cw = columns(2, gap=40)
    for x, (name, body, sub, role) in zip(xs, (('Bull case', 'hold / add', 'cites the pack', 'green'),
                                              ('Bear case', 'trim / cut', 'hits the strongest view', 'warm'))):
        d.card(x, y, cw, h, role)
        d.icon('up' if role == 'green' else 'down', x + 18, y + 14, role)
        d.text(x + 48, y + 32, name, 'h', fill=ROLE[role])
        d.text(x + 18, y + 56, body, 'b')
        fits(sub, 'm', cw - 26, 'bullbear')
        d.text(x + 18, y + 78, sub, 'm', fill=MUT)
    mx = xs[0] + cw
    d.wire(f'M{mx + 2:g} {y + 40:g}H{xs[1] - 4:g}', pulses=(0,), dur=1.3, pulse=ROLE['green'])
    d.wire(f'M{xs[1] - 2:g} {y + 58:g}H{mx + 4:g}', pulses=(.65,), dur=1.3, pulse=ROLE['warm'])
    top = y + h
    y = top + 14
    d.add(f'<rect x="{M:g}" y="{y:g}" width="{CW:g}" height="34" rx="10" fill="{TINT["warm"]}"/>')
    d.text(W / 2, y + 22, [('OPPOSING CASE REQUIRED', ROLE['warm'])], 'tag', anchor='middle')
    top = y + 34
    fy = top + 48
    d.turn(W / 2, top, fy, first=top + 22, enter=fy, reach=W / 2 + 2, tail=20,
           pulses=(0,), pulse=ROLE['slate'], arrow=False)
    d.section(top + 34, 'TIER 3 · RISK + JUDGE')
    y = fy + 40
    xs, cw = columns(3, gap=10)
    for i, (x, name) in enumerate(zip(xs, ('Aggressive', 'Conservative', 'Neutral'))):
        d.curve(W / 2, fy, x + cw / 2, y, pulses=(i * .5,), dur=1.8, pulse=ROLE['slate'])
        d.card(x, y, cw, 84, 'slate')
        d.icon(('up', 'shield', 'balance')[i], x + cw / 2 - 11, y + 15, 'slate')
        fits(name, 'b', cw - 20, 'risk')
        d.text(x + cw / 2 + 2, y + 65, name, 'b', anchor='middle')
    top = y + 84
    y = top + 46
    for i, x in enumerate(xs):
        d.curve(x + cw / 2, top, W / 2, y, pulses=(i * .5 + .3,), dur=1.8, pulse=ROLE['slate'])
    h = 96
    d.card(M, y, CW, h, 'slate')
    d.icon('judge', M + 20, y + 14, 'slate')
    d.text(M + 50, y + 32, 'Judge', 'h')
    d.tag(W - M - 16, y + 30, 'ATTRIBUTED', 'slate', anchor='end')
    d.lines(M + 20, y + 58, CW - 36, ['Names the strategy frame driving each call',
                                      [('→ plan.json', ROLE['blue'])]], lh=21, where='judge')
    top = y + h
    y = top + 40
    d.down(W / 2, top, y, pulses=(0, 1.1))
    h = 76
    d.card(M, y, CW, h, 'blue')
    d.icon('checks', M + 20, y + 12)
    d.text(M + 50, y + 30, "Next session's grading", 'h')
    d.text(M + 20, y + 54, 'code, not the model, settles the score', 'm', fill=MUT)
    y += h + 26
    d.lines(M, y, CW, ['The bear attacks the strongest consensus, never the weakest;',
                       "the risk voices' first mover rotates every four trading days."],
            cls='m', lh=19, where='notes')
    return d.render(y + 20 + M)

# ---------------------------------------------------------------------------
def decision_pipeline(wide=False):
    """site/assets/decision-pipeline.svg — README hero: one trading day, raw data to a graded call."""
    d = D('clawock decision pipeline — collect, compute and gate, debate, deliver, settle and calibrate',
          'Every trading day Python collects quotes through ordered fallback chains (HK Tencent plus '
          'Eastmoney, then stooq, then yfinance; US through a seven-route chain; USD/HKD Frankfurter, '
          'exchangerate.host, Yahoo), SEC and HKEX filings, Eastmoney capital flow, bilingual news, '
          'Reddit and influencer sentiment, and macro and catalyst calendars. It reconciles the book, '
          'computes portfolio risk (beta, volatility, drawdown), per-leg concentration, the leverage '
          'regime dial, quant factors, cross-sectional ranks and peer residuals. Validated factor '
          'authority requires a bootstrap interval clear of 50%; prospective activation and capped '
          'exploration have separate rules. Code gates hold risk caps, the entry gate, earnings '
          'quality, thesis drift and the news evidence graph. A preflight hands the agents one context '
          'pack; four analyst lenses, a bull and a bear who must disagree, three risk voices and a judge '
          'write plan.json. A postflight validates it, books it in memory/decisions.jsonl, renders the '
          'brief card, sends WeChat and Telegram and publishes the dashboard. Python then records what '
          'was executed (mark-followed), settles each episode on canonical bars, calibrates confidence, '
          'replays a shadow portfolio against buy and hold and publishes the scorecard, which the next '
          "brief reads. In dsh, Decision Mind shows real fills beside their plans and T+1 verdicts; "
          "the trader can ask a follow-up and record a conversation verdict. Execution stays human, "
          "the trace is read-only, and the model never grades itself.",
          wide=wide)
    d.logo('clawock', d.pw - M - 34, 26)
    y = d.header('EVERY TRADING DAY · HK + US',
                 ['Raw market data in,', 'graded decisions out'],
                 ['Python collects, computes, gates and settles;',
                  'the agents only argue over the pack it assembles.'],
                 [('fetch · deliver', 'blue'), ('python · code gate', 'green'), ('agents · LLM', 'slate'),
                  ('never self-graded', 'warm')], title_lh=34)

    # 01 collect
    y += 34
    d.flow(y - 12)
    d.section(y, '01 · BEFORE OPEN / THE DATA ARRIVES')
    y += 14
    h = 354
    d.card(M, y, CW, h, 'blue')
    d.icon('market', M + 20, y + 14)
    d.text(M + 50, y + 32, 'Your HK + US book wakes up', 'h')
    d.text(M + 20, y + 56, '44 modules · 8 layers · deterministic collection', 'm', fill=MUT)
    xs, cw = columns(3, gap=16, x0=M + 16, w=CW - 32)
    sources = [('market', 'Quotes + FX', 'Tencent/Nasdaq'),
               ('filing', 'SEC · HKEX', 'primary filings'),
               ('bars', 'Capital flow', 'Eastmoney'),
               ('news', 'Bilingual news', 'Google/Finnhub'),
               ('chat', 'Sentiment', 'Reddit · radar'),
               ('calendar', 'Macro + events', 'calendars')]
    for i, (icon, name, source) in enumerate(sources):
        x, yy = xs[i % 3], y + 70 + (i // 3) * 100
        d.add(f'<rect x="{x:g}" y="{yy:g}" width="{cw:g}" height="90" rx="9" '
              f'fill="{TINT["blue"]}"/>')
        d.icon(icon, x + 12, yy + 10, size=24)
        d.text(x + 12, yy + 51, name, 'b')
        d.text(x + 12, yy + 70, source, 'm', fill=MUT)
        fits(name, 'b', cw - 20, 'source tile')
        fits(source, 'm', cw - 20, 'source origin')
    d.lines(M + 20, y + 297, CW - 36,
            ['Ordered quote / FX fallback; one Eastmoney gateway.',
             'An empty fetch keeps the prior value.'], cls='m', lh=19, where='collect note')
    top = y + h
    y = top + 76
    d.down(W / 2, top, y - 36, pulses=(0, 1.1))

    # 02 compute and gate
    d.section(y - 12, '02 · BEFORE THE CALL / FACTORS + GATES')
    blocks = [('Factors + risk', 'PYTHON', [
                  ('reconcile', 1, 'money and FX must balance'),
                  ('portfolio-risk', 1, 'β · volatility · drawdown'),
                  ('concentration', 0, 'HHI + top-2, per leg'),
                  ('regime', 1, 'trend × volatility leverage dial'),
                  ('quant', 1, 'trend, momentum, risk factors'),
                  ('cross-factor', 1, 'sector-neutral ranks'),
                  ('peer-residual', 1, 'move vs curated peers')]),
              ('Gates', 'CODE, NOT PROSE', [
                  ('risk', 1, 'caps + a durable breach ledger'),
                  ('entry-gate', 1, 'a new name, before research'),
                  ('earnings', 1, 'quality from ≥4 periods'),
                  ('thesis', 1, 'moves only on new evidence'),
                  ('news-evidence', 1, 'expiring event graph'),
                  ('adds', 0, 'two independent evidence families')])]
    for i, (name, tag, rows) in enumerate(blocks):
        h = 56 + len(rows) * 22 + (78 if i == 0 else 0)
        d.card(M, y, CW, h, 'green')
        d.icon('factor' if i == 0 else 'gate', M + 20, y + 14, 'green')
        d.text(M + 50, y + 32, name, 'h')
        d.tag(W - M - 16, y + 30, tag, 'green', anchor='end')
        for j, (key, cmd, what) in enumerate(rows):
            yy = y + 60 + j * 22
            if cmd:
                d.text(M + 20, yy, key, 'code', fill=ROLE['green'])
            else:
                d.text(M + 20, yy, key, 'm', fill=MUT)
            fits(key, 'code', 146, 'compute key')
            fits(what, 'm', CW - 36 - 150, 'compute what')
            d.text(M + 170, yy, what, 'm')
        if i == 0:
            d.mini_charts(M + 20, y + h - 62, CW - 40)
            top = y + h
            y = top + 24
    top = y + h
    y = top + 24
    h = 104
    d.card(M, y, CW, h, 'green', tint=True)
    d.icon('shield', M + 20, y + 13, 'green')
    d.text(M + 50, y + 31, [('Backtest gate', INK)], 'b')
    d.tag(W - M - 16, y + 30, 'BEFORE IT COUNTS', 'green', anchor='end')
    d.lines(M + 20, y + 58, CW - 36,
            ['validated authority: bootstrap CI clears 50%',
             'prospective activation ≠ capped exploration'],
            cls='m', lh=24, where='backtest')
    top = y + h
    # preflight is a step in the flow, so it is drawn as one: the connector
    # arrives at a node and the next one leaves from it. As a bare label it sat
    # in the path with a line stopping short above it.
    y = top + 66
    d.add(f'<rect x="92" y="{y - 22:g}" width="{W - 184}" height="36" rx="10" fill="#ffffff" '
          f'stroke="{CARD_STROKE}"/>')
    d.text(W / 2 + 12, y + 2, [('preflight', ROLE['green']), (' → one context pack per run', MUT)],
           'm', anchor='middle')
    fits('preflight → one context pack per run', 'm', W - 184 - 56, 'preflight label')
    d.icon('checks', 106, y - 14, 'green', size=20)
    loop_y = y - 4
    d.down(W / 2, top, y - 22, pulses=(0,), pulse=ROLE['green'])
    top = y + 14
    node = d.at(W / 2, top)
    y = top + 76
    d.turn(W / 2, top, y - 36, first=y - 26, enter=y + 28, leave=(W - 92, loop_y), tail=40,
           pulses=(0, 1.6), pulse=ROLE['slate'])

    # 03 decide
    d.section(y - 12, '03 · YOUR MORNING PLAN / DEBATE')
    h = 510
    d.card(M, y, CW, h, 'slate')
    d.logo('openclaw', M + 16, y + 12, size=30)
    d.text(M + 56, y + 32, 'Swarm debate', 'h')
    d.tag(W - M - 16, y + 30, 'LLM · READ ONLY', 'slate', anchor='end')
    d.text(M + 20, y + 62, 'four analyst lenses', 'm', fill=MUT)
    ix, iw = M + 16, CW - 32
    lx, lw = columns(2, gap=18, x0=ix, w=iw)
    for i, (name, icon) in enumerate(zip(('fundamental', 'technical', 'sentiment', 'sector'),
                                         ('lens', 'factor', 'chat', 'sector'))):
        d.chip(lx[i % 2], y + 74 + (i // 2) * 48, lw, name, icon=icon, h=36)
    ry = y + 172
    d.down(W / 2, ry, ry + 30, pulses=(0,), dur=1.6, pulse=ROLE['slate'])
    bx, bw = columns(2, gap=18, x0=ix, w=iw)
    by = ry + 42
    for x, (name, role, sub) in zip(bx, (('Bull', 'green', 'builds the case for'),
                                         ('Bear', 'warm', 'attacks the consensus'))):
        d.add(f'<rect x="{x:g}" y="{by:g}" width="{bw:g}" height="70" rx="10" fill="{TINT[role]}" '
              f'stroke="{CARD_STROKE}"/>')
        d.text(x + 14, by + 26, [(name, ROLE[role])], 'h')
        d.icon('up' if name == 'Bull' else 'down', x + bw - 36, by + 12, role)
        fits(sub, 'm', bw - 24, 'bull bear')
        d.text(x + 14, by + 50, sub, 'm', fill=MUT)
    d.text(W / 2, by + 94, [('must disagree on at least one position', ROLE['warm'])], 'm', anchor='middle')
    vy = by + 110
    d.down(W / 2, vy, vy + 30, pulses=(.5,), dur=1.6, pulse=ROLE['slate'])
    d.text(M + 20, vy + 56, 'three risk voices', 'm', fill=MUT)
    vx, vw = columns(3, gap=18, x0=ix, w=iw)
    for x, name in zip(vx, ('aggressive', 'conservative', 'neutral')):
        d.add(f'<rect x="{x:g}" y="{vy + 68:g}" width="{vw:g}" height="56" rx="9" fill="{CHIP}" stroke="{CARD_STROKE}"/>')
        d.text(x + vw / 2, vy + 113, name, 'm', anchor='middle')
        d.icon({'aggressive': 'up', 'conservative': 'shield', 'neutral': 'balance'}[name],
               x + vw / 2 - 9, vy + 74, 'slate', size=18)
    jy = vy + 158
    d.icon('judge', M + 20, jy - 17, 'slate', size=22)
    d.text(M + 50, jy, [('Judge', INK), (' names the strategy frame → ', MUT), ('plan.json', ROLE['slate'])],
           'b')
    fits('Judge names the strategy frame → plan.json', 'b', CW - 66, 'judge')
    top = y + h
    y = top + 76
    d.down(W / 2, top, y - 36, pulses=(0, 1.1), pulse=ROLE['green'])

    # 04 deliver
    d.section(y - 12, '04 · THROUGH THE SESSION / REACH YOUR PHONE')
    h = 118
    d.card(M, y, CW, h, 'green')
    d.icon('shield', M + 20, y + 14, 'green')
    d.text(M + 50, y + 32, 'Postflight', 'h')
    d.tag(W - M - 16, y + 30, 'PYTHON', 'green', anchor='end')
    d.lines(M + 20, y + 58, CW - 36, [[('validates plan.json, books it in ', INK)],
                                      [('memory/decisions.jsonl', ROLE['green']), (', renders the card', INK)]],
            lh=21, where='postflight')
    top = y + h
    y = top + 56
    xs, cw = columns(3, gap=18)
    outs = [('Brief card', ['report + card,', 'laid out by', 'code']),
            ('Your phone', ['WeChat +', 'Telegram;', 'watchdog checks']),
            ('Dashboard', ['data-plane', 'branch, polled', 'every 60 s'])]
    h = 160
    for i, (x, (name, body)) in enumerate(zip(xs, outs)):
        d.curve(W / 2, top, x + cw / 2, y, pulses=(i * .5,), dur=1.8)
        d.card(x, y, cw, h, 'blue')
        d.text(x + 16, y + 30, name, 'h')
        d.lines(x + 16, y + 57, cw - 24, body, cls='m', lh=21, where='deliver')
        if i == 0:
            d.icon('filing', x + 16, y + 118, size=26)
        elif i == 1:
            d.icon('chat', x + 16, y + 118, size=26)
            d.icon('plane', x + 52, y + 118, size=26)
        else:
            d.icon('dashboard', x + 16, y + 118, size=26)
    top = y + h
    y = top + 76
    d.down(W / 2, top, y - 36, pulses=(0, 1.1), pulse=ROLE['green'])

    # 05 settle and calibrate
    d.section(y - 12, '05 · AFTER THE SESSION / GRADE THE CALL')
    h = 284
    d.card(M, y, CW, h, 'green')
    d.icon('dashboard', M + 20, y + 14, 'green')
    d.text(M + 50, y + 32, 'Graded by code', 'h')
    d.tag(M + 20, y + 61, 'THE MODEL NEVER SCORES', 'warm')
    rows = [('mark-followed', 'what was actually executed'),
            ('settle', 'canonical bars, per episode'),
            ('calibrate', 'beta-binomial, earlier dates only'),
            ('shadow', 'followed calls vs buy-and-hold'),
            ('scorecard', 'public, losses included')]
    sweep(d, M + 12, y + 78, CW - 24, len(rows), lh=28)
    for i, (cmd, what) in enumerate(rows):
        yy = y + 97 + i * 28
        d.icon({'mark-followed': 'checks', 'settle': 'balance', 'calibrate': 'factor',
                'shadow': 'replay', 'scorecard': 'dashboard'}[cmd], M + 20, yy - 15, 'green', size=18)
        d.text(M + 46, yy, cmd, 'code', fill=ROLE['green'])
        fits(what, 'm', CW - 36 - 160, 'settle what')
        d.text(M + 180, yy, what, 'm')
    d.add(f'<path d="M{M + 20:g} {y + 238:g}H{W - M - 16:g}" stroke="{CARD_STROKE}"/>')
    d.text(M + 20, y + 264, [('↺ ', ROLE['blue']), ('tomorrow’s brief reads the record', MUT)], 'm')
    fits('↺ tomorrow’s brief reads the record', 'm', CW - 36, 'loop note')
    # the loop: the settled record returns to the next run's preflight
    if d.wide:
        # Across to the first column, under everything it draws, and up into
        # the preflight node from below.
        x1, y1 = d.at(M, y + 256)
        y1 = max(y1, node[1] + 22)
        d.page_wire(f'M{x1:g} {y1:g}H{node[0] + 8:g}Q{node[0]:g} {y1:g} {node[0]:g} {y1 - 8:g}V{node[1] + 4:g}',
                    pulses=(0,), dur=4.5, dash=True, color='#9fc0da')
        d.bottoms.append(y1 + 4)
    else:
        gx = W - 11
        d.wire(f'M{W - M:g} {y + 256:g}H{gx:g}V{loop_y:g}H{W - 92 + 8:g}',
               pulses=(0,), dur=4.5, dash=True, color='#9fc0da')
    # dsh is the interactive view of the same real fills, not an execution engine.
    top = y + h
    y = top + 76
    d.down(W / 2, top, y - 36, pulses=(0,), pulse=ROLE['violet'])
    d.section(y - 12, '06 · BACK AT YOUR DESK / ASK WHY')
    h = 138
    d.card(M, y, CW, h, 'violet')
    d.logo('deepseek-harness', M + 20, y + 16, size=36)
    d.text(M + 70, y + 38, 'dsh · Decision Mind', 'h')
    d.lines(M + 20, y + 71, CW - 40,
            ['Open a real fill: plan → execution → T+1 → P&L.',
             'Ask a follow-up in chat; record the new verdict.',
             'The trace stays read-only. You place the orders.'], cls='m', where='dsh loop')
    return d.render(y + h + M)


LAYOUTS = {
    'decision-pipeline': decision_pipeline,
    'harnesses': harnesses,
    'information-flow': information_flow,
    'architecture': architecture,
    'product-architecture': product_architecture,
    'debate-flow': debate_flow,
}
#: Every file this builder owns: the wide layout under the diagram's name, the
#: single column beside it. A `partial` keeps `build()` the whole interface.
DIAGRAMS = {
    f'{name}{suffix}.svg': partial(draw, wide=wide)
    for name, draw in LAYOUTS.items()
    for suffix, wide in (('', True), ('-narrow', False))
}


def main(argv):
    rendered = {name: build() for name, build in DIAGRAMS.items()}
    if WARN:
        print('\n'.join(WARN), file=sys.stderr)
        return 1
    stale = [n for n, svg in rendered.items()
             if not (ASSETS / n).exists() or (ASSETS / n).read_text(encoding='utf-8') != svg]
    if '--check' in argv:
        for n in stale:
            print(f'site/assets/{n} differs from its builder', file=sys.stderr)
        return 1 if stale else 0
    for n in stale:
        (ASSETS / n).write_text(rendered[n], encoding='utf-8')
        print(f'wrote site/assets/{n}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
