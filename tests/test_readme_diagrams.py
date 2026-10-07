"""The README diagrams are generated; the SVGs must be what the builder emits.

`site/tools/build_readme_diagrams.py` owns every label and coordinate. A hand
edit to one of the SVGs would be overwritten by the next rebuild, so the drift
is caught here instead of in a later diff nobody connects to it.

The README shows them through `<img>`, where browsers run no script and load no
external resource; the animation must come from CSS and SMIL inside the file.

Each diagram is one composition. The README scales the same file for a phone
instead of swapping in a second, single-column drawing, so both readers see the
same picture. Every diagram shares one 1016-unit canvas and one type scale, so
the same class of label is the same size in every figure on the page.
"""
import importlib.util
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / 'site/tools/build_readme_diagrams.py'
SVG = '{http://www.w3.org/2000/svg}'


def _builder():
    spec = importlib.util.spec_from_file_location('build_readme_diagrams', BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_diagrams_match_their_builder():
    assert _builder().main(['--check']) == 0, (
        'run `python3 site/tools/build_readme_diagrams.py` and commit the SVGs')


def test_rsi_views_share_the_house_style_and_stay_small():
    builder = _builder()
    names = {'rsi-loop', 'feedback-learning'}
    assert names <= builder.LAYOUTS.keys()
    for name in names:
        path = ROOT / 'site/assets' / f'{name}.svg'
        text = path.read_text(encoding='utf-8')
        # Vector only: the overview inlines nine logos and still loads like an icon.
        assert path.stat().st_size < 100_000, path.name
        for primitive in ('url(#glass)', 'url(#sheen)', 'url(#rim)', 'url(#grain)'):
            assert primitive in text, (path.name, primitive)
        assert '@media (prefers-reduced-motion:reduce)' in text
        root = ET.fromstring(text)
        for motion in root.iter(f'{SVG}animateMotion'):
            parent = next(el for el in root.iter() if motion in list(el))
            assert 'pulse' in parent.attrib.get('class', '').split(), path.name


def test_diagrams_animate_without_anything_an_img_would_drop():
    for name in _builder().DIAGRAMS:
        root = ET.parse(ROOT / 'site/assets' / name).getroot()
        tags = {el.tag.removeprefix(SVG) for el in root.iter()}
        assert 'script' not in tags and 'foreignObject' not in tags, name
        # A filter rasterises the text beneath it at the viewBox resolution.
        assert 'filter' not in tags, name
        assert 'animateMotion' in tags, f'{name} has no moving packets'
        assert root.find(f'{SVG}title') is not None, name
        for image in root.iter(f'{SVG}image'):
            assert image.attrib['href'].startswith('data:image/png;base64,'), (
                f'{name}: an SVG inside an img cannot load an external screenshot')


def _placed(root, tag, dx=0.0, dy=0.0):
    """Every `tag` element with the offset of the column group it is drawn in.

    A column flow draws each run inside `<g transform="translate">`, so a walk
    over the root's own children would see the header and nothing else.
    """
    for el in root:
        if el.tag == f'{SVG}{tag}':
            yield el, dx, dy
        elif el.tag == f'{SVG}g':
            # A column group is a bare translate; an icon's group also scales.
            column = re.fullmatch(r'translate\((\S+) (\S+)\)', el.attrib.get('transform', ''))
            if column:
                cx, cy = map(float, column.groups())
                yield from _placed(el, tag, dx + cx, dy + cy)
            elif not el.attrib.get('transform'):
                # The large overview names semantic regions with untransformed
                # groups. Walk their cards too; they must not evade overlap checks.
                yield from _placed(el, tag, dx, dy)


def test_one_composition_serves_every_width():
    """A phone gets the desktop drawing scaled down, never a second layout.

    A separate single-column file is a different picture: its own seams, gaps
    and wraps, drifting from the one that was actually looked at. The hero's
    book card is owned by build_readme_book_charts.py and is not covered here.
    """
    builder = _builder()
    assert set(builder.DIAGRAMS) == {f'{name}.svg' for name in builder.LAYOUTS}
    for readme, base in (('README.md', 'refs/heads/master/site/assets/'), ('README.zh.md', 'site/assets/')):
        text = (ROOT / readme).read_text(encoding='utf-8')
        for name in builder.LAYOUTS:
            width = builder.WIDE
            assert re.search(rf'<img src="[^"]*{re.escape(base + name)}\.svg" width="{width}"', text), (readme, name)
            assert f'{name}-narrow.svg' not in text, (readme, name)
    for name in builder.LAYOUTS:
        assert not (ROOT / 'site/assets' / f'{name}-narrow.svg').exists(), name
        root = ET.parse(ROOT / 'site/assets' / f'{name}.svg').getroot()
        assert float(root.attrib['width']) == builder.WIDE


def _wire_points(d, step=4.0):
    """Points along a connector path: the builder emits M, H, V, C, Q and full-turn A."""
    out, x, y = [], 0.0, 0.0
    for cmd, args in re.findall(r'([MHVCQA])([^MHVCQA]*)', d):
        n = [float(v) for v in re.findall(r'-?\d+(?:\.\d+)?', args)]
        if cmd == 'M':
            x, y = n
            out.append((x, y))
            continue
        if cmd == 'A':                 # a wheel: start at twelve o'clock, come back round
            r = n[0]
            out += [(x + r * math.sin(t / 30 * math.pi), y + r - r * math.cos(t / 30 * math.pi))
                    for t in range(60)]
            x, y = n[-2:]
            continue
        ctrl = {'H': [(n[0], y)], 'V': [(x, n[0])]}.get(cmd) or list(zip(n[::2], n[1::2]))
        pts = [(x, y)] + ctrl
        length = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
        for i in range(1, max(2, int(length / step)) + 1):
            t, level = i / max(2, int(length / step)), pts
            while len(level) > 1:      # de Casteljau: a line, a quadratic or a cubic alike
                level = [(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                         for a, b in zip(level, level[1:])]
            out.append(level[0])
        x, y = ctrl[-1]
    return out


def _connector_label_collisions(builder, root):
    """(connector id, label) pairs where a stroke passes through set text."""
    sizes = {cls: size for cls, (size, _, _) in builder.TYPE.items()}
    for style in root.iter(f'{SVG}style'):       # a diagram may enlarge its own scale
        sizes.update({cls: float(px) for cls, px in
                      re.findall(r'\.(\w+)\{font-size:([\d.]+)px\}', style.text or '')})
    labels = []
    for el, dx, dy in _placed(root, 'text'):
        label, cls = ''.join(el.itertext()), el.attrib.get('class', 'b')
        if 'transform' in el.attrib or cls not in builder.TYPE or not label.strip():
            continue
        size = sizes[cls]
        w = len(label) * size * builder.TYPE[cls][2] * .9      # fits() pads its advances
        x = float(el.attrib['x']) + dx - {'middle': w / 2, 'end': w}.get(el.attrib.get('text-anchor'), 0)
        y = float(el.attrib['y']) + dy
        labels.append((label, x, y - size * .72, x + w, y + size * .2))
    hits = set()
    for el, dx, dy in _placed(root, 'path'):
        if not re.fullmatch(r'w\d+', el.attrib.get('id', '')):
            continue
        for px, py in _wire_points(el.attrib['d']):
            for label, x0, y0, x1, y1 in labels:
                if x0 < px + dx < x1 and y0 < py + dy < y1:
                    hits.add((el.attrib['id'], label))
    return hits


def test_no_connector_runs_through_a_label():
    """A stroke behind words is the overlap a reader sees first.

    Text is measured with the builder's own advances, so this needs no browser
    and no font; the second half proves the check can fail.
    """
    builder = _builder()
    for name in builder.DIAGRAMS:
        root = ET.parse(ROOT / 'site/assets' / name).getroot()
        assert not _connector_label_collisions(builder, root), name
    d = builder.D('probe', 'a label with a connector drawn straight through it')
    d.text(100, 100, 'Execution', 'm')
    d.wire('M60 96H240')
    assert _connector_label_collisions(builder, ET.fromstring(d.render(200))) == {('w1', 'Execution')}


def test_fan_arrows_land_on_the_node_they_point_at():
    """A curved branch ends where a straight one does: at the node, not short of it."""
    d = _builder().D('probe', 'one straight and one curved connector to the same edge')
    d.down(40, 10, 100)
    d.curve(80, 10, 120, 100)
    ends = [re.findall(r'-?\d+(?:\.\d+)?', el.attrib['d'])[-1]
            for el in ET.fromstring(d.render(200)).iter(f'{SVG}path') if el.attrib.get('id')]
    assert ends == ['98', '98']


def test_every_diagram_sets_type_on_the_one_shared_scale():
    """A figure that enlarges its own labels reads as a different page.

    The overview once redeclared five sizes to survive a 1440-unit canvas, so its
    body text was a third larger than the figure under it. Sizes come from
    `TYPE` alone; the two logo wordmark tiles are lettering inside a mark.
    """
    builder = _builder()
    scale = {f'{size:g}' for size, _, _ in builder.TYPE.values()}
    assert len(scale) <= 5, scale
    for name in builder.DIAGRAMS:
        text = (ROOT / 'site/assets' / name).read_text(encoding='utf-8')
        text = re.sub(r'<text [^>]*class="code"[^>]*style="font-size:[\d.]+px;font-weight:700">', '', text)
        declared = set(re.findall(r'font-size:([\d.]+)px', text))
        assert declared == scale, (name, declared ^ scale)


def test_the_overview_carries_every_step_and_every_harness_logo():
    """The first figure is the whole loop: all nine panels, all five harnesses."""
    text = (ROOT / 'site/assets/rsi-loop.svg').read_text(encoding='utf-8')
    root = ET.fromstring(text)
    labels = [''.join(el.itertext()) for el in root.iter(f'{SVG}text')]
    steps = [label for label in labels if re.match(r'0\d · ', label)]
    assert [step[:2] for step in steps] == [f'0{n}' for n in range(1, 10)], steps
    for harness in ('Claude Code', 'Codex', 'OpenClaw', 'DeepSeek Harness', 'Your own CLI'):
        assert harness in labels, harness
    # The harness rail and the clawock mark, then the background team that
    # maintains the desk: Claude Code, Codex and the dsh panel that watches them.
    assert len(root.findall(f'{SVG}svg')) == 9, 'six marks above, three in the maintenance loop'
    assert 'Currencies never sum directly' not in labels, 'a rule nobody needs drawn'
    assert float(root.attrib['height']) > 1.5 * float(root.attrib['width'])


def test_no_diagram_prints_a_file_path():
    """A label names the thing; where it lives on disk belongs to the docs."""
    for name in _builder().DIAGRAMS:
        root = ET.parse(ROOT / 'site/assets' / name).getroot()
        for el in root.iter(f'{SVG}text'):
            label = ''.join(el.itertext())
            assert not re.search(r'\b(?:memory|src|site|docs)/\w', label), (name, label)


def test_peer_nodes_do_not_touch_or_overlap():
    """Ignore intentional containment; sibling node boxes need breathing room.

    Tags, logos, chart marks and list sweep highlights aren't flow nodes. This
    catches the source-chip rows collapsing back to a two-unit gutter without
    depending on a specific label, row count, or font installed on the runner.
    """
    from itertools import combinations

    for name in _builder().DIAGRAMS:
        root = ET.parse(ROOT / 'site/assets' / name).getroot()
        nodes = []
        for el, dx, dy in _placed(root, 'rect'):
            # Highlights are light on a node, not nodes: the list sweep, the glass sheen.
            if el.attrib.get('class', '').split()[-1:] in (['sweep'], ['sheen']):
                continue
            x, y, w, h = (float(el.attrib[k]) for k in ('x', 'y', 'width', 'height'))
            if w >= 60 and h >= 30:
                nodes.append((x + dx, y + dy, x + dx + w, y + dy + h))
        assert len(nodes) > 6, f'{name}: only {len(nodes)} boxes found — did the walk break?'
        for a, b in combinations(nodes, 2):
            if (a[0] <= b[0] and a[1] <= b[1] and a[2] >= b[2] and a[3] >= b[3]
                    or b[0] <= a[0] and b[1] <= a[1] and b[2] >= a[2] and b[3] >= a[3]):
                continue
            dx = max(a[0], b[0]) - min(a[2], b[2])
            dy = max(a[1], b[1]) - min(a[3], b[3])
            if dx < 0:
                assert dy >= 5.99, (name, a, b, 'vertical gap', dy)
            elif dy < 0:
                assert dx >= 5.99, (name, a, b, 'horizontal gap', dx)


def _text_crowding(builder, root, clear=8.0):
    """(label, what it crowds, gap) wherever set text shares a line with something too near.

    A label is boxed with the builder's advances at full pad, wider than any face
    in the stack draws it. What it may crowd: another label, any rect (a card, a
    chip, a tag pill, a legend swatch) and any inlined mark. A box that wholly
    contains the label is its own container, not a neighbour.
    """
    texts, shapes = [], []
    for el, dx, dy in _placed(root, 'text'):
        label, cls = ''.join(el.itertext()), el.attrib.get('class', 'b')
        # Rotated margin notes and the lettering inside a wordmark tile are not set text.
        if 'transform' in el.attrib or 'style' in el.attrib or not label.strip():
            continue
        size, _, advance = builder.TYPE[cls]
        w = len(label) * size * advance
        x = float(el.attrib['x']) + dx - {'middle': w / 2, 'end': w}.get(el.attrib.get('text-anchor'), 0)
        y = float(el.attrib['y']) + dy
        texts.append((label, x, y - size * .72, x + w, y + size * .2))
    for tag in ('rect', 'svg', 'image'):
        for el, dx, dy in _placed(root, tag):
            if 'transform' in el.attrib or el.attrib.get('class', '').split()[-1:] in (['sweep'], ['sheen']):
                continue
            x, y, w, h = (float(el.attrib.get(k, 0)) for k in ('x', 'y', 'width', 'height'))
            shapes.append((f'{tag} {w:g}x{h:g} at {x + dx:g},{y + dy:g}', x + dx, y + dy, x + dx + w, y + dy + h))
    found = []
    for i, a in enumerate(texts):
        for b in texts[i + 1:] + shapes:
            if b[1] <= a[1] and b[2] <= a[2] and b[3] >= a[3] and b[4] >= a[4]:
                continue
            if min(a[4], b[4]) - max(a[2], b[2]) <= 0:
                continue                   # not on the same line: stacked rows are leading, not crowding
            gap = max(a[1], b[1]) - min(a[3], b[3])
            # A swatch or bullet belongs to the label it sits beside.
            if gap < (5.0 if b[3] - b[1] <= 12 and b[4] - b[2] <= 12 else clear):
                found.append((a[0], b[0], round(gap, 1)))
    return found


def test_no_label_crowds_what_shares_its_line():
    """Words that run into the pill, chip or words beside them read as one smear.

    The box gate above sees rects of node size only, so a heading could grow into
    the tag on its own baseline unnoticed: "You decide" stood 2 units from HUMAN.
    Labels set side by side on purpose pass by keeping the same clearance.
    """
    builder = _builder()
    for name in builder.DIAGRAMS:
        root = ET.parse(ROOT / 'site/assets' / name).getroot()
        assert len(list(_placed(root, 'text'))) > 30, f'{name}: did the walk break?'
        assert not _text_crowding(builder, root), name
    d = builder.D('probe', 'a heading against its tag, two labels run together, one label out of its chip')
    d.card(40, 40, 200, 120, 'warm')
    d.text(60, 72, 'You decide', 'h')
    d.tag(224, 70, 'HUMAN', 'warm', anchor='end')
    d.text(60, 110, 'HK session', 'm')
    d.text(130, 112, 'Bull', 'h')
    d.chip(300, 40, 80, 'a label wider than its chip')
    d.text(60, 128, 'Stacked rows', 'm')
    d.text(60, 149, 'in one card are fine', 'm')
    builder.WARN.clear()                   # the chip's own fits() warning is the builder's, not this gate's
    crowded = {(a, b.split()[0]) for a, b, _ in _text_crowding(builder, ET.fromstring(d.render(200)))}
    assert crowded == {('You decide', 'rect'), ('HK session', 'Bull'), ('a label wider than its chip', 'rect')}


def _packet_trouble(builder, root, clear=4.0):
    """(connector id, what it meets) wherever a running packet has too little room.

    A packet is a disc of `PACKET_R` that travels the stretch of its connector
    named by `keyPoints`. Along all of it the disc keeps `clear` from set text,
    inlined marks and glyphs, and never sits across the edge of a box: it is
    either inside the pane it runs in or outside the node it runs past.
    """
    r, texts, boxes = builder.PACKET_R, [], []
    for el, dx, dy in _placed(root, 'text'):
        label, cls = ''.join(el.itertext()), el.attrib.get('class', 'b')
        if 'style' in el.attrib or not label.strip():
            continue
        size, _, advance = builder.TYPE[cls]
        w, x, y = len(label) * size * advance, float(el.attrib['x']) + dx, float(el.attrib['y']) + dy
        if el.attrib.get('transform', '').startswith('rotate(90 '):     # a margin note, read downwards
            texts.append((label, x - size * .2, y - w / 2, x + size * .72, y + w / 2))
            continue
        x -= {'middle': w / 2, 'end': w}.get(el.attrib.get('text-anchor'), 0)
        # A kicker in capitals stands on its baseline; mixed case hangs descenders under it.
        texts.append((label, x, y - size * .72, x + w, y + (0 if label == label.upper() else size * .2)))
    for tag in ('svg', 'image'):
        for el, dx, dy in _placed(root, tag):
            x, y, w, h = (float(el.attrib.get(k, 0)) for k in ('x', 'y', 'width', 'height'))
            texts.append((tag, x + dx, y + dy, x + dx + w, y + dy + h))

    def glyphs(node, dx, dy):
        for el in node:
            move = re.match(r'translate\((\S+) (\S+)\)(?: scale\((\S+)\))?$', el.attrib.get('transform', ''))
            if el.tag != f'{SVG}g' or not move and el.attrib.get('transform'):
                continue
            x, y = dx + float(move[1] if move else 0), dy + float(move[2] if move else 0)
            if 'data-icon' in el.attrib:
                texts.append((f'glyph {el.attrib["data-icon"]}', x, y, x + 24 * float(move[3]), y + 24 * float(move[3])))
            else:
                glyphs(el, x, y)
    glyphs(root, 0, 0)
    for el, dx, dy in _placed(root, 'rect'):
        if el.attrib.get('class', '').split()[-1:] in (['sweep'], ['sheen']):
            continue
        x, y, w, h = (float(el.attrib.get(k, 0)) for k in ('x', 'y', 'width', 'height'))
        if w >= 20 and h >= 14:
            boxes.append((f'rect {w:g}x{h:g}', x + dx, y + dy, x + dx + w, y + dy + h))
    wires = {el.attrib['id']: (el.attrib['d'], dx, dy) for el, dx, dy in _placed(root, 'path') if 'id' in el.attrib}
    found, packets = set(), 0
    for el, _, _ in _placed(root, 'use'):
        packets += 1
        motion = el.find(f'{SVG}animateMotion')
        wire = motion.find(f'{SVG}mpath').attrib['href'][1:]
        first, last = map(float, motion.attrib['keyPoints'].split(';'))
        d, dx, dy = wires[wire]
        points, along = builder.path_points(d, 2), [0.0]
        for a, b in zip(points, points[1:]):
            along.append(along[-1] + math.dist(a, b))
        for (px, py), s in zip(points, along):
            if not first <= s / along[-1] <= last:
                continue
            px, py = px + dx, py + dy
            for what, x0, y0, x1, y1 in texts:
                if max(x0 - px, px - x1, y0 - py, py - y1) - r < clear:
                    found.add((wire, what))
            for what, x0, y0, x1, y1 in boxes:
                inside = x0 <= px - r and px + r <= x1 and y0 <= py - r and py + r <= y1
                outside = max(x0 - px, px - x1, y0 - py, py - y1) >= r
                if not inside and not outside:
                    found.add((wire, what.split()[0]))
    return found, packets


def test_no_running_packet_brushes_a_label_or_rides_a_box_edge():
    """A packet is an icon the size of a letter, moving: it needs the room a label does.

    The stroke gate above only asks whether the line itself passes behind words.
    A packet is 16 units across, so a line that clears a label by 6 still drags
    its icon over the descenders, and a fan curve that leaves a card sideways
    carries it along under the card's edge. The probe shows both can fail.
    """
    builder = _builder()
    for name in builder.DIAGRAMS:
        trouble, packets = _packet_trouble(builder, ET.parse(ROOT / 'site/assets' / name).getroot())
        assert not trouble, (name, sorted(trouble))
        assert packets, f'{name}: no connector is long enough to carry a packet'
    d = builder.D('probe', 'a packet under a label, one along a card edge, one in the open')
    d.card(40, 40, 200, 80, 'blue')
    d.text(60, 160, 'Settled', 'm')
    d.wire('M30 172H300')                  # the line clears the word; its packet does not
    d.wire('M20 124H300', kind='money')    # along the card's lower edge
    d.wire('M20 260H300', kind='task')
    trouble, packets = _packet_trouble(builder, ET.fromstring(d.render(320)))
    assert trouble == {('w1', 'Settled'), ('w2', 'rect')} and packets == 3
    assert not _connector_label_collisions(builder, ET.fromstring(d.render(320)))


def test_each_kind_of_flow_keeps_its_own_line_when_nothing_moves():
    """Reduced motion hides every packet; the line and its arrowhead still say what is carried.

    Colour is left out of the comparison on purpose: two kinds that differ only
    in hue are one kind to a reader who cannot tell the hues apart.
    """
    builder = _builder()
    d = builder.D('probe', 'one connector of every kind')
    for i, kind in enumerate(builder.KIND):
        d.wire(f'M40 {40 + i * 30}H400', kind=kind)
    root = ET.fromstring(d.render(320))
    heads = {m.attrib['id']: (m[0].attrib['d'], m[0].attrib['fill'] != 'none') for m in root.iter(f'{SVG}marker')}
    paths = [el for el in root.iter(f'{SVG}path') if 'id' in el.attrib or 'marker-end' in el.attrib]
    looks = {}
    for kind in builder.KIND:
        own = [el for el in paths if el.attrib.get('data-kind') == kind]
        rails = [el for el in paths if el.attrib.get('marker-end') == f'url(#arr-{kind})']
        assert len(own) == 1 and len(rails) == 1, kind
        looks[kind] = (own[0].attrib.get('stroke-dasharray'), own[0].attrib['stroke-width'],
                       own[0] is not rails[0], heads[f'arr-{kind}'])
    assert len(set(looks.values())) == len(builder.KIND) >= 8, looks
    for name in builder.DIAGRAMS:
        root = ET.parse(ROOT / 'site/assets' / name).getroot()
        ids = {el.attrib['id'] for el in root.iter() if 'id' in el.attrib}
        for el, _, _ in _placed(root, 'path'):
            if re.fullmatch(r'w\d+', el.attrib.get('id', '')):
                assert el.attrib.get('data-kind') in builder.KIND, (name, el.attrib['id'])
        for el in root.iter(f'{SVG}use'):
            # An <img> loads nothing from outside the file, so a packet is drawn from its own <defs>.
            assert el.attrib['href'][0] == '#' and el.attrib['href'][1:] in ids, (name, el.attrib['href'])
