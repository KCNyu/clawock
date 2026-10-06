"""Build the README diagrams in site/assets/ as one visual system.

    python3 site/tools/build_readme_diagrams.py            # rewrite the SVGs
    python3 site/tools/build_readme_diagrams.py --check    # exit 1 if any differs

The system: a pearl canvas washed with four soft colour fields, translucent
glass cards with a thin role-coloured accent bar, system sans type on a fixed
scale, graphite ink with blue kept for data and dispatch flow, green for code
gates and warm red for isolation / arbitration.

One composition per diagram, scaled identically on desktop and mobile.
The 1016 canvas uses at least 32-unit labels; the 1440 overview uses at least
46. At a 324 CSS-pixel image width both preserve a ten-pixel label floor.
Sources, receipt matrices, opposing cases, timelines and feedback rings each
own their reading shape. The primitives supply only the shared material.

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
import ast
import base64
import struct
import re
import xml.etree.ElementTree as ET
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ASSETS = Path(__file__).resolve().parents[1] / 'assets'
WIDE, M = 1016, 24      # house canvas and outer margin
GUTTER = 24
CW = (WIDE - 2 * M - GUTTER) / 2  # protected hero's two book panes
COL2 = CW + GUTTER
DESKTOP_WIDTHS = {'rsi-loop': 1440}  # the total-to-parts overview needs side regions

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
    # Single-composition diagrams. Legacy sizes above remain for the frozen hero.
    'display': (56, 750, .60), 'heading': (38, 700, .60),
    'body': (32, 450, .60), 'mono': (32, 500, .62),
    'overview': (46, 450, .60), 'overview_h': (48, 700, .60),
    'overview_title': (68, 750, .60),
}
GLOW = {color: role for role, color in ROLE.items()}   # pulse colour -> halo gradient id
WARN = []


def width(text, cls):
    size, _, adv = TYPE[cls]
    if cls not in {'display', 'heading', 'body', 'mono', 'overview', 'overview_h', 'overview_title'}:
        return len(text) * size * adv  # frozen hero's historical width contract
    if cls == 'mono':
        return len(text) * size * .62
    # Conservative glyph envelopes. Rendering checks also measure browser bboxes;
    # these envelopes keep generation independent of installed fonts.
    narrow = set(" ilIjft.,:;!'|()[]")
    broad = set('MWmw@%&')
    return size * sum(.36 if c in narrow else .95 if c in broad else
                      .74 if c.isupper() else .65 for c in text)


def fits(text, cls, room, where):
    need = width(text, cls)
    if need > room:
        WARN.append(f'{where}: "{text}" needs {need:.0f}, has {room:.0f}')


class D:
    """One diagram: collects SVG fragments on a fixed-width canvas."""

    def __init__(self, title, desc):
        self.title, self.desc = title, desc
        self.pw = WIDE
        self.parts, self.n, self.h = [], 0, 0

    def add(self, s):
        self.parts.append(s)

    def text(self, x, y, segs, cls='b', anchor='start', fill=INK):
        if isinstance(segs, str):
            segs = [(segs, fill)]
        spans = ''.join(f'<tspan fill="{c}">{escape(t)}</tspan>' for t, c in segs)
        a = f' text-anchor="{anchor}"' if anchor != 'start' else ''
        self.add(f'<text x="{x:g}" y="{y:g}" class="{cls}"{a}>{spans}</text>')

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

    def chip(self, x, y, w, label, cls='m', fill=INK, bg=CHIP, h=30):
        fits(label, cls, w - 12, f'chip {label}')
        self.add(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h}" rx="9" fill="{bg}" '
                 f'fill-opacity=".62" stroke="url(#rim)"/>')
        self.text(x + w / 2, y + h / 2 + (TYPE[cls][0] * .32 if cls == 'body' else 5),
                  [(label, fill)], cls, anchor='middle')

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
        self.add(f'<image data-obstacle="screenshot" x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" '
                 f'preserveAspectRatio="xMidYMid meet" href="{uri}">'
                 f'<title>Existing live-host capture: {escape(name)}</title></image>')
        return h


    # --- connectors --------------------------------------------------------
    def wire(self, d, pulses=(0,), dur=2.2, arrow=True, color=LINE, pulse=None, dash=False):
        self.n += 1
        pid = f'w{self.n}'
        marker = f'arrow-{GLOW[color]}' if color in GLOW else 'arr'
        mk = f' marker-end="url(#{marker})"' if arrow else ''
        ds = ' stroke-dasharray="3 5"' if dash else ''
        self.add(f'<path id="{pid}" d="{d}" fill="none" stroke="{color}" stroke-width="1.5"{ds}{mk}/>')
        for b in pulses:
            c = pulse or ROLE['blue']
            for r, fill in ((7, f'url(#glow-{GLOW[c]})'), (3.4, c)):
                self.add(f'<circle class="pulse" r="{r}" fill="{fill}">'
                         f'<animateMotion dur="{dur}s" begin="{-b:.2f}s" repeatCount="indefinite" '
                         f'keyPoints="0;1" keyTimes="0;1" calcMode="spline" keySplines=".45 0 .55 1">'
                         f'<mpath href="#{pid}" xlink:href="#{pid}"/></animateMotion></circle>')

    def render(self, h):
        style = (
            f'text{{font-family:{SANS}}}'
            + ''.join(f'.{k}{{font-size:{s}px;font-weight:{w}}}' for k, (s, w, _) in TYPE.items())
            + '.kick{letter-spacing:1.1px}.title{letter-spacing:-.5px}.h{letter-spacing:-.2px}'
            '.tag{letter-spacing:.9px}'
            f'.code,.mono{{font-family:{MONO}}}'
            '.breathe{animation:breathe 2.4s ease-in-out infinite}'
            '@keyframes breathe{50%{opacity:.35}}'
            '@media (prefers-reduced-motion:reduce){.pulse{display:none}.breathe,.sweep{animation:none}}'
        )
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
                ''.join(f'<marker id="arrow-{role}" markerWidth="14" markerHeight="14" refX="12" refY="7" orient="auto" markerUnits="userSpaceOnUse"><path d="M2 2L12 7L2 12" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></marker>' for role, color in ROLE.items())
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


# Original full descriptions remain accessible in every figure.
DESCRIPTIONS = {'scorecard': ('How clawock grades a call',
               'The model writes a versioned decision with its strategy, condition, regime, size '
               'and confidence into memory/decisions.jsonl. From there the model has no write '
               'access. Python evaluates the trigger against canonical unadjusted daily bars on '
               "each market's own calendar; an unfinished session grades nothing and a gap through "
               'a trigger fills at the open. Repeated calls on one thesis collapse into one '
               'episode. Code settles the outcome and scores it against a plain directional '
               'baseline, then publishes wins, losses and the cases that cannot be graded, which '
               'stay visible and out of the win-rate denominator. The record is a diagnostic, not '
               'proof of return.'),
 'information-flow': ('clawock data flow — sources, fetch fallback, portfolio and risk, three '
                      'cadences, agent, postflight, data plane and delivery',
                      'Eight information layers feed ordered fetch-fallback routes (HK quotes '
                      'Tencent plus Eastmoney HK, then stooq, then yfinance; US quotes Nasdaq, '
                      'Eastmoney, Finnhub, Yahoo, yfinance, Alpha Vantage, Polygon; USDHKD '
                      'Frankfurter, exchangerate.host, Yahoo; every live Eastmoney call through '
                      'one throttled gateway; an empty fetch keeps the prior value). Python '
                      'reconciles the book, runs the integrity gate and builds risk. The pre-open '
                      'brief, session reports and intraday check-ins each run a preflight that '
                      'assembles only the blocks that run can use; the agent reads those files and '
                      'never fetches; a Python postflight validates and publishes to master, to '
                      'the data-plane branch the dashboard polls, and to WeChat and Telegram. An '
                      'LLM-free crontab watchdog checks every slot and mirrors to Telegram when '
                      'the send is not confirmed.'),
 'product-architecture': ('clawock product architecture',
                          'External agent runtimes own the model, conversation, memory, planning, '
                          'tools, permissions and credentials. They install a standard skill and '
                          'call the clawock CLI using JSON. The clawock package owns portable '
                          'decision workflows, certified inputs, artifact contracts, deterministic '
                          'money and foreign-exchange reconciliation, outcome evaluation, '
                          'receipts, and bounded proposal review and rollback. User instances own '
                          'strategy, evidence, ledgers, schedules, delivery and user interfaces. '
                          'Every harness drives the same three steps: clawock run prepare, the '
                          'agent writes decision.json, clawock run publish.'),
 'harnesses': ('The clawock-dsh plugin — delegate, watch, steer, ship, hear back',
               'On a host configured with agent-dispatch, a user can ask in dsh chat to delegate '
               'repository work to Claude Code, Codex or OpenCode. The runner starts a background '
               'systemd task that outlives the conversation. The plugin shows provider allowances, '
               'each agent queue, running tasks, recent results and notification receipts. Its '
               'controls reorder waiting work, change the next attempt model where allowed, adjust '
               'budgets, retry an ended unfinished session or cancel a task through the audited '
               'ops entry. The repository task pictured requests an isolated branch, a PR, '
               'required CI, squash merge and host refresh; these are its delivery instructions, '
               'not automatic plugin actions. The runner records the report and sends best-effort '
               'WeChat and Telegram notifications, with delivery receipts visible in the panel. '
               'The queue image is an existing full-frame capture from a live host, not an example '
               'result.'),
 'start-here': ('Where to start with clawock',
                'Three readers and where each one starts. If you trade your own Hong Kong and US '
                'book, you get a plan before the open, cards through the session and a grade after '
                'the close, and you start with clawock init. If you already run an agent such as '
                'Claude Code, Codex, OpenClaw or DeepSeek Harness, you install the '
                'investment-decision workflow and your agent keeps the model call. If you want to '
                'see the record first, the live dashboard shows every call settled by code with '
                'the losses included. Underneath all three sits one contract: certified evidence, '
                'a required opposing case, checked money arithmetic and an outcome linked back to '
                'the decision.'),
 'debate-flow': ('Inside the clawock multi-agent debate',
                 'A pipeline. One shared evidence pack feeds four analyst lenses that merge into a '
                 'single table. Two researchers are asked to argue opposing bull and bear cases '
                 'and to record where they disagree, so unanimous agreement reads as a flag. Three '
                 'risk voices then stress every call and a judge names the strategy frame driving '
                 'each decision, resolving the argument into plan.json — which enters the next '
                 "session's grading pipeline, where code, not the model, settles the score."),
 'rsi-loop': ('RSI: one stock book, a continuing decision loop',
              'A total-to-parts overview: information sources at left; evidence, opposing-case '
              'decision and code-settled feedback at centre; runtime, human, code and review '
              'ownership at right; history, earlier-date calibration and reviewed evidence '
              'requirements return along the bottom to the next context. The human executes. '
              'Content certification is not a truth guarantee and measured feedback is not a '
              'promise of return.'),
 'guardrails': ('What clawock code enforces',
                'The model writes opinions; code enforces risk, money and evidence boundaries. '
                'Risk labels are generated from src/clawock/portfolio/guardrail.py:GUARDRAIL_CAPS. '
                'Execution stays human.'),
 'architecture': ('KCNyu live investment instance built with clawock contracts',
                  'This is the KCNyu deployment, not the reusable clawock product architecture. '
                  'Python assembles one immutable evidence pack. OpenClaw agents run four analyst '
                  'lenses, a bull case, a bear case and three risk voices, and a judge names the '
                  'strategy frame and writes plan.json. A Python decision contract validates '
                  'plan.json and the brief sections, and flags any risk breach the plan ignores, '
                  'before the ledger, brief and dashboard publish it. On the return path code '
                  'triggers each call against canonical unadjusted daily bars, groups repeated '
                  'calls into episodes, grades them against a directional baseline and publishes '
                  'the scorecard, which feeds the next brief.'),
 'evidence-receipt': ('Evidence matrix: source, output, check',
                      'Eight information families as a matrix, not a sequential feed: market, '
                      'filings, flow, news, macro/sentiment, quant/risk, book/FX and '
                      'backtest/calibration. Each source maps to an output and a check. Source '
                      'provenance is distinct from content certification; context and pack hashes '
                      'identify input, not truth. Credentials stay with the runtime.'),
 'decision-pipeline': ('clawock decision pipeline — collect, compute and gate, debate, deliver, '
                       'settle and calibrate',
                       'Every trading day Python collects quotes through ordered fallback chains '
                       '(HK Tencent plus Eastmoney, then stooq, then yfinance; US through a '
                       'seven-route chain; USD/HKD Frankfurter, exchangerate.host, Yahoo), SEC and '
                       'HKEX filings, Eastmoney capital flow, bilingual news, Reddit and '
                       'influencer sentiment, and macro and catalyst calendars. It reconciles the '
                       'book, computes portfolio risk (beta, volatility, drawdown), per-leg '
                       'concentration, the leverage regime dial, quant factors, cross-sectional '
                       'ranks and peer residuals. Validated factor authority requires a bootstrap '
                       'interval clear of 50%; prospective activation and capped exploration have '
                       'separate rules. Code gates hold risk caps, the entry gate, earnings '
                       'quality, thesis drift and the news evidence graph. A preflight hands the '
                       'agents one context pack; four analyst lenses, a bull and a bear who must '
                       'disagree, three risk voices and a judge write plan.json. A postflight '
                       'validates it, books it in memory/decisions.jsonl, renders the brief card, '
                       'sends WeChat and Telegram and publishes the dashboard. Python then records '
                       'what was executed (mark-followed), settles each episode on canonical bars, '
                       'calibrates confidence, replays a shadow portfolio against buy and hold and '
                       'publishes the scorecard, which the next brief reads. In dsh, Decision Mind '
                       'shows real fills beside their plans and T+1 verdicts; the trader can ask a '
                       'follow-up and record a conversation verdict. Execution stays human, the '
                       'trace is read-only, and the model never grades itself.'),
 'feedback-learning': ('Feedback: a live learning wheel and a portable adoption state machine',
                       'Left: a live loop connects execution evidence, canonical-bar episodes, '
                       'history and earlier-date calibration back to the next brief. Right: '
                       'portable source-linked outcome and directional evaluation can trigger a '
                       'bounded proposal; exact-hash named review accepts or rejects it, accepted '
                       'changes apply with rollback records. Only evidence/provenance strictness '
                       'changes, not strategy. Neither path promises returns.')}

class Canvas(D):
    """One immutable composition; card anchors and text bounds are testable."""

    def __init__(self, name, title):
        original_title, desc = DESCRIPTIONS[name]
        super().__init__(original_title, desc)
        self.pw = DESKTOP_WIDTHS.get(name, WIDE)
        self.nodes = {}
        self.font = 'overview' if self.pw == 1440 else 'body'
        self.head = 'overview_h' if self.pw == 1440 else 'heading'
        self.in_node = None
        self.add(f'<g data-diagram="{name}">')
        cls = 'overview_title' if self.pw == 1440 else 'display'
        self.wrap(36, 88, self.pw - 72, title, cls=cls)

    def text(self, x, y, segs, cls='body', anchor='start', fill=INK):
        super().text(x, y, segs, cls, anchor, fill)
        if self.in_node:
            self.parts[-1] = self.parts[-1].replace('<text ', f'<text data-in="{self.in_node}" ', 1)

    def wrap(self, x, y, room, text, cls=None, fill=INK, lh=None):
        cls = cls or self.font
        lh = lh or TYPE[cls][0] * 1.4
        rows = []
        line = ''
        for word in text.split():
            # Long artifact names still get exact text, with explicit visual line breaks.
            chunks = []
            chunk = ''
            for char in word:
                if width(chunk + char, cls) > room and chunk:
                    chunks.append(chunk)
                    chunk = ''
                chunk += char
            chunks.append(chunk)
            for i, part in enumerate(chunks):
                trial = (line + ' ' + part).strip()
                if width(trial, cls) > room and line:
                    rows.append(line)
                    line = part
                else:
                    line = trial
                if i < len(chunks) - 1:
                    rows.append(line)
                    line = ''
        if line:
            rows.append(line)
        for line in rows:
            fits(line, cls, room, 'single composition label')
            self.text(x, y, line, cls, fill=fill)
            y += lh
        return y

    def panel(self, node, x, y, w, h, title, rows=(), role='blue', region=None):
        self.nodes[node] = (x, y, w, h)
        attr = f' data-region="{region}"' if region else ''
        self.add(f'<g{attr}>')
        self.card(x, y, w, h, role)
        # The material has three rects; only its body is the semantic boundary.
        self.parts[-4] = self.parts[-4].replace('<rect ', f'<rect data-node="{node}" ', 1)
        self.in_node = node
        pos = self.wrap(x + 24, y + 68, w - 48, title, cls=self.head, fill=ROLE[role]) + 18
        for row in rows:
            pos = self.wrap(x + 24, pos, w - 48, row) + 10
        self.in_node = None
        self.add('</g>')
        return pos

    def chip(self, x, y, w, label, **kwargs):
        super().chip(x, y, w, label, cls=self.font, h=64, **kwargs)

    def glyph(self, name, x, y, role='blue', size=56):
        self.add(f'<svg data-obstacle="icon" x="{x}" y="{y}" width="{size}" height="{size}" viewBox="0 0 24 24">')
        self.icon(name, 0, 0, role, size=24)
        self.add('</svg>')

    def brand(self, name, x, y, size=56):
        first = len(self.parts)
        self.logo(name, x, y, size)
        self.parts[first] = self.parts[first].replace('<svg ', '<svg data-obstacle="brand" ', 1)

    def schematic(self, y):
        self.text(36, y, 'Schematic: price · factor ranks · risk', fill=MUT)
        xs, cw = columns(3, gap=32, x0=36, w=944)
        for x, role in zip(xs, ('blue', 'green', 'warm')):
            self.add(f'<svg data-obstacle="schematic" x="{x}" y="{y + 32}" width="{cw}" height="112" viewBox="0 0 300 112">')
            self.add(f'<rect x="0" y="0" width="300" height="112" rx="12" fill="{TINT[role]}"/>')
            if role == 'blue':
                self.add(f'<path d="M16 88L54 64L92 76L130 32L168 48L214 24L284 40" fill="none" stroke="{ROLE[role]}" stroke-width="4"/>')
            elif role == 'green':
                for j, h in enumerate((30, 58, 80, 40, 68)):
                    self.add(f'<rect x="{24 + j * 52}" y="{96 - h}" width="32" height="{h}" rx="5" fill="{ROLE[role]}" fill-opacity=".7"/>')
            else:
                for j, w in enumerate((244, 168, 92)):
                    self.add(f'<rect x="24" y="{22 + j * 28}" width="{w}" height="12" rx="6" fill="{ROLE[role]}" fill-opacity=".7"/>')
            self.add('</svg>')

    def anchor(self, node, side):
        x, y, w, h = self.nodes[node]
        return {'left': (x, y + h / 2), 'right': (x + w, y + h / 2),
                'top': (x + w / 2, y), 'bottom': (x + w / 2, y + h)}[side]

    def link(self, start, end, via=(), role='blue'):
        points = [self.anchor(*start), *via, self.anchor(*end)]
        path = ' '.join(f'{"M" if i == 0 else "L"}{x:g} {y:g}' for i, (x, y) in enumerate(points))
        begin = len(self.parts)
        self.wire(path, arrow=True, pulse=ROLE[role], color=ROLE[role])
        self.parts[begin] = self.parts[begin].replace('<path ',
            f'<path data-from="{start[0]}:{start[1]}" data-to="{end[0]}:{end[1]}" ', 1)
        self.parts[begin] = self.parts[begin].replace('stroke-width="1.5"',
            'stroke-width="3" stroke-linecap="round" stroke-linejoin="round"')

    def finish(self, h):
        self.add('</g>')
        svg = self.render(h)
        validate_geometry(svg)
        return svg


def rsi_loop():
    d = Canvas('rsi-loop', 'The stock-book decision loop')
    d.wrap(40, 188, 1360, 'Agent judges. Human trades. Code settles.')
    d.panel('sources', 40, 244, 208, 500, 'Feed',
            ['Quote', 'File', 'News', 'Event', 'Up?'], region='sources')
    for node, x, title, rows, role in (
        ('input', 288, 'Input', ['Who?', 'When?', 'Auth?', 'Hash', 'Packet'], 'blue'),
        ('decision', 584, 'Decide', ['Bull', 'Bear', 'Trigger', 'plan', '.json'], 'warm'),
        ('outcome', 880, 'Grade', ['Filled?', 'Bars', 'Settle', 'Known?', 'Ledger'], 'green')):
        d.panel(node, x, 244, 256, 500, title, rows, role, region=node)
    d.panel('owners', 1176, 244, 240, 500, 'Who',
            ['Agent', 'Human', 'Code', 'Review'], 'slate', region='owners')
    d.link(('sources', 'right'), ('input', 'left'))
    d.link(('input', 'right'), ('decision', 'left'))
    d.link(('decision', 'right'), ('outcome', 'left'), role='green')
    d.panel('return', 40, 844, 1360, 300, 'The next judgment uses the record',
            ['Calibrate from earlier dates. Review rules. Keep rollback.'], 'violet', region='return')
    d.link(('outcome', 'bottom'), ('return', 'top'), via=((1008, 794), (720, 794)), role='violet')
    d.link(('return', 'left'), ('input', 'top'),
           via=((20, 994), (20, 218), (416, 218)), role='violet')
    return d.finish(1192)


def evidence_receipt():
    d = Canvas('evidence-receipt', 'Evidence has a receipt')
    d.wrap(36, 168, 944, 'Source family · evidence · check')
    xs, cw = columns(3, gap=28, x0=36, w=944)
    d.panel('matrix', 36, 222, 944, 850, 'Different sources, different checks', role='blue')
    y = 370
    d.in_node = 'matrix'
    # A matrix has rows, not arrows. Align every cell to the same baselines.
    for family, evidence, check in (
        ('Market', 'Quotes + time', 'Fresh?'), ('Filings', 'SEC / HKEX', 'Primary?'),
        ('Flow', 'Capital flow', 'Complete?'), ('News', 'Dated cite', 'Old or live?'),
        ('Macro / view', 'Dates / views', 'Fact or view?'), ('Quant + risk', 'Factors, risk', 'Available?'),
        ('Book + FX', 'Ledger + rate', 'Balanced?'), ('Backtest', 'Bars + tests', 'OOS?')):
        for x, value in zip(xs, (family, evidence, check)):
            fits(value, d.font, cw - 48, 'matrix cell')
            d.text(x + 24, y, value)
        d.add(f'<path d="M60 {y + 26}H956" stroke="{CARD_STROKE}"/>')
        y += 80
    d.in_node = None
    d.panel('cert', 36, 1132, 944, 310, 'Content pinned. Truth still needs evidence.',
            ['request.json carries provenance and content hashes.',
             'Your harness owns credentials and permissions.'], 'green')
    d.link(('matrix', 'bottom'), ('cert', 'top'), role='green')
    return d.finish(1490)


def feedback_learning():
    d = Canvas('feedback-learning', 'Each call leaves a record')
    d.wrap(36, 168, 944, 'Live history closes the loop; portable changes need review.')
    d.panel('call', 376, 244, 264, 166, 'Decision', role='warm')
    d.panel('outcome', 696, 478, 284, 166, 'Outcome', role='green')
    d.panel('history', 376, 712, 264, 166, 'History', role='violet')
    d.panel('context', 36, 478, 284, 166, 'Context', role='blue')
    d.add('<circle cx="508" cy="561" r="100" fill="url(#glass)" stroke="url(#rim)"/>')
    d.text(508, 551, 'Next', anchor='middle')
    d.text(508, 603, 'judgment', anchor='middle')
    d.link(('call', 'right'), ('outcome', 'top'), via=((838, 327),), role='green')
    d.link(('outcome', 'bottom'), ('history', 'right'), via=((838, 795),), role='violet')
    d.link(('history', 'left'), ('context', 'bottom'), via=((178, 795),), role='blue')
    d.link(('context', 'top'), ('call', 'left'), via=((178, 327),), role='warm')
    d.panel('review', 36, 964, 944, 440, 'Portable improvement has an adoption gate',
            ['Observe → propose → named review → apply',
             'Only evidence / provenance rules change. Rollback stays recorded.'], 'slate')
    d.in_node = 'review'
    d.chip(60, 1320, 350, 'Strategy stays put')
    d.chip(440, 1320, 516, 'Direction ≠ realized P&L')
    d.in_node = None
    return d.finish(1452)


def start_here():
    d = Canvas('start-here', 'Start from your question')
    d.panel('question', 268, 192, 480, 152, 'What brings you here?', role='slate')
    xs, cw = columns(3, gap=40, x0=36, w=944)
    for node, x, title, rows, role in (
        ('book', xs[0], 'My book', ['Plan before open', 'Session cards', 'After-close grade', 'clawock init'], 'blue'),
        ('agent', xs[1], 'My agent', ['Keep your model', 'Install the skill', 'Call the CLI', 'Same artifacts'], 'green'),
        ('record', xs[2], 'The record', ['Open dashboard', 'Inspect the calls', 'Losses stay in', 'Read the receipts'], 'warm')):
        d.panel(node, x, 444, cw, 644, title, rows, role)
        d.link(('question', 'bottom'), (node, 'top'), via=((508, 394), (x + cw / 2, 394)))
    d.panel('contract', 36, 1188, 944, 242, 'Every route reaches the same contract',
            ['Certified input · opposing case · checked money · linked outcome'], 'violet')
    for node, x in zip(('book', 'agent', 'record'), xs):
        d.link((node, 'bottom'), ('contract', 'top'),
               via=((x + cw / 2, 1138), (508, 1138)), role='violet')
    return d.finish(1478)


def scorecard():
    d = Canvas('scorecard', 'Keep losses and unknowns')
    d.panel('decision', 36, 210, 432, 240, 'Decision', ['Human records execution.'], 'warm')
    d.panel('episode', 548, 210, 432, 240, 'Episode', ['Repeated stances count once.'], 'blue')
    d.link(('decision', 'right'), ('episode', 'left'))
    d.panel('settle', 268, 518, 480, 242, 'Code settles', ['Canonical bars + calendar'], 'green')
    d.link(('episode', 'bottom'), ('settle', 'top'), via=((764, 470), (508, 470)), role='green')
    xs, cw = columns(3, gap=40, x0=36, w=944)
    for node, x, title, rows, role in (
        ('win', xs[0], 'Win', ['Keep it', 'Read why'], 'green'),
        ('loss', xs[1], 'Loss', ['Keep it', 'Read why'], 'warm'),
        ('unknown', xs[2], 'Ungraded', ['Missing bars', 'Say why'], 'slate')):
        d.panel(node, x, 884, cw, 308, title, rows, role)
        d.link(('settle', 'bottom'), (node, 'top'), via=((508, 822), (x + cw / 2, 822)), role=role)
    d.wrap(36, 1284, 944, 'Directional accuracy is a diagnostic. It does not prove returns.')
    return d.finish(1420)


def risk_caps():
    """Read literal policy constants without importing runtime/market modules."""
    source = ASSETS.parents[1] / 'src/clawock/portfolio/guardrail.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    for assignment in tree.body:
        if isinstance(assignment, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == 'GUARDRAIL_CAPS'
                for target in assignment.targets):
            return ast.literal_eval(assignment.value)
    raise ValueError('GUARDRAIL_CAPS has no literal policy definition')


def guardrails():
    d = Canvas('guardrails', 'Opinions meet code boundaries')
    d.panel('risk', 36, 210, 944, 500, 'Risk caps are checked against the book', role='warm')
    # Source: src/clawock/portfolio/guardrail.py:GUARDRAIL_CAPS.
    # Threshold ticks, never fabricated current exposures. Two aligned columns.
    caps = risk_caps()
    rows = [('Leveraged name', f"≤ {caps['leveraged_single_name_pct']:g}%"),
            ('Core name', f"≤ {caps['single_name_mandatory_pct']:g}% / review {caps['single_name_review_pct']:g}%"),
            ('Correlated cluster', f"≤ {caps['correlated_cluster_pct']:g}%"),
            ('Leverage ETFs', f"≤ {caps['lev_etf_leg_pct']:g}%"),
            ('US portfolio beta', f"≤ {caps['us_beta_max']:.1f}"),
            ('ETF stop vs cost', f"{caps['lev_etf_stop_pct']:g}%".replace('-', '−'))]
    d.desc = ('Risk limits, not current exposures. Source: '
              'src/clawock/portfolio/guardrail.py:GUARDRAIL_CAPS. '
              + '; '.join(f'{label}: {cap}' for label, cap in rows)
              + '. Core review is advisory; a breach freezes same-risk adds until compliance. '
              'Currencies remain separate, the book reconciles before push, sources support '
              'numbers and a bear case is required. Execution stays human.')
    xs, cw = columns(2, gap=48, x0=60, w=896)
    d.in_node = 'risk'
    for index, (label, cap) in enumerate(rows):
        x, y = xs[index % 2], 366 + (index // 2) * 112
        d.text(x, y, label)
        d.text(x + 16, y + 52, cap, fill=ROLE['warm'])
        d.add(f'<path d="M{x:g} {y + 18:g}V{y + 66:g}" stroke="{ROLE["warm"]}" stroke-width="4"/>')
    d.in_node = None
    d.panel('money', 36, 782, 432, 530, 'Money', ['USD stays USD', 'HKD stays HKD', 'FX is sourced', 'Reconcile before push', 'Use the named basis'], 'green')
    d.panel('evidence', 548, 782, 432, 530, 'Evidence', ['Independent families', 'New facts move thesis', 'Sources back numbers', 'Bear case is required', 'Human places orders'], 'blue')
    d.link(('risk', 'bottom'), ('money', 'top'), via=((508, 746), (252, 746)), role='green')
    d.link(('risk', 'bottom'), ('evidence', 'top'), via=((508, 746), (764, 746)), role='blue')
    return d.finish(1360)


def information_flow():
    d = Canvas('information-flow', 'Many feeds. One context.')
    xs, cw = columns(3, gap=40, x0=36, w=944)
    for node, x, title, rows in (
        ('hk', xs[0], 'HK quotes', ['Tencent + Eastmoney', 'Then stooq', 'Then yfinance']),
        ('us', xs[1], 'US quotes', ['Nasdaq first', 'Ordered fallback', 'Failure is explicit']),
        ('fx', xs[2], 'USD / HKD', ['Frankfurter', 'FX fallback', 'Then Yahoo'])):
        d.panel(node, x, 210, cw, 500, title, rows, 'blue')
        d.glyph('fx' if node == 'fx' else 'market', x + 24, 610)
    d.panel('fetch', 36, 830, 944, 210, 'Fetch → reconcile → risk → context',
            ['Documented source layers. Failures stay visible.'], 'green')
    for node, x in zip(('hk', 'us', 'fx'), xs):
        d.link((node, 'bottom'), ('fetch', 'top'), via=((x + cw / 2, 770), (508, 770)), role='green')
    for node, x, title, rows in (
        ('brief', xs[0], 'Brief', ['Before open', 'Plan + triggers']),
        ('session', xs[1], 'Report', ['After session', 'Settle + reflect']),
        ('intraday', xs[2], 'Intraday', ['During session', 'Check what changed'])):
        d.panel(node, x, 1160, cw, 340, title, rows, 'slate')
        d.link(('fetch', 'bottom'), (node, 'top'), via=((508, 1100), (x + cw / 2, 1100)))
    d.panel('send', 36, 1620, 944, 310, 'Validated output reaches the reader',
            ['Postflight → dashboard + WeChat + Telegram', 'Watchdog checks each slot; receipts track delivery.'], 'violet')
    for node, x in zip(('brief', 'session', 'intraday'), xs):
        d.link((node, 'bottom'), ('send', 'top'), via=((x + cw / 2, 1560), (508, 1560)), role='violet')
    return d.finish(1978)


def product_architecture():
    d = Canvas('product-architecture', 'Any harness. Clear owners.')
    d.panel('runtime', 36, 210, 944, 360, 'Your runtime owns the agent',
            ['Claude Code · Codex · OpenClaw · DeepSeek Harness · any CLI',
             'Model, conversation, tools, memory, credentials and permissions.'], 'slate')
    d.panel('boundary', 128, 666, 760, 222, 'Skill + CLI + JSON',
            ['prepare → your agent writes → publish'], 'blue')
    d.link(('runtime', 'bottom'), ('boundary', 'top'))
    for x, logo in zip((60, 244, 428, 612, 796), ('claude-code', 'codex', 'openclaw', 'deepseek-harness', 'any-cli')):
        d.brand(logo, x, 600, size=48)
    d.panel('package', 36, 984, 944, 340, 'clawock owns the decision contract',
            ['Certified inputs · validation · money + FX reconciliation',
             'Evaluation · receipts · reviewed improvement · rollback'], 'green')
    d.link(('boundary', 'bottom'), ('package', 'top'), role='green')
    d.panel('instance', 36, 1420, 944, 310, 'Your workspace owns the continuity',
            ['Strategy, evidence, ledgers, schedules, delivery and views.',
             'Keep the artifacts and reconnect them to the next harness.'], 'violet')
    d.link(('package', 'bottom'), ('instance', 'top'), role='violet')
    return d.finish(1778)


def debate_flow():
    d = Canvas('debate-flow', 'A call faces its opposite')
    d.panel('pack', 268, 210, 480, 164, 'Shared evidence packet', role='blue')
    d.panel('lenses', 36, 478, 944, 240, 'Analyst lenses',
            ['Fundamentals · news · sentiment · technicals'], 'slate')
    d.link(('pack', 'bottom'), ('lenses', 'top'))
    for x, icon in zip((80, 304, 528, 752), ('lens', 'news', 'chat', 'factor')):
        d.glyph(icon, x, 658, 'slate', size=48)
    d.panel('bull', 36, 838, 432, 280, 'Bull case', ['Why this action?', 'What would confirm it?'], 'green')
    d.panel('bear', 548, 838, 432, 280, 'Bear case', ['What breaks it?', 'Cite opposing evidence.'], 'warm')
    d.link(('lenses', 'bottom'), ('bull', 'top'), via=((508, 778), (252, 778)), role='green')
    d.link(('lenses', 'bottom'), ('bear', 'top'), via=((508, 778), (764, 778)), role='warm')
    d.panel('risk', 36, 1238, 944, 240, 'Risk voices stress both arguments',
            ['Aggressive · neutral · conservative'], 'slate')
    for node, x in (('bull', 252), ('bear', 764)):
        d.link((node, 'bottom'), ('risk', 'top'), via=((x, 1178), (508, 1178)), role='warm')
    d.panel('judge', 36, 1598, 944, 280, 'Judge → plan.json → code validation',
            ['Action · trigger · confidence · invalidation', 'The prompt requests disagreement; code checks the artifacts.'], 'violet')
    d.link(('risk', 'bottom'), ('judge', 'top'), role='violet')
    return d.finish(1926)


def architecture():
    d = Canvas('architecture', 'The desk: who does what')
    # Ownership swimlanes: each owner faces its operation and output, not a
    # repeated vertical pipeline. This is a different reading shape from the day.
    for owner, node, y, name, title, rows, role in (
        ('python', 'input', 210, 'Code', 'Before judgment', ['Fetch + reconcile + risk', 'Output: certified context'], 'green'),
        ('agent', 'decision', 610, 'Agent', 'During judgment', ['Lenses + bull / bear + risk + judge', 'Output: morning plan + session cards'], 'slate'),
        ('code', 'outcome', 1010, 'Code', 'After judgment', ['Validate + publish + settle + evaluate', 'Output: ledger + public scorecard'], 'blue'),
        ('files', 'history', 1410, 'Files', 'The next judgment', ['Earlier history enters context + calibration', 'Output: continuity across runs'], 'violet')):
        d.panel(owner, 36, y, 180, 320, name, role=role)
        d.panel(node, 248, y, 732, 320, title, rows, role)
        d.link((owner, 'right'), (node, 'left'), role=role)
    d.schematic(1810)
    return d.finish(2010)


def decision_pipeline():
    d = Canvas('decision-pipeline', 'A day and its receipts')
    # Two time lanes with branch detail, rather than one anonymous chain.
    xs, cw = columns(2, gap=80, x0=36, w=944)
    d.text(xs[0], 182, 'Before / during the session', fill=ROLE['blue'])
    d.text(xs[1], 182, 'After close / next session', fill=ROLE['green'])
    for node, col, y, title, rows, role in (
        ('collect', 0, 244, 'Collect', ['Quotes + FX + filings + news', 'Macro + sentiment + factors + peers'], 'blue'),
        ('compute', 0, 700, 'Compute + gate', ['Book risk + leverage regime', 'Entry + earnings + thesis + evidence'], 'green'),
        ('argue', 0, 1156, 'Argue + publish', ['Lenses → bull / bear → risk → judge', 'plan.json → checked card → delivery'], 'warm'),
        ('execute', 1, 244, 'Record execution', ['Human places orders', 'mark-followed records the status'], 'slate'),
        ('settle', 1, 700, 'Settle + evaluate', ['Canonical bars + episode grouping', 'Calibration + simulated shadow book'], 'green'),
        ('return', 1, 1156, 'Return the record', ['Public scorecard, losses included', 'Next brief reads earlier history'], 'violet')):
        d.panel(node, xs[col], y, cw, 372, title, rows, role)
    for a, b in (('collect', 'compute'), ('compute', 'argue'), ('execute', 'settle'), ('settle', 'return')):
        d.link((a, 'bottom'), (b, 'top'))
    d.link(('argue', 'right'), ('execute', 'left'), via=((508, 1342), (508, 430)), role='warm')
    d.wrap(36, 1636, 944, 'One day leaves context, a decision, execution status and a settled outcome.')
    return d.finish(1774)


def harnesses():
    d = Canvas('harnesses', 'Delegate. Watch. Steer.')
    d.panel('ask', 36, 210, 432, 300, 'Ask in dsh chat', ['Choose the task', 'Name the delivery contract'], 'slate')
    d.panel('runner', 548, 210, 432, 300, 'Runner', ['Claude / Codex', 'OpenCode', 'Outlives chat'], 'green')
    d.link(('ask', 'right'), ('runner', 'left'))
    for x, logo in zip((572, 712), ('claude-code', 'codex')):
        d.brand(logo, x, 554, size=56)
    d.wrap(36, 572, 432, 'Existing live-host queue capture')
    h = d.screenshot('dsh-dispatch-queue.png', 36, 676, 432)
    for node, y, title, rows, role in (
        ('watch', 676, 'Watch', ['Allowances + queue', 'Model + elapsed time', 'Estimated API-price cost'], 'blue'),
        ('steer', 1124, 'Steer', ['Reorder queue', 'Set next attempt', 'Set budgets', 'Retry / cancel'], 'warm'),
        ('result', 1572, 'Keep the result', ['PR + checks + merge', 'Refresh the host', 'Outcome ≠ send receipt'], 'violet')):
        d.panel(node, 548, y, 432, 340, title, rows, role)
    d.link(('watch', 'bottom'), ('steer', 'top'), role='warm')
    d.link(('steer', 'bottom'), ('result', 'top'), role='violet')
    return d.finish(max(1960, 676 + h + 48))


def _box(el):
    return tuple(float(el.attrib[k]) for k in ('x', 'y', 'width', 'height'))


def _intersects(a, b, inset=0):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return min(ax + aw, bx + bw) - max(ax, bx) > inset and min(ay + ah, by + bh) - max(ay, by) > inset


def validate_geometry(svg):
    """Check actual SVG coordinates, not precomputed success flags.

    Conservative text envelopes catch escaped text, line collisions and labels
    outside their own pane. Node anchors are read back from the SVG, so a moved
    endpoint or a moved card fails even when the Python layout metadata is stale.
    Rendered glyph bboxes are additionally measured by the screenshot harness.
    """
    root = ET.fromstring(svg)
    ns = '{http://www.w3.org/2000/svg}'
    pw, ph = map(float, (root.attrib['width'], root.attrib['height']))
    nodes = {el.attrib['data-node']: _box(el) for el in root.iter(ns + 'rect') if 'data-node' in el.attrib}
    assert nodes, 'missing geometric node contracts'
    for node, (x, y, w, h) in nodes.items():
        assert 0 <= x and 0 <= y and x + w <= pw and y + h <= ph, ('pane canvas overflow', node)
    texts = []
    for el in root.iter(ns + 'text'):
        cls = el.attrib['class']
        size = TYPE[cls][0]
        assert size * 324 / pw >= 10, ('mobile font floor', cls, size, pw)
        x, y = float(el.attrib['x']), float(el.attrib['y'])
        tw = width(''.join(el.itertext()), cls)
        anchor = el.attrib.get('text-anchor', 'start')
        x -= tw / 2 if anchor == 'middle' else tw if anchor == 'end' else 0
        box = (x, y - size, tw, size * 1.25)
        assert x >= 0 and y - size >= 0 and x + tw <= pw and y + size * .25 <= ph, ('canvas text overflow', el.attrib)
        if 'data-in' in el.attrib:
            nx, ny, nw, nh = nodes[el.attrib['data-in']]
            assert nx + 16 <= x and ny + 16 <= y - size and x + tw <= nx + nw - 16 and y + size * .25 <= ny + nh - 16, ('pane text overflow', el.attrib, box)
        else:
            for pane in nodes.values():
                assert not _intersects(box, pane), ('unowned text touches pane', el.attrib, pane)
        texts.append(box)
    for el in root.iter():
        if 'data-obstacle' in el.attrib:
            for text in texts:
                assert not _intersects(_box(el), text), ('graphic crosses text', el.attrib, text)
    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            assert not _intersects(a, b), ('text collision', a, b)
    panes = list(nodes.values())
    for i, a in enumerate(panes):
        for b in panes[i + 1:]:
            assert not _intersects(a, b), ('pane collision', a, b)
            ax, ay, aw, ah = a
            bx, by, bw, bh = b
            if min(ay + ah, by + bh) > max(ay, by):
                assert max(ax, bx) - min(ax + aw, bx + bw) >= 28, ('horizontal breathing room', a, b)
            if min(ax + aw, bx + bw) > max(ax, bx):
                assert max(ay, by) - min(ay + ah, by + bh) >= 28, ('vertical breathing room', a, b)
    for path in root.iter(ns + 'path'):
        if 'data-from' not in path.attrib:
            continue
        points = [tuple(map(float, pair)) for pair in re.findall(r'[ML]([-\d.]+) ([-\d.]+)', path.attrib['d'])]
        for key, point in (('data-from', points[0]), ('data-to', points[-1])):
            node, side = path.attrib[key].split(':')
            x, y, w, h = nodes[node]
            expected = {'left': (x, y + h / 2), 'right': (x + w, y + h / 2),
                        'top': (x + w / 2, y), 'bottom': (x + w / 2, y + h)}[side]
            assert point == expected, ('connector seam', key, point, expected)
        for a, b in zip(points, points[1:]):
            assert a[0] == b[0] or a[1] == b[1], ('connector off grid', a, b)
            # A three-unit path must not run through any label or pane interior.
            segment = (min(a[0], b[0]) - 1.5, min(a[1], b[1]) - 1.5,
                       abs(a[0] - b[0]) + 3, abs(a[1] - b[1]) + 3)
            for text in texts:
                assert not _intersects(segment, text), ('connector crosses text', path.attrib, text)
            for x, y, w, h in panes:
                assert not _intersects(segment, (x + 2, y + 2, w - 4, h - 4)), ('connector crosses pane', path.attrib)
    return True


LAYOUTS = {
    'rsi-loop': rsi_loop, 'evidence-receipt': evidence_receipt,
    'feedback-learning': feedback_learning, 'decision-pipeline': decision_pipeline,
    'harnesses': harnesses, 'information-flow': information_flow,
    'architecture': architecture, 'product-architecture': product_architecture,
    'debate-flow': debate_flow, 'start-here': start_here,
    'scorecard': scorecard, 'guardrails': guardrails,
}
DIAGRAMS = {f'{name}.svg': draw for name, draw in LAYOUTS.items()}


def main(argv):
    WARN.clear()
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
