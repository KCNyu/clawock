"""Build the README diagrams in site/assets/ as one visual system.

    python3 site/tools/build_readme_diagrams.py            # rewrite the SVGs
    python3 site/tools/build_readme_diagrams.py --check    # exit 1 if any differs

The system: a pearl canvas, white cards with a thin role-coloured accent bar,
system sans type on a fixed scale, graphite ink with blue kept for data and
dispatch flow, green for code gates and warm red for isolation / arbitration.
Every diagram is a single 520-unit column so it still reads on a phone.

Motion is SMIL <animateMotion> pulses along the connectors plus a few CSS
keyframes. No script, no external font or image, no filter (a filter rasterises
the text beneath it) — so the diagrams animate inside the README's <img>, stop
under prefers-reduced-motion, and the first frame is already complete.

Every label is sourced from the code or docs it names; change the wording here,
not in the SVG. `fits()` warns when a label would overflow its box, and the
build refuses to write while it does.
"""
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ASSETS = Path(__file__).resolve().parents[1] / 'assets'
W, M = 520, 24          # canvas width, outer margin
CW = W - 2 * M          # content width

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

    def __init__(self, title, desc):
        self.title, self.desc = title, desc
        self.parts, self.n, self.h = [], 0, 0

    def add(self, s):
        self.parts.append(s)

    def text(self, x, y, segs, cls='b', anchor='start', fill=INK):
        if isinstance(segs, str):
            segs = [(segs, fill)]
        spans = ''.join(f'<tspan fill="{c}">{escape(t)}</tspan>' for t, c in segs)
        a = f' text-anchor="{anchor}"' if anchor != 'start' else ''
        self.add(f'<text x="{x:g}" y="{y:g}" class="{cls}"{a}>{spans}</text>')

    # --- building blocks -------------------------------------------------
    def header(self, kicker, title, sub, legend):
        self.text(M, 46, kicker, 'kick', fill=ROLE['blue'])
        y = 80
        for line in title:
            fits(line, 'title', CW, 'title')
            self.text(M, y, line, 'title')
            y += 30
        y += 2
        for line in sub:
            fits(line, 'sub', CW, 'sub')
            self.text(M, y, line, 'sub', fill=MUT)
            y += 21
        x, y = M, y + 10
        for label, role in legend:
            w = width(label, 'm') + 22
            if x + w > W - M:
                x, y = M, y + 22
            self.add(f'<circle cx="{x + 5}" cy="{y - 4.5}" r="4.5" fill="{ROLE[role]}"/>')
            self.text(x + 15, y, label, 'm', fill=MUT)
            x += w + 14
        self.add(f'<path d="M{M} {y + 20}H{W - M}" stroke="{CARD_STROKE}"/>')
        return y + 20

    def section(self, y, label):
        self.text(M, y, label, 'kick', fill=FAINT)

    def card(self, x, y, w, h, role, tint=False):
        fill = TINT[role] if tint else '#ffffff'
        self.add(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="12" fill="{fill}" '
                 f'stroke="{CARD_STROKE}" stroke-width="1.2"/>')
        self.add(f'<path d="M{x + 1.5:g} {y + 12:g}V{y + h - 12:g}" stroke="{ROLE[role]}" '
                 f'stroke-width="4" stroke-linecap="round"/>')

    def tag(self, x, y, label, role, anchor='start'):
        w = width(label, 'tag') + 16
        if anchor == 'end':
            x -= w
        self.add(f'<rect x="{x:g}" y="{y - 14:g}" width="{w:g}" height="20" rx="10" fill="{TINT[role]}"/>')
        self.text(x + w / 2, y, [(label, ROLE[role])], 'tag', anchor='middle')
        return w

    def chip(self, x, y, w, label, cls='m', fill=INK, bg=CHIP):
        fits(label, cls, w - 12, f'chip {label}')
        self.add(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="30" rx="9" fill="{bg}" stroke="{CARD_STROKE}"/>')
        self.text(x + w / 2, y + 20, [(label, fill)], cls, anchor='middle')

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
        }
        self.add(f'<g class="hero-icon" data-icon="{name}" transform="translate({x:g} {y:g}) scale({size / 24:g})" '
                 f'fill="none" stroke="{ROLE[role]}" stroke-width="1.7" stroke-linecap="round" '
                 f'stroke-linejoin="round" aria-hidden="true">{shapes[name]}</g>')

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
            for r, op in ((7, .16), (3.4, 1)):
                self.add(f'<circle class="pulse" r="{r}" fill="{c}" fill-opacity="{op}">'
                         f'<animateMotion dur="{dur}s" begin="{-b:.2f}s" repeatCount="indefinite" '
                         f'keyPoints="0;1" keyTimes="0;1" calcMode="spline" keySplines=".45 0 .55 1">'
                         f'<mpath href="#{pid}" xlink:href="#{pid}"/></animateMotion></circle>')

    def down(self, x, y1, y2, **kw):
        self.wire(f'M{x:g} {y1:g}V{y2 - 2:g}', **kw)

    def curve(self, x1, y1, x2, y2, **kw):
        ym = (y1 + y2) / 2
        self.wire(f'M{x1:g} {y1:g}C{x1:g} {ym:g} {x2:g} {ym:g} {x2:g} {y2 - 2:g}', **kw)

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
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                f'width="{W}" height="{h}" viewBox="0 0 {W} {h}" role="img" aria-labelledby="title desc">\n'
                f'  <title id="title">{escape(self.title)}</title>\n'
                f'  <desc id="desc">{escape(self.desc)}</desc>\n'
                '  <!-- Generated by site/tools/build_readme_diagrams.py; edit the builder, not this file. -->\n'
                '  <defs><linearGradient id="page" x1="0" y1="0" x2="1" y2="1">'
                '<stop offset="0" stop-color="#fbfbfc"/><stop offset=".6" stop-color="#f4f6f8"/>'
                '<stop offset="1" stop-color="#edf1f4"/></linearGradient>'
                f'<marker id="arr" markerWidth="10" markerHeight="10" refX="6" refY="5" orient="auto" '
                f'markerUnits="userSpaceOnUse"><path d="M1 1.5L6.5 5L1 8.5" fill="none" stroke="{LINE}" '
                f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></marker>'
                f'<style>{style}</style></defs>\n'
                f'  <rect x=".5" y=".5" width="{W - 1}" height="{h - 1}" rx="22" fill="url(#page)" stroke="#e1e6eb"/>\n')
        return head + '\n'.join('  ' + p for p in self.parts) + '\n</svg>\n'


