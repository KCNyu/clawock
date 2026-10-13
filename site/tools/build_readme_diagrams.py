"""Build the README diagrams in site/assets/ as one visual system.

    python3 site/tools/build_readme_diagrams.py            # rewrite the SVGs
    python3 site/tools/build_readme_diagrams.py --check    # exit 1 if any differs

The system: a pearl canvas washed with four soft colour fields, translucent
glass cards with a thin role-coloured accent bar, system sans type on a fixed
scale, graphite ink with blue kept for data and dispatch flow, green for code
gates and warm red for isolation / arbitration.

Every diagram is one composition, served at every width: the README's `<img>`
scales the same file down for a phone, so the picture a desktop reader sees is the
picture a phone reader sees. Every diagram uses the 1016-unit canvas and the one
five-step type scale in `TYPE`; none redeclares a size, so a label class is the
same size in every figure. Detailed desk flows read down two 472-unit columns. The
overview is a tall poster of nine panels: tile grid, logo rail, versus split,
limit bars beside a breach track, verdict tiles, two return loops through one
record, and the maintenance loop around the dsh panel. Shared primitives draw the
material; each diagram owns the arrangement that best explains its content.

Drawing rules for the plugin figures
------------------------------------
`strategy-plugins`, `strategy-evolution`, `proposal-review`,
`feedback-learning`, `product-architecture`, `debate-flow` and
`information-flow` are drawn to the rules below, and
`tests/test_readme_diagrams.py` checks the countable ones (`RULE_BOUND`).
`rsi-loop`, `architecture`, `decision-pipeline` and `harnesses` are still the
older card-and-column drawings and are not held to them yet.

Before the rules: say what the one thing is that a figure shows and the text
beside it argues, and draw that. `strategy-plugins` is one real call across
the line between rows and what is not a row; `feedback-learning` is the same
call on its calendar; `debate-flow` is its two cases either side of the
evidence both cite; `product-architecture` is two owners and the three files
that cross between them; `information-flow` is a grid of what each run is
handed. No two of them share a skeleton.
They come from three references: hierarchy is built from size, weight and
leading together, emphasis is weight and not a second face, and nothing is
random (Apple, typography and craft); every element earns its place, and good
defaults beat options (Kowalski); and a surface seen tens of times a day has
its motion removed or drastically reduced, with "it looks cool" not a purpose
(the animation frequency table).

Layout
  L1  One idea per figure, at most four blocks, read top-left to bottom-right.
  L2  Left edges sit on the grid: 24 and 520 for halves, 24 / 352 / 680 for
      thirds, and a block's text at its edge + 20. No free-floating notes.
  L3  Gaps come from one set: 8, 12, 16, 24, 32, 48. Blocks are 24 apart,
      bands 48.
  L4  Text is left-aligned. It is centred only inside a symmetric mark (a
      pill, a disc, a cell) or under one. It is set towards its mark, and so
      ends at it, only for the labels on the left half of a ring.
  L5  Marks of one kind share one size and one distance to their label.
Type
  T1  Four roles: heading 18/700, body 15/450, caption 13/500, kicker 12/700
      capitals. A label is body; what explains it is a caption.
  T2  One family. No monospace.
  T3  Two inks, graphite and muted. A role colour on text only for a verdict.
Colour and material
  C1  At most three role colours in a figure, each with one meaning there.
  C2  Hierarchy never comes from transparency: marks are solid tints and
      solid strokes. Only the shared glass pane is translucent.
  C3  Two stroke weights: 1.5 for lines and axes, 2.5 for the thing measured.
  C4  One material. A pane of glass is the only surface with a sheen and a
      shadow; discs, cells and pills are flat.
Motion
  M1  One moving packet per figure, on the connector the figure is about.
      Everything else is still. No breathing, no sweeps.
Forms
  F1  A shape other than a pane is used where it is the data: a ring for
      rows mounted on one kernel, a grid for a searched grid, an axis for a
      threshold, an interval or a run of sessions.
  F2  One axis style, one dot, one interval, one pill, in all three figures.

A connector says what it carries. `KIND` gives each of eight kinds of flow its
own line, arrowhead and packet: evidence is a solid line with a page running along
it, an LLM judgment is dashed, a code gate ends on a bar, a task is a string of
beads, money runs on a double rail. The line and arrowhead carry the meaning on
their own; the packet is the moving part.

Motion is SMIL <animateMotion> packets along the connectors plus a few CSS
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
import math
import re
import struct
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ASSETS = Path(__file__).resolve().parents[1] / 'assets'
W, M = 520, 24          # one column's width, outer margin
CW = W - 2 * M          # content width of a column
GUTTER = 24             # between the two columns
COL2 = CW + GUTTER      # x offset of the second column
WIDE = W + COL2         # canvas width

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
    'kick': (12, 700, .74), 'title': (26, 750, .55), 'sub': (15, 450, .53),
    'h': (18, 700, .55), 'b': (15, 450, .53), 'm': (15, 450, .53),
    'code': (13, 500, .62), 'tag': (12, 700, .78),
    # Secondary text in the rule-bound figures below: one clear step under body.
    'c': (13, 500, .56),
}
GOLD = '#a8791c'          # money on a connector; no card or label takes it
WARN = []

# What a connector carries: (ink, line, dash, line cap, line width, arrowhead, packet).
# `money` is a real fill on its way to settlement, or the same fills shown back;
# a call being scored, a verdict and a record coming back are not money.
# The packet is what a connector of that kind carries when its call names
# nothing more specific; `wire(carry=)` names the payload of one edge instead.
# These eight glyphs are Lucide icons (ISC, see NOTICE), 24-unit outlines; the
# first shape of a closed glyph is filled so the line does not show through it.
KIND = {
    'data': (ROLE['blue'], '#8fb6d4', None, None, 1.5, 'open', 'file-text'),
    'decision': (ROLE['slate'], '#9aabb9', '7 4', None, 1.5, 'open', 'scale'),
    'gate': (ROLE['green'], '#7dbda4', None, None, 1.5, 'bar', 'shield-check'),
    'task': (ROLE['slate'], '#9aabb9', '.1 5', 'round', 2.6, 'solid', 'clipboard-check'),
    'money': (GOLD, '#cfb378', None, None, 4.4, 'double', 'circle-dollar-sign'),
    'deliver': (ROLE['blue'], '#8fb6d4', None, None, 1.5, 'solid', 'send'),
    'feedback': (ROLE['violet'], '#aaa3cf', '9 3 1.5 3', None, 1.5, 'open', 'rotate-ccw'),
    'alert': (ROLE['warm'], '#d9a19b', '3 5', None, 1.5, 'open', 'triangle-alert'),
}
DISC = '<circle fill="#fff" stroke-width="1.5" cx="12" cy="12" r="14"/>'    # open glyphs ride on one
GLYPH = {
    'file-text': '<path fill="#fff" d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588'
                 'A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/><path d="M14 2v5a1 1 0 0 0 1 1h5M10 9H8M16 13H8M16 17H8"/>',
    'shield-check': '<path fill="#fff" d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6'
                    'a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>'
                    '<path d="m9 12 2 2 4-4"/>',
    'clipboard-check': '<path fill="#fff" d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>'
                       '<rect fill="#fff" width="8" height="4" x="8" y="2" rx="1"/><path d="m9 14 2 2 4-4"/>',
    'circle-dollar-sign': '<circle fill="#fff" cx="12" cy="12" r="10"/>'
                          '<path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8M12 18V6"/>',
    'send': '<path fill="#fff" d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5'
            'a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/><path d="m21.854 2.147-10.94 10.939"/>',
    'triangle-alert': '<path fill="#fff" d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/>'
                      '<path d="M12 9v4M12 17h.01"/>',
    'scale': DISC + '<path d="M12 3v18M19 8l3 8a5 5 0 0 1-6 0zV7'
             'M3 7h1a17 17 0 0 0 8-2 17 17 0 0 0 8 2h1M5 8l3 8a5 5 0 0 1-6 0zV7M7 21h10"/>',
    'rotate-ccw': DISC +
                  '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8M3 3v5h5"/>',
}
# Node glyphs: original outlines drawn for clawock (MIT), not provider logos.
ICON = {
    'lens': '<circle cx="10" cy="10" r="6"/><path d="M14 14l7 7M7 10h6m-3-3v6"/>',
    'sector': '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    'balance': '<path d="M12 3v17M5 21h14M4 7h16M6 7l-4 7h8Zm12 0-4 7h8Z"/>',
    'judge': '<path d="M8 4l5-2 5 10-5 2ZM11 10l-6 9M12 21h9"/>',
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
    'seal': '<circle cx="12" cy="9" r="6"/><path d="M9.5 9l2 2 3-4M8.5 14L7 22l5-3 5 3-1.5-8"/>',
    'ci': '<circle cx="5" cy="5" r="2"/><circle cx="5" cy="19" r="2"/><path d="M5 7v10M9 5h6a3 3 0 0 1 3 3v2M13 17l3 3 6-7"/>',
    'followed': '<circle cx="9" cy="7" r="4"/><path d="M2 21v-2a5 5 0 0 1 5-5h4a5 5 0 0 1 3 1M15 19l2 2 5-5"/>',
    'receipt': '<path d="M5 3v18l2.5-2 2.5 2 2-2 2 2 2.5-2 2.5 2V3ZM9 8h6M9 12h6"/>',
    'even': '<circle cx="12" cy="12" r="9"/><path d="M8 10h8M8 14h8"/>',
    # What a source stack, a price bar, the call record and the context pack look like.
    'layers': '<path d="M12 2l9 5-9 5-9-5ZM3 12l9 5 9-5M3 17l9 5 9-5"/>',
    'candles': '<path d="M7 2v4M7 16v5M4 6h6v10H4ZM17 4v5M17 15v4M14 9h6v6h-6Z"/>',
    'record': '<path d="M3 4h18v5H3ZM5 9v11h14V9M10 13h4"/>',
    'pack': '<path d="M12 2l9 5v10l-9 5-9-5V7ZM3 7l9 5 9-5M12 12v10"/>',
    'eight': '<path d="M12 12C9.5 8.5 8 7 6.5 7a5 5 0 0 0 0 10c1.5 0 3-1.5 5.5-5s4-5 5.5-5a5 5 0 0 1 0 10c-1.5 0-3-1.5-5.5-5Z"/>',
    'cycle': '<path d="M4 11a8 8 0 0 1 14-4l2 2M20 4v5h-5M20 13a8 8 0 0 1-14 4l-2-2M4 20v-5h5"/>',
    'closed': '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
    'sunrise': '<path d="M2 18h20M6 18a6 6 0 0 1 12 0M12 5v3M4.5 9.5l2 2M19.5 9.5l-2 2M8 22h8"/>',
    'clipboard': '<path d="M9 2h6v4H9ZM15 4h3v18H6V4h3M9 11h6M9 15h4"/>',
    'pulse': '<path d="M2 12h4l3-7 4 14 3-7h6"/>',
    'scan': '<path d="M3 8V5a2 2 0 0 1 2-2h3M16 3h3a2 2 0 0 1 2 2v3M21 16v3a2 2 0 0 1-2 2h-3M8 21H5a2 2 0 0 1-2-2v-3M7 12h10"/>',
    'gear': '<circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="7"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.2 2.2M16.9 16.9l2.2 2.2M4.9 19.1l2.2-2.2M16.9 7.1l2.2-2.2"/>',
    'alarm': '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2M5 3L2 6M19 3l3 3"/>',
    'twin': '<circle cx="9" cy="12" r="6"/><circle cx="15" cy="12" r="6"/>',
    'review': '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
}
# Arrowheads, 10 units tall, tip half a unit past the reference point that sits
# on the connector's end: (path, filled, reference x).
HEAD = {
    'open': ('M1 1.5L6.5 5L1 8.5', False, 6),
    'solid': ('M1 1.5L6.5 5L1 8.5Z', True, 6),
    'bar': ('M1 1.5V8.5M4.5 1.5L10 5L4.5 8.5', False, 9.5),
    # One chevron closing over both rails, as in "⇒": the rails end inside it.
    'double': ('M3 1.5L9 5L3 8.5', False, 5),
}
RAIL_REACH = 3.5          # the rails stop this far short, so the chevron's tip lands where other heads do
MOTION = ('<animateMotion dur="{dur}s" begin="{begin:.2f}s" repeatCount="indefinite" keyPoints="{k}" '
          'keyTimes="0;1" calcMode="spline" keySplines=".45 0 .55 1">'
          '<mpath href="#{pid}" xlink:href="#{pid}"/></animateMotion>')
PACKET_R = 8              # half the widest packet: what it needs clear on either side
PACKET_RUN = 40           # a connector shorter than this carries a plain dot instead


def path_points(d, step=3.0):
    """Points along a connector: the builder writes M, H, V, L, C and Q, all absolute."""
    out, x, y = [], 0.0, 0.0
    for cmd, args in re.findall(r'([MHVLCQ])([^MHVLCQ]*)', d):
        n = [float(v) for v in re.findall(r'-?\d*\.?\d+', args)]
        if cmd == 'M':
            x, y = n
            out.append((x, y))
            continue
        ctrl = {'H': [(n[0], y)], 'V': [(x, n[0])]}.get(cmd) or list(zip(n[::2], n[1::2]))
        pts = [(x, y)] + ctrl
        steps = max(2, int(sum(math.dist(a, b) for a, b in zip(pts, pts[1:])) / step))
        for i in range(1, steps + 1):
            level = pts
            while len(level) > 1:      # de Casteljau: a line, a quadratic or a cubic alike
                level = [(a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps)
                         for a, b in zip(level, level[1:])]
            out.append(level[0])
        x, y = ctrl[-1]
    return out


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

    def __init__(self, title, desc, wide=True):
        # `wide=False` is the 520-unit single column. No diagram here uses it;
        # build_readme_book_charts.py still draws the hero's phone card on it.
        self.title, self.desc, self.wide = title, desc, wide
        self.pw = WIDE if wide else W          # page width
        self.parts, self.n, self.h = [], 0, 0
        self.kinds, self.packets = {}, {}      # connector kinds drawn, and those with a packet
        # Column flows draw in column coordinates and each run of them is a
        # group translated into place. `dx, dy` is the current group's
        # offset; `bottoms` collects where each closed group ended on the page.
        self.dx = self.dy = 0
        self.group, self.bottoms = None, []

    def add(self, s):
        (self.parts if self.group is None else self.group).append(s)

    # --- column flow -------------------------------------------------------
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
        self.group = []

    def place(self, col, first, page_y, bottom):
        """Continue in column `col`, with column-y `first` at `page_y`.

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

    def turn(self, x, top, *, first, enter, reach=M, leave=None, tail=26, **kw):
        """The connector from the foot of the first column into the second.

        The first column ends at `top`; the flow leaves it, runs up the gutter
        and enters the second column from the left at column-y `enter`, stopping
        at column-x `reach`. `first` is the column-y that lines up with the top
        of the first column, `leave` an exit point on a node's right edge
        instead of straight down, and `tail` how far below `top` the first
        column still draws.
        """
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
        title, sub = [' '.join(title)], [' '.join(sub)]     # one line each
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
        self.header_bottom = y + 20
        return y + 20

    def section(self, y, label, x=M):
        self.text(x, y, label, 'kick', fill=FAINT)

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

        One glyph per role, the same in every diagram: `checks` is code checking
        an output against its rules, `seal` a context certified before the model
        reads it, `balance` settling or grading a call, `even` the neutral voice,
        `followed` what the human executed, `ci` required CI, `receipt` a
        delivery receipt, `shield` risk. A glyph that had come to stand for two
        things was split: `market` is quotes and `layers` the source stack,
        `candles` canonical daily bars; `book` is the portfolio, `record` the
        kept calls and their history, `pack` the context pack; `filing` is a
        regulatory filing, `sunrise` the pre-open brief, `clipboard` a task's
        brief; `chat` is a chat channel and `pulse` sentiment; `clock` a
        schedule and `alarm` the watchdog; `lens` is research and `scan` the
        patrol; `replay` is a backtest, `cycle` a daily loop, `eight` the two
        loops round the record, `closed` a closed issue.
        """
        self.add(f'<g class="hero-icon" data-icon="{name}" transform="translate({x:g} {y:g}) scale({size / 24:g})" '
                 f'fill="none" stroke="{ROLE[role]}" stroke-width="1.7" stroke-linecap="round" '
                 f'stroke-linejoin="round" aria-hidden="true">{ICON[name]}</g>')

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
    def wire(self, d, pulses=(0,), dur=2.2, arrow=True, kind='data', packet=True, inset=None, carry=None):
        """A connector of one `KIND`, with a packet of that kind running along it.

        `carry` names what this edge moves when that is more specific than its
        kind: a `GLYPH` or a node `ICON`, or one per pulse. The line and the
        arrowhead still say the kind; the packet says the payload.

        A packet stays in the open run between the two nodes and fades at either
        end, so it never rides over a card: it starts once it stands clear of the
        edge it left, measured along the direction the connector leaves in, and
        stops clear of the arrowhead. `inset` is that distance along the path for
        a connector that leaves along its node's edge instead of away from it. A
        run too short for a packet carries the plain dot, as does `packet=False`.
        """
        ink, line, dash, cap, sw, head, _ = KIND[kind]
        self.n += 1
        self.kinds[kind] = True
        pid = f'w{self.n}'
        mk = f' marker-end="url(#arr-{kind})"' if arrow else ''
        look = ((f' stroke-dasharray="{dash}"' if dash else '')
                + (f' stroke-linecap="{cap}"' if cap else ''))
        rail = kind == 'money'
        if rail and arrow:             # the tip, not the rails' end, lands on the node
            cmd, end = re.fullmatch(r'.*([HV])(-?[\d.]+)', d).groups()
            (x0, y0), (x1, y1) = path_points(d)[-2:]
            back = RAIL_REACH * (1 if (x1 - x0) + (y1 - y0) < 0 else -1)
            d = f'{d[:-len(end)]}{float(end) + back:g}'
        self.add(f'<path id="{pid}" data-kind="{kind}" d="{d}" fill="none" stroke="{line}" '
                 f'stroke-width="{sw:g}"{look}{"" if rail else mk}/>')
        if rail:                       # the same run again, hollowing the stroke into two rails
            self.add(f'<path d="{d}" fill="none" stroke="#ffffff" stroke-opacity=".92" stroke-width="1.8"{mk}/>')
        pts = path_points(d)
        at = [0.0]
        for p, q in zip(pts, pts[1:]):
            at.append(at[-1] + math.dist(p, q))
        run = at[-1]
        if run < PACKET_RUN or not packet:
            return self._dots(pid, kind, pulses, dur)
        # Clear of the node it leaves and of the arrowhead it runs into.
        ends = []
        for seq, need in ((list(zip(pts, at)), PACKET_R + 2),
                          ([(q, run - a) for q, a in zip(pts[::-1], at[::-1])], PACKET_R + (8 if arrow else 2))):
            (ox, oy), (nx, ny) = seq[0][0], seq[1][0]
            step = math.dist((ox, oy), (nx, ny))
            ends.append(inset or next((a for (x, y), a in seq
                                       if ((x - ox) * (nx - ox) + (y - oy) * (ny - oy)) / step >= need), run))
        if ends[0] + ends[1] > run - 4:            # nowhere to run once both ends are clear
            return self._dots(pid, kind, pulses, dur)
        k = f'{ends[0] / run:.3f};{1 - ends[1] / run:.3f}'
        fade = ('<animate attributeName="opacity" values="0;1;1;0" keyTimes="0;.14;.86;1" '
                'dur="{dur}s" begin="{begin:.2f}s" repeatCount="indefinite"/>')
        carried = (carry,) if isinstance(carry, (str, type(None))) else carry
        for i, b in enumerate(pulses[:max(1, int(run // 64))]):
            glyph = carried[i % len(carried)] or KIND[kind][6]
            ref = f'pk-{kind}' + ('' if glyph == KIND[kind][6] else f'-{glyph}')
            self.packets[ref] = (kind, glyph)
            self.add(f'<use class="pulse" href="#{ref}" xlink:href="#{ref}">'
                     + (MOTION + fade).format(dur=dur, begin=-b, k=k, pid=pid) + '</use>')

    def _dots(self, pid, kind, pulses, dur):
        for b in pulses:
            self.add(f'<g class="pulse"><circle r="7" fill="url(#glow-{kind})"/>'
                     f'<circle r="3.4" fill="{KIND[kind][0]}"/>'
                     + MOTION.format(dur=dur, begin=-b, k='0;1', pid=pid) + '</g>')

    def down(self, x, y1, y2, **kw):
        self.wire(f'M{x:g} {y1:g}V{y2 - 2:g}', **kw)

    def curve(self, x1, y1, x2, y2, **kw):
        ym = (y1 + y2) / 2
        # Like down(): the arrowhead lands on the node it points at, not short of it.
        self.wire(f'M{x1:g} {y1:g}C{x1:g} {ym:g} {x2:g} {ym:g} {x2:g} {y2 - 2:g}', **kw)

    def _kind_defs(self, kind):
        """The halo, arrowhead and packet one kind of connector refers to."""
        ink, line, _, _, _, head, _ = KIND[kind]
        path, filled, ref = HEAD[head]
        out = (f'<radialGradient id="glow-{kind}"><stop offset=".4" stop-color="{ink}" stop-opacity=".36"/>'
               f'<stop offset=".72" stop-color="{ink}" stop-opacity=".14"/>'
               f'<stop offset="1" stop-color="{ink}" stop-opacity="0"/></radialGradient>'
               f'<marker id="arr-{kind}" markerWidth="12" markerHeight="10" refX="{ref:g}" refY="5" orient="auto" '
               f'markerUnits="userSpaceOnUse"><path d="{path}" fill="{line if filled else "none"}" stroke="{line}" '
               f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></marker>')
        for ref, (owner, glyph) in self.packets.items():
            if owner != kind:
                continue
            # A closed glyph is drawn 15 units across; an open one 13, on a 16-unit disc.
            shape = GLYPH.get(glyph) or DISC + ICON[glyph]
            scale = .56 if DISC in shape else .64
            out += (f'<g id="{ref}"><circle r="12" fill="url(#glow-{kind})"/>'
                    f'<g class="pk" transform="scale({scale}) translate(-12 -12)" stroke="{ink}">{shape}</g></g>')
        return out

    def render(self, h):
        style = (
            f'text{{font-family:{SANS}}}'
            + ''.join(f'.{k}{{font-size:{s}px;font-weight:{w}}}' for k, (s, w, _) in TYPE.items())
            + '.kick{letter-spacing:1.1px}.title{letter-spacing:-.5px}.h{letter-spacing:-.2px}'
            '.tag{letter-spacing:.9px}'
            '.pk{fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}'
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
        body = '\n'.join(self.parts)
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
                    for role, tint in TINT.items() if f'url(#glass-{role})' in body)
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
                          for role, color in ROLE.items() if f'url(#glow-{role})' in body)
                + f'<marker id="arr" markerWidth="10" markerHeight="10" refX="6" refY="5" orient="auto" '
                f'markerUnits="userSpaceOnUse"><path d="M1 1.5L6.5 5L1 8.5" fill="none" stroke="{LINE}" '
                f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></marker>'
                + ''.join(self._kind_defs(kind) for kind in KIND if kind in self.kinds)
                + f'<style>{style}</style></defs>\n'
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
def harnesses():
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
          'image is an existing full-frame capture from a live host, not an example result.')
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
    d.down(W / 2, top, y - 38, pulses=(0, 1.1), kind='task')
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
        d.curve(W / 2, top, x + cw / 2, y, pulses=(i * .6,), kind='task')
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
        d.curve(x + cw / 2, top, W / 2, y - 38, pulses=(i * .6,), kind='task', carry='branch')

    # The panel watches the work while it runs, so it stands beside the story
    # instead of interrupting it.
    merge = d.at(W / 2, y - 38)[1]
    side = d.at(W - M, runner)
    d.place(1, y - 26, d.top, y - 38)
    d.page_wire(f'M{side[0]:g} {side[1]:g}H{COL2 + M - 2:g}', pulses=(.3,), dur=1.4, kind='data')
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
        ('gate', 'Set its budgets', ['Deadline, retries', 'and quota resumes.'], 'warm'),
        ('clipboard', 'Open the brief', ['Read the task and', 'appended instructions.'], 'slate'),
        ('receipt', 'See the receipts', ['Report status and', 'notification delivery', 'shown separately.'], 'green'),
    ]
    for i, (icon, title, rows, role) in enumerate(facts):
        yy = y + 68 + i * 112
        d.icon(icon, tx, yy, role, size=24)
        d.text(tx, yy + 42, title, 'b')
        fits(title, 'b', room, 'queue title')
        d.lines(tx, yy + 61, room, rows, cls='m', lh=18, where='queue detail')
    d.text(M + 20, y + h - 20, 'Existing screenshot · open the full-size capture below', 'm', fill=MUT)
    top = y + h
    y = top + 76
    d.place(0, y - 26, merge + 12, top)

    d.section(y - 12, '04 · THE REPO TASK SHIPS WHAT YOU REQUESTED')
    h = 138
    d.card(M, y, CW, h, 'green')
    xs, cw = columns(3, gap=18, x0=M + 16, w=CW - 32)
    for i, (x, (icon, name, sub)) in enumerate(zip(xs, (
            ('branch', 'Branch + PR', 'own worktree'),
            ('ci', 'Required CI', 'all gates pass'),
            ('commit', 'Squash merge', 'review the diff')))):
        d.icon(icon, x + cw / 2 - 16, y + 18, 'green', size=32)
        d.text(x + cw / 2, y + 77, name, 'b', anchor='middle')
        d.text(x + cw / 2, y + 100, sub, 'm', anchor='middle', fill=MUT)
        fits(name, 'b', cw, 'repo step')
        fits(sub, 'm', cw, 'repo sub')
        if i:
            d.wire(f'M{x - 16:g} {y + 34:g}H{x - 3:g}', pulses=(i * .4,), dur=1.2, kind='gate')
    top = y + h
    y = top + 54
    d.down(W / 2, top, y, pulses=(0,), kind='gate')
    h = 92
    d.card(M, y, CW, h, 'green', tint=True)
    d.logo('clawock', M + 20, y + 18, size=40)
    d.text(M + 74, y + 38, 'Merged → live on your host', 'h')
    d.text(M + 74, y + 63, 'refresh_live.sh applies the checked change', 'm', fill=MUT)
    fits('refresh_live.sh applies the checked change', 'm', CW - 94, 'live')
    top = y + h
    y = top + 76
    d.down(W / 2, top, y - 38, pulses=(0, 1.1), kind='deliver')

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
def architecture():
    """site/assets/architecture.svg — the KCNyu live desk: argue, gate, publish, settle, loop."""
    d = D('KCNyu live investment instance built with clawock contracts',
          'This is the KCNyu deployment, not the reusable clawock product architecture. Python '
          'assembles one immutable evidence pack. OpenClaw agents run four analyst lenses, a bull '
          'case, a bear case and three risk voices, and a judge names the strategy frame and writes '
          'plan.json. A Python decision contract validates plan.json and the brief sections, and '
          'flags any risk breach the plan ignores, before the ledger, brief and dashboard publish '
          'it. On the return path code triggers each call against canonical unadjusted daily bars, '
          'groups repeated calls into episodes, grades them against a directional baseline and '
          'publishes the scorecard, which feeds the next brief.')
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
    d.icon('pack', M + 20, y + 14, 'green')
    d.text(M + 50, y + 32, 'Evidence pack', 'h')
    d.tag(M + IW - 16, y + 30, 'PYTHON', 'green', anchor='end')
    d.text(M + 20, y + 54, [('context.json', INK), (' — reconciled, immutable', MUT)], 'm')
    xs, cw = columns(4, gap=6, x0=M + 16, w=IW - 32)
    for x, label in zip(xs, ('book', 'market', 'risk', 'events')):
        d.chip(x, y + 72, cw, label)
    top = y + h
    y = top + 44
    d.section(y - 12, '02 · DECISION ROOM')
    d.down(M + IW / 2, top, y, pulses=(0,), kind='data', carry='pack')
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
        d.curve(M + IW / 2, top, x + cw / 2, y, pulses=(i * .5,), dur=1.8, kind='decision',
                carry=('up', 'down', 'shield')[i])
        d.card(x, y, cw, h, role)
        fits(name, 'h', cw - 24, 'fork')
        d.icon({'Bull case': 'up', 'Bear case': 'down', 'Risk voices': 'shield'}[name], x + 16, y + 14, role)
        d.text(x + 16, y + 64, name, 'h')
        d.text(x + 16, y + 88, body, 'm', fill=MUT)
    top = y + h
    y = top + 48
    for i, x in enumerate(xs):
        d.curve(x + cw / 2, top, M + IW / 2, y, pulses=(i * .5 + .3,), dur=1.8, kind='decision',
                carry=('up', 'down', 'shield')[i])
    h = 96
    d.card(M, y, IW, h, 'slate')
    d.icon('judge', M + 20, y + 14, 'slate')
    d.text(M + 50, y + 32, 'Judge', 'h')
    d.tag(M + IW - 16, y + 30, 'LLM', 'slate', anchor='end')
    d.lines(M + 20, y + 58, IW - 36, ['Names the strategy frame of each call:',
                                      [('action · trigger · confidence → plan.json', MUT)]], lh=21, where='judge')
    top = y + h
    y = top + 50
    d.turn(M + IW / 2, top, first=y - 26, enter=y + 28, pulses=(0, 1.6), kind='decision')
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
    pubs = [('Ledger', 'every call'), ('Brief', 'the chat card'), ('Dashboard', 'data-plane')]
    h = 106
    for i, (x, (name, body)) in enumerate(zip(xs, pubs)):
        d.curve(M + IW / 2, top, x + cw / 2, y, pulses=(i * .5,), dur=1.8, kind='deliver',
                carry=('record', 'sunrise', 'dashboard')[i])
        d.card(x, y, cw, h, 'blue')
        d.icon(('record', 'sunrise', 'dashboard')[i], x + 16, y + 12)
        d.text(x + 16, y + 60, name, 'h')
        fits(body, 'm', cw - 20, 'pub')
        d.text(x + 12, y + 84, body, 'm', fill=MUT)
    top = y + h
    y = top + 48
    d.text(xs[0] + cw / 2 + 14, y - 14, '04 · SETTLE IN THE OPEN', 'kick', fill=FAINT)
    d.down(xs[0] + cw / 2, top, y, pulses=(0,), kind='data', carry='record')
    steps = [('Record', 'the model submits; it never grades itself'),
             ('Trigger', 'canonical unadjusted daily bars, per market'),
             ('Group', 'repeat calls of one strategy = one episode'),
             ('Grade', 'code scores it against a directional baseline'),
             ('Public scorecard', 'ungradeable calls stay visible in coverage')]
    h = 30 + len(steps) * 46
    d.card(M, y, IW, h, 'blue')
    for i, (name, body) in enumerate(steps):
        yy = y + 34 + i * 46
        d.icon(('record', 'candles', 'sector', 'balance', 'dashboard')[i], M + 20, yy - 16, size=20)
        d.text(M + 52, yy, name, 'b')
        fits(body, 'm', IW - 70, 'settle')
        d.text(M + 52, yy + 20, body, 'm', fill=MUT)
        if i:
            d.add(f'<path d="M{M + 30:g} {yy - 30:g}V{yy - 18:g}" stroke="{LINE}" stroke-width="1.5"/>')
    bottom = y + h
    # the loop: the scorecard feeds the next brief's evidence
    # Up the second column's rail, over both columns, down the first one's.
    x1, yb = d.at(M + IW, bottom - 30)
    r1, over = d.at(RAIL, 0)[0], d.top - 12
    d.page_wire(f'M{x1:g} {yb:g}H{r1 - 8:g}Q{r1:g} {yb:g} {r1:g} {yb - 8:g}V{over + 8:g}'
                f'Q{r1:g} {over:g} {r1 - 8:g} {over:g}H{RAIL + 8:g}Q{RAIL:g} {over:g} {RAIL:g} {over + 8:g}'
                f'V{ey + 24:g}Q{RAIL:g} {ey + 32:g} {RAIL - 8:g} {ey + 32:g}H{M + IW + 4:g}',
                pulses=(0, 3.5), dur=7, kind='feedback', carry=('dashboard', None))
    ty = d.top + (yb - d.top) / 2 - d.dy
    d.add(f'<text x="{W - M - 2:g}" y="{ty:g}" class="kick" fill="{ROLE["blue"]}" '
          f'transform="rotate(90 {W - M - 2:g} {ty:g})" text-anchor="middle">FEEDS THE NEXT BRIEF</text>')
    return d.render(bottom + M)


# ---------------------------------------------------------------------------
def decision_pipeline():
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
          "the trace is read-only, and the model never grades itself.")
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
    d.icon('layers', M + 20, y + 14)
    d.text(M + 50, y + 32, 'Your HK + US book wakes up', 'h')
    d.text(M + 20, y + 56, '44 modules · 8 layers · deterministic collection', 'm', fill=MUT)
    xs, cw = columns(3, gap=10, x0=M + 16, w=CW - 32)
    sources = [('market', 'Quotes + FX', 'Tencent/Nasdaq'),
               ('filing', 'SEC · HKEX', 'filings'),
               ('bars', 'Capital flow', 'Eastmoney'),
               ('news', 'Bilingual news', 'Google/Finnhub'),
               ('pulse', 'Sentiment', 'Reddit · radar'),
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
    d.down(W / 2, top, y - 36, pulses=(0, 1.1), kind='data', carry='layers')

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
                d.text(M + 20, yy, key, 'code', fill=MUT)
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
    d.icon('gate', M + 20, y + 13, 'green')
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
    d.text(W / 2 + 12, y + 2, [('preflight', ROLE['green']), (' → one pack per run', MUT)],
           'm', anchor='middle')
    fits('preflight → one pack per run', 'm', W - 184 - 56, 'preflight label')
    d.icon('seal', 106, y - 14, 'green', size=20)
    loop_y = y - 4
    d.down(W / 2, top, y - 22, pulses=(0,), kind='gate')
    top = y + 14
    node = d.at(W / 2, top)
    y = top + 76
    d.turn(W / 2, top, first=y - 26, enter=y + 28, leave=(W - 92, loop_y), tail=40,
           pulses=(0, 1.6), kind='data', carry='pack')

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
                                         ('lens', 'factor', 'pulse', 'sector'))):
        d.chip(lx[i % 2], y + 74 + (i // 2) * 48, lw, name, icon=icon, h=36)
    ry = y + 172
    d.down(W / 2, ry, ry + 30, pulses=(0,), dur=1.6, kind='decision')
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
    d.down(W / 2, vy, vy + 30, pulses=(.5,), dur=1.6, kind='decision')
    d.text(M + 20, vy + 56, 'three risk voices', 'm', fill=MUT)
    vx, vw = columns(3, gap=18, x0=ix, w=iw)
    for x, name in zip(vx, ('aggressive', 'conservative', 'neutral')):
        d.add(f'<rect x="{x:g}" y="{vy + 68:g}" width="{vw:g}" height="56" rx="9" fill="{CHIP}" stroke="{CARD_STROKE}"/>')
        d.text(x + vw / 2, vy + 113, name, 'm', anchor='middle')
        d.icon({'aggressive': 'up', 'conservative': 'shield', 'neutral': 'even'}[name],
               x + vw / 2 - 9, vy + 74, 'slate', size=18)
    jy = vy + 158
    d.icon('judge', M + 20, jy - 17, 'slate', size=22)
    d.text(M + 50, jy, [('Judge', INK), (' names the strategy frame → ', MUT), ('plan.json', ROLE['slate'])],
           'b')
    fits('Judge names the strategy frame → plan.json', 'b', CW - 66, 'judge')
    top = y + h
    y = top + 76
    d.down(W / 2, top, y - 36, pulses=(0, 1.1), kind='decision')

    # 04 deliver
    d.section(y - 12, '04 · THROUGH THE SESSION / REACH YOUR PHONE')
    h = 118
    d.card(M, y, CW, h, 'green')
    d.icon('checks', M + 20, y + 14, 'green')
    d.text(M + 50, y + 32, 'Postflight', 'h')
    d.tag(W - M - 16, y + 30, 'PYTHON', 'green', anchor='end')
    d.lines(M + 20, y + 58, CW - 36, [[('validates plan.json, books it in ', INK)],
                                      [('decisions.jsonl', ROLE['green']), (', renders the card', INK)]],
            lh=21, where='postflight')
    top = y + h
    y = top + 56
    xs, cw = columns(3, gap=18)
    outs = [('Brief card', ['report + card,', 'laid out by', 'code']),
            ('Your phone', ['WeChat +', 'Telegram,', '+ watchdog']),
            ('Dashboard', ['data-plane', 'branch, polled', 'every 60 s'])]
    h = 160
    for i, (x, (name, body)) in enumerate(zip(xs, outs)):
        d.curve(W / 2, top, x + cw / 2, y, pulses=(i * .5,), dur=1.8, kind='deliver',
                carry=('sunrise', None, 'dashboard')[i])
        d.card(x, y, cw, h, 'blue')
        d.text(x + 16, y + 30, name, 'h')
        d.lines(x + 16, y + 57, cw - 24, body, cls='m', lh=21, where='deliver')
        if i == 0:
            d.icon('sunrise', x + 16, y + 118, size=26)
        elif i == 1:
            d.icon('chat', x + 16, y + 118, size=26)
            d.icon('plane', x + 52, y + 118, size=26)
        else:
            d.icon('dashboard', x + 16, y + 118, size=26)
    top = y + h
    y = top + 76
    d.down(W / 2, top, y - 36, pulses=(0, 1.1), kind='money')

    # 05 settle and calibrate
    d.section(y - 12, '05 · AFTER THE SESSION / GRADE THE CALL')
    h = 284
    d.card(M, y, CW, h, 'green')
    d.icon('balance', M + 20, y + 14, 'green')
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
        d.icon({'mark-followed': 'followed', 'settle': 'balance', 'calibrate': 'factor',
                'shadow': 'replay', 'scorecard': 'dashboard'}[cmd], M + 20, yy - 15, 'green', size=18)
        d.text(M + 46, yy, cmd, 'code', fill=ROLE['green'])
        fits(what, 'm', CW - 36 - 160, 'settle what')
        d.text(M + 180, yy, what, 'm')
    d.add(f'<path d="M{M + 20:g} {y + 238:g}H{W - M - 16:g}" stroke="{CARD_STROKE}"/>')
    d.text(M + 20, y + 264, [('↺ ', ROLE['blue']), ('tomorrow’s brief reads the record', MUT)], 'm')
    fits('↺ tomorrow’s brief reads the record', 'm', CW - 36, 'loop note')
    # the loop: the settled record returns to the next run's preflight
    # Across to the first column, under everything it draws, and up into the
    # preflight node from below.
    x1, y1 = d.at(M, y + 256)
    y1 = max(y1, node[1] + 22)
    d.page_wire(f'M{x1:g} {y1:g}H{node[0] + 8:g}Q{node[0]:g} {y1:g} {node[0]:g} {y1 - 8:g}V{node[1] + 4:g}',
                pulses=(0,), dur=4.5, kind='feedback', carry='record')
    d.bottoms.append(y1 + 4)
    # dsh is the interactive view of the same real fills, not an execution engine.
    top = y + h
    y = top + 76
    d.down(W / 2, top, y - 36, pulses=(0,), kind='money')
    d.section(y - 12, '06 · BACK AT YOUR DESK / ASK WHY')
    h = 138
    d.card(M, y, CW, h, 'violet')
    d.logo('deepseek-harness', M + 20, y + 16, size=36)
    d.text(M + 70, y + 38, 'dsh · Decision Mind', 'h')
    d.lines(M + 20, y + 71, CW - 40,
            ['Open a real fill: plan → execution → T+1 → P&L.',
             'Ask a follow-up in chat; record the new verdict.',
             'The trace stays read-only. You place the orders.'], cls='m', where='dsh loop')
    # The first column ends at the preflight; the room under the return line holds
    # the same day as a clock strip instead of another box-and-arrow run.
    foot = d.at(0, y + h)[1]
    group, dx, dy = d.group, d.dx, d.dy
    d.group, d.dx, d.dy = None, 0, 0
    _day_strip(d, M, foot - 198, CW, 198)
    assert foot - 198 >= y1 + 24, 'the day strip needs room under the return line'
    d.group, d.dx, d.dy = group, dx, dy
    return d.render(y + h + M)


def _day_strip(d, x, y, w, h):
    """One HKT day of scheduled runs, from config/cron-schedules.json (New York summer time)."""
    d.card(x, y, w, h, 'blue')
    d.icon('clock', x + 20, y + 14)
    d.text(x + 50, y + 32, 'One day on the desk', 'h')
    d.tag(x + w - 16, y + 30, 'HKT', 'blue', anchor='end')
    bx, bw, by, bh = x + 20, w - 40, y + 54, 24
    at = lambda hour: bx + bw * hour / 24
    d.add(f'<rect x="{bx:g}" y="{by:g}" width="{bw:g}" height="{bh}" rx="6" fill="{CHIP}" stroke="{CARD_STROKE}"/>')
    for a, b, role in ((9.5, 16, 'blue'), (21.5, 24, 'slate'), (0, 4, 'slate')):
        d.add(f'<rect x="{at(a):g}" y="{by:g}" width="{at(b) - at(a):g}" height="{bh}" rx="6" '
              f'fill="{ROLE[role]}" fill-opacity=".2"/>')
    checkins = ([h_ + m for h_ in (10, 11, 14, 15, 22, 23, 0, 1, 2) for m in (.05, .55)])
    for t in checkins:
        d.add(f'<path d="M{at(t):g} {by + 7:g}V{by + bh - 7:g}" stroke="{ROLE["slate"]}" stroke-width="1.5" '
              f'stroke-linecap="round"/>')
    for t in (9.55, 12.05, 13.55, 16.17, 21.55, 4.05):
        d.add(f'<circle cx="{at(t):g}" cy="{by + bh / 2:g}" r="4" fill="{ROLE["blue"]}" stroke="#ffffff"/>')
    d.add(f'<circle cx="{at(8.05):g}" cy="{by + bh / 2:g}" r="6" fill="{ROLE["green"]}" stroke="#ffffff" '
          f'stroke-width="1.5"/>')
    d.add(f'<circle cx="{at(3):g}" cy="{by + bh / 2:g}" r="4" fill="{ROLE["violet"]}" stroke="#ffffff"/>')
    for hour in range(0, 25, 4):
        d.text(at(hour), by + bh + 18, f'{hour:02d}', 'code', anchor='middle', fill=FAINT)
    rows = [[('dot', 'green', 'brief 08:03'), ('dot', 'blue', 'session reports'), ('tick', 'slate', 'check-ins')],
            [('band', 'blue', 'HK session'), ('band', 'slate', 'US session'), ('dot', 'violet', 'memory 03:00')]]
    for i, row in enumerate(rows):
        lx, ly = bx, by + bh + 46 + i * 22
        for kind, role, label in row:
            if kind == 'dot':
                d.add(f'<circle cx="{lx + 5:g}" cy="{ly - 5:g}" r="4.5" fill="{ROLE[role]}"/>')
            elif kind == 'tick':
                d.add(f'<path d="M{lx + 5:g} {ly - 10:g}V{ly:g}" stroke="{ROLE[role]}" stroke-width="1.5" '
                      f'stroke-linecap="round"/>')
            else:
                d.add(f'<rect x="{lx:g}" y="{ly - 10:g}" width="10" height="10" rx="2.5" fill="{ROLE[role]}" '
                      f'fill-opacity=".3"/>')
            d.text(lx + 16, ly, label, 'm', fill=MUT)
            lx += bw / 3
            fits(label, 'm', bw / 3 - 22, 'day legend')
    note = 'Check-ins every 30 min · US slots follow New York DST'
    d.text(bx, by + bh + 46 + 44, note, 'm', fill=FAINT)
    fits(note, 'm', bw, 'day note')

def _wrap(row, cls, room, scale=1):
    # A separator stays with the word before it: no line opens on "·" or "/".
    tokens = []
    for word in row.split():
        if word in ('·', '/', '+', '→') and tokens:
            tokens[-1] += ' ' + word
        else:
            tokens.append(word)
    lines = ['']
    for word in tokens:
        candidate = f'{lines[-1]} {word}'.strip()
        if lines[-1] and width(candidate, cls) * scale > room:
            lines.append(word)
        else:
            lines[-1] = candidate
    return lines


def _words(d, x, y, room, rows, cls='m', lh=21, scale=1, anchor='start', fill=MUT):
    """Wrap labels into `room`, balancing the lines so none ends on a stray word."""
    for row in rows:
        lines = _wrap(row, cls, room, scale)
        # The narrowest measure that still takes this many lines evens them out.
        even = room
        while even > 40 and len(_wrap(row, cls, even - 6, scale)) == len(lines):
            even -= 6
        for line in _wrap(row, cls, even, scale):
            d.text(x, y, line, cls, anchor=anchor, fill=fill)
            y += lh
    return y


def _panel(d, x, y, w, h, role, icon, title, tag=None, tint=False):
    """A titled pane: glyph, heading and an optional role tag on one baseline."""
    d.card(x, y, w, h, role, tint=tint)
    d.icon(icon, x + 20, y + 14, role)
    d.text(x + 50, y + 32, title, 'h')
    room = w - 66
    if tag:
        room -= d.tag(x + w - 16, y + 30, tag, role, anchor='end') + 10
    fits(title, 'h', room, f'panel {title}')
    return y + 62


def rsi_loop():
    """site/assets/rsi-loop.svg — the whole loop on one page, and who owns each step."""
    d = D('clawock on one page: the whole decision loop and who owns each step',
          'One poster of the whole loop. Eight source layers arrive through ordered fallback '
          'routes; Python reconciles the book and certifies one context pack; the agent you '
          'already run argues a bull and a bear case over it; code holds risk limits, currency '
          'rules and evidence requirements; the plan reaches you and you place the orders; code '
          'settles every call as a win, a loss or ungradeable; history, earlier-date calibration '
          'and reviewed proposals return to the next context. No promise of returns.')
    y = d.header('CLAWOCK · THE WHOLE LOOP ON ONE PAGE',
                 ['One stock book. Every step of the loop,', 'and who owns it.'],
                 ['Sources in, an argued decision out, code settles it,',
                  'and the record opens the next judgment.'],
                 [('data · sources', 'blue'), ('python · code gates', 'green'), ('agents · LLM', 'slate'),
                  ('opposing case · limits', 'warm'), ('what returns', 'violet')])
    d.logo('clawock', d.pw - M - 44, 30, 44)
    full, gap = d.pw - 2 * M, 24

    # --- row A: what comes in, and which agent carries it -------------------
    y += 44
    ah, aw = 300, 632
    ax2, aw2 = M + aw + gap, full - aw - gap
    d.section(y - 12, '01 · INFORMATION IN')
    top = _panel(d, M, y, aw, ah, 'blue', 'layers', 'Eight source layers', 'HK + US')
    layers = [('market', 'Quotes + FX', 'Tencent, Nasdaq'), ('filing', 'Filings', 'SEC · HKEX'),
              ('bars', 'Capital flow', 'Eastmoney'), ('news', 'News', 'two languages'),
              ('calendar', 'Macro + mood', 'calendars'), ('factor', 'Quant + risk', 'price history'),
              ('book', 'Your book', 'your ledger'), ('replay', 'Backtest', 'local bars')]
    xs, cw = columns(4, gap=8, x0=M + 16, w=aw - 32)
    for i, (icon, name, origin) in enumerate(layers):
        x, yy = xs[i % 4], top + (i // 4) * 84
        role = 'blue' if i < 5 else 'green'
        d.add(f'<rect x="{x:g}" y="{yy:g}" width="{cw:g}" height="76" rx="9" fill="{TINT[role]}"/>')
        d.icon(icon, x + 12, yy + 9, role, size=20)
        d.text(x + 12, yy + 48, name, 'b')
        d.text(x + 12, yy + 66, origin, 'm', fill=MUT)
        fits(name, 'b', cw - 20, 'layer')
        fits(origin, 'm', cw - 20, 'layer origin')
    d.icon('fx', M + 20, top + 176, 'blue', size=18)
    d.lines(M + 48, top + 190, aw - 68,
            ['Every quote has an ordered fallback route.',
             [('A failed source says “not fetched”, never “no news”.', MUT)]], cls='m', where='fallback')

    d.section(y - 12, 'ANY HARNESS', x=ax2)
    top = _panel(d, ax2, y, aw2, ah, 'slate', 'terminal', 'Your agent', 'LLM')
    agents = [('claude-code', 'Claude Code'), ('codex', 'Codex'), ('openclaw', 'OpenClaw'),
              ('deepseek-harness', 'DeepSeek Harness'), ('any-cli', 'Your own CLI')]
    for i, (logo, name) in enumerate(agents):
        yy = top - 6 + i * 40
        d.logo(logo, ax2 + 20, yy, 32)
        d.text(ax2 + 64, yy + 21, name, 'b')
    d.text(ax2 + 20, y + ah - 18, 'keeps its model · memory · tools', 'm', fill=MUT)
    fits('keeps its model · memory · tools', 'm', aw2 - 36, 'agent note')

    # --- row B: the pack, then the argument over it ---------------------------
    a_bottom = y + ah
    y = a_bottom + 48
    bh, bw = 322, 400
    bx2, bw2 = M + bw + gap, full - bw - gap
    d.down(M + 330, a_bottom, y, pulses=(0, 1.1), kind='data', carry='layers')
    d.down(ax2 + aw2 / 2, a_bottom, y, pulses=(.5,), kind='task')
    d.section(y - 12, '02 · PYTHON BUILDS THE PACK')
    top = _panel(d, M, y, bw, bh, 'green', 'seal', 'Certified context', 'PYTHON')
    rows = [('reconcile', ['money and FX must balance']), ('risk', ['β · volatility · drawdown']),
            ('factors', ['trend · momentum · ranks']), ('backtest', ['bootstrap CI clears 50%']),
            ('certify', ['hashes pin what was read'])]
    sweep(d, M + 12, top - 16, bw - 24, len(rows))
    for i, (key, values) in enumerate(rows):
        d.text(M + 20, top + i * 22, key, 'code', fill=ROLE['green'])
        fits(values[0], 'm', bw - 36 - 112, 'pack row')
        d.text(M + 132, top + i * 22, values[0], 'm')
    d.mini_charts(M + 20, top + 132, bw - 40)
    d.chip(M + 16, y + bh - 46, bw - 32, 'one context pack per run', fill=ROLE['green'])

    d.section(y - 12, '03 · THE DEBATE', x=bx2)
    top = _panel(d, bx2, y, bw2, bh, 'slate', 'debate', 'Argue both sides', 'LLM · READ ONLY')
    xs, cw = columns(4, gap=6, x0=bx2 + 16, w=bw2 - 32)
    for x, lens in zip(xs, ('fundamental', 'technical', 'sentiment', 'sector')):
        d.chip(x, top - 12, cw, lens)
    xs, cw = columns(2, gap=44, x0=bx2 + 16, w=bw2 - 32)
    vy = top + 34
    for x, (icon, name, body, role) in zip(xs, (('up', 'Bull case', 'builds the case for', 'green'),
                                                ('down', 'Bear case', 'attacks the consensus', 'warm'))):
        d.add(f'<rect x="{x:g}" y="{vy:g}" width="{cw:g}" height="72" rx="9" fill="{TINT[role]}" '
              f'stroke="{ROLE[role]}" stroke-opacity=".18"/>')
        d.text(x + 14, vy + 30, [(name, ROLE[role])], 'h')
        d.text(x + 14, vy + 54, body, 'm', fill=MUT)
        d.icon(icon, x + cw - 36, vy + 12, role)
        fits(body, 'm', cw - 28, 'side')
    mid = bx2 + bw2 / 2
    d.wire(f'M{mid - 16:g} {vy + 28:g}H{mid + 14:g}', pulses=(0,), dur=1.6, kind='decision')
    d.wire(f'M{mid + 16:g} {vy + 46:g}H{mid - 14:g}', pulses=(.8,), dur=1.6, kind='alert')
    d.text(mid, vy + 96, [('must disagree on at least one position', ROLE['warm'])], 'm', anchor='middle')
    xs, cw = columns(3, gap=8, x0=bx2 + 16, w=bw2 - 32)
    for x, (icon, voice) in zip(xs, (('up', 'aggressive'), ('shield', 'conservative'), ('even', 'neutral'))):
        d.chip(x, vy + 112, cw, voice, icon=icon)
    d.icon('judge', bx2 + 20, y + bh - 42, 'slate', size=20)
    d.text(bx2 + 50, y + bh - 26, [('Judge', INK), (' names the strategy frame → plan', MUT)], 'm')
    d.wire(f'M{M + bw:g} {y + bh / 2:g}H{bx2 - 2:g}', pulses=(0, 1.2), kind='data')

    # --- row C: one wide band of limits, in three different shapes --------------
    b_bottom = y + bh
    y = b_bottom + 48
    ch = 286
    d.down(bx2 + bw2 / 2, b_bottom, y, pulses=(0, 1.3), kind='decision')
    d.section(y - 12, '04 · CODE HOLDS THE BOUNDARY')
    top = _panel(d, M, y, full, ch, 'green', 'gate', 'Code enforces stops / regime delever; *strategy exemptions apply.',
                 'PYTHON · UNIT-TESTED')
    cx, cw1 = M + 20, 330
    d.text(cx, top, 'RISK POLICY', 'kick', fill=ROLE['warm'])
    caps = [('single name >35%', 'review', .35), ('name / cluster caps', '100%', 1),
            ('ETF sleeve base cap', '100%', 1), ('HK sleeve', '× regime', .7),
            ('US portfolio β', '≤ 6.0', .6), ('ETF hard stop*', '−18%', .18)]
    for i, (label, limit, part) in enumerate(caps):
        yy = top + 30 + i * 32
        d.text(cx, yy, label, 'm')
        d.text(cx + cw1, yy, limit, 'b', anchor='end', fill=ROLE['warm'])
        d.add(f'<rect x="{cx}" y="{yy + 7}" width="{cw1}" height="5" rx="2.5" fill="{CHIP}"/>')
        d.add(f'<rect x="{cx}" y="{yy + 7}" width="{cw1 * part:g}" height="5" rx="2.5" '
              f'fill="{ROLE["warm"]}" fill-opacity=".5"/>')
    mx, mw = cx + cw1 + 28, 252
    rx_, rw = mx + mw + 28, M + full - 20 - (mx + mw + 28)
    for sep in (mx - 14, rx_ - 14):
        d.add(f'<path d="M{sep:g} {top - 10:g}V{y + ch - 22:g}" stroke="{CARD_STROKE}"/>')
    # What happens after a cap is crossed: a short track, not a fourth list.
    d.text(mx, top, 'WHEN A LIMIT BREAKS', 'kick', fill=ROLE['green'])
    track = [('Breach recorded with its age', INK), ('Same-risk adds freeze', INK),
             ('Strategy exemptions apply*', INK), ('Execution stays human', MUT)]
    d.add(f'<path d="M{mx + 7:g} {top + 32:g}V{top + 32 + 40 * (len(track) - 1):g}" stroke="{LINE}" '
          f'stroke-width="1.5"/>')
    for i, (label, fill) in enumerate(track):
        yy = top + 32 + i * 40
        last = i == len(track) - 1
        d.add(f'<circle cx="{mx + 7:g}" cy="{yy:g}" r="6" fill="{"#ffffff" if last else ROLE["green"]}" '
              f'stroke="{ROLE["green"]}" stroke-width="1.5"/>')
        d.text(mx + 26, yy + 5, label, 'm', fill=fill)
        fits(label, 'm', mw - 26, 'breach step')
    d.icon('gate', mx - 3, top + 176, 'green', size=20)
    d.text(mx + 26, top + 191, 'Unreconciled book: no push', 'm')
    fits('Unreconciled book: no push', 'm', mw - 26, 'breach footer')
    d.text(rx_, top, 'EVIDENCE', 'kick', fill=ROLE['blue'])
    # Each rule under the glyph of what it is about, as that thing is drawn elsewhere.
    for i, (icon, rule) in enumerate((('twin', 'Two evidence families per add'),
                                      ('candles', 'Price alone never moves a thesis'),
                                      ('layers', 'Two sources per published number'),
                                      ('down', 'No bear case, no publication'),
                                      ('shield', 'Unknown risk never reads green'))):
        yy = top + 36 + i * 38
        d.icon(icon, rx_, yy - 15, 'blue', size=20)
        d.text(rx_ + 30, yy, rule, 'm')
        fits(rule, 'm', rw - 30, 'evidence rule')

    # --- row D: out to you, your call, back to code -----------------------------
    c_bottom = y + ch
    y = c_bottom + 48
    dh = 208
    w1, w2 = 292, 224
    x2 = M + w1 + gap
    x3 = x2 + w2 + gap
    w3 = M + full - x3
    d.down(M + 240, c_bottom, y, pulses=(0, 1.2), kind='gate')
    d.section(y - 12, '05 · DELIVERED')
    top = _panel(d, M, y, w1, dh, 'blue', 'plane', 'Reaches you', 'PUBLISH')
    for i, (icon, label) in enumerate((('sunrise', 'Brief + plan before the open'),
                                       ('chat', 'WeChat + Telegram cards'),
                                       ('dashboard', 'Live dashboard, polled 60 s'),
                                       ('alarm', 'Watchdog backstop, no LLM'))):
        yy = top + 6 + i * 32
        d.icon(icon, M + 20, yy - 15, 'blue', size=20)
        d.text(M + 50, yy, label, 'm')
        fits(label, 'm', w1 - 66, 'delivery')
    d.section(y - 12, '06 · YOUR CALL', x=x2)
    d.card(x2, y, w2, dh, 'warm', tint=True)
    d.text(x2 + 20, y + 32, 'You decide', 'h')
    fits('You decide', 'h', w2 - 46 - d.tag(x2 + w2 - 16, y + 30, 'HUMAN', 'warm', anchor='end'),
         'your call')
    d.lines(x2 + 20, top + 6, w2 - 36, ['You place orders.', 'You mark each call',
                                        'followed or not.'], cls='m', lh=24, where='you')
    d.chip(x2 + 16, y + dh - 46, w2 - 32, 'mark-followed', cls='code', fill=ROLE['warm'])
    d.section(y - 12, '07 · SETTLED BY CODE', x=x3)
    top = _panel(d, x3, y, w3, dh, 'green', 'balance', 'Code settles it', 'NO SELF-SCORE')
    xs, cw = columns(3, gap=8, x0=x3 + 16, w=w3 - 32)
    for x, (name, body, role) in zip(xs, (('Win', 'published', 'green'), ('Loss', 'published', 'warm'),
                                          ('Ungradeable', 'still shown', 'slate'))):
        d.add(f'<rect x="{x:g}" y="{top - 12:g}" width="{cw:g}" height="62" rx="9" fill="{TINT[role]}" '
              f'stroke="{ROLE[role]}" stroke-opacity=".18"/>')
        d.text(x + 12, top + 14, [(name, ROLE[role])], 'b')
        d.text(x + 12, top + 36, body, 'm', fill=MUT)
        fits(name, 'b', cw - 22, 'verdict')
        fits(body, 'm', cw - 22, 'verdict body')
    d.lines(x3 + 20, top + 78, w3 - 36, ['Canonical bars · each market’s calendar',
                                         [('One thesis = one episode · nothing hand-tuned', MUT)]],
            cls='m', lh=22, where='settle')
    for a, b, kind in ((M + w1, x2, 'deliver'), (x2 + w2, x3, 'money')):
        d.wire(f'M{a:g} {y + dh / 2:g}H{b - 2:g}', pulses=(0, 1.2), kind=kind)

    # --- row E: the record comes back, around two loops ---------------------------
    d_bottom = y + dh
    y = d_bottom + 48
    eh = 306
    d.down(x3 + w3 / 2, d_bottom, y, pulses=(0, 1.2), kind='feedback', carry='balance')
    d.section(y - 12, '08 · WHAT RETURNS')
    top = _panel(d, M, y, full, eh, 'violet', 'eight', 'The next judgment starts from the record',
                 'RSI · RECURSIVE SELF-IMPROVEMENT', tint=True)
    ty, th, r = top + 58, 96, 48
    cy, k = ty + th / 2, 26.5
    hub_x, hub_w = M + full / 2 - 68, 136
    # What goes round each loop is what its stations name, not one icon three times.
    lobes = [
        (hub_x, -1, ('record', 'factor', 'balance'), 'THE JUDGMENT', 'every brief',
         [('History + reviews', ['enter the next brief']),
          ('Calibration', ['earlier dates only', 'shrinks or abstains'])],
         [('Next judgment', ['starts from the record']), ('Settled by code', ['never by the model'])]),
        (hub_x + hub_w, 1, ('branch', 'review', 'commit'), 'THE EVIDENCE RULES', 'when a named review accepts',
         [('Bounded proposal', ['evidence rules only']),
          ('Named review', ['accepts the exact hash', 'or rejects it'])],
         [('Applied', ['with a rollback record']), ('No silent edits', ['strategy stays yours'])]),
    ]
    for x0, s, carry, kick, cadence, out, back in lobes:
        # A stadium that leaves the record along the top and comes back along the foot.
        near, far = x0 + s * r, x0 + s * (376 - r)
        end = x0 + s * 376
        d.wire(f'M{x0:g} {cy:g}C{x0:g} {cy - k:g} {near - s * k:g} {ty:g} {near:g} {ty:g}H{far:g}'
               f'C{far + s * k:g} {ty:g} {end:g} {cy - k:g} {end:g} {cy:g}'
               f'C{end:g} {cy + k:g} {far + s * k:g} {ty + th:g} {far:g} {ty + th:g}H{near:g}'
               f'C{near - s * k:g} {ty + th:g} {x0:g} {cy + k:g} {x0 + s * 2:g} {cy + 3:g}',
               pulses=(0, 3, 6), dur=9, arrow=False, kind='feedback', inset=32, carry=carry)
        mid = x0 + s * 188
        d.text(mid, cy - 3, kick, 'kick', anchor='middle', fill=ROLE['violet'])
        d.text(mid, cy + 18, cadence, 'm', anchor='middle', fill=MUT)
        for row, edge, names in ((out, ty, (0, 1)), (back, ty + th, (1, 0))):
            for (name, body), slot in zip(row, names):
                xx = x0 + s * (97 + slot * 184)
                d.add(f'<circle cx="{xx:g}" cy="{edge:g}" r="6.5" fill="{ROLE["violet"]}" stroke="#ffffff" '
                      f'stroke-width="2"/>')
                # Three lines above the edge end 13 clear of it: room for the packet that runs there.
                base = edge - 56 if edge == ty else edge + 28
                d.text(xx, base, name, 'b', anchor='middle')
                fits(name, 'b', 170, 'loop station')
                for j, line in enumerate(body):
                    d.text(xx, base + 20 + j * 20, line, 'm', anchor='middle', fill=MUT)
                    fits(line, 'm', 176, 'loop station body')
        # Which way round: one chevron on the outbound edge, one on the way back.
        for xx, edge, way in ((mid, ty, s), (mid, ty + th, -s)):
            d.add(f'<path d="M{xx - way * 4:g} {edge - 5:g}L{xx + way * 3:g} {edge:g}L{xx - way * 4:g} {edge + 5:g}" '
                  f'fill="none" stroke="{ROLE["violet"]}" stroke-width="1.8" stroke-linecap="round" '
                  f'stroke-linejoin="round"/>')
    d.add(f'<rect x="{hub_x:g}" y="{cy - 40:g}" width="{hub_w}" height="80" rx="14" fill="#ffffff" '
          f'stroke="{ROLE["violet"]}" stroke-opacity=".45" stroke-width="1.5"/>')
    d.text(hub_x + hub_w / 2, cy - 2, [('The record', ROLE['violet'])], 'h', anchor='middle')
    d.text(hub_x + hub_w / 2, cy + 20, 'every call kept', 'm', anchor='middle', fill=MUT)
    fits('every call kept', 'm', hub_w - 16, 'record hub')
    # The return leaves the far end of the judgment loop and climbs the margin
    # back to the sources, clear of every pane.
    first = d.header_bottom + 44 + ah / 2
    # The margin is 24 wide: room for the line and its dot, not for a packet.
    d.wire(f'M{hub_x - 376:g} {cy:g}H{M - 13:g}V{first:g}H{M - 2:g}', pulses=(0, 4, 8), dur=12, kind='feedback',
           packet=False)

    # --- row F: the desk's own code goes round the same kind of loop --------------
    e_bottom = y + eh
    y = e_bottom + 48
    fh = 336
    d.section(y - 12, '09 · THE DESK FIXES ITSELF THE SAME WAY')
    top = _panel(d, M, y, full, fh, 'blue', 'gear', 'Audited, fixed and shipped in the background',
                 'ON THE AUTHOR’S HOST')
    xs, cw = columns(3, gap=36, x0=M + 20, w=full - 40)
    th, band = 78, 52
    y1, y2 = top - 4, top - 4 + th + 22 + band + 22
    stations = [
        (xs[0], y1, 'scan', 'Patrol round', 'audits what the desk published'),
        (xs[1], y1, 'gate', 'Filing gate', 'proven first, or it is not filed'),
        (xs[2], y1, None, 'Background agent', 'own worktree · own task unit'),
        (xs[2], y2, 'ci', 'PR + required CI', 'every gate passes before merge'),
        (xs[1], y2, 'commit', 'Merged → live', 'the refresh applies what passed'),
        (xs[0], y2, 'closed', 'A closed issue is feedback', 'repeat false alarms get demoted'),
    ]
    for x, yy, icon, name, body in stations:
        d.add(f'<rect x="{x:g}" y="{yy:g}" width="{cw:g}" height="{th}" rx="9" fill="{TINT["blue"]}" '
              f'stroke="{ROLE["blue"]}" stroke-opacity=".18"/>')
        if icon:
            d.icon(icon, x + 12, yy + 12, 'blue', size=20)
        d.text(x + (42 if icon else 14), yy + 28, name, 'b')
        d.text(x + 14, yy + 58, body, 'm', fill=MUT)
        fits(name, 'b', cw - (56 if icon else 120), 'system station')
        fits(body, 'm', cw - 24, 'system station body')
    lx = xs[2] + cw - 12 - 3 * 30
    d.logo('claude-code', lx, y1 + 9, 26)
    d.logo('codex', lx + 30, y1 + 9, 26)
    d.wordmark_tile(lx + 60, y1 + 9, 26, '[', ']')
    for a, b in ((0, 1), (1, 2)):
        d.wire(f'M{xs[a] + cw:g} {y1 + th / 2:g}H{xs[b] - 2:g}', pulses=(a * .5,), dur=1.6, kind=('alert', 'task')[a])
        d.wire(f'M{xs[b]:g} {y2 + th / 2:g}H{xs[a] + cw + 2:g}', pulses=(a * .5 + 1.5,), dur=1.6, kind=('feedback', 'gate')[a])
    d.wire(f'M{xs[2] + cw / 2:g} {y1 + th:g}V{y2 - 2:g}', pulses=(1,), dur=2, kind='task')
    d.wire(f'M{xs[0] + cw / 2:g} {y2:g}V{y1 + th + 2:g}', pulses=(3,), dur=2, kind='feedback', carry='closed')
    bx, bw_, by = xs[1] - 18, cw + 36, y1 + th + 22
    d.add(f'<rect x="{bx:g}" y="{by:g}" width="{bw_:g}" height="{band}" rx="12" fill="{TINT["violet"]}" '
          f'stroke="{ROLE["violet"]}" stroke-opacity=".2"/>')
    d.logo('deepseek-harness', bx + 10, by + 8, 36)
    d.text(bx + 56, by + 22, 'Watched and steered from dsh', 'b')
    d.text(bx + 56, by + 42, 'queue · quota · receipts', 'm', fill=MUT)
    fits('Watched and steered from dsh', 'b', bw_ - 66, 'dsh band')
    eh = fh
    bottom = y + eh
    note = 'No promise of returns. The active calls have yet to show an edge; what accumulates is a record you can check.'
    fits(note, 'm', full - 40, 'overview note')
    d.text(M + 20, bottom + 36, note, 'm', fill=MUT)
    return d.render(bottom + 36 + M)


# --- the kit of the rule-bound figures (see "Drawing rules" in the module docstring) ---
HAIR, BOLD = 1.5, 2.5          # C3: the two stroke weights
GRID2 = (M, M + COL2)          # L2: halves
GRID3 = (M, 352, 680)          # L2: thirds, 312 wide with a 16 gutter
THIRD = 312


def _blend(role, share):
    """A solid tint: `share` of the role colour over white (C2: no transparency)."""
    ink = ROLE[role].lstrip('#')
    return '#' + ''.join(f'{round(255 + (int(ink[i:i + 2], 16) - 255) * share):02x}' for i in (0, 2, 4))


def _polar(cx, cy, r, deg):
    """A point on a circle, degrees counter-clockwise from three o'clock."""
    t = math.radians(deg)
    return cx + r * math.cos(t), cy - r * math.sin(t)


