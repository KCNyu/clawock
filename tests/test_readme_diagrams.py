"""The README diagrams are generated; the SVGs must be what the builder emits.

`site/tools/build_readme_diagrams.py` owns every label and coordinate. A hand
edit to one of the SVGs would be overwritten by the next rebuild, so the drift
is caught here instead of in a later diff nobody connects to it.

The README shows them through `<img>`, where browsers run no script and load no
external resource; the animation must come from CSS and SMIL inside the file.

Each diagram exists twice: a desktop layout under its name and a narrow one
beside it as `<name>-narrow.svg`. The RSI overview has a larger canvas and
semantic side regions; the other views retain their established desktop width.
Both variants share content, so the checks below run over both.
"""
import importlib.util
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
        for suffix in ('', '-narrow'):
            path = ROOT / 'site/assets' / f'{name}{suffix}.svg'
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


def _placed_rects(root, dx=0.0, dy=0.0):
    """Every rect with the offset of the column group it is drawn in.

    The wide layout draws each run of a column inside `<g transform="translate">`,
    so a walk over the root's own children would see the header and nothing else.
    """
    for el in root:
        if el.tag == f'{SVG}rect':
            yield el, dx, dy
        elif el.tag == f'{SVG}g':
            # A column group is a bare translate; an icon's group also scales.
            column = re.fullmatch(r'translate\((\S+) (\S+)\)', el.attrib.get('transform', ''))
            if column:
                cx, cy = map(float, column.groups())
                yield from _placed_rects(el, dx + cx, dy + cy)
            elif not el.attrib.get('transform'):
                # The large overview names semantic regions with untransformed
                # groups. Walk their cards too; they must not evade overlap checks.
                yield from _placed_rects(el, dx, dy)


def test_every_diagram_has_a_wide_and_a_narrow_layout_and_the_readmes_use_both():
    """A phone gets the single column and a desktop the two-column canvas.

    The wide layout is unreadable at phone width and the narrow one is a tower
    three screens tall in a README column, so each README entry has to name both
    and the two files have to carry the same words.
    """
    builder = _builder()
    # The requested total-to-parts overview needs source/ownership sidebars,
    # three central stages and a bottom return lane. Its larger text is drawn
    # on a 1440 canvas; all other desktop views keep the established 1016.
    desktop_widths = builder.DESKTOP_WIDTHS
    for readme, base in (('README.md', 'refs/heads/master/site/assets/'), ('README.zh.md', 'site/assets/')):
        text = (ROOT / readme).read_text(encoding='utf-8')
        for name in builder.LAYOUTS:
            assert ('<source media="(max-width: 700px)" srcset="' in text
                    and f'{base}{name}-narrow.svg"><img src=' in text), (readme, name)
            width = desktop_widths.get(name, builder.WIDE)
            assert f'{base}{name}.svg" width="{width}"' in text, (readme, name)
    for name in builder.LAYOUTS:
        wide = ET.parse(ROOT / 'site/assets' / f'{name}.svg').getroot()
        narrow = ET.parse(ROOT / 'site/assets' / f'{name}-narrow.svg').getroot()
        assert float(wide.attrib['width']) == desktop_widths.get(name, builder.WIDE)
        assert float(narrow.attrib['width']) == builder.W
        assert float(wide.attrib['height']) < float(narrow.attrib['height']) * .75, (
            f'{name}: the wide layout is not meaningfully shorter than the column')
        # The wide header sets on one line what the column sets on two.
        words = lambda root: sorted(' '.join(  # noqa: E731
            ''.join(t.itertext()) for t in root.iter(f'{SVG}text')).split())
        assert words(wide) == words(narrow), f'{name}: the two layouts say different things'


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
        for el, dx, dy in _placed_rects(root):
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