def columns(n, gap=12, x0=M, w=CW):
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
    """site/assets/harnesses.svg — README hero: several agent harnesses, one desk."""
    d = D('clawock desk — several agent harnesses coexist and hand work to each other',
          'OpenClaw (kcn chat), DeepSeek Harness (a sidebar task chip that reorders, retries and '
          'cancels queued work) and the clawock-patrol service start work through one '
          'agent-dispatch runner; any interactive coding session that names a worker dispatches '
          'the same way. The runner gives each task its own systemd unit and arbitrates: one lock '
          'and queue per agent, patrol rounds last, run slots per agent from the host limits.env, a '
          'session lock so no two tasks resume one session, quota waits that free the agent lock, '
          'and dispatched workers never dispatch again. Claude Code, Codex and OpenCode share one '
          'AGENTS.md, one memory store and the same skills, and hand work on with dispatch.sh '
          'append and result or review each other with --template review. Every change lands in '
          'KCNyu/clawock through its own worktree and branch, then the same PR, required CI and '
          'squash-merge gate; the runner reports through result.env to WeChat and Telegram.')
    y = d.header('ONE DESK · MANY AGENT HARNESSES',
                 ['Different agents, one desk:', 'they hand work to each other'],
                 ['OpenClaw, Claude Code, Codex, OpenCode and DeepSeek',
                  'Harness share one runner, one memory and one gate.'],
                 [('harness · agent', 'slate'), ('dispatch', 'blue'), ('shared context', 'violet'),
                  ('merge gate', 'green'), ('isolation · arbitration', 'warm')])

    # who starts work
    y += 34
    d.section(y, 'WHO STARTS WORK')
    y += 14
    xs, cw = columns(3)
    entries = [
        ('openclaw', ['OpenClaw'], ["kcn's chat;", 'names a worker']),
        ('deepseek-harness', ['DeepSeek', 'Harness'], ['sidebar task chip', 'steers the queue']),
        ('clawock', ['clawock-', 'patrol'], ['review rounds,', 'always last']),
    ]
    eh = 150
    for x, (logo, title, body) in zip(xs, entries):
        d.card(x, y, cw, eh, 'slate')
        d.logo(logo, x + cw / 2 - 17, y + 14)
        ty = y + 72
        for t in title:
            fits(t, 'h', cw - 16, 'entry')
            d.text(x + cw / 2, ty, t, 'h', anchor='middle')
            ty += 19
        for i, t in enumerate(body):
            fits(t, 'm', cw - 14, 'entry body')
            d.text(x + cw / 2, y + eh - 36 + i * 18, t, 'm', anchor='middle', fill=MUT)
    y += eh
    ry = y + 56
    for i, x in enumerate(xs):
        d.curve(x + cw / 2, y, W / 2, ry, pulses=(i * .7,), dur=2.2)

    # the runner
    rh = 234
    d.card(M, ry, CW, rh, 'blue')
    d.text(M + 20, ry + 32, 'agent-dispatch', 'h')
    d.tag(W - M - 16, ry + 30, 'ONE RUNNER', 'blue', anchor='end')
    d.text(M + 20, ry + 54, 'a systemd unit per task · task_queue_ops.py orders', 'm', fill=MUT)
    fits('a systemd unit per task · task_queue_ops.py orders', 'm', CW - 36, 'runner sub')
    d.text(M + 20, ry + 74, 'called the same way by any session that names a worker', 'm', fill=MUT)
    fits('called the same way by any session that names a worker', 'm', CW - 36, 'runner sub')
    rows = ['One lock and one queue per agent', 'Patrol rounds last; a long wait is protected',
            'Run slots per agent, set in host limits.env', 'Session lock: one resume per session',
            'A quota wait frees the agent lock', 'Dispatched workers never re-dispatch']
    sweep(d, M + 12, ry + 90, CW - 24, len(rows), lh=22)
    d.bullets(M + 22, ry + 106, CW - 40, rows)

    # workers inside the shared-context frame
    fy = ry + rh + 46
    wy = fy + 18
    wh = 134
    ay = wy + wh                      # relay arcs hang below the worker cards
    ky = ay + 52                      # the shared-context label and chips
    fh = ky - fy + 84
    d.add(f'<rect x="{M:g}" y="{fy:g}" width="{CW:g}" height="{fh}" rx="16" fill="{TINT["violet"]}" '
          f'stroke="#dcd8ee" stroke-dasharray="4 4"/>')
    for i, x in enumerate(xs):
        d.curve(W / 2, ry + rh, x + cw / 2, wy, pulses=(i * .6,), dur=2.2)
    workers = [('claude-code', 'Claude Code', 'writes · reviews'),
               ('codex', 'Codex', 'writes · reviews'),
               (None, 'OpenCode', 'patrol · explores')]
    for x, (logo, name, body) in zip(xs, workers):
        d.card(x, wy, cw, wh, 'slate')
        if logo:
            d.logo(logo, x + cw / 2 - 17, wy + 12)
        else:  # OpenCode ships no logo in this repository: its name, set as text
            d.wordmark_tile(x + cw / 2 - 17, wy + 12, 34, 'open', 'code')
        fits(name, 'h', cw - 16, 'worker')
        d.text(x + cw / 2, wy + 70, name, 'h', anchor='middle')
        d.text(x + cw / 2, wy + 94, body, 'm', anchor='middle', fill=MUT)
        d.add(f'<circle class="breathe" cx="{x + cw / 2 - width("own unit", "m") / 2 - 8:g}" '
              f'cy="{wy + wh - 13:g}" r="3.5" fill="{ROLE["warm"]}"/>')
        d.text(x + cw / 2 + 4, wy + wh - 8, 'own unit', 'm', anchor='middle', fill=ROLE['warm'])
    # relay arcs: work handed on between workers, both ways
    for a, b in ((0, 1), (1, 2)):
        x1, x2 = xs[a] + cw / 2, xs[b] + cw / 2
        d.wire(f'M{x1 + 16:g} {ay:g}C{x1 + 16:g} {ay + 30:g} {x2 - 16:g} {ay + 30:g} {x2 - 16:g} {ay + 2:g}',
               pulses=(0,), dur=1.8, arrow=False, color='#b9b2dc', pulse=ROLE['violet'])
        d.wire(f'M{x2 - 28:g} {ay:g}C{x2 - 28:g} {ay + 20:g} {x1 + 28:g} {ay + 20:g} {x1 + 28:g} {ay + 2:g}',
               pulses=(.9,), dur=1.8, arrow=False, color='#b9b2dc', pulse=ROLE['violet'])
    d.text(W / 2, ay + 44, [('hand work on: ', MUT), ('append · result · --template review', ROLE['violet'])],
           'm', anchor='middle')
    fits('hand work on: append · result · --template review', 'm', CW - 20, 'relay')
    d.text(M + 16, ky + 18, 'SHARED BY EVERY CODING AGENT', 'kick', fill=ROLE['violet'])
    cx, ccw = columns(3, gap=8, x0=M + 16, w=CW - 32)
    for x, label in zip(cx, ('one AGENTS.md', 'shared memory', 'same skills')):
        d.chip(x, ky + 30, ccw, label, fill=ROLE['violet'], bg='#ffffff')

    # one gate
    gy = fy + fh + 46
    d.down(W / 2, fy + fh, gy, pulses=(0, 1.1), dur=2.2, pulse=ROLE['green'])
    gh = 162
    d.card(M, gy, CW, gh, 'green')
    d.logo('clawock', M + 20, gy + 16, size=30)
    d.text(M + 60, gy + 37, 'KCNyu/clawock', 'h')
    d.tag(W - M - 16, gy + 36, 'ONE GATE', 'green', anchor='end')
    d.bullets(M + 22, gy + 74, CW - 40, ['Own worktree and branch per task',
                                         'PR → required CI → squash-merge',
                                         'Live checkout stays on master',
                                         'One identity: reviews go in reports'], role='green')
    by = gy + gh + 14
    xs2, cw2 = columns(2)
    d.chip(xs2[0], by, cw2, 'report → WeChat + Telegram', fill=MUT, bg='#ffffff')
    d.chip(xs2[1], by, cw2, 'merge → refresh_live.sh', fill=MUT, bg='#ffffff')
    return d.render(by + 30 + M)