def _line(d, path, ink=LINE, width=HAIR):
    d.add(f'<path d="{path}" fill="none" stroke="{ink}" stroke-width="{width:g}" '
          f'stroke-linecap="round" stroke-linejoin="round"/>')


def _node(d, cx, cy, role, icon, r=22):
    """A flat disc holding a glyph (C4): solid tint, hairline in the role colour."""
    d.add(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:g}" fill="{TINT[role]}" stroke="{ROLE[role]}" '
          f'stroke-width="{HAIR:g}"/>')
    d.icon(icon, cx - 10, cy - 10, role, size=20)


def _dot(d, x, y, role, hollow=False, r=5.5):
    d.add(f'<circle cx="{x:.1f}" cy="{y:g}" r="{r:g}" fill="{"#ffffff" if hollow else ROLE[role]}" '
          f'stroke="{ROLE[role]}" stroke-width="{HAIR:g}"/>')


def _interval(d, x0, x1, y, role, mid=None):
    """What was measured, as a span on an axis (C3: the bold weight)."""
    _line(d, f'M{x0:.1f} {y:g}H{x1:.1f}M{x0:.1f} {y - 6:g}v12M{x1:.1f} {y - 6:g}v12', ROLE[role], BOLD)
    if mid is not None:
        _dot(d, mid, y, role)


