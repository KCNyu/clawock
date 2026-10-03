"""The README diagrams are generated; the SVGs must be what the builder emits.

`site/tools/build_readme_diagrams.py` owns every label and coordinate. A hand
edit to one of the SVGs would be overwritten by the next rebuild, so the drift
is caught here instead of in a later diff nobody connects to it.

The README shows them through `<img>`, where browsers run no script and load no
external resource; the animation must come from CSS and SMIL inside the file.
"""
import importlib.util
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
        for el in root.findall(f'{SVG}rect'):
            if 'sweep' in el.attrib.get('class', ''):
                continue
            x, y, w, h = (float(el.attrib[k]) for k in ('x', 'y', 'width', 'height'))
            if w >= 60 and h >= 30:
                nodes.append((x, y, x + w, y + h))
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


def _path_endpoint(d):
    """Interpret absolute generated SVG segments; don't guess from the last digit."""
    import re
    tokens = re.findall(r'[A-Za-z]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?', d)
    i, point = 0, (0.0, 0.0)
    arity = {'M': 2, 'L': 2, 'H': 1, 'V': 1, 'C': 6, 'Q': 4}
    while i < len(tokens):
        command = tokens[i]
        assert command in arity, f'unsupported generated segment {command}'
        n = arity[command]
        coords = list(map(float, tokens[i + 1:i + n + 1]))
        assert len(coords) == n
        if command == 'H':
            point = (coords[0], point[1])
        elif command == 'V':
            point = (point[0], coords[0])
        else:
            point = tuple(coords[-2:])
        i += n + 1
    return point


def test_connectors_declare_real_targets_and_enter_their_outlines():
    """CI catches detached arrowheads even when they happen to miss every label.

    Browser bbox/marker/halo checks are provided by audit_readme_diagrams.py.
    Here the declared graph and rounded rectangle interiors need no fonts or
    browser downloads, and a whole-page rectangle cannot serve as a target.
    """
    from collections import defaultdict

    for name in _builder().DIAGRAMS:
        root = ET.parse(ROOT / 'site/assets' / name).getroot()
        nodes = {e.attrib['id']: e for e in root.iter() if 'data-node' in e.attrib}
        fanout = defaultdict(list)
        for edge in root.iter(f'{SVG}path'):
            if not edge.attrib.get('id', '').startswith('w'):
                continue
            source, target = edge.attrib.get('data-source'), edge.attrib.get('data-target')
            assert source in nodes and target in nodes, (name, edge.attrib)
            assert source != target, (name, source, target)
            fanout[source].append(target)
            node = nodes[target]
            if node.tag != f'{SVG}rect':
                # Operation glyph bounds are checked in the rendered audit.
                assert node.attrib.get('class') == 'hero-icon'
                continue
            x, y, w, h = (float(node.attrib[k]) for k in ('x', 'y', 'width', 'height'))
            ex, ey = _path_endpoint(edge.attrib['d'])
            assert x < ex < x + w and y < ey < y + h, (name, edge.attrib['id'], target, ex, ey)
            radius = float(node.attrib.get('rx', 0))
            nx = min(max(ex, x + radius), x + w - radius)
            ny = min(max(ey, y + radius), y + h - radius)
            assert (ex - nx)**2 + (ey - ny)**2 < radius**2, (name, target, 'rounded corner')
        assert all(len(targets) == len(set(targets)) for targets in fanout.values()), (name, fanout)


def test_morning_debate_fanout_has_both_cases_and_all_risk_voices():
    root = ET.parse(ROOT / 'site/assets/decision-pipeline.svg').getroot()
    graph = {(e.attrib['data-source'], e.attrib['data-target'])
             for e in root.iter(f'{SVG}path') if 'data-target' in e.attrib}
    assert {('merged-table', 'bull'), ('merged-table', 'bear')} <= graph
    assert {(lens, 'merged-table') for lens in ('fundamental', 'technical', 'sentiment', 'sector')} <= graph
    assert {('opposition', voice) for voice in ('aggressive', 'conservative', 'neutral')} <= graph
    assert {('preflight', lens) for lens in ('fundamental', 'technical', 'sentiment', 'sector')} <= graph
    assert ('judge', 'postflight') in graph


def test_harness_keeps_the_complete_live_host_capture():
    """The real quota bars and task history are evidence, not illustrative states."""
    import base64
    root = ET.parse(ROOT / 'site/assets/harnesses.svg').getroot()
    images = list(root.iter(f'{SVG}image'))
    assert len(images) == 1
    assert base64.b64decode(images[0].attrib['href'].split(',', 1)[1]) == (
        ROOT / 'site/assets/dsh-dispatch-queue.png').read_bytes()


def test_connectors_have_at_most_three_rounded_turns():
    """A target-valid detour can still be unreadable; cap avoidance corners."""
    import re
    for name in _builder().DIAGRAMS:
        root = ET.parse(ROOT / 'site/assets' / name).getroot()
        for edge in root.iter(f'{SVG}path'):
            if edge.attrib.get('class') == 'connection':
                assert len(re.findall('[Qq]', edge.attrib['d'])) <= 3, (name, edge.attrib['id'])
