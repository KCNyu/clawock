"""One SVG composition at every width, with generated and geometric contracts.

The user replaced the dual-layout intent: text parity and a desktop/narrow
height ratio no longer describe the design. Pin one composition, a readable
font floor, exact anchor seams, collision-free labels, spacing and both README
consumers instead. Deliberate malformed drawings prove the geometry gate fails.
"""
import importlib.util
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

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
        assert not tags & {'script', 'foreignObject', 'filter'}, name
        assert 'animateMotion' in tags, f'{name} has no moving packets'
        assert root.find(f'{SVG}title') is not None, name
        assert root.find(f'{SVG}desc') is not None, name
        for image in root.iter(f'{SVG}image'):
            assert image.attrib['href'].startswith('data:image/png;base64,'), name


def test_one_composition_and_both_readme_consumers():
    builder = _builder()
    assert set(builder.DIAGRAMS) == {f'{name}.svg' for name in builder.LAYOUTS}
    # The sole exception is a byte-identical filename alias needed by the
    # separately protected first 33 lines. It is never a different layout.
    assert {p.name for p in (ROOT / 'site/assets').glob('*-narrow.svg')} == {'books-narrow.svg'}
    assert (ROOT / 'site/assets/books-narrow.svg').read_bytes() == (ROOT / 'site/assets/books.svg').read_bytes()
    for readme in ('README.md', 'README.zh.md'):
        body = '\n'.join((ROOT / readme).read_text(encoding='utf-8').splitlines()[33:])
        assert '<picture>' not in body and '-narrow.svg' not in body, readme
        for name in builder.LAYOUTS:
            width = builder.DESKTOP_WIDTHS.get(name, builder.WIDE)
            assert re.search(rf'<img[^>]+site/assets/{name}\.svg" width="{width}"', body), (readme, name)
    for name in builder.LAYOUTS:
        root = ET.parse(ROOT / 'site/assets' / f'{name}.svg').getroot()
        expected_width = builder.DESKTOP_WIDTHS.get(name, builder.WIDE)
        assert float(root.attrib['width']) == expected_width
        assert root.attrib['viewBox'] == f'0 0 {expected_width} {root.attrib["height"]}'


def test_font_floor_at_324_css_pixels():
    """Arithmetic contract, explicitly not a substitute for real-device testing."""
    builder = _builder()
    for name in builder.DIAGRAMS:
        root = ET.parse(ROOT / 'site/assets' / name).getroot()
        css = ''.join(el.text or '' for el in root.iter(f'{SVG}style'))
        sizes = {cls: float(size) for cls, size in re.findall(r'\.([\w-]+)\{font-size:([\d.]+)px', css)}
        scale = 324 / float(root.attrib['width'])
        for text in root.iter(f'{SVG}text'):
            assert 'style' not in text.attrib, (name, 'inline font escapes the scale contract')
            size = sizes[text.attrib['class']]
            assert size * scale >= 10, (name, ''.join(text.itertext()), size, scale)
            assert size == builder.TYPE[text.attrib['class']][0]


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
    assert any(p.attrib.get('data-from') == 'return:left' and p.attrib.get('data-to') == 'input:top'
               for p in root.iter(f'{SVG}path')), 'feedback must visibly return to input'


def test_all_committed_diagrams_pass_geometry_checks():
    builder = _builder()
    for name in builder.DIAGRAMS:
        svg = (ROOT / 'site/assets' / name).read_text(encoding='utf-8')
        assert builder.validate_geometry(svg), name


def _fixture(builder):
    d = builder.Canvas('architecture', 'Geometry fixture')
    d.panel('left', 36, 200, 432, 240, 'Left', ['Evidence'], 'blue')
    d.panel('right', 548, 200, 432, 240, 'Right', ['Decision'], 'green')
    d.link(('left', 'right'), ('right', 'left'))
    return ET.fromstring(d.finish(500))


@pytest.mark.parametrize('fault, message', [
    ('seam', 'connector seam'), ('overflow', 'pane text overflow'),
    ('text_collision', 'text collision'), ('pane_collision', 'pane collision'),
    ('spacing', 'horizontal breathing room'), ('through_text', 'connector crosses text'),
    ('graphic_collision', 'graphic crosses text'), ('small_font', 'mobile font floor'),
    ('off_canvas', 'pane canvas overflow'), ('unowned', 'unowned text touches pane'),
])
def test_deliberately_bad_drawings_are_rejected(fault, message):
    builder = _builder()
    root = _fixture(builder)
    text = next(el for el in root.iter(f'{SVG}text') if el.attrib.get('data-in') == 'left')
    path = next(el for el in root.iter(f'{SVG}path') if 'data-from' in el.attrib)
    nodes = {el.attrib['data-node']: el for el in root.iter(f'{SVG}rect') if 'data-node' in el.attrib}
    if fault == 'seam':
        path.set('d', 'M467 320 L548 320')  # visible one-unit gap at the source boundary
    elif fault == 'overflow':
        text.set('x', '40')
    elif fault == 'text_collision':
        duplicate = ET.fromstring(ET.tostring(text, encoding='unicode'))
        duplicate.set('y', str(float(text.attrib['y']) + 2))
        root.append(duplicate)
    elif fault == 'pane_collision':
        nodes['left'].set('width', '600')
    elif fault == 'spacing':
        nodes['left'].set('width', '488')  # 24-unit gap, below the 28-unit floor
    elif fault == 'unowned':
        del text.attrib['data-in']
    elif fault == 'small_font':
        text.set('class', 'code')
    elif fault == 'off_canvas':
        nodes['left'].set('x', '-1')
    elif fault == 'graphic_collision':
        root.append(ET.fromstring('<rect xmlns="http://www.w3.org/2000/svg" data-obstacle="icon" x="60" y="230" width="60" height="60"/>'))
    elif fault == 'through_text':
        path.set('d', 'M468 320 L500 320 L500 250 L60 250 L60 320 L548 320')
    with pytest.raises(AssertionError, match=message):
        builder.validate_geometry(ET.tostring(root, encoding='unicode'))


def test_a_label_overflow_prevents_any_write(monkeypatch):
    builder = _builder()
    monkeypatch.setattr(builder, 'DIAGRAMS', {'broken.svg': lambda: builder.fits('W' * 20, 'body', 50, 'broken') or ''})
    assert builder.main([]) == 1
    assert not (ROOT / 'site/assets/broken.svg').exists()


def test_risk_labels_are_generated_from_policy_constants():
    import ast

    tree = ast.parse((ROOT / 'src/clawock/portfolio/guardrail.py').read_text())
    assignment = next(n for n in tree.body if isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == 'GUARDRAIL_CAPS' for t in n.targets))
    caps = ast.literal_eval(assignment.value)
    builder = _builder()
    assert builder.risk_caps() == caps
    root = ET.fromstring(builder.guardrails())
    labels = [''.join(t.itertext()) for t in root.iter(f'{SVG}text')]
    for key in ('leveraged_single_name_pct', 'correlated_cluster_pct', 'lev_etf_leg_pct'):
        assert f"≤ {caps[key]:g}%" in labels
    assert f"≤ {caps['single_name_mandatory_pct']:g}% / review {caps['single_name_review_pct']:g}%" in labels
    assert f"≤ {caps['us_beta_max']:.1f}" in labels
    assert f"{caps['lev_etf_stop_pct']:g}%".replace('-', '−') in labels
    assert 'guardrail.py:GUARDRAIL_CAPS' in root.find(f'{SVG}desc').text