def _threshold(d, x, y, role='warm'):
    _line(d, f'M{x:.1f} {y - 10:g}v20', ROLE[role], BOLD)


def _pill(d, x, y, w, label, role, h=30):
    """A verdict: the one place a role colour sets text (T3)."""
    d.add(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h}" rx="{h / 2:g}" fill="{TINT[role]}" '
          f'stroke="{ROLE[role]}" stroke-width="{HAIR:g}"/>')
    d.text(x + w / 2, y + h / 2 + 4.5, [(label, ROLE[role])], 'c', anchor='middle')


def _pane(d, x, y, w, h, role, title, icon=None):
    """A pane with its heading; returns the baseline of its first body line."""
    d.card(x, y, w, h, role)
    if icon:
        d.icon(icon, x + 20, y + 16, role)
    fits(title, 'h', w - (66 if icon else 40), f'pane {title}')
    d.text(x + (50 if icon else 20), y + 34, title, 'h')
    return y + 64


def _captions(d, x, y, rows, lh=19):
    for n, row in enumerate(rows):
        d.text(x, y + n * lh, row, 'c', fill=MUT)
    return y + len(rows) * lh


def _arrow(d, x, y, towards, ink=LINE):
    """A small open chevron at the end of a hairline: 1 points right, -1 left."""
    _line(d, f'M{x - 7 * towards:g} {y - 5:g}L{x:g} {y:g}L{x - 7 * towards:g} {y + 5:g}', ink)


