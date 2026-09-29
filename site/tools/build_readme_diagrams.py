"""Build the four terminal-style README diagrams in site/assets/.

    python3 site/tools/build_readme_diagrams.py            # rewrite the SVGs
    python3 site/tools/build_readme_diagrams.py --check    # exit 1 if any differs

Everything is plain SVG: CSS keyframes (dash flow, log highlight, cursor) and
SMIL <animateMotion> packets. No script, no external font and no filter (a filter
rasterises the text under it) — so the diagrams animate inside the README's
<img>, stop under prefers-reduced-motion, and degrade to a complete static frame.

Every label is sourced from the code or docs it names; change the wording here,
not in the SVG. `fits()` warns when a label would overflow its box at the
monospace stack's advance width, and the build refuses to write while it does.
"""
import sys
from pathlib import Path
from xml.sax.saxutils import escape

W = 880
FONT = ('ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,'
        '"Liberation Mono","DejaVu Sans Mono",monospace')
CHAR = 0.61  # advance width / font size for the monospace stack

C = {
    'blue': '#79a8ff', 'green': '#6fd08c', 'orange': '#f0a35e',
    'pink': '#f07cb4', 'purple': '#b69cf5', 'red': '#f47067',
    'ink': '#e3e6eb', 'mut': '#9aa1ac', 'dim': '#626a76',
    'win': '#15171c', 'bar': '#1e2127', 'node': '#1a1d23', 'line': '#2c313a',
}
SIZES = {'h': 13, 'b': 12.5, 's': 12}

WARN = []


def fits(s, size, room, where):
    need = len(s) * CHAR * size
    if need > room:
        WARN.append(f'{where}: "{s}" needs {need:.0f}px, has {room:.0f}px')


class Svg:
    def __init__(self, h, title, desc, bar_title):
        self.h = h
        self.parts = []
        self.defs = []
        self.nid = 0
        self.title, self.desc, self.bar_title = title, desc, bar_title
        self.log_lines = 0

    # --- primitives -------------------------------------------------------
    def add(self, s):
        self.parts.append(s)

    def text(self, x, y, segs, size='b', anchor='start', weight=None, cls=''):
        """segs: str or [(text, color[, bold])]."""
        if isinstance(segs, str):
            segs = [(segs, 'ink')]
        out = []
        for seg in segs:
            t, col = seg[0], seg[1]
            bold = len(seg) > 2 and seg[2]
            attrs = f' class="{col}{" k" if bold else ""}"'
            out.append(f'<tspan{attrs}>{escape(t)}</tspan>')
        w = f' font-weight="{weight}"' if weight else ''
        a = f' text-anchor="{anchor}"' if anchor != 'start' else ''
        c = f' {cls}' if cls else ''
        self.add(f'<text x="{x}" y="{y}" class="{size}{c}"{a}{w}>{"".join(out)}</text>')
        return sum(len(s[0]) for s in segs)

    def node(self, x, y, w, h, color, lines, pad=14, lh=20, first=24, center=False,
             status=None):
        """A stroked box. lines: list of segs (see text); None = blank line."""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="3" '
                 f'fill="{C["node"]}" stroke="{C[color]}" stroke-width="1.4"/>')
        yy = y + first
        for i, ln in enumerate(lines):
            if ln is not None:
                segs = [(ln, 'ink')] if isinstance(ln, str) else ln
                size = 'h' if i == 0 else 'b'
                room = w - 2 * pad
                fits(''.join(s[0] for s in segs), SIZES[size], room, f'node@{x},{y}')
                if center:
                    self.text(x + w / 2, yy, segs, size, anchor='middle')
                else:
                    self.text(x + pad, yy, segs, size)
            yy += lh
        if status:
            label, col = status
            cx = x + w / 2 - len(label) * CHAR * SIZES['b'] / 2 - 6 if center else x + pad + 4
            sy = y + h - 14
            self.add(f'<circle class="pulse" cx="{cx:.1f}" cy="{sy - 4}" r="3.6" fill="{C[col]}"/>')
            self.text(cx + 10, sy, [(label, col)], 'b')

    def dot(self, x, y, color, r=4):
        self.add(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{C[color]}"/>')

    def edge(self, d, color, packets=(), arrow=True, dashed=False, flow=True, dur=2.4,
             width=1.4, pcolor=None):
        """Path plus optional travelling packets (list of begin offsets, seconds)."""
        self.nid += 1
        pid = f'p{self.nid}'
        cls = 'flow' if flow else ''
        dash = ' stroke-dasharray="2 5"' if dashed and not flow else ''
        mk = f' marker-end="url(#a-{color})"' if arrow else ''
        self.add(f'<path id="{pid}" d="{d}" fill="none" stroke="{C[color]}" '
                 f'stroke-opacity=".75" stroke-width="{width}" class="{cls}"{dash}{mk}/>')
        for b in packets:
            self.packet(pid, pcolor or color, dur, b)
        return pid

    def packet(self, pid, color, dur, begin):
        # A bright head and a fainter tail a few frames behind, like "•●".
        for r, op, lag in ((3.2, 1, 0), (2.1, .45, .09)):
            self.add(f'<circle class="pkt" r="{r}" fill="{C[color]}" fill-opacity="{op}">'
                     f'<animateMotion dur="{dur}s" begin="{-(begin + lag):.2f}s" '
                     f'repeatCount="indefinite" calcMode="linear">'
                     f'<mpath xlink:href="#{pid}" href="#{pid}"/></animateMotion></circle>')

    # --- chrome -----------------------------------------------------------
    def chrome(self, header, legend):
        h = self.h
        self.add(f'<rect x=".5" y=".5" width="{W - 1}" height="{h - 1}" rx="12" '
                 f'fill="{C["win"]}" stroke="{C["line"]}"/>')
        self.add(f'<path d="M.5 34V12.5A12 12 0 0 1 12.5 .5H{W - 12.5}A12 12 0 0 1 {W - .5} 12.5V34Z" '
                 f'fill="{C["bar"]}"/>')
        self.add(f'<path d="M1 34.5H{W - 1}" stroke="{C["line"]}"/>')
        for i, col in enumerate(('#ff5f57', '#febc2e', '#28c840')):
            self.add(f'<circle cx="{20 + i * 18}" cy="17.5" r="5.5" fill="{col}"/>')
        self.text(W / 2, 22, [(self.bar_title, 'dim')], 's', anchor='middle')
        fits(''.join(s[0] for s in header), SIZES['h'], W - 56, 'header')
        self.text(W / 2, 64, header, 'h', anchor='middle', cls='k')
        self.add(f'<path d="M28 78.5H{W - 28}" stroke="{C["line"]}"/>')
        # legend
        total = sum(len(t) + 2 for t, _ in legend) + 3 * (len(legend) - 1)
        fits('x' * total, SIZES['s'], W - 56, 'legend')
        x = W / 2 - total * CHAR * SIZES['s'] / 2
        for t, col in legend:
            self.add(f'<rect x="{x:.1f}" y="95" width="8" height="8" fill="{C[col]}"/>')
            self.text(round(x + 14, 1), 103, [(t, 'mut')], 's')
            x += (len(t) + 5) * CHAR * SIZES['s']

    def panel(self, x, y, w, h, color, label_y=None):
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="3" fill="none" '
                 f'stroke="{C[color]}" stroke-width="1.4"/>')
        self.add(f'<path d="M{x + 12} {y + 8}V{y + h - 8}" stroke="{C[color]}" stroke-opacity=".25"/>')

    def log(self, x, y, w, rows, cols, title='session log', period=None):
        """Bottom session-log box; rows = [[(text,color[,bold]) per column]]."""
        h = 26 + len(rows) * 21
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="3" fill="none" '
                 f'stroke="{C["line"]}" stroke-width="1.4"/>')
        tw = len(title) * CHAR * SIZES['s'] + 20
        self.add(f'<rect x="{x + 18}" y="{y - 8}" width="{tw:.0f}" height="16" fill="{C["win"]}"/>')
        self.add(f'<path d="M{x + 18} {y - 7}v14M{x + 18 + tw:.0f} {y - 7}v14" stroke="{C["line"]}" stroke-width="1.4"/>')
        self.text(x + 28, y + 4, [(title, 'mut')], 's')
        n = len(rows)
        period = period or n * 1.6
        for i, row in enumerate(rows):
            yy = y + 28 + i * 21
            delay = -(period - i * period / n)
            self.add(f'<g class="ln" style="animation-delay:{delay:.2f}s;animation-duration:{period:.1f}s">')
            for j, cell in enumerate(row):
                if cell is None:
                    continue
                segs = [cell] if isinstance(cell, tuple) else cell
                nxt = cols[j + 1] if j + 1 < len(cols) else w - 16
                fits(''.join(s[0] for s in segs), SIZES['b'], nxt - cols[j] - 8, f'log r{i}c{j}')
                self.text(x + cols[j], yy, segs, 'b')
            self.add('</g>')
        return y + h

    def prompt(self, x, y, cmd, status):
        n = self.text(x, y, [('~/clawock $ ', 'green', True), (cmd, 'ink')], 'b')
        cx = x + n * CHAR * SIZES['b'] + 2
        self.add(f'<rect class="cur" x="{cx:.1f}" y="{y - 11}" width="7.5" height="14" fill="{C["ink"]}"/>')
        fits(''.join(s[0] for s in status), SIZES['b'], W - 56, 'status')
        self.text(x, y + 22, status, 'b')

    # --- output -----------------------------------------------------------
    def render(self):
        markers = ''.join(
            f'<marker id="a-{k}" markerWidth="8" markerHeight="8" refX="6" refY="4" '
            f'orient="auto" markerUnits="userSpaceOnUse"><path d="M0 0L7 4L0 8Z" fill="{v}"/></marker>'
            for k, v in C.items() if k in ('blue', 'green', 'orange', 'pink', 'purple', 'red', 'mut'))
        colors = ''.join(f'.{k}{{fill:{v}}}' for k, v in C.items())
        style = (
            f'text{{font-family:{FONT};white-space:pre}}'
            '.h{font-size:13px;font-weight:700}.b{font-size:12.5px}.s{font-size:12px}.k{font-weight:700}'
            + colors +
            '.flow{stroke-dasharray:5 4;animation:flow 1.1s linear infinite}'
            '@keyframes flow{to{stroke-dashoffset:-9}}'
            '.ln{animation:ln 12s linear infinite}'
            '@keyframes ln{0%,100%{opacity:.42}3%,14%{opacity:1}20%{opacity:.42}}'
            '.cur{animation:cur 1.1s steps(1) infinite}@keyframes cur{50%{opacity:0}}'
            '.pulse{animation:pulse 1.8s ease-in-out infinite}@keyframes pulse{50%{opacity:.25}}'
            '@media (prefers-reduced-motion:reduce){.flow,.ln,.cur,.pulse{animation:none}.pkt{display:none}}'
        )
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                f'width="{W}" height="{self.h}" viewBox="0 0 {W} {self.h}" role="img" '
                f'aria-labelledby="title desc">\n'
                f'  <title id="title">{escape(self.title)}</title>\n'
                f'  <desc id="desc">{escape(self.desc)}</desc>\n'
                f'  <!-- Generated by site/tools/build_readme_diagrams.py; edit the builder, not this file. -->\n'
                f'  <defs>{markers}<style>{style}</style></defs>\n')
        return head + '\n'.join('  ' + p for p in self.parts) + '\n</svg>\n'