# ---------------------------------------------------------------------------
def information_flow():
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
          'mirrors to Telegram when the send is not confirmed.')
    y = d.header('DATA FLOW · HK + US',
                 ['From eight source layers', 'to a delivered card'],
                 ['Python fetches, computes and settles; the model', 'only reads the files a run assembles.'],
                 [('source · fetch', 'blue'), ('python', 'green'), ('agent · LLM', 'slate'),
                  ('gate · watchdog', 'warm')])

    y += 30
    d.section(y, '1 · SOURCES')
    y += 14
    h = 178
    d.card(M, y, CW, h, 'blue')
    d.text(M + 20, y + 32, '8 information layers', 'h')
    d.tag(W - M - 16, y + 30, 'HK + US', 'blue', anchor='end')
    xs, cw = columns(2, gap=8, x0=M + 16, w=CW - 32)
    layers = ['L1 market', 'L2 filings', 'L3 capital flow', 'L4 news', 'L5 macro · mood',
              'L6 quant · risk', 'L7 book · FX', 'L8 backtest']
    for i, name in enumerate(layers):
        col, row = i % 2, i // 2
        d.chip(xs[col], y + 46 + row * 32, cw, name)
    top = y + h
    y = top + 44
    d.down(W / 2, top, y, pulses=(0, 1.1))

    h = 248
    d.card(M, y, CW, h, 'blue')
    d.text(M + 20, y + 32, 'Fetch with fallback', 'h')
    d.tag(W - M - 16, y + 30, 'ORDERED ROUTES', 'blue', anchor='end')
    fb = [(' → ', FAINT)]
    yy = d.kv(M + 20, y + 60, 84, CW - 36, [
        ('HK quotes', [[('Tencent + Eastmoney HK', INK)], [('→ stooq → yfinance', MUT)]]),
        ('US quotes', [[('Nasdaq', INK), (' → Eastmoney → Finnhub', MUT)],
                       [('→ Yahoo → yfinance', MUT)], [('→ Alpha Vantage → Polygon', MUT)]]),
        ('USD/HKD', [[('Frankfurter', INK), (' → exchangerate.host', MUT)], [('→ Yahoo', MUT)]]),
    ], lh=20)
    del fb
    d.add(f'<path d="M{M + 20:g} {yy - 6:g}H{W - M - 16:g}" stroke="{CARD_STROKE}"/>')
    d.lines(M + 20, yy + 14, CW - 36, [[('One throttled gateway for every live Eastmoney', MUT)],
                                       [('call; an empty fetch keeps the prior value.', MUT)]],
            cls='m', lh=19, where='fetch note')
    top = y + h
    y = top + 44
    d.down(W / 2, top, y, pulses=(.4, 1.5))

    h = 150
    d.card(M, y, CW, h, 'green')
    d.text(M + 20, y + 32, 'Portfolio + risk', 'h')
    d.tag(W - M - 16, y + 30, 'PYTHON', 'green', anchor='end')
    d.kv(M + 20, y + 60, 84, CW - 36, [
        ('reconcile', ['recompute every money field']),
        ('integrity', ['data-health gate on the book']),
        ('fx', ['HK + US sum only through it']),
        ('risk', ['β · vol · drawdown → risk.json']),
    ])
    top = y + h
    y = top + 30
    d.text(W / 2, y + 2, [('preflight', ROLE['green']), (' · only the blocks this run can use', MUT)],
           'm', anchor='middle')
    fits('preflight · only the blocks this run can use', 'm', CW, 'preflight label')
    d.down(W / 2, top, y - 14, arrow=False, pulses=())
    y += 34
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
    d.text(M + 20, y + 32, 'Agent', 'h')
    d.tag(W - M - 16, y + 30, 'LLM', 'slate', anchor='end')
    d.lines(M + 20, y + 58, CW - 36, ['Reads the context files, never fetches;',
                                      'the brief also writes plan.json.'], lh=21, where='agent')
    top = y + h
    y = top + 40
    d.down(W / 2, top, y, pulses=(0, 1.1), pulse=ROLE['green'])
    h = 96
    d.card(M, y, CW, h, 'green')
    d.text(M + 20, y + 32, 'Postflight', 'h')
    d.tag(W - M - 16, y + 30, 'PYTHON', 'green', anchor='end')
    d.lines(M + 20, y + 58, CW - 36, ['Validates the output, then publishes;',
                                      'sends WeChat and co-sends Telegram.'], lh=21, where='postflight')
    top = y + h
    y = top + 50
    outs = [('Deliver', ['WeChat +', 'Telegram']),
            ('data-plane', ['7 files, one', 'generation']),
            ('master', ['ledger +', 'pre-push gate'])]
    h = 100
    for i, (x, (name, body)) in enumerate(zip(xs, outs)):
        d.curve(W / 2, top, x + cw / 2, y, pulses=(i * .5,), dur=1.8)
        d.card(x, y, cw, h, 'blue')
        d.text(x + 16, y + 30, name, 'h')
        d.lines(x + 16, y + 56, cw - 24, body, cls='m', lh=20, where='outputs')
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
    d.text(M + 20, y + 32, 'Watchdog', 'h')
    d.tag(W - M - 16, y + 30, 'CRONTAB · NO LLM', 'warm', anchor='end')
    yy = d.kv(M + 20, y + 60, 84, CW - 36, [
        ('brief', [[('08:36', INK), (' · miss check 09:05', MUT)]]),
        ('report', ['10–20 min after its slot']),
        ('intraday', [':13 and :43']),
    ])
    d.text(M + 20, yy + 2, 'Unconfirmed send → mirror to Telegram', 'm', fill=ROLE['warm'])
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
                  ('gate', 'warm')])
    RAIL = W - M - 6          # the return loop runs up the right edge
    IW = CW - 30              # inner column, leaving room for the loop
    y += 30
    d.section(y, '01 · EVIDENCE')
    y += 14
    ey = y
    h = 118
    d.card(M, y, IW, h, 'green')
    d.text(M + 20, y + 32, 'Evidence pack', 'h')
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
    d.text(M + 20, y + 30, 'Four analyst lenses', 'h')
    d.tag(M + IW - 16, y + 28, 'LLM', 'slate', anchor='end')
    d.text(M + 20, y + 54, 'fundamental · technical · sentiment · sector', 'm', fill=MUT)
    fits('fundamental · technical · sentiment · sector', 'm', IW - 36, 'lenses')
    top = y + h
    y = top + 44
    xs, cw = columns(3, gap=10, x0=M, w=IW)
    fork = [('Bull case', 'hold / add', 'green'), ('Bear case', 'trim / cut', 'warm'),
            ('Risk voices', 'three of them', 'slate')]
    h = 84
    for i, (x, (name, body, role)) in enumerate(zip(xs, fork)):
        d.curve(M + IW / 2, top, x + cw / 2, y, pulses=(i * .5,), dur=1.8, pulse=ROLE['slate'])
        d.card(x, y, cw, h, role)
        fits(name, 'h', cw - 24, 'fork')
        d.text(x + 16, y + 32, name, 'h')
        d.text(x + 16, y + 56, body, 'm', fill=MUT)
    top = y + h
    y = top + 48
    for i, x in enumerate(xs):
        d.curve(x + cw / 2, top, M + IW / 2, y, pulses=(i * .5 + .3,), dur=1.8, pulse=ROLE['slate'])
    h = 96
    d.card(M, y, IW, h, 'slate')
    d.text(M + 20, y + 32, 'Judge', 'h')
    d.tag(M + IW - 16, y + 30, 'LLM', 'slate', anchor='end')
    d.lines(M + 20, y + 58, IW - 36, ['Names the strategy frame of each call:',
                                      [('action · trigger · confidence → plan.json', MUT)]], lh=21, where='judge')
    top = y + h
    y = top + 50
    d.section(y - 14, '03 · DECISION CONTRACT')
    d.down(M + IW / 2, top, y, pulses=(0, 1.1), pulse=ROLE['green'])
    h = 134
    d.card(M, y, IW, h, 'green')
    d.text(M + 20, y + 32, 'Code gate', 'h')
    d.tag(M + IW - 16, y + 30, 'PYTHON', 'green', anchor='end')
    d.bullets(M + 22, y + 62, IW - 40, ['plan.json schema: fields, enums, confidence',
                                        'Brief sections: tiers, judge, next session',
                                        'A risk breach the plan ignores is flagged'], role='green')
    top = y + h
    y = top + 48
    xs, cw = columns(3, gap=10, x0=M, w=IW)
    pubs = [('Ledger', 'decisions.jsonl'), ('Brief', 'the chat card'), ('Dashboard', 'data-plane')]
    h = 76
    for i, (x, (name, body)) in enumerate(zip(xs, pubs)):
        d.curve(M + IW / 2, top, x + cw / 2, y, pulses=(i * .5,), dur=1.8)
        d.card(x, y, cw, h, 'blue')
        d.text(x + 16, y + 30, name, 'h')
        fits(body, 'm', cw - 24, 'pub')
        d.text(x + 16, y + 54, body, 'm', fill=MUT)
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
        d.add(f'<circle cx="{M + 30:g}" cy="{yy - 5:g}" r="11" fill="{TINT["blue"]}"/>')
        d.text(M + 30, yy, str(i + 1), 'tag', anchor='middle', fill=ROLE['blue'])
        d.text(M + 52, yy, name, 'b')
        fits(body, 'm', IW - 70, 'settle')
        d.text(M + 52, yy + 20, body, 'm', fill=MUT)
        if i:
            d.add(f'<path d="M{M + 30:g} {yy - 30:g}V{yy - 18:g}" stroke="{LINE}" stroke-width="1.5"/>')
    bottom = y + h
    # the loop: the scorecard feeds the next brief's evidence
    d.wire(f'M{M + IW:g} {bottom - 30:g}H{RAIL - 8:g}Q{RAIL:g} {bottom - 30:g} {RAIL:g} {bottom - 38:g}'
           f'V{ey + 40:g}Q{RAIL:g} {ey + 32:g} {RAIL - 8:g} {ey + 32:g}H{M + IW + 4:g}',
           pulses=(0, 2.5), dur=5, color='#b8c9d8')
    d.add(f'<text x="{RAIL + 4:g}" y="{(ey + bottom) / 2:g}" class="kick" fill="{ROLE["blue"]}" '
          f'transform="rotate(90 {RAIL + 4:g} {(ey + bottom) / 2:g})" text-anchor="middle">FEEDS THE NEXT BRIEF</text>')
    return d.render(bottom + M)