def product_architecture():
    """Three owners, and the three files that cross between two of them."""
    d = D('clawock product architecture: what your runtime keeps, what clawock keeps, and the three '
          'files that cross between them',
          'On the left, what the external runtime keeps: the model, the conversation, memory, tools '
          'and credentials, in OpenClaw, Claude Code, Codex, DeepSeek Harness or your own CLI. On the '
          'right, what clawock keeps: the workflow, certified inputs, reconciliation, evaluation and '
          'bounded improvement. Between them is one contract, and three files cross it: request.json '
          'from clawock run prepare, decision.json written by the agent, and a receipt from clawock '
          'run publish. Below, the user instance owns strategy, evidence, ledger, schedules, delivery '
          'and interface. Drop the opposing evidence from decision.json and publish refuses it.')
    y = d.header('PRODUCT ARCHITECTURE · RUNTIME NEUTRAL',
                 ['The runtime thinks. clawock keeps it reconciled.'],
                 ['Two sides, one contract between them, and three files that cross it.'],
                 [('your runtime', 'slate'), ('clawock', 'green'), ('your instance', 'blue')]) + 32
    h = 268
    left, right = GRID3[0], GRID3[2]
    top = _pane(d, left, y, THIRD, h, 'slate', 'Your runtime keeps')
    for i, name in enumerate(('openclaw', 'claude-code', 'codex', 'deepseek-harness', 'any-cli')):
        d.logo(name, left + 20 + i * 42, top - 8)
    for n, row in enumerate(('the model', 'the conversation and memory', 'research tools', 'credentials and permissions')):
        d.text(left + 20, top + 62 + n * 26, row, 'b')
    d.text(left + 20, y + h - 22, 'clawock starts no model of its own.', 'c', fill=MUT)
    top = _pane(d, right, y, THIRD, h, 'green', 'clawock keeps')
    duties = (('Workflow', 'evidence and an opposing case'), ('Certify', 'pinned inputs, hashed'),
              ('Reconcile', 'orders, cash and FX'), ('Evaluate', 'outcome against price'),
              ('Improve', 'bounded, reviewed, reversible'))
    for n, (label, note) in enumerate(duties):
        d.text(right + 20, top + 2 + n * 38, label, 'b')
        d.text(right + 20, top + 21 + n * 38, note, 'c', fill=MUT)
    # The contract: a line down the middle, and the three files that cross it.
    cx = (left + THIRD + right) / 2
    x0, x1 = left + THIRD + 14, right - 14
    _line(d, f'M{cx:g} {y + 8:g}V{y + h - 8:g}', INK, BOLD)
    d.text(cx + 12, y + 20, 'THE CONTRACT', 'kick', fill=FAINT)
    crossings = (('request.json', 'run prepare', -1), ('decision.json', 'the agent writes it', 1),
                 ('a receipt', 'run publish', -1))
    for n, (name, how, towards) in enumerate(crossings):
        cy = y + 76 + n * 72
        if n == 1:                                       # M1: the file the agent writes
            d.wire(f'M{x0:g} {cy:g}H{x1 - 4:g}', kind='data', dur=3.2)
        else:
            _line(d, f'M{x0:g} {cy:g}H{x1:g}')
            _arrow(d, x0, cy, -1)
        d.text(x0 + 6, cy - 22, name, 'b')
        d.text(x0 + 6, cy + 28, how, 'c', fill=MUT)
    y += h + 24
    body = _pane(d, M, y, WIDE - 2 * M, 124, 'blue', 'Your instance owns the rest', 'book')
    d.text(M + 20, body, 'Strategy, evidence, ledger, schedules, delivery and interface, kept in your workspace.', 'b')
    d.text(M + 20, body + 24, 'The author\'s desk is one live instance. It is proof, not the product.', 'c', fill=MUT)
    y += 124
    d.text(M, y + 34, 'Drop the opposing evidence from decision.json and publish refuses it, exit code 1.', 'c',
           fill=MUT)
    return d.render(y + 58)


