"""The README diagrams are generated; the SVGs must be what the builder emits.

`site/tools/build_readme_diagrams.py` owns every label and coordinate. A hand
edit to one of the SVGs would be overwritten by the next rebuild, so the drift
is caught here instead of in a later diff nobody connects to it.

The README shows them through `<img>`, where browsers run no script and load no
external resource; the animation must come from CSS and SMIL inside the file.

Each diagram is one composition. The README scales the same file for a phone
instead of swapping in a second, single-column drawing, so both readers see the
same picture. The RSI overview has a larger canvas and semantic side regions;
the other views share the established 1016-unit width.
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
    names = {'rsi-loop', 'evidence-receipt', 'feedback-learning'}
    assert names <= builder.LAYOUTS.keys()
    for name in names:
        path = ROOT / 'site/assets' / f'{name}.svg'
        text = path.read_text(encoding='utf-8')
        assert path.stat().st_size < 40_000, path.name
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
    desktop_widths = builder.DESKTOP_WIDTHS
    assert set(builder.DIAGRAMS) == {f'{name}.svg' for name in builder.LAYOUTS}
    for readme, base in (('README.md', 'refs/heads/master/site/assets/'), ('README.zh.md', 'site/assets/')):
        text = (ROOT / readme).read_text(encoding='utf-8')
        for name in builder.LAYOUTS:
            width = desktop_widths.get(name, builder.WIDE)
            assert re.search(rf'<img src="[^"]*{re.escape(base + name)}\.svg" width="{width}"', text), (readme, name)
            assert f'{name}-narrow.svg' not in text, (readme, name)
    for name in builder.LAYOUTS:
        assert not (ROOT / 'site/assets' / f'{name}-narrow.svg').exists(), name
        root = ET.parse(ROOT / 'site/assets' / f'{name}.svg').getroot()
        assert float(root.attrib['width']) == desktop_widths.get(name, builder.WIDE)


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


def test_rsi_overview_has_side_regions_and_a_bottom_return_lane():
    root = ET.parse(ROOT / 'site/assets/rsi-loop.svg').getroot()
    assert float(root.attrib['width']) == 1440
    regions = {el.attrib['data-region']: el for el in root.iter(f'{SVG}g')
               if 'data-region' in el.attrib}
    assert set(regions) == {'sources', 'input', 'decision', 'outcome', 'owners', 'return'}
    cards = {key: group.find(f'{SVG}rect') for key, group in regions.items()}
    bounds = {key: tuple(float(card.attrib[a]) for a in ('x', 'y', 'width', 'height'))
              for key, card in cards.items()}
    assert bounds['sources'][0] < bounds['input'][0] < bounds['decision'][0] < bounds['outcome'][0]
    assert bounds['outcome'][0] < bounds['owners'][0]
    assert bounds['return'][1] > max(y + h for key, (_, y, _, h) in bounds.items() if key != 'return')
    assert bounds['return'][2] > bounds['input'][2] + bounds['decision'][2] + bounds['outcome'][2]


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