# ---------------------------------------------------------------------------
def product_architecture():
    """site/assets/product-architecture.svg — runtime / package / instance ownership."""
    d = D('clawock product architecture',
          'External agent runtimes own the model, conversation, memory, planning, tools, permissions '
          'and credentials. They install a standard skill and call the clawock CLI using JSON. The '
          'clawock package owns portable decision workflows, certified inputs, artifact contracts, '
          'deterministic money and foreign-exchange reconciliation, outcome evaluation, receipts, '
          'and bounded proposal review and rollback. User instances own strategy, evidence, ledgers, '
          'schedules, delivery and user interfaces. Every harness drives the same three steps: '
          'clawock run prepare, the agent writes decision.json, clawock run publish.')
    y = d.header('PRODUCT ARCHITECTURE · RUNTIME NEUTRAL',
                 ['The runtime thinks.', 'clawock keeps it reconciled.'],
                 ['Three owners, one contract between them:', 'skill + CLI + JSON in, adapter-owned I/O out.'],
                 [('external runtime', 'slate'), ('clawock package', 'green'), ('user instance', 'violet')])
    y += 30
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
        d.text(M + 54, yy, [(name, INK), (' · ', FAINT), (what, MUT)], 'm')
        fits(name + ' · ' + what, 'm', CW - 70, 'stage')
        d.text(M + 54, yy + 20, cmd, 'code', fill=ROLE['green'])
    top = y + h
    y = top + 44
    d.down(W / 2, top, y, pulses=(0,), pulse=ROLE['violet'])
    d.text(W / 2 + 14, top + 26, 'adapter-owned I/O', 'm', fill=MUT)
    h = 118
    d.card(M, y, CW, h, 'violet')
    d.text(M + 20, y + 32, 'Your instance', 'h')
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
    h = 76
    for i, (x, (name, body, role)) in enumerate(zip(xs, stepsb)):
        d.card(x, y, cw, h, role)
        d.text(x + 16, y + 30, name, 'b')
        fits(body, 'm', cw - 24, 'steps')
        d.text(x + 16, y + 54, body, 'm', fill=MUT)
        if i:
            d.wire(f'M{x - 17:g} {y + h / 2:g}H{x - 3:g}', pulses=(i * .4,), dur=1.2)
    y += h + 26
    d.lines(M, y, CW, ['Drop the opposing evidence from decision.json and',
                       'publish refuses it with exit code 1.'], cls='m', lh=19, where='steps note')
    return d.render(y + 20 + M)