def debate_flow():
    """One real debate: both sides over the same evidence, and a resolution with a name on it."""
    d = D('The debate: both sides read the same evidence, and the resolution is attributed',
          'One real debate, Goldwind on 2026-10-08. Four analyst lenses read one evidence pack. A bull '
          'case and a bear case cite the same two pieces of evidence: the leveraged exposure of the '
          'Hong Kong book and the distance from the 200-day average. The bear must name the consensus '
          'it attacks. Three risk voices follow, aggressive, conservative and neutral, and a judge '
          'names the frame behind the call, relative strength, and writes the plan: watch, act only '
          'above 8.97, dead at 8.923, confidence 0.34, marked contested. Without an opposing case '
          'that cites evidence, publication is refused.')
    y = d.header('THE DEBATE · HK + US',
                 ['Disagreement is required. The resolution is attributed.'],
                 [f'One real debate: {CALL["name"]}, {CALL["date"]}.'],
                 [('the evidence both cite', 'blue'), ('the case for', 'green'), ('the case against', 'warm')]) + 32
    h = 232
    top = _pane(d, GRID3[0], y, THIRD, h, 'green', 'Bull', 'up')
    _captions(d, GRID3[0] + 20, top, ['The only peer with a confirmation', 'price you could act on. The book',
                                      'holds little outside HK tech and AI.', 'One lot is under 3% of the HK',
                                      'book: wrong would not hurt much.'])
    top = _pane(d, GRID3[2], y, THIRD, h, 'warm', 'Bear', 'down')
    _captions(d, GRID3[2] + 20, top, ['Trend off, 31.8% under the 200-day', 'average, and four risk limits',
                                      'already tripped. New exposure here', 'trades the weakest position for',
                                      'the weakest evidence.'])
    d.text(GRID3[2] + 20, y + h - 22, 'It must name the consensus it attacks.', 'c', fill=MUT)
    mx = GRID3[1] + THIRD / 2
    d.text(GRID3[1] + 20, y + 20, 'BOTH CITE THE SAME EVIDENCE', 'kick', fill=FAINT)
    for n, (icon, label, note) in enumerate((('shield', 'risk', 'leveraged exposure, HK book'),
                                             ('factor', 'factor', 'distance from the 200-day average'))):
        ey = y + 84 + n * 84
        _line(d, f'M{GRID3[0] + THIRD + 6:g} {ey:g}H{mx - 24:g}')
        if n:
            _line(d, f'M{mx + 24:g} {ey:g}H{GRID3[2] - 6:g}')
        else:                                            # M1: the evidence the bear case has to cite
            d.wire(f'M{mx + 24:g} {ey:g}H{GRID3[2] - 4:g}', kind='data', dur=3.2)
        _node(d, mx, ey, 'blue', icon)
        d.text(mx, ey + 42, note, 'c', anchor='middle', fill=MUT)
    y += h + 24
    jh = 128
    body = _pane(d, M, y, WIDE - 2 * M, jh, 'blue', 'Judge: watch, and pin the trigger before the price gets there',
                 'judge')
    d.text(M + 20, body, 'Act only above 8.97 within five sessions. Dead at 8.923. Confidence 0.34, marked contested.', 'b')
    d.text(M + 20, body + 24, 'The judge names the frame behind the call: relative strength.', 'c', fill=MUT)
    y += jh + 24
    vh = 150
    top = _pane(d, GRID2[0], y, CW, vh, 'blue', 'Four lenses read the pack first')
    for n, (icon, label) in enumerate((('lens', 'Fundamental'), ('factor', 'Technical'),
                                       ('pulse', 'Sentiment'), ('sector', 'Sector rotation'))):
        lx, ly = GRID2[0] + 20 + (n % 2) * 216, top + 8 + (n // 2) * 40
        d.icon(icon, lx, ly - 14, 'blue')
        d.text(lx + 32, ly + 3, label, 'b')
    top = _pane(d, GRID2[1], y, CW, vh, 'blue', 'Three risk voices speak before the judge')
    for n, (icon, label) in enumerate((('up', 'Aggressive'), ('shield', 'Conservative'), ('even', 'Neutral'))):
        lx = GRID2[1] + 20 + n * 144
        d.icon(icon, lx, top - 6, 'blue')
        d.text(lx + 32, top + 11, label, 'b')
    d.text(GRID2[1] + 20, y + vh - 22, 'The first voice rotates every four trading days.', 'c', fill=MUT)
    y += vh
    d.text(M, y + 34, 'Without an opposing case that cites evidence, publication is refused.', 'c', fill=MUT)
    return d.render(y + 58)


def information_flow():
    """Eight layers come in; no run is handed all of them; a source that fails says so."""
    d = D('Information: eight layers come in, and no run is handed all of them',
          'Eight information layers: market, filings, capital flow, news, macro and mood, quant and '
          'risk, book and FX, backtest. Critical sources have fallbacks tried in order: Hong Kong '
          'quotes from Tencent and Eastmoney, then stooq, then yfinance; US quotes from Nasdaq through '
          'six further routes; USD/HKD from Frankfurter, then exchangerate.host, then Yahoo. A source '
          'that fails is printed as not fetched, never as no news. A grid shows what each run is '
          'handed: the pre-open brief receives every kind of block in full, while session reports and '
          'intraday check-ins receive narrower cuts and no history. The model reads those files and '
          'does not fetch; code checks the result before anything is sent.')
    y = d.header('DATA FLOW · HK + US',
                 ['Eight layers come in. No run is handed all of them.'],
                 ['Code fetches, reconciles and decides what each run may read. The model reads; it does not fetch.'],
                 [('a layer, a block', 'blue'), ('handed over in full', 'green'), ('not fetched', 'warm')]) + 32
    full = WIDE - 2 * M

    # --- eight layers --------------------------------------------------------
    d.section(y, 'EIGHT LAYERS COME IN')
    layers = (('market', 'Quotes'), ('filing', 'Filings'), ('bars', 'Capital flow'), ('news', 'News'),
              ('calendar', 'Macro, mood'), ('factor', 'Quant, risk'), ('fx', 'USD/HKD, book'), ('replay', 'Backtest'))
    pitch = full / 8
    for index, (icon, label) in enumerate(layers):
        nx, ny = M + pitch / 2 + index * pitch, y + 46
        _node(d, nx, ny, 'blue', icon)
        d.text(nx, ny + 44, label, 'c', anchor='middle')
    y += 46 + 44 + 16
    d.wire(f'M{M + pitch / 2:g} {y:g}V{y + 52:g}', kind='data', dur=3.2)
    y += 56

    # --- fallbacks, and what a failure looks like ----------------------------
    h = 214
    top = _pane(d, GRID2[0], y, CW, h, 'blue', 'Critical sources fall back, in order')
    chains = (('HK quotes', 3, 'Tencent + Eastmoney, then stooq, yfinance'),
              ('US quotes', 7, 'Nasdaq first, then six further routes'),
              ('USD/HKD', 3, 'Frankfurter, exchangerate.host, Yahoo'))
    for n, (label, count, note) in enumerate(chains):
        ly = top + 6 + n * 46
        d.text(GRID2[0] + 20, ly + 5, label, 'b')
        x0 = GRID2[0] + 124
        _line(d, f'M{x0:g} {ly:g}H{x0 + (count - 1) * 24:g}')
        for k in range(count):
            _dot(d, x0 + k * 24, ly, 'blue', hollow=k > 0)
        d.text(x0 - 6, ly + 26, note, 'c', fill=MUT)
    top = _pane(d, GRID2[1], y, CW, h, 'warm', 'A source that fails says so')
    _pill(d, GRID2[1] + 20, top - 8, 108, 'not fetched', 'warm')
    d.text(GRID2[1] + 144, top + 12, 'never printed as "no news"', 'b')
    _captions(d, GRID2[1] + 20, top + 54, ['An empty fetch keeps the earlier value and says how old it is.',
                                         'Old news is labelled apart from what is live.'], lh=24)
    y += h + 24

    # --- what each run is handed --------------------------------------------
    rows = (('Position truth', 2, 2, 2), ('Risk', 2, 1, 1), ('Signals', 2, 1, 2), ('News and events', 2, 1, 1),
            ('Research state', 2, 1, 1), ('History', 2, 0, 1), ('Today\'s plan', 2, 1, 1))
    mh = 96 + len(rows) * 34 + 56
    top = _pane(d, M, y, full, mh, 'green', 'What each run is handed')
    cols = (M + 300, M + 520, M + 740)
    for cx, (icon, label) in zip(cols, (('sunrise', 'Brief, pre-open'), ('clipboard', 'Session reports'),
                                        ('clock', 'Intraday check-ins'))):
        d.icon(icon, cx - 11, top - 8, 'blue')
        d.text(cx + 19, top + 9, label, 'b')
    for n, (label, *given) in enumerate(rows):
        ry = top + 50 + n * 34
        _line(d, f'M{M + 20:g} {ry + 17:g}H{M + full - 20:g}', CARD_STROKE)
        d.text(M + 20, ry + 5, label, 'b')
        for cx, level in zip(cols, given):
            if level:
                _dot(d, cx, ry, 'green', hollow=level == 1, r=7)
            else:
                _line(d, f'M{cx - 7:g} {ry:g}h14')
    ky = y + mh - 24
    _dot(d, M + 27, ky - 4, 'green', r=7)
    d.text(M + 44, ky, 'in full', 'c', fill=MUT)
    _dot(d, M + 127, ky - 4, 'green', hollow=True, r=7)
    d.text(M + 144, ky, 'a narrower cut: flagged names, or only when signals ask', 'c', fill=MUT)
    _line(d, f'M{M + 560:g} {ky - 4:g}h14')
    d.text(M + 584, ky, 'not handed over', 'c', fill=MUT)
    y += mh
    d.text(M, y + 34, 'The model reads these files and does not fetch. Code checks the result before anything is sent.',
           'c', fill=MUT)
    return d.render(y + 58)


def feedback_learning():
    """One call on the calendar, the three things it can become, and where the verdict goes."""
    call = CALL
    d = D('After the close: code settles the call and the record feeds the next one',
          'One real call on its market calendar: Goldwind, published 2026-10-08 by the model, '
          'marked by code at the next close 4.22 percent lower and settled as a loss; its five and '
          'twenty session marks are not reached yet. A call ends as a win, a loss or ungradeable, '
          'and all three are published; an ungradeable call stays out of the hit rate instead of '
          'being guessed. On the live desk execution, settlement, history and calibration feed the '
          'next brief. In any other harness an observed outcome can anchor a bounded proposal that '
          'a named review accepts or rejects, applied with a way back. A directional evaluation is '
          'not realized P&L and nothing here promises returns.')
    y = d.header('AFTER THE CLOSE · SETTLE, THEN LEARN',
                 ['Code settles the call. The record teaches the next one.'],
                 ['Wins, losses and the calls that cannot be graded all stay on the page.'],
                 [('written once, by the model', 'blue'), ('a win', 'green'), ('a loss', 'warm')]) + 32
    full = WIDE - 2 * M

    # --- one call on its calendar -------------------------------------------
    h = 204
    top = _pane(d, M, y, full, h, 'blue', f'One call on the calendar: {call["name"]}', 'candles')
    ay = top + 44
    stops = [M + 60 + index * (full - 320) / 3 for index in range(4)]
    _line(d, f'M{stops[0]:g} {ay:g}H{stops[3] + 40:g}')
    marks = (('published', call['date'], 'blue', False), ('next close', '−4.22%', 'warm', False),
             ('5 sessions', 'not reached', 'blue', True), ('20 sessions', 'not reached', 'blue', True))
    for x, (label, value, role, hollow) in zip(stops, marks):
        _dot(d, x, ay, role, hollow=hollow, r=7)
        d.text(x - 7, ay - 22, label, 'b')
        d.text(x - 7, ay + 30, value, 'c', fill=MUT)
    _line(d, f'M{stops[0]:g} {ay:g}H{stops[1]:g}', ROLE['warm'], BOLD)
    _dot(d, stops[0], ay, 'blue', r=7)
    _dot(d, stops[1], ay, 'warm', r=7)
    _pill(d, stops[1] + 84, ay + 10, 70, 'loss', 'warm')
    d.text(M + 20, y + h - 22, 'The model wrote this call once. From there on, only code touches it.', 'c',
           fill=MUT)
    y += h + 24

    # --- the three things a call becomes ------------------------------------
    verdicts = (('green', 'closed', 'Win', ['It went the call\'s way by the mark.', 'Published.']),
                ('warm', 'down', 'Loss', ['It did not. Published the same way,', 'on the same page.']),
                ('blue', 'even', 'Ungradeable', ['No clean price to mark it on.', 'Published; kept out of the hit rate.']))
    for x, (role, icon, title, lines) in zip(GRID3, verdicts):
        body = _pane(d, x, y, THIRD, 116, role, title, icon)
        _captions(d, x + 20, body, lines)
    y += 116 + 24

    # --- where the verdict goes ---------------------------------------------
    h = 262
    top = _pane(d, GRID2[0], y, CW, h, 'blue', 'On the desk, the next brief starts here', 'cycle')
    steps = (('followed', 'Execution', 'followed, not followed or unknown'),
             ('balance', 'Settle', 'wins, losses and ungradeable kept'),
             ('record', 'History', 'metrics and past reviews'),
             ('factor', 'Calibrate', 'on earlier dates only'))
    lx = GRID2[0] + 64
    for index, (icon, label, note) in enumerate(steps):
        ly = top + 4 + index * 44
        d.icon(icon, lx, ly - 12, 'blue')
        d.text(lx + 32, ly + 5, label, 'b')
        d.text(lx + 150, ly + 4.5, note, 'c', fill=MUT)
    d.wire(f'M{lx - 8:g} {top + 4 + 3 * 44:g}H{lx - 30:g}V{top + 4:g}H{lx - 10:g}', kind='feedback', dur=3.6)
    top = _pane(d, GRID2[1], y, CW, h, 'green', 'In any other harness, a reviewed change')
    rx, ry = GRID2[1] + 36, top + 122
    stairs = (('Observe', 'an outcome'), ('Propose', 'a bounded change'), ('Review', 'accept or reject'),
              ('Apply', 'with a way back'))
    path = f'M{rx:g} {ry:g}'
    for index, (label, note) in enumerate(stairs):
        sx, sy = rx + index * 104, ry - index * 36
        path += f'H{sx + 104:g}' + (f'V{sy - 36:g}' if index < 3 else '')
        _dot(d, sx + 8, sy, 'green', r=6)
        d.text(sx + 2, sy - 18, label, 'b')
        d.text(sx + 2, sy + 24, note, 'c', fill=MUT)
    _line(d, path, ROLE['green'])
    d.text(GRID2[1] + 20, y + h - 22, 'Only evidence requirements change. Strategy does not.', 'c', fill=MUT)
    y += h
    d.text(M, y + 34, 'A directional evaluation is not realized P&L. A diagnostic, not proof of return.', 'c',
           fill=MUT)
    return d.render(y + 58)


def proposal_review():
    """Two checks can stop a proposal, an objection cannot, and the record keeps all of them."""
    d = D('Open proposals: two checks can stop one, an objection cannot, and all of them are kept',
          'A proposal passes two checks that can stop it: facts, and feasibility. Each refusal '
          'is a recorded outcome. A strategy objection stays attached to the proposal and does '
          'not stop it. Published, refused and unpublished proposals all enter the method record. '
          'From that record, payoff and forecast score are read on two separate axes, and a frozen '
          'trial runs three arms forward from the same capital with missing marks left as holes. '
          'Nothing is promoted and no order is placed.')
    y = d.header('CLAWOCK · PROPOSALS AND EVIDENCE',
                 ['A different strategy can still be a valid proposal.'],
                 ['Code checks facts and authority. The model owns the hypothesis.'],
                 [('the proposal', 'blue'), ('can stop it, or passes', 'green'),
                  ('refused, or objected to', 'warm')]) + 32
    full = WIDE - 2 * M

    # --- one proposal on its way to publication ----------------------------
    top = _pane(d, M, y, full, 296, 'blue', 'One proposal, two checks that can stop it', 'lens')
    track = top + 62
    x0, x1 = M + 40, M + full - 164
    gates = ((M + 250, 'Facts', ['real citations and prices,', 'sums that replay']),
             (M + 500, 'Feasibility', ['cash, shares, lots,', 'authority in force']))
    _line(d, f'M{x0:g} {track:g}H{gates[1][0]:g}')
    d.wire(f'M{gates[1][0]:g} {track:g}H{x1 - 4:g}', kind='data', dur=3.2)
    _dot(d, x0, track, 'blue', r=7)
    d.text(x0 - 16, track - 22, 'a proposal', 'b')
    _captions(d, x0 - 16, track + 30, ['hypothesis, action,', 'size and forecast'])
    for gx, title, lines in gates:
        _line(d, f'M{gx:g} {track - 16:g}v32', ROLE['green'], BOLD)
        d.text(gx + 14, track - 22, title, 'b')
        _captions(d, gx + 14, track + 30, lines)
        _line(d, f'M{gx:g} {track + 16:g}V{track + 82:g}')
        _pill(d, gx - 42, track + 82, 84, 'refused', 'warm')
    fx = M + 700
    _line(d, f'M{fx:g} {track:g}V{track - 48:g}', ROLE['warm'])
    _dot(d, fx, track - 48, 'warm', hollow=True)
    d.text(fx + 14, track - 58, 'Strategy objection', 'b')
    _captions(d, fx + 14, track - 39, ['stays attached; cannot stop it'])
    _pill(d, x1, track - 14, 104, 'published', 'green')
    _line(d, f'M{x1 + 52:g} {track + 14:g}V{track + 82:g}')
    _pill(d, x1 - 2, track + 82, 108, 'unpublished', 'blue')
    d.text(M + 20, y + 296 - 22, 'Every outcome enters the method record. A refused proposal still counts.', 'c',
           fill=MUT)
    y += 296 + 24

    # --- two readings of the record ----------------------------------------
    h = 226
    left = _pane(d, GRID2[0], y, CW, h, 'blue', 'Read the record on two axes', 'record')
    ax0, ax1 = GRID2[0] + 150, GRID2[0] + CW - 24
    dots = ((.16, .58, .38, .80, .50), (.72, .28, .60, .20, .44))
    for row, (label, note) in enumerate((('payoff', 'per episode, after assumed costs'),
                                         ('forecast score', 'was the stated probability right'))):
        ay = left + 12 + row * 62
        d.text(GRID2[0] + 20, ay + 5, label, 'b')
        _line(d, f'M{ax0:g} {ay:g}H{ax1:g}M{(ax0 + ax1) / 2:g} {ay - 6:g}v12')
        for at in dots[row]:
            _dot(d, ax0 + at * (ax1 - ax0), ay, 'blue')
        _captions(d, ax0, ay + 26, [note])
    d.text(GRID2[0] + 20, y + h - 22, 'A call can be right and lose money. The two are never merged.', 'c',
           fill=MUT)
    right = _pane(d, GRID2[1], y, CW, h, 'green', 'Freeze a comparison going forward', 'replay')
    lx = GRID2[1] + 20
    start = GRID2[1] + 170
    for row, (label, missing) in enumerate((('old policy', ()), ('observations', (3,)),
                                            ('policy reference', (1, 4)))):
        ay = right + 8 + row * 38
        d.text(lx, ay + 5, label, 'b')
        _line(d, f'M{start:g} {ay:g}H{GRID2[1] + CW - 24:g}')
        for index in range(7):
            _dot(d, start + 22 + index * 38, ay, 'green', hollow=index in missing)
    _line(d, f'M{start:g} {right - 10:g}V{right + 102:g}', INK)
    d.text(lx, y + h - 22, 'Same capital and costs. A missing mark stays a hole.', 'c',
           fill=MUT)
    y += h
    d.text(M, y + 34, 'Evidence for human review: no automatic method promotion, sizing or order placement.',
           'c', fill=MUT)
    return d.render(y + 58)


#: The live rows: (row id, glyph). The first is the one the figure follows.
LIVE_ROWS = (
    ('factors', 'factor'), ('bar-signals', 'bars'), ('sentiment', 'pulse'),
    ('morning-scans', 'news'), ('signal-panel', 'sector'), ('strategy-scores', 'lens'),
    ('daily-bars', 'candles'), ('add-policy', 'layers'), ('add-alpha', 'branch'),
    ('add-side', 'scan'), ('left-side', 'commit'), ('preposition', 'clock'),
    ('intraday-policy', 'alarm'),
)
#: One real call, `dec-6d9e8bdc8817` in memory/decisions.jsonl: Goldwind, 2026-10-08.
CALL = {'name': 'Goldwind · 02208', 'date': '2026-10-08', 'reading': 'trend off, 31.8% under its 200-day average',
        'act': 8.97, 'dead': 8.923, 'reference': 8.645, 'next_pct': -4.2221, 'confidence': '0.34',
        'id': 'dec-6d9e8bdc8817'}


def strategy_plugins():
    """One real call drawn across the line between what is a row and what is not."""
    call = CALL
    d = D('Plugins: one real call, and the line between what you can swap and what judges it',
          'Above a line, thirteen live rows, each in one socket; any of them can be swapped. One, '
          'the factors row, computed a reading for Goldwind on 2026-10-08: trend off, 31.8 percent '
          'under its 200-day average. In the middle, your agent argued a bull case and a bear case '
          'over that reading and wrote a plan: watch, act only above 8.97 within five sessions, dead '
          'at 8.923, confidence 0.34. Below the line is what is not a row: code took 8.645 as the '
          'reference, the first tradable price after publication, marked the next close 4.22 percent '
          'lower, called it a loss, and kept it on the public ledger. No row can change that part.')
    y = d.header('CLAWOCK · PLUGINS',
                 ['Swap what computes. Not what a result is allowed to do.'],
                 [f'One real call, {call["name"]}, {call["date"]}: what was a row, and what was not.'],
                 [('rows and their readings', 'blue'), ('the case for; the trigger', 'green'),
                  ('the case against; the loss', 'warm')]) + 32

    # --- above the line: rows, any of which can be swapped ------------------
    d.section(y, 'ROWS · SWAP ANY OF THEM')
    pitch, r = (WIDE - 2 * M) / 7, 22
    first = None
    for index, (label, icon) in enumerate(LIVE_ROWS):
        col, row = index % 7, index // 7
        # The second shelf sits half a pitch in, under the gaps of the first.
        nx, ny = M + pitch / 2 + col * pitch + (pitch / 2 if row else 0), y + 46 + row * 92
        _node(d, nx, ny, 'blue', icon, r)
        if index == 0:
            d.add(f'<circle cx="{nx:.1f}" cy="{ny:.1f}" r="{r + 5:g}" fill="none" stroke="{ROLE["blue"]}" '
                  f'stroke-width="{BOLD:g}"/>')
            first = (nx, ny)
        d.text(nx, ny + r + 22, label, 'c', anchor='middle')
    fx, fy = first
    y += 46 + 92 + r + 22 + 40
    d.wire(f'M{fx - 44:.1f} {fy:.1f}H{M + 6:g}V{y + 30:g}H{M + 28:g}', kind='data', dur=3.6)
    d.text(M + 40, y + 24, call['name'], 'h')
    d.text(M + 40, y + 46, f'the factors row read its daily bars: {call["reading"]}', 'b')

    # --- the argument: your agent, over that reading -------------------------
    y += 46 + 40
    d.section(y, 'YOUR AGENT ARGUES OVER THE READING')
    cases = (('green', 'up', 'Bull', ['The only peer with a confirmation', 'price you could act on, and the book',
                                      'holds little outside HK tech and AI.']),
             ('warm', 'down', 'Bear', ['Trend off, four risk limits already', 'tripped: the weakest position on',
                                       'the weakest evidence.']),
             ('blue', 'judge', 'Judge: the plan', ['Watch. Act only above 8.97 within', 'five sessions. Dead at 8.923.',
                                                   'Confidence 0.34.']))
    for x, (role, icon, title, lines) in zip(GRID3, cases):
        body = _pane(d, x, y + 16, THIRD, 132, role, title, icon)
        _captions(d, x + 20, body, lines)
    y += 16 + 132 + 48

    # --- the line, and what is under it --------------------------------------
    _line(d, f'M{M} {y:g}H{WIDE - M}', INK, BOLD)
    d.section(y + 30, 'NOT ROWS · THE SAME CODE JUDGES EVERY STRATEGY')
    y += 46
    h = 208
    top = _pane(d, GRID2[0], y, CW, h, 'warm', 'Code settled it', 'balance')
    ax0, ax1, lo, hi = GRID2[0] + 36, GRID2[0] + CW - 36, 8.20, 9.05
    def px(price):
        return ax0 + (price - lo) / (hi - lo) * (ax1 - ax0)
    ay = top + 46
    close = call['reference'] * (1 + call['next_pct'] / 100)
    _line(d, f'M{ax0:g} {ay:g}H{ax1:g}')
    _interval(d, px(close), px(call['reference']), ay, 'warm')
    _dot(d, px(call['reference']), ay, 'blue')
    _dot(d, px(close), ay, 'warm')
    _threshold(d, px(call['act']), ay, 'green')
    _threshold(d, px(call['dead']), ay, 'warm')
    d.text(px(call['reference']), ay - 20, 'reference 8.645', 'c', anchor='middle')
    d.text(px(close), ay - 20, 'next close', 'c', anchor='middle')
    d.text(px(close), ay + 28, '−4.22%', 'c', anchor='middle')
    d.text(px(call['act']) + 8, ay - 20, 'act 8.97', 'c')
    d.text(px(call['dead']) - 8, ay + 28, 'dead 8.923', 'c', anchor='middle')
    d.text(GRID2[0] + 20, y + h - 44, 'The first tradable price after publication,', 'c', fill=MUT)
    d.text(GRID2[0] + 20, y + h - 25, 'marked at the close of the next session.', 'c', fill=MUT)
    top = _pane(d, GRID2[1], y, CW, h, 'warm', 'The record kept it', 'record')
    _pill(d, GRID2[1] + 20, top - 6, 76, 'loss', 'warm')
    d.text(GRID2[1] + 110, top + 14, call['id'], 'b')
    _captions(d, GRID2[1] + 20, top + 52, ['On the public ledger, and counted by the', 'track record the next brief reads.'])
    d.text(GRID2[1] + 20, y + h - 44, 'No row can mark its own call, move the', 'c', fill=MUT)
    d.text(GRID2[1] + 20, y + h - 25, 'reference, change the outcome or leave it out.', 'c', fill=MUT)
    return d.render(y + h + 32)


#: One real run of `clawock strategy-lab optimize rsi`, 2026-10-12, on the
#: desk's 28 names. The figure draws this run and nothing else; a later run
#: reads differently, and `strategy-lab evolution rsi` prints the current one.
RSI_RUN = {
    'date': '2026-10-12',
    'periods': (5, 7, 9, 14, 21, 28),
    # Mean rank IC of each configuration; reversion is the same score, signed.
    'momentum': (.0424, .0486, .0538, .0646, .0680, .0694),
    'registered': ('reversion', 14),
    'selected': ('momentum', 28),
    'sessions': 771, 'oos_sessions': 705,
    'edge': (.0177, .1125), 'lift': (.0414, .2198), 'pbo': 0.0,
    'net': (.000491, .009011),
    'all': (28, .0656, (.0177, .1125)),
    'adjusted': (16, .0042, (-.0448, .0502)),
    'after_session': '2026-10-09',
}


def strategy_evolution():
    """A strategy searching its own parameters, drawn from one real run, and where that stops."""
    run = RSI_RUN
    d = D('A strategy proposes its next parameters and cannot adopt them: one real run',
          'RSI on 2026-10-12. The declared grid of six periods and two directions, shaded by mean '
          'rank IC: the row registers reversion with period 14 and the search picks momentum with '
          'period 28. The registered gate, check by check: every observed value clears its '
          'threshold, and the alternate after costs does not object. The same search on the 16 '
          'names the provider answered adjusted, without the 12 it only has no corporate action on '
          'record for, is refused: its interval spans zero. Registration starts scoring on later '
          'sessions only; none is scored yet, and the row keeps its parameters until it is edited.')
    y = d.header('CLAWOCK · A STRATEGY THAT SEARCHES ITSELF',
                 ['It may propose its next parameters. It cannot adopt them.'],
                 [f'One real run, drawn as it came out: RSI on {run["date"]}.'],
                 [('measured', 'blue'), ('threshold, refused', 'warm'), ('passes, candidate', 'green')]) + 32
    full = WIDE - 2 * M

    # --- 01 the declared grid ----------------------------------------------
    h1 = 284
    top = _pane(d, GRID2[0], y, CW, h1, 'blue', 'The grid it declared')
    gx, cw, ch, gap = GRID2[0] + 116, 50, 40, 6
    peak = max(run['momentum'])
    d.text(GRID2[0] + 20, top + 2, 'period', 'c', fill=MUT)
    for col, period in enumerate(run['periods']):
        d.text(gx + col * (cw + gap) + cw / 2, top + 2, str(period), 'c', anchor='middle', fill=MUT)
    def cell(direction, period):
        return (gx + run['periods'].index(period) * (cw + gap),
                top + 16 + (direction == 'reversion') * (ch + gap))
    for direction, sign, role in (('momentum', 1, 'blue'), ('reversion', -1, 'warm')):
        for period, value in zip(run['periods'], run['momentum']):
            x, cy = cell(direction, period)
            d.add(f'<rect x="{x:g}" y="{cy:g}" width="{cw}" height="{ch}" rx="8" '
                  f'fill="{_blend(role, .12 + .38 * value / peak)}"/>')
            d.text(x + cw / 2, cy + ch / 2 + 4.5, f'{sign * value:+.3f}'.replace('-', '−'), 'c',
                   anchor='middle')
        d.text(GRID2[0] + 20, cell(direction, 5)[1] + ch / 2 + 5, direction, 'b')
    for (direction, period), ink, width in ((run['registered'], INK, HAIR), (run['selected'], ROLE['green'], BOLD)):
        x, cy = cell(direction, period)
        d.add(f'<path d="M{x + 8:g} {cy - 3:g}h{cw - 10:g}q5 0 5 5v{ch - 4:g}q0 5 -5 5h-{cw - 4:g}q-5 0 -5 -5'
              f'v-{ch - 4:g}q0 -5 5 -5z" fill="none" stroke="{ink}" stroke-width="{width:g}"/>')
    ky = top + 16 + 2 * ch + gap + 36
    for n, (ink, width, label) in enumerate(((INK, HAIR, 'the row today: reversion, 14 sessions'),
                                             (ROLE['green'], BOLD, 'the search picks: momentum, 28 sessions'))):
        d.add(f'<rect x="{GRID2[0] + 20}" y="{ky - 12 + n * 24:g}" width="16" height="14" rx="4" fill="none" '
              f'stroke="{ink}" stroke-width="{width:g}"/>')
        d.text(GRID2[0] + 46, ky + n * 24, label, 'c')
    d.text(GRID2[0] + 20, y + h1 - 22, f'Mean rank IC, {run["sessions"]} sessions, 28 names. All 12 trials counted.',
           'c', fill=MUT)

    # --- 02 the gate, one axis per check -----------------------------------
    px = GRID2[1]
    top = _pane(d, px, y, CW, h1, 'warm', 'The registered gate')
    ax0, ax1, vx = px + 150, px + 320, px + 340
    gauges = (('sessions', (0, 800), 60, run['oos_sessions'], '705, needs 60'),
              ('edge', (-.05, .25), 0, run['edge'], 'above zero'),
              ('lift', (-.05, .25), 0, run['lift'], 'above zero'),
              ('overfitting', (0, 1), .5, run['pbo'], '0.0, under 0.5'),
              ('after costs', (-.005, .015), 0, run['net'], 'no objection'))
    for index, (label, (lo, hi), threshold, seen, value) in enumerate(gauges):
        ly = top + 8 + index * 32 + (16 if index == 4 else 0)
        def at(v, lo=lo, hi=hi):
            return ax0 + (v - lo) / (hi - lo) * (ax1 - ax0)
        d.text(px + 20, ly + 5, label, 'b')
        _line(d, f'M{ax0:g} {ly:g}H{ax1:g}')
        _threshold(d, at(threshold), ly)
        if isinstance(seen, tuple):
            _interval(d, at(seen[0]), at(seen[1]), ly, 'blue')
        else:
            _dot(d, at(seen), ly, 'blue')
        d.text(vx, ly + 4.5, value, 'c', fill=MUT)
    d.text(px + 20, top + 8 + 4 * 32 - 2, 'ALTERNATE GATE', 'kick', fill=FAINT)
    d.text(px + 20, y + h1 - 22, 'Bars adjusted: yes. An alternate can object, not pass.', 'c',
           fill=MUT)
    y += h1 + 24

    # --- 03 without the single-source names --------------------------------
    h3 = 264
    top = _pane(d, M, y, full, h3, 'warm', 'The same search without the names one provider vouches for')
    for index in range(28):
        _dot(d, M + 28 + (index % 7) * 24, top + 10 + (index // 7) * 24, 'blue', hollow=index >= 16, r=7)
    _captions(d, M + 20, top + 112, ['16 answered adjusted,', '12 raw, no action on record'])
    ix0, ix1, lo, hi = M + 400, M + 760, -.08, .14
    def ic(v):
        return ix0 + (v - lo) / (hi - lo) * (ix1 - ix0)
    base = top + 86
    _line(d, f'M{ix0:g} {base:g}H{ix1:g}')
    for tick in (-.05, 0, .05, .10):
        _line(d, f'M{ic(tick):.1f} {base:g}v6')
        d.text(ic(tick), base + 24, f'{tick:+.2f}'.replace('-', '−') if tick else '0', 'c', anchor='middle',
               fill=MUT)
    _line(d, f'M{ic(0):.1f} {top - 6:g}V{base:g}', ROLE['warm'], BOLD)
    for row, (key, role, verdict) in enumerate((('all', 'green', 'candidate'), ('adjusted', 'warm', 'refused'))):
        names, mean, (low, high) = run[key]
        ry = top + 12 + row * 40
        d.text(ix0 - 112, ry + 5, f'{names} names', 'b')
        _interval(d, ic(low), ic(high), ry, 'blue', ic(mean))
        _pill(d, ix1 + 24, ry - 14, 96, verdict, role)
    d.text(M + 20, y + h3 - 22, 'An edge interval across zero is no edge: the candidate rests on those 12 names.',
           'c', fill=MUT)
    y += h3 + 24

    # --- 04 what registration starts ---------------------------------------
    h4 = 176
    top = _pane(d, M, y, full, h4, 'green', 'What registration starts, and where it stops')
    ty = top + 34
    t0, treg, tend = M + 28, M + 500, M + 740
    _line(d, f'M{t0:g} {ty:g}H{treg:g}', ROLE['blue'], BOLD)
    d.text(t0, ty - 22, f'{run["sessions"]} sessions searched, walking forward', 'b')
    _captions(d, t0, ty + 28, ['a result about the past'])
    _line(d, f'M{treg:g} {ty - 16:g}v32', INK, BOLD)
    d.text(treg + 14, ty - 22, f'registered after {run["after_session"]}', 'b')
    d.wire(f'M{treg:g} {ty:g}H{tend - 4:g}', kind='data', dur=3.2)
    for index in range(6):
        _dot(d, treg + 40 + index * 30, ty, 'blue', hollow=True)
    _captions(d, treg + 14, ty + 28, ['sessions it had not seen:', 'scored from here, 0 so far'])
    _line(d, f'M{tend:g} {ty - 16:g}v32', ROLE['warm'], BOLD)
    d.text(tend + 14, ty - 22, 'the row', 'b')
    _captions(d, tend + 14, ty + 28, ['still reversion, 14.', 'Editing it is reviewed.'])
    return d.render(y + h4 + 32)


LAYOUTS = {
    'strategy-plugins': strategy_plugins,
    'strategy-evolution': strategy_evolution,
    'proposal-review': proposal_review,
    'rsi-loop': rsi_loop,
    'feedback-learning': feedback_learning,
    'decision-pipeline': decision_pipeline,
    'harnesses': harnesses,
    'information-flow': information_flow,
    'architecture': architecture,
    'product-architecture': product_architecture,
    'debate-flow': debate_flow,
}
#: Every file this builder owns: one composition per diagram, at every width.
DIAGRAMS = {f'{name}.svg': draw for name, draw in LAYOUTS.items()}


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