def information_flow():
    """site/assets/information-flow.svg — the live desk's data flow, end to end."""

    H = 1640
    s = Svg(H,
            'clawock data flow — sources, fetch fallback, portfolio and risk, three cadences, '
            'agent, postflight, data plane and delivery',
            'Eight information layers feed ordered fetch-fallback routes (HK quotes Tencent plus '
            'Eastmoney HK then stooq then yfinance; US quotes Nasdaq, Eastmoney, Finnhub, Yahoo, '
            'yfinance, Alpha Vantage, Polygon; USDHKD Frankfurter, exchangerate.host, Yahoo; every '
            'live Eastmoney call through one throttled gateway; an empty fetch keeps the prior value). '
            'Python reconciles the book, runs the integrity gate and builds risk. Each cadence - the '
            'pre-open brief, session reports and intraday check-ins - runs a preflight that assembles '
            'only the blocks it can use; the agent reads those files and never fetches; a Python '
            'postflight validates and publishes to master, to the data-plane branch the dashboard '
            'polls, and to WeChat and Telegram. An LLM-free crontab watchdog checks every slot and '
            'mirrors to Telegram when the send is not confirmed.',
            '~/clawock — data-flow — zsh')
    s.chrome([('CLAWOCK DATA FLOW', 'ink'), (' · ', 'dim'), ('PYTHON FETCHES', 'blue'),
              (' · ', 'dim'), ('AGENT ARGUES', 'orange'), (' · ', 'dim'), ('CODE SETTLES', 'green')],
             [('sources · fetch', 'blue'), ('python · deterministic', 'green'),
              ('agent · LLM', 'orange'), ('publish · deliver', 'pink'),
              ('watchdog · crontab', 'purple')])

    MX, MW = 252, 600          # main column
    CX = MX + MW // 2          # 552
    PAD = 14

    # --- 8 information layers -------------------------------------------------
    y0 = 128
    s.add(f'<rect x="{MX}" y="{y0}" width="{MW}" height="156" rx="3" fill="{C["node"]}" '
          f'stroke="{C["blue"]}" stroke-width="1.4"/>')
    s.text(MX + PAD, y0 + 24, [('8 INFORMATION LAYERS', 'blue', True), ('   HK + US · bilingual', 'mut')], 'h')
    layers = [('L1', 'market'), ('L2', 'fundamentals · filings'), ('L3', 'capital flow'),
              ('L4', 'news · catalysts'), ('L5', 'macro · sentiment'), ('L6', 'quant · risk'),
              ('L7', 'book · FX integrity'), ('L8', 'backtest · calibration')]
    for i, (n, name) in enumerate(layers):
        col, row = divmod(i, 4)
        s.text(MX + PAD + col * 290, y0 + 48 + row * 20, [(n + ' ', 'blue'), (name, 'ink')])
    foot = 'Tencent · Nasdaq · Eastmoney · SEC EDGAR · HKEXnews · Finnhub · …'
    fits(foot, SIZES['b'], MW - 2 * PAD, 'layers foot')
    s.text(MX + PAD, y0 + 140, [(foot, 'mut')])

    s.edge(f'M{CX} 284V316', 'blue', packets=(0, 1.2))
    s.dot(CX, 300, 'blue')

    # --- fetch / fallback ------------------------------------------------------
    s.node(MX, 318, MW, 176, 'blue', [
        [('FETCH · FALLBACK', 'blue', True), ('   ordered routes per source', 'mut')],
        [('HK quote  ', 'mut'), ('Tencent + Eastmoney HK', 'ink'), (' › stooq › yfinance', 'mut')],
        [('US quote  ', 'mut'), ('Nasdaq', 'ink'), (' › Eastmoney › Finnhub › Yahoo', 'mut')],
        [('          › yfinance › Alpha Vantage › Polygon', 'mut')],
        [('USDHKD    ', 'mut'), ('Frankfurter', 'ink'), (' › exchangerate.host › Yahoo', 'mut')],
        [('Eastmoney ', 'mut'), ('one throttled gateway, every live call', 'ink')],
        [('empty     ', 'mut'), ('keeps the prior value — never a blank', 'ink')],
    ])
    s.edge(f'M{CX} 494V526', 'blue', packets=(.4, 1.6))
    s.dot(CX, 510, 'green')

    # --- portfolio / risk ------------------------------------------------------
    s.node(MX, 528, MW, 124, 'green', [
        [('PORTFOLIO · RISK', 'green', True), ('   python, zero LLM', 'mut')],
        [('reconcile       ', 'mut'), ('recompute every derived money field', 'ink')],
        [('integrity       ', 'mut'), ('data-health gate on the book', 'ink')],
        [('fx              ', 'mut'), ('HK + US totals sum only through it', 'ink')],
        [('portfolio-risk  ', 'mut'), ('β · vol · drawdown → risk.json', 'ink')],
    ])

    # --- preflight fan-out -----------------------------------------------------
    s.add(f'<path d="M{CX} 652V668" stroke="{C["green"]}" stroke-opacity=".75" stroke-width="1.4"/>')
    s.text(CX, 686, [('preflight', 'green', True), (' · only the blocks this run can use', 'mut')], 'b', anchor='middle')
    NW, GAP = 190, 15
    xs = [MX, MX + NW + GAP, MX + 2 * (NW + GAP)]
    cxs = [x + NW // 2 for x in xs]
    for i, cx in enumerate(cxs):
        s.edge(f'M{CX} 694V708H{cx}V730', 'green', packets=(i * .5,), dur=2.0)
    s.dot(CX, 708, 'green')
    for cx in (cxs[0] + 100, cxs[2] - 100):
        s.dot(cx, 708, 'green', r=3.2)

    cad = [
        ['brief', 'pre-open deep brief', '08:03 HKT · weekdays', 'debate → plan.json'],
        ['report', 'HK open·mid·pm·close', 'US open · close', 'fresh quote block'],
        ['intraday', 'every 30 min while', 'a market is open', 'judgment packet'],
    ]
    for x, lines in zip(xs, cad):
        ls = [[(lines[0], 'green', True)]] + [[(l, 'ink')] for l in lines[1:]]
        s.node(x, 732, NW, 118, 'green', ls, center=True, status=('preflight', 'green'))

    # --- merge into the agent --------------------------------------------------
    for i, cx in enumerate(cxs):
        d = f'M{cx} 850V874H{CX}V900' if cx != CX else f'M{CX} 850V900'
        s.edge(d, 'orange', packets=(i * .6 + .3,), dur=2.0)
    for cx in (cxs[0] + 100, cxs[2] - 100):
        s.dot(cx, 874, 'orange', r=3.2)
    s.dot(CX, 874, 'orange')

    AX, AW = 352, 400
    s.node(AX, 902, AW, 100, 'orange', [
        [('AGENT', 'orange', True), (' · reads, argues, writes', 'ink')],
        'reads the context files, never fetches',
        'brief also writes plan.json',
        [('OpenClaw cron on this desk', 'mut')],
    ], center=True)
    s.edge(f'M{CX} 1002V1032', 'orange', packets=(0, 1.1), dur=2.2)

    s.node(AX, 1034, AW, 80, 'green', [
        [('POSTFLIGHT', 'green', True), (' · python', 'ink')],
        'validates the output, then publishes',
        'sends WeChat, co-sends Telegram',
    ], center=True)

    # --- publish fan-out -------------------------------------------------------
    for i, cx in enumerate(cxs):
        s.edge(f'M{CX} 1114V1132H{cx}V1154', 'pink', packets=(i * .5 + .2,), dur=2.0)
    s.dot(CX, 1132, 'pink')
    for cx in (cxs[0] + 100, cxs[2] - 100):
        s.dot(cx, 1132, 'pink', r=3.2)

    outs = [
        [[('deliver', 'pink', True)], [('WeChat   ', 'ink'), ('unknown', 'mut')],
         [('Telegram ', 'ink'), ('confirmed', 'green')], [('4-state receipt', 'mut')]],
        [[('data-plane branch', 'pink', True)], '7-file generation', 'replaced, not appended',
         [('Pages: cold-start copy', 'mut')]],
        [[('master', 'pink', True)], 'ledger · memory · book', 'pre-push gate: the',
         'book must reconcile'],
    ]
    for x, lines in zip(xs, outs):
        s.node(x, 1156, NW, 104, 'pink', lines, center=True, pad=8)

    s.edge(f'M{CX} 1260V1290', 'pink', packets=(0, 1.0), dur=2.0)
    s.node(AX, 1292, AW, 62, 'pink', [
        [('DASHBOARD', 'pink', True), ('  kcnyu.github.io/clawock', 'ink')],
        [('browser re-reads data-plane every 60 s', 'mut')],
    ], center=True)

    # --- watchdog side panel ---------------------------------------------------
    PX, PW = 28, 200
    s.panel(PX, 128, PW, 1226, 'purple')
    T = PX + 22
    s.text(T, 152, [('WATCHDOG', 'purple', True)], 'h')
    s.text(T, 174, [('system crontab', 'ink')])
    s.text(T, 194, [('LLM-free, out of band', 'mut')])
    s.text(T, 236, [('a run can end "ok"', 'mut')])
    s.text(T, 256, [('and still not land', 'mut')])

    # row that points at the cadences
    s.add(f'<rect x="{PX + 4}" y="{744 - 15}" width="{PW - 8}" height="22" fill="{C["purple"]}" fill-opacity=".12"/>')
    s.text(T - 12, 744, [('◇ ', 'purple'), ('checks every slot', 'ink', True)])
    s.edge(f'M{PX + PW - 2} 740H{MX - 2}', 'purple', packets=(0, .9), dur=1.8)
    for i, (k, v) in enumerate([('brief', '08:36'), ('  miss', '09:05'), ('report', '+10–20 min'),
                                ('intraday', ':13 · :43')]):
        s.text(T, 770 + i * 20, [(f'{k:<9}', 'mut'), (v, 'ink')])

    s.text(T, 940, [('reads the send marker', 'mut')])
    s.text(T, 960, [('postflight wrote', 'mut')])
    s.text(T, 980, [('for that slot', 'mut')])
    s.text(T, 1040, [('never writes the', 'mut')])
    s.text(T, 1060, [('analysis itself', 'mut')])

    s.add(f'<rect x="{PX + 4}" y="{1186 - 15}" width="{PW - 8}" height="22" fill="{C["purple"]}" fill-opacity=".12"/>')
    s.text(T - 12, 1186, [('◆ ', 'purple'), ('cosend unconfirmed', 'ink', True)])
    s.edge(f'M{PX + PW - 2} 1182H{MX - 2}', 'purple', packets=(.3, 1.2), dur=1.8)
    s.text(T, 1208, [('→ mirror to Telegram', 'purple')])
    s.text(T, 1248, [('WeChat resend only', 'mut')])
    s.text(T, 1268, [('on a confirmed fail', 'mut')])
    s.text(T, 1288, [('(one retry + alert)', 'mut')])
    for t in ('checks every slot', 'cosend unconfirmed', 'reads the send marker', 'WeChat resend only',
              'on a confirmed fail', '(one retry + alert)', 'LLM-free, out of band'):
        fits(t, SIZES['b'], PW - 30, 'panel')

    # --- session log -----------------------------------------------------------
    cols = [16, 72, 176, 432]
    rows = [
        [('08:03', 'dim'), ('cron', 'green', True), ('brief preflight', 'ink'),
         [('→ ', 'dim'), ('memory/.tmp/brief-context-*.json', 'mut')]],
        [('  └─', 'dim'), ('agent', 'orange', True), ('reads core + bundles', 'ink'),
         [('→ ', 'dim'), ('prose + plan.json', 'mut')]],
        [('  └─', 'dim'), ('python', 'green', True), ('brief postflight', 'ink'),
         [('→ ', 'dim'), ('validate · publish · deliver', 'mut')]],
        [('08:36', 'dim'), ('watchdog', 'purple', True), ('send marker confirmed?', 'ink'),
         [('→ ', 'dim'), ('else mirror to Telegram', 'mut')]],
        [('09:33', 'dim'), ('cron', 'green', True), ('report --hk open', 'ink'),
         [('→ ', 'dim'), ('memory/.tmp/report-context-*.json', 'mut')]],
        [('10:03', 'dim'), ('cron', 'green', True), ('intraday --hk', 'ink'),
         [('→ ', 'dim'), ('judgment packet', 'mut')]],
        [('10:13', 'dim'), ('watchdog', 'purple', True), ('intraday slot landed?', 'ink'),
         [('→ ', 'dim'), ('else mirror to Telegram', 'mut')]],
    ]
    end = s.log(28, 1390, 824, rows, cols, title='session log · HKT')
    s.prompt(28, end + 34, 'clawock brief preflight',
             [('cadence ', 'dim'), ('[brief · report · intraday]', 'green'),
              ('  store ', 'dim'), ('[master · data-plane]', 'pink'),
              ('  deliver ', 'dim'), ('[wechat · telegram]', 'pink')])
    assert end + 34 + 22 + 18 <= H, end
    return s.render()


def architecture():
    """site/assets/architecture.svg — the KCNyu live desk: argue, gate, publish, settle, loop."""

    H = 1130
    s = Svg(H,
            'KCNyu live investment instance built with clawock contracts',
            'This is the KCNyu deployment, not the reusable clawock product architecture. Python '
            'assembles one immutable evidence pack. OpenClaw agents run four analyst lenses, a bull '
            'case, a bear case and three risk voices, and a judge names the strategy frame and writes '
            'plan.json. A Python decision contract validates plan.json and the brief sections, and flags any risk breach the plan ignores, before the brief, ledger and '
            'dashboard publish it. On the return path code triggers each call against canonical '
            'unadjusted daily bars, groups repeated calls into episodes, grades them against a '
            'directional baseline and publishes the scorecard, which feeds the next brief.',
            '~/clawock — kcnyu-desk — zsh')
    s.chrome([('KCNYU LIVE DESK · HK + US', 'ink'), (' · ', 'dim'), ('OPENCLAW ARGUES', 'orange'),
              (' · ', 'dim'), ('CODE GATES', 'green'), (' · ', 'dim'), ('THE BARS SETTLE', 'blue')],
             [('python · deterministic', 'green'), ('agent · LLM', 'orange'),
              ('publish', 'pink'), ('settle · grade', 'blue'), ('loop', 'purple')])

    MX, MW, CX, PAD = 252, 600, 552, 14
    NW, GAP = 190, 15
    xs = [MX, MX + NW + GAP, MX + 2 * (NW + GAP)]
    cxs = [x + NW // 2 for x in xs]

    # 01 evidence pack
    s.node(MX, 128, MW, 112, 'green', [
        [('01 · EVIDENCE PACK', 'green', True), ('   python', 'mut')],
        [('context.json', 'ink'), (' — one reconciled, immutable input', 'mut')],
    ])
    for i, chip in enumerate(('book', 'market', 'risk', 'events')):
        x = MX + PAD + i * 143
        s.add(f'<rect x="{x}" y="196" width="129" height="28" rx="2" fill="none" stroke="{C["line"]}" stroke-width="1.2"/>')
        s.text(x + 64.5, 215, [(chip, 'ink')], anchor='middle')

    s.edge(f'M{CX} 240V270', 'green', packets=(0, 1.1), dur=2.0)
    s.text(MX + MW, 262, [('02 · DECISION ROOM', 'orange', True), (' · OpenClaw agents', 'mut')], 's', anchor='end')

    AX, AW = 352, 400
    s.node(AX, 272, AW, 62, 'orange', [
        [('ANALYSTS', 'orange', True), (' · 4 lenses, one table', 'ink')],
        [('fundamental · technical · sentiment · sector', 'mut')],
    ], center=True)

    for i, cx in enumerate(cxs):
        s.edge(f'M{CX} 334V350H{cx}V372', 'orange', packets=(i * .5,), dur=1.8)
    s.dot(CX, 350, 'orange')
    for cx in (cxs[0] + 100, cxs[2] - 100):
        s.dot(cx, 350, 'orange', r=3.2)
    fork = [
        [[('bull case', 'green', True)], 'hold / add', [('cites the pack', 'mut')]],
        [[('bear case', 'red', True)], 'trim / cut', [('attacks consensus', 'mut')]],
        [[('risk voices', 'orange', True)], 'aggressive', 'conservative · neutral'],
    ]
    for x, lines in zip(xs, fork):
        s.node(x, 374, NW, 84, 'orange', lines, center=True, pad=8)
    for i, cx in enumerate(cxs):
        d = f'M{cx} 458V476H{CX}V500' if cx != CX else f'M{CX} 458V500'
        s.edge(d, 'orange', packets=(i * .5 + .3,), dur=1.8)
    s.dot(CX, 476, 'orange')
    for cx in (cxs[0] + 100, cxs[2] - 100):
        s.dot(cx, 476, 'orange', r=3.2)

    s.node(AX, 502, AW, 82, 'orange', [
        [('JUDGE', 'orange', True), (' · names the strategy frame', 'ink')],
        'action · trigger · confidence',
        [('→ plan.json', 'orange')],
    ], center=True)
    s.edge(f'M{CX} 584V614', 'orange', packets=(0, 1.0), dur=2.0)

    # 03 decision contract
    s.node(MX, 616, MW, 104, 'green', [
        [('03 · DECISION CONTRACT', 'green', True), ('   python code gate', 'mut')],
        [('✓ ', 'green'), ('plan.json schema: fields, enums, confidence 0–1', 'ink')],
        [('✓ ', 'green'), ('brief sections: tiers 1–3, judge, next session', 'ink')],
        [('! ', 'orange'), ('a risk breach the plan ignores is flagged', 'ink')],
    ])

    for i, cx in enumerate(cxs):
        s.edge(f'M{CX} 720V738H{cx}V760', 'pink', packets=(i * .5 + .2,), dur=1.8)
    s.dot(CX, 738, 'pink')
    for cx in (cxs[0] + 100, cxs[2] - 100):
        s.dot(cx, 738, 'pink', r=3.2)
    pubs = [
        [[('ledger', 'pink', True)], 'decisions.jsonl', [('versioned record', 'mut')]],
        [[('brief', 'pink', True)], 'WeChat · Telegram', [('pre-open card', 'mut')]],
        [[('dashboard', 'pink', True)], 'data-plane branch', [('public on Pages', 'mut')]],
    ]
    for x, lines in zip(xs, pubs):
        s.node(x, 762, NW, 84, 'pink', lines, center=True, pad=8)

    # return path panel: flows upward, bottom to top
    PX, PW = 28, 200
    T = PX + 22
    s.panel(PX, 128, PW, 718, 'blue')
    s.add(f'<rect x="{PX + 4}" y="{172 - 15}" width="{PW - 8}" height="22" fill="{C["purple"]}" fill-opacity=".14"/>')
    s.text(T - 12, 172, [('◆ ', 'purple'), ('feeds next brief', 'ink', True)])
    s.edge(f'M{PX + PW - 2} 168H{MX - 2}', 'purple', packets=(0, .9), dur=1.8)

    blocks = [
        (210, 'PUBLIC SCORECARD', ['win rate · coverage', 'ungradeable stays', 'visible, out of the', 'denominator']),
        (350, 'GRADE', ['vs a directional', 'baseline, by code']),
        (450, 'GROUP', ['repeat calls of one', 'strategy = 1 episode']),
        (550, 'TRIGGER', ['canonical unadjusted', 'daily bars, on each', "market's calendar"]),
        (670, 'RECORD', ['the model submits;', 'it never grades', 'itself']),
    ]
    for y, head, lines in blocks:
        s.text(T, y, [(head, 'blue', True)], 'h')
        for i, l in enumerate(lines):
            fits(l, SIZES['b'], PW - 30, 'panel')
            s.text(T, y + 20 + i * 20, [(l, 'mut')])
    # upward arrows between blocks (bottom → top)
    for top, bottom in ((300, 330), (400, 432), (500, 532), (620, 652)):
        s.edge(f'M{PX + PW - 30} {bottom}V{top}', 'blue', packets=(0,), dur=1.4)
    s.edge(f'M{PX + PW - 30} 190V178', 'purple', packets=(), flow=False)

    s.add(f'<rect x="{PX + 4}" y="{806 - 15}" width="{PW - 8}" height="22" fill="{C["blue"]}" fill-opacity=".12"/>')
    s.text(T - 12, 806, [('◇ ', 'blue'), ('every decision', 'ink', True)])
    s.edge(f'M{MX - 2} 802H{PX + PW - 2}', 'blue', packets=(0, .9), dur=1.8)
    s.edge(f'M{PX + PW - 30} 786V752', 'blue', packets=(.3,), dur=1.4)

    cols = [16, 72, 176, 432]
    rows = [
        [('01', 'dim'), ('python', 'green', True), ('evidence pack', 'ink'), [('→ ', 'dim'), ('context.json', 'mut')]],
        [('02', 'dim'), ('analysts', 'orange', True), ('four lenses read it', 'ink'), [('→ ', 'dim'), ('one merged table', 'mut')]],
        [('03', 'dim'), ('debate', 'orange', True), ('bull vs bear · risk voices', 'ink'), [('→ ', 'dim'), ('disagreement on the record', 'mut')]],
        [('04', 'dim'), ('judge', 'orange', True), ('names the strategy frame', 'ink'), [('→ ', 'dim'), ('plan.json', 'mut')]],
        [('05', 'dim'), ('python', 'green', True), ('decision contract', 'ink'), [('→ ', 'dim'), ('brief · ledger · dashboard', 'mut')]],
        [('06', 'dim'), ('settle', 'blue', True), ('canonical daily bars', 'ink'), [('→ ', 'dim'), ('episode graded by code', 'mut')]],
        [('07', 'dim'), ('scorecard', 'blue', True), ('published, losses included', 'ink'), [('→ ', 'dim'), ("the next brief's evidence", 'mut')]],
    ]
    end = s.log(28, 880, 824, rows, cols, title='one decision, end to end')
    s.prompt(28, end + 34, 'clawock brief postflight',
             [('argue ', 'dim'), ('[openclaw]', 'orange'), ('  gate ', 'dim'), ('[python]', 'green'),
              ('  settle ', 'dim'), ('[canonical bars]', 'blue'), ('  record ', 'dim'), ('[public]', 'pink')])
    assert end + 34 + 22 + 18 <= H, end
    return s.render()


def product_architecture():
    """site/assets/product-architecture.svg — runtime / package / instance ownership."""

    H = 896
    s = Svg(H,
            'clawock product architecture',
            'External agent runtimes own the model, conversation, memory, planning, tools, permissions '
            'and credentials. They install a standard skill and call the clawock CLI using JSON. The '
            'clawock package owns portable decision workflows, certified inputs, artifact contracts, '
            'deterministic money and foreign-exchange reconciliation, outcome evaluation, receipts, '
            'and bounded proposal review and rollback. User instances own strategy, evidence, ledgers, '
            'schedules, delivery and user interfaces. Every harness drives the same three steps: '
            'clawock run prepare, the agent writes decision.json, clawock run publish.',
            '~/clawock — product — zsh')
    s.chrome([('CLAWOCK PRODUCT ARCHITECTURE', 'ink'), (' · ', 'dim'), ('RUNTIME THINKS', 'orange'),
              (' · ', 'dim'), ('PACKAGE RECONCILES', 'green'), (' · ', 'dim'), ('INSTANCE OWNS I/O', 'pink')],
             [('external runtime', 'orange'), ('clawock package', 'green'),
              ('user instance', 'pink'), ('adapter-owned I/O', 'purple')])

    MX, MW, CX, PAD = 252, 600, 552, 14

    s.node(352, 128, 400, 122, 'orange', [
        [('EXTERNAL RUNTIME', 'orange', True)],
        'OpenClaw · Claude Code · Codex',
        'DeepSeek Harness · other agents',
        [('model · conversation · memory · tools', 'mut')],
        [('reads · reasons · writes', 'orange')],
    ], center=True)

    # runtime <-> package: CLI call down, JSON back up
    s.edge(f'M{CX - 12} 250V292', 'orange', packets=(0, .9), dur=1.8)
    s.edge(f'M{CX + 12} 292V252', 'green', packets=(.45, 1.35), dur=1.8)
    s.text(CX - 26, 276, [('install skill · call CLI', 'orange')], 's', anchor='end')
    s.text(CX + 26, 276, [('JSON back', 'green')], 's')

    # the package, as a table with a scan line running down the stages
    PY = 294
    s.add(f'<rect x="{MX}" y="{PY}" width="{MW}" height="188" rx="3" fill="{C["node"]}" '
          f'stroke="{C["green"]}" stroke-width="1.4"/>')
    s.text(MX + PAD, PY + 24, [('CLAWOCK PACKAGE', 'green', True), ('   src/clawock/ · workflow + verifiable harness', 'mut')], 'h')
    s.add('<style>.scan{animation:scan 7.5s steps(1) infinite}'
          '@keyframes scan{0%{transform:translateY(0)}20%{transform:translateY(24px)}'
          '40%{transform:translateY(48px)}60%{transform:translateY(72px)}80%{transform:translateY(96px)}}'
          '@media (prefers-reduced-motion:reduce){.scan{animation:none}}</style>')
    s.add(f'<rect class="scan" x="{MX + 6}" y="{PY + 38}" width="{MW - 12}" height="22" fill="{C["green"]}" fill-opacity=".11"/>')
    stages = [
        ('01 WORKFLOW', 'evidence + opposition, bounded', 'workflow install'),
        ('02 CERTIFY', 'pinned input · context hashes', 'run prepare'),
        ('03 RECONCILE', 'order · cash · FX · validation', 'run publish'),
        ('04 EVALUATE', 'observed price + FX · receipt', 'workflow evaluate'),
        ('05 IMPROVE', 'bounded proposal, exact diff', 'review · apply · rollback'),
    ]
    for i, (st, what, cmd) in enumerate(stages):
        y = PY + 54 + i * 24
        s.text(MX + PAD, y, [(st, 'green', True)])
        fits(what, SIZES['b'], 392 - 124 - 8, 'stage what')
        fits(cmd, SIZES['b'], MW - 392 - 12, 'stage cmd')
        s.text(MX + 124, y, [(what, 'ink')])
        s.text(MX + 392, y, [(cmd, 'mut')])
    s.text(MX + PAD, PY + 54 + 5 * 24 + 4, [('never silent: apply writes a rollback record', 'mut')], 's')

    # same three steps, whatever the harness
    s.text(CX, 510, [('every harness drives the same three steps', 'mut')], 's', anchor='middle')
    NW, GAP = 176, 36
    xs = [MX, MX + NW + GAP, MX + 2 * (NW + GAP)]
    steps = [
        ('green', [[('run prepare', 'green', True)], '→ request.json', [('certified input', 'mut')]]),
        ('orange', [[('agent writes', 'orange', True)], 'decision.json', [('in your runtime', 'mut')]]),
        ('green', [[('run publish', 'green', True)], [('published', 'green')], [('or rejected, exit 1', 'red')]]),
    ]
    for x, (col, lines) in zip(xs, steps):
        s.node(x, 522, NW, 84, col, lines, center=True, pad=8)
    s.edge(f'M{xs[0] + NW + 1} 564H{xs[1] - 2}', 'orange', packets=(0, .8), dur=1.6)
    s.edge(f'M{xs[1] + NW + 1} 564H{xs[2] - 2}', 'green', packets=(.4, 1.2), dur=1.6)

    # user instance panel
    PX, PW = 28, 200
    T = PX + 22
    s.panel(PX, 128, PW, 478, 'pink')
    s.text(T, 152, [('USER INSTANCE', 'pink', True)], 'h')
    s.text(T, 174, [('not in the wheel', 'mut')])
    for i, item in enumerate(('strategy', 'evidence', 'ledger', 'schedules', 'delivery', 'UI')):
        s.text(T, 204 + i * 20, [('· ', 'pink'), (item, 'ink')])
    s.add(f'<rect x="{PX + 4}" y="{376 - 15}" width="{PW - 8}" height="22" fill="{C["purple"]}" fill-opacity=".14"/>')
    s.text(T - 12, 376, [('◆ ', 'purple'), ('adapter-owned I/O', 'ink', True)])
    s.edge(f'M{MX - 2} 368H{PX + PW - 2}', 'purple', packets=(0, .9), dur=1.8)
    s.edge(f'M{PX + PW - 2} 382H{MX - 2}', 'purple', packets=(.45, 1.35), dur=1.8)
    for i, l in enumerate(('default store:', 'FilesystemStore', 'a foreign install', 'never pushes to', 'this repository')):
        fits(l, SIZES['b'], PW - 30, 'panel')
        s.text(T, 420 + i * 20, [(l, 'ink' if i in (1,) else 'mut')])
    s.text(T, 558, [('KCNyu is one live', 'mut')])
    s.text(T, 578, [('proof, not the product', 'pink')])
    fits('proof, not the product', SIZES['b'], PW - 30, 'panel')

    cols = [16, 72, 170, 520]
    rows = [
        [('01', 'dim'), ('you', 'ink', True), ('pip install clawock', 'ink'), [('→ ', 'dim'), ('Python ≥ 3.11', 'mut')]],
        [('02', 'dim'), ('clawock', 'green', True), ('workflow install investment-decision', 'ink'), [('→ ', 'dim'), ('a standard Agent Skill', 'mut')]],
        [('03', 'dim'), ('clawock', 'green', True), ('init ./my-book --workflow …', 'ink'), [('→ ', 'dim'), ('workspace', 'mut')]],
        [('04', 'dim'), ('clawock', 'green', True), ('run prepare', 'ink'), [('→ ', 'dim'), ('request.json', 'mut')]],
        [('05', 'dim'), ('agent', 'orange', True), ('reads it, writes decision.json', 'ink'), [('→ ', 'dim'), ('model call stays in your runtime', 'mut')]],
        [('06', 'dim'), ('clawock', 'green', True), ('run publish --artifact …', 'ink'), [('→ ', 'dim'), ('status: published', 'green')]],
        [('07', 'dim'), ('clawock', 'green', True), ('run publish, no opposing case', 'ink'), [('→ ', 'dim'), ('rejected · exit 1', 'red')]],
    ]
    end = s.log(28, 642, 824, rows, cols, title='examples/cli/workflow-run')
    s.prompt(28, end + 34, 'clawock run publish --request .clawock/work/request.json',
             [('runtime ', 'dim'), ('[thinks]', 'orange'), ('  package ', 'dim'),
              ('[prepare · publish · evaluate]', 'green'), ('  instance ', 'dim'), ('[owns I/O]', 'pink')])
    assert end + 34 + 22 + 18 <= H, end
    return s.render()


def debate_flow():
    """site/assets/debate-flow.svg — the three-tier debate inside the pre-open brief."""

    H = 1128
    s = Svg(H,
            'Inside the clawock multi-agent debate',
            "A pipeline. One shared evidence pack feeds four analyst lenses that merge into a single "
            "table. Two researchers are asked to argue opposing bull and bear cases and to record where "
            "they disagree, so unanimous agreement reads as a flag. Three risk voices then stress every "
            "call and a judge names the strategy frame driving each decision, resolving the argument "
            "into plan.json — which enters the next session's grading pipeline, where code, not the "
            "model, settles the score.",
            '~/clawock — debate — zsh')
    s.chrome([('THE DEBATE · HK + US', 'ink'), (' · ', 'dim'), ('DISAGREEMENT IS REQUIRED', 'orange'),
              (' · ', 'dim'), ('THE RESOLUTION IS ATTRIBUTED', 'green')],
             [('evidence · python', 'green'), ('agents · LLM', 'orange'), ('opposing case', 'red'),
              ('plan · grading', 'pink'), ('protocol', 'purple')])

    MX, MW, CX = 252, 600, 552


    def fan(y_from, y_bus, y_to, cxs, color, off=0.0):
        for i, cx in enumerate(cxs):
            s.edge(f'M{CX} {y_from}V{y_bus}H{cx}V{y_to}', color, packets=(off + i * .45,), dur=1.8)
        s.dot(CX, y_bus, color)


    def merge(y_from, y_bus, y_to, cxs, color, off=0.0):
        for i, cx in enumerate(cxs):
            d = f'M{cx} {y_from}V{y_bus}H{CX}V{y_to}' if cx != CX else f'M{CX} {y_from}V{y_to}'
            s.edge(d, color, packets=(off + i * .45,), dur=1.8)
        s.dot(CX, y_bus, color)


    s.node(MX, 128, MW, 66, 'green', [
        [('SHARED INPUT', 'green', True), ('   context.json — one immutable evidence pack', 'ink')],
        [('every claim below has to cite it', 'mut')],
    ])

    # tier 1: four lenses
    s.text(MX + MW, 218, [('TIER 1 · ANALYST LENSES', 'orange', True)], 's', anchor='end')
    W4, G4 = 138, 16
    x4 = [MX + i * (W4 + G4) for i in range(4)]
    c4 = [x + W4 // 2 for x in x4]
    fan(194, 226, 248, c4, 'green')
    for x, name in zip(x4, ('Fundamental', 'Technical', 'Sentiment', 'Sector rotation')):
        s.node(x, 250, W4, 44, 'orange', [[(name, 'orange', True)]], center=True, pad=8, first=27)
    merge(294, 314, 342, c4, 'orange', .2)
    s.text(CX - 14, 334, [('one merged table', 'mut')], 's', anchor='end')
    s.text(MX + MW, 334, [('TIER 2 · RESEARCHERS', 'orange', True)], 's', anchor='end')

    # tier 2: bull vs bear
    BW = 270
    bull_x, bear_x = MX, MX + MW - BW
    s.edge(f'M{CX} 342V352H{bull_x + BW // 2}V370', 'orange', packets=(0,), dur=1.4)
    s.edge(f'M{CX} 342V352H{bear_x + BW // 2}V370', 'orange', packets=(.5,), dur=1.4)
    s.node(bull_x, 372, BW, 84, 'green', [[('BULL CASE', 'green', True)], 'hold / add',
                                          [('cites the evidence pack', 'mut')]], center=True)
    s.node(bear_x, 372, BW, 84, 'red', [[('BEAR CASE', 'red', True)], 'trim / cut',
                                        [('attacks the strongest consensus', 'mut')]], center=True)
    s.text(CX, 398, [('vs', 'ink', True)], 'h', anchor='middle')
    s.edge(f'M{bull_x + BW + 2} 414H{bear_x - 2}', 'green', packets=(0, .7), dur=1.4)
    s.edge(f'M{bear_x - 2} 428H{bull_x + BW + 2}', 'red', packets=(.35, 1.05), dur=1.4)

    merge_c = [bull_x + BW // 2, bear_x + BW // 2]
    merge(456, 500, 516, merge_c, 'orange', .1)
    s.dot(CX, 520, 'orange')
    s.add(f'<rect x="{MX}" y="468" width="{MW}" height="24" rx="2" fill="{C["win"]}" stroke="{C["red"]}" stroke-opacity=".6"/>')
    s.add(f'<rect x="{MX}" y="468" width="{MW}" height="24" rx="2" fill="{C["red"]}" fill-opacity=".1"/>')
    s.text(CX, 485, [('OPPOSING CASE REQUIRED', 'red', True),
                     (' · unanimous agreement gets flagged', 'mut')], 'b', anchor='middle')
    s.text(MX + MW, 522, [('TIER 3 · RISK + JUDGE', 'orange', True)], 's', anchor='end')

    # tier 3: three risk voices then the judge
    W3, G3 = 190, 15
    x3 = [MX + i * (W3 + G3) for i in range(3)]
    c3 = [x + W3 // 2 for x in x3]
    for i, cx in enumerate(c3):
        s.edge(f'M{CX} 520V532H{cx}V552', 'orange', packets=(i * .45,), dur=1.6)
    for x, name in zip(x3, ('Aggressive', 'Conservative', 'Neutral')):
        s.node(x, 554, W3, 44, 'orange', [[(name, 'orange', True)]], center=True, first=27)
    merge(598, 618, 646, c3, 'orange', .3)

    s.node(352, 648, 400, 82, 'orange', [
        [('JUDGE', 'orange', True)],
        'names the strategy frame driving the call',
        [('→ plan.json', 'pink')],
    ], center=True)
    s.edge(f'M{CX} 730V760', 'pink', packets=(0, 1.0), dur=2.0)
    s.node(352, 762, 400, 82, 'pink', [
        [('plan.json', 'pink', True)],
        "enters the next session's grading —",
        [('code, not the model, settles the score', 'mut')],
    ], center=True)

    # protocol side panel
    PX, PW = 28, 200
    T = PX + 22
    s.panel(PX, 128, PW, 716, 'purple')
    s.text(T, 152, [('PROTOCOL', 'purple', True)], 'h')
    s.text(T, 174, [('rules set in the', 'mut')])
    s.text(T, 194, [('brief prompt and', 'mut')])
    s.text(T, 214, [('recorded in the brief', 'mut')])


    def hot(y, label, color='purple', arrow_to=None):
        s.add(f'<rect x="{PX + 4}" y="{y - 15}" width="{PW - 8}" height="22" fill="{C[color]}" fill-opacity=".14"/>')
        s.text(T - 12, y, [('◆ ', color), (label, 'ink', True)])
        fits('◆ ' + label, SIZES['b'], PW - 16, 'hot')
        if arrow_to:
            s.edge(f'M{PX + PW - 2} {y - 4}H{arrow_to - 2}', color, packets=(0, .9), dur=1.8)


    def lines(y, ls):
        for i, l in enumerate(ls):
            fits(l, SIZES['b'], PW - 30, 'panel')
            s.text(T, y + i * 20, [(l, 'mut')])


    hot(276, 'one pack for all', arrow_to=MX)
    hot(414, 'must disagree', arrow_to=MX)
    lines(438, ['on at least one', 'position, in writing'])
    lines(492, ['the bear attacks the', 'strongest view, not', 'the weakest'])
    hot(580, 'rotating order', arrow_to=MX)
    lines(604, ['first mover changes', 'every 4 trading days'])
    hot(690, 'attributed', arrow_to=352)
    lines(714, ['each resolution names', 'its strategy frame'])
    lines(778, ['code checks the tier', 'sections exist; the', 'argument: the model\'s'])

    cols = [16, 72, 176, 470]
    rows = [
        [('T1', 'dim'), ('analysts', 'orange', True), ('4 lenses read context.json', 'ink'), [('→ ', 'dim'), ('one merged table', 'mut')]],
        [('T2', 'dim'), ('bull', 'green', True), ('hold / add case', 'ink'), [('→ ', 'dim'), ('cites the pack', 'mut')]],
        [('T2', 'dim'), ('bear', 'red', True), ('trim / cut case', 'ink'), [('→ ', 'dim'), ('attacks the strongest consensus', 'mut')]],
        [('T2', 'dim'), ('record', 'purple', True), ('where they disagree', 'ink'), [('→ ', 'dim'), ('written into the brief', 'mut')]],
        [('T3', 'dim'), ('risk', 'orange', True), ('aggressive · conservative · neutral', 'ink'), [('→ ', 'dim'), ('every call stressed', 'mut')]],
        [('T3', 'dim'), ('judge', 'orange', True), ('names the strategy frame', 'ink'), [('→ ', 'dim'), ('plan.json', 'pink')]],
        [('next', 'dim'), ('python', 'green', True), ('grades the calls', 'ink'), [('→ ', 'dim'), ('code settles the score', 'mut')]],
    ]
    end = s.log(28, 878, 824, rows, cols, title='pre-open brief · debate')
    s.prompt(28, end + 34, 'clawock brief postflight',
             [('tier 1 ', 'dim'), ('[4 lenses]', 'orange'), ('  tier 2 ', 'dim'), ('[bull · bear]', 'red'),
              ('  tier 3 ', 'dim'), ('[3 risk voices · judge]', 'orange'), ('  out ', 'dim'), ('[plan.json]', 'pink')])
    assert end + 34 + 22 + 18 <= H, end
    return s.render()


DIAGRAMS = {
    'information-flow.svg': information_flow,
    'architecture.svg': architecture,
    'product-architecture.svg': product_architecture,
    'debate-flow.svg': debate_flow,
}


def main(argv):
    assets = Path(__file__).resolve().parents[1] / 'assets'
    rendered = {name: build() for name, build in DIAGRAMS.items()}
    if WARN:
        print('\n'.join(WARN), file=sys.stderr)
        return 1
    stale = [n for n, svg in rendered.items() if (assets / n).read_text(encoding='utf-8') != svg]
    if '--check' in argv:
        for n in stale:
            print(f'site/assets/{n} differs from its builder', file=sys.stderr)
        return 1 if stale else 0
    for n in stale:
        (assets / n).write_text(rendered[n], encoding='utf-8')
        print(f'wrote site/assets/{n}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