# ---------------------------------------------------------------------------
def debate_flow():
    """site/assets/debate-flow.svg — the three-tier debate inside the pre-open brief."""
    d = D('Inside the clawock multi-agent debate',
          "A pipeline. One shared evidence pack feeds four analyst lenses that merge into a single "
          "table. Two researchers are asked to argue opposing bull and bear cases and to record where "
          "they disagree, so unanimous agreement reads as a flag. Three risk voices then stress every "
          "call and a judge names the strategy frame driving each decision, resolving the argument "
          "into plan.json — which enters the next session's grading pipeline, where code, not the "
          "model, settles the score.")
    y = d.header('THE DEBATE · HK + US',
                 ['Disagreement is required.', 'The resolution is attributed.'],
                 ['Protocol rules set in the brief prompt; code only', 'checks that each tier was written.'],
                 [('evidence · python', 'green'), ('agents · LLM', 'slate'), ('opposing case', 'warm'),
                  ('grading', 'blue')])
    y += 30
    d.section(y, 'SHARED INPUT')
    y += 14
    h = 76
    d.card(M, y, CW, h, 'green')
    d.text(M + 20, y + 30, [('context.json', INK)], 'h')
    d.text(M + 20, y + 54, 'one immutable evidence pack; every claim cites it', 'm', fill=MUT)
    top = y + h
    d.section(top + 34, 'TIER 1 · ANALYST LENSES')
    y = top + 48
    d.down(W / 2, top, y, pulses=(0,), pulse=ROLE['slate'])
    h = 150
    d.card(M, y, CW, h, 'slate')
    d.text(M + 20, y + 32, 'Four analyst lenses', 'h')
    d.tag(W - M - 16, y + 30, 'LLM', 'slate', anchor='end')
    xs, cw = columns(2, gap=8, x0=M + 16, w=CW - 32)
    for i, name in enumerate(['Fundamental', 'Technical', 'Sentiment', 'Sector rotation']):
        d.chip(xs[i % 2], y + 46 + (i // 2) * 36, cw, name)
    d.text(M + 20, y + h - 14, 'same context → one merged table', 'm', fill=MUT)
    top = y + h
    d.section(top + 34, 'TIER 2 · RESEARCHERS')
    y = top + 48
    d.down(W / 2, top, y, pulses=(0,), pulse=ROLE['slate'])
    h = 96
    xs, cw = columns(2, gap=40)
    for x, (name, body, sub, role) in zip(xs, (('Bull case', 'hold / add', 'cites the pack', 'green'),
                                              ('Bear case', 'trim / cut', 'hits the strongest view', 'warm'))):
        d.card(x, y, cw, h, role)
        d.text(x + 18, y + 32, name, 'h', fill=ROLE[role])
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
    d.section(top + 34, 'TIER 3 · RISK + JUDGE')
    fy = top + 48
    d.wire(f'M{W / 2:g} {top:g}V{fy:g}', pulses=(), arrow=False)
    y = fy + 40
    xs, cw = columns(3, gap=10)
    for i, (x, name) in enumerate(zip(xs, ('Aggressive', 'Conservative', 'Neutral'))):
        d.curve(W / 2, fy, x + cw / 2, y, pulses=(i * .5,), dur=1.8, pulse=ROLE['slate'])
        d.card(x, y, cw, 50, 'slate')
        fits(name, 'b', cw - 20, 'risk')
        d.text(x + cw / 2 + 2, y + 31, name, 'b', anchor='middle')
    top = y + 50
    y = top + 46
    for i, x in enumerate(xs):
        d.curve(x + cw / 2, top, W / 2, y, pulses=(i * .5 + .3,), dur=1.8, pulse=ROLE['slate'])
    h = 96
    d.card(M, y, CW, h, 'slate')
    d.text(M + 20, y + 32, 'Judge', 'h')
    d.tag(W - M - 16, y + 30, 'ATTRIBUTED', 'slate', anchor='end')
    d.lines(M + 20, y + 58, CW - 36, ['Names the strategy frame driving each call',
                                      [('→ plan.json', ROLE['blue'])]], lh=21, where='judge')
    top = y + h
    y = top + 40
    d.down(W / 2, top, y, pulses=(0, 1.1))
    h = 76
    d.card(M, y, CW, h, 'blue')
    d.text(M + 20, y + 30, "Next session's grading", 'h')
    d.text(M + 20, y + 54, 'code, not the model, settles the score', 'm', fill=MUT)
    y += h + 26
    d.lines(M, y, CW, ['The bear attacks the strongest consensus, never the weakest;',
                       "the risk voices' first mover rotates every four trading days."],
            cls='m', lh=19, where='notes')
    return d.render(y + 20 + M)

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
          "brief reads. The model never grades itself.")
    d.logo('clawock', W - M - 34, 26)
    y = d.header('EVERY TRADING DAY · HK + US',
                 ['Raw market data in,', 'graded decisions out'],
                 ['Python collects, computes, gates and settles;',
                  'the agents only argue over the pack it assembles.'],
                 [('fetch · deliver', 'blue'), ('python · code gate', 'green'), ('agents · LLM', 'slate'),
                  ('never self-graded', 'warm')])

    # 01 collect
    y += 34
    d.section(y, '01 · COLLECT')
    y += 14
    h = 282
    d.card(M, y, CW, h, 'blue')
    d.icon('market', M + 20, y + 14)
    d.text(M + 50, y + 32, 'Market information', 'h')
    d.tag(W - M - 16, y + 30, '44 MODULES · 8 LAYERS', 'blue', anchor='end')
    for j, name in enumerate(('market', 'market', 'fx', 'filing', 'bars', 'news', 'chat', 'calendar')):
        d.icon(name, M + 18, y + 47 + j * 21, size=18)
    yy = d.kv(M + 44, y + 62, 82, CW - 60, [
        ('HK quotes', [[('Tencent + Eastmoney', INK), (' → stooq → yfinance', MUT)]]),
        ('US quotes', [[('Nasdaq', INK), (' → 6 more routes, in order', MUT)]]),
        ('USD/HKD', [[('Frankfurter', INK), (' → exchangerate.host → Yahoo', MUT)]]),
        ('filings', [[('SEC EDGAR + XBRL · HKEXnews', INK)]]),
        ('fundflow', [[('Eastmoney daily capital flow', INK)]]),
        ('news', [[('Eastmoney · Finnhub · Google News · 10jqka', INK)]]),
        ('sentiment', [[('Reddit · influencer radar', INK)]]),
        ('macro', [[('major indices · catalyst calendar', INK)]]),
    ], lh=21)
    d.add(f'<path d="M{M + 20:g} {yy - 6:g}H{W - M - 16:g}" stroke="{CARD_STROKE}"/>')
    d.lines(M + 20, yy + 14, CW - 36, [[('One throttled Eastmoney gateway; an empty fetch', MUT)],
                                       [('keeps the prior value instead of a blank.', MUT)]],
            cls='m', lh=19, where='collect note')
    top = y + h
    y = top + 48
    d.down(W / 2, top, y, pulses=(0, 1.1))

    # 02 compute and gate
    d.section(y - 12, '02 · COMPUTE AND GATE')
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
            y = top + 12
    top = y + h
    y = top + 12
    h = 91
    d.card(M, y, CW, h, 'green', tint=True)
    d.icon('shield', M + 20, y + 10, 'green')
    d.text(M + 50, y + 28, [('Backtest gate', INK)], 'b')
    d.tag(W - M - 16, y + 27, 'BEFORE IT COUNTS', 'green', anchor='end')
    d.lines(M + 20, y + 52, CW - 36,
            ['validated authority: bootstrap CI clears 50%',
             'prospective activation ≠ capped exploration'],
            cls='m', lh=21, where='backtest')
    top = y + h
    y = top + 30
    d.text(W / 2, y + 2, [('preflight', ROLE['green']), (' → one context pack per run', MUT)],
           'm', anchor='middle')
    fits('preflight → one context pack per run', 'm', CW, 'preflight label')
    loop_y = y - 3
    d.down(W / 2, top, y - 14, arrow=False, pulses=())
    y += 60
    d.down(W / 2, y - 52, y, pulses=(0, 1.1), pulse=ROLE['slate'])

    # 03 decide
    d.section(y - 12, '03 · DECIDE')
    h = 344
    d.card(M, y, CW, h, 'slate')
    d.icon('debate', M + 20, y + 14, 'slate')
    d.text(M + 50, y + 32, 'Swarm debate', 'h')
    d.tag(W - M - 16, y + 30, 'LLM · READ ONLY', 'slate', anchor='end')
    d.text(M + 20, y + 58, 'four analyst lenses', 'm', fill=MUT)
    ix, iw = M + 16, CW - 32
    lx, lw = columns(4, gap=6, x0=ix, w=iw)
    for x, name in zip(lx, ('fundamental', 'technical', 'sentiment', 'sector')):
        d.chip(x, y + 68, lw, name)
    ry = y + 98
    d.down(W / 2, ry, ry + 24, pulses=(0,), dur=1.6, pulse=ROLE['slate'])
    bx, bw = columns(2, gap=8, x0=ix, w=iw)
    by = ry + 26
    for x, (name, role, sub) in zip(bx, (('Bull', 'green', 'builds the case for'),
                                         ('Bear', 'warm', 'attacks the consensus'))):
        d.add(f'<rect x="{x:g}" y="{by:g}" width="{bw:g}" height="56" rx="10" fill="{TINT[role]}" '
              f'stroke="{CARD_STROKE}"/>')
        d.text(x + 14, by + 24, [(name, ROLE[role])], 'h')
        d.icon('up' if name == 'Bull' else 'down', x + bw - 36, by + 10, role)
        fits(sub, 'm', bw - 24, 'bull bear')
        d.text(x + 14, by + 45, sub, 'm', fill=MUT)
    d.text(W / 2, by + 76, [('must disagree on at least one position', ROLE['warm'])], 'm', anchor='middle')
    vy = by + 90
    d.down(W / 2, vy, vy + 22, pulses=(.5,), dur=1.6, pulse=ROLE['slate'])
    d.text(M + 20, vy + 42, 'three risk voices', 'm', fill=MUT)
    vx, vw = columns(3, gap=6, x0=ix, w=iw)
    for x, name in zip(vx, ('aggressive', 'conservative', 'neutral')):
        d.chip(x, vy + 52, vw, name)
    jy = vy + 114
    d.text(M + 20, jy, [('Judge', INK), (' names the strategy frame → ', MUT), ('plan.json', ROLE['slate'])],
           'b')
    fits('Judge names the strategy frame → plan.json', 'b', CW - 36, 'judge')
    top = y + h
    y = top + 44
    d.down(W / 2, top, y, pulses=(0, 1.1), pulse=ROLE['green'])

    # 04 deliver
    d.section(y - 12, '04 · DELIVER')
    h = 96
    d.card(M, y, CW, h, 'green')
    d.icon('shield', M + 20, y + 14, 'green')
    d.text(M + 50, y + 32, 'Postflight', 'h')
    d.tag(W - M - 16, y + 30, 'PYTHON', 'green', anchor='end')
    d.lines(M + 20, y + 58, CW - 36, [[('validates plan.json, books it in ', INK)],
                                      [('memory/decisions.jsonl', ROLE['green']), (', renders the card', INK)]],
            lh=21, where='postflight')
    top = y + h
    y = top + 44
    xs, cw = columns(3)
    outs = [('Brief card', ['report + card,', 'laid out by', 'code']),
            ('WeChat', ['co-sent to', 'Telegram; a', 'watchdog checks']),
            ('Dashboard', ['data-plane', 'branch, polled', 'every 60 s'])]
    h = 156
    for i, (x, (name, body)) in enumerate(zip(xs, outs)):
        d.curve(W / 2, top, x + cw / 2, y, pulses=(i * .5,), dur=1.8)
        d.card(x, y, cw, h, 'blue')
        d.text(x + 16, y + 30, name, 'h')
        d.lines(x + 16, y + 56, cw - 24, body, cls='m', lh=20, where='deliver')
        if i == 0:
            d.icon('filing', x + 16, y + 115, size=26)
        elif i == 1:
            d.icon('chat', x + 16, y + 115, size=26)
            d.icon('plane', x + 52, y + 115, size=26)
        else:
            d.icon('dashboard', x + 16, y + 115, size=26)
    top = y + h
    y = top + 44
    d.down(W / 2, top, y, pulses=(0, 1.1), pulse=ROLE['green'])

    # 05 settle and calibrate
    d.section(y - 12, '05 · SETTLE AND CALIBRATE')
    h = 244
    d.card(M, y, CW, h, 'green')
    d.icon('dashboard', M + 20, y + 14, 'green')
    d.text(M + 50, y + 32, 'Graded by code', 'h')
    d.tag(W - M - 16, y + 30, 'THE MODEL NEVER SCORES', 'warm', anchor='end')
    rows = [('mark-followed', 'what was actually executed'),
            ('settle', 'canonical bars, per episode'),
            ('calibrate', 'beta-binomial, earlier dates only'),
            ('shadow', 'followed calls vs buy-and-hold'),
            ('scorecard', 'public, losses included')]
    sweep(d, M + 12, y + 46, CW - 24, len(rows), lh=26)
    for i, (cmd, what) in enumerate(rows):
        yy = y + 64 + i * 26
        d.text(M + 20, yy, cmd, 'code', fill=ROLE['green'])
        fits(what, 'm', CW - 36 - 140, 'settle what')
        d.text(M + 160, yy, what, 'm')
    d.add(f'<path d="M{M + 20:g} {y + 196:g}H{W - M - 16:g}" stroke="{CARD_STROKE}"/>')
    d.text(M + 20, y + 222, [('↺ ', ROLE['blue']), ('tomorrow’s brief reads the record', MUT)], 'm')
    fits('↺ tomorrow’s brief reads the record', 'm', CW - 36, 'loop note')
    # the loop: the settled record returns to the next run's preflight
    gx = W - 11
    d.wire(f'M{W - M:g} {y + 214:g}H{gx:g}V{loop_y:g}H{W / 2 + width("preflight → one context pack per run", "m") / 2 + 10:g}',
           pulses=(0,), dur=4.5, dash=True, color='#9fc0da')
    return d.render(y + h + M)


DIAGRAMS = {
    'decision-pipeline.svg': decision_pipeline,
    'harnesses.svg': harnesses,
    'information-flow.svg': information_flow,
    'architecture.svg': architecture,
    'product-architecture.svg': product_architecture,
    'debate-flow.svg': debate_flow,
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
