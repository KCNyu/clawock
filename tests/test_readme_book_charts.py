"""The README's per-book P&L charts are drawn from the dashboard payload.

`site/tools/build_readme_book_charts.py` turns `dashboard.json` into
`site/assets/books.svg` and `books-narrow.svg`, one composition and a legacy filename alias of the two-book
card in the README's hero; the weekly README refresh calls it from the payload
it reads the placeholders from. The payload is not in a test checkout, so these
run the builder on a small synthetic one and pin what a chart of money can get
quietly wrong: reading a snapshot column by position, printing a percentage
without the basis the payload divided by, letting the hero alias select a different
composition, writing a partial chart when a label no longer fits, and motion that
ignores prefers-reduced-motion or leaves the first frame incomplete.
"""
import importlib.util
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SVG = '{http://www.w3.org/2000/svg}'


def _load(relative, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def charts():
    return _load('site/tools/build_readme_book_charts.py', 'build_readme_book_charts')


def _payload(columns=None):
    rows = [
        {'date': '2026-06-03', 'us_profit': 100.0, 'us_realized': 40.0,
         'hk_profit': -500.0, 'hk_realized': 70.0},
        {'date': '2026-07-01', 'us_profit': -20.0, 'us_realized': 60.0,
         'hk_profit': -9000.0, 'hk_realized': 70.0},
        {'date': '2026-08-04', 'us_profit': 300.0, 'us_realized': 250.0,
         'hk_profit': -4000.0, 'hk_realized': 70.0},
    ]
    columns = columns or ['date', 'us_profit', 'us_realized', 'hk_profit', 'hk_realized']
    return {
        'snapshots_columns': columns,
        'snapshots': [[row[c] for c in columns] for row in rows],
        'net_principal_return': {
            'us': {'net_principal': 800.0, 'total_profit': 300.0, 'return_pct': 30.0,
                   'return_basis': 'true_principal', 'true_principal': 1000.0},
            'hk': {'net_principal': 20000.0, 'total_profit': -4000.0, 'return_pct': -20.0,
                   'return_basis': 'net_principal'},
            'combined_usd': {'return_pct': -5.0, 'return_basis': 'mixed'},
        },
        'realized_vs_unrealized': {
            'us': {'realized': 250.0, 'unrealized': 50.0},
            'hk': {'realized': 70.0, 'unrealized': -4070.0},
        },
    }


def _labels(svg):
    return [''.join(el.itertext()) for el in ET.fromstring(svg).iter(f'{SVG}text')]


def _text(svg):
    return ' '.join(_labels(svg))


def _desc(svg):
    return ET.fromstring(svg).find(f'{SVG}desc').text


def test_the_curve_is_read_by_column_name(charts):
    """The packed rows carry no keys; a reordered payload must draw the same curve."""
    reordered = ['hk_realized', 'us_profit', 'date', 'hk_profit', 'us_realized']
    assert charts.series(_payload(reordered), 'us') == charts.series(_payload(), 'us')
    assert [total for _, total in charts.series(_payload(reordered), 'hk')] == [
        -500.0, -9000.0, -4000.0]
    assert charts.render_all(_payload(reordered)) == charts.render_all(_payload())


def test_each_percentage_is_printed_with_the_basis_the_payload_used(charts):
    """The amounts left the card; which denominator each return has did not."""
    for name, svg in charts.render_all(_payload()).items():
        labels = _labels(svg)
        # Each pane reads book, return, basis, in that order, then the footer.
        assert labels[:3] == ['US BOOK', '+30.00%', '÷ true_principal'], name
        assert labels[3:6] == ['HK BOOK', '\u221220.00%', '÷ net_principal'], name
        # The one figure spanning both books is the payload's own, with its own basis.
        assert labels[6] == 'combined \u22125.00%÷ mixed', name
        assert len(labels) == 8, f'{name}: a label was added to the card: {labels}'
        # No money is printed; the amounts behind each return are in the description.
        assert '$' not in ' '.join(labels), name
        desc = _desc(svg)
        assert '+US$300 on US$1,000 (true_principal)' in desc, name
        assert '\u2212HK$4,000 on HK$20,000 (net_principal)' in desc, name
        assert 'US$800' not in desc, 'the US book quoted net_principal for a true_principal return'

    # The basis is the payload's, not this file's: give HK a true_principal and
    # the card must follow it rather than keep the wording it had.
    payload = _payload()
    payload['net_principal_return']['hk'].update(
        return_basis='true_principal', true_principal=25000.0, return_pct=-16.0)
    payload['net_principal_return']['combined_usd']['return_basis'] = 'true_principal'
    svg = charts.render_all(payload)['books.svg']
    assert 'net_principal' not in _text(svg) and 'mixed' not in _text(svg)
    assert _labels(svg)[5] == '÷ true_principal'
    assert 'HK$25,000' in _desc(svg) and 'HK$20,000' not in _desc(svg)


def test_the_hero_compatibility_alias_is_the_same_composition(charts):
    """The protected hero link survives, but cannot select different geometry."""
    rendered = charts.render_all(_payload())
    assert set(rendered) == {'books.svg', 'books-narrow.svg'}
    assert rendered['books.svg'] == rendered['books-narrow.svg']
    assert (ROOT / 'site/assets/books.svg').read_bytes() == (ROOT / 'site/assets/books-narrow.svg').read_bytes()
    root = ET.fromstring(rendered['books.svg'])
    assert float(root.attrib['width']) == charts.house.WIDE


def test_the_two_books_never_share_a_scale_or_a_sum(charts):
    """One card, two plots: each curve spans its own half and its own range."""
    for name, svg in charts.render_all(_payload()).items():
        root = ET.fromstring(svg)
        curves = [el.attrib['d'] for el in root.iter(f'{SVG}path')
                  if el.attrib.get('class') == 'curve']
        assert len(curves) == 2, name
        points = [[tuple(map(float, pair.split())) for pair in d.replace('M', 'L').split('L')
                   if pair.strip()] for d in curves]
        half = float(root.attrib['width']) / 2
        assert max(x for x, _ in points[0]) < half < min(x for x, _ in points[1]), name
        # Own range: US moves 320 dollars and HK 8,500, yet the US curve is the
        # taller one, which a scale shared with HKD would flatten to a line.
        us_tall, hk_tall = (max(y for _, y in pts) - min(y for _, y in pts) for pts in points)
        assert us_tall > hk_tall > 20, (name, us_tall, hk_tall)
        # USD 300 and HKD -4000 are never combined into one amount, drawn or described.
        said = _text(svg) + _desc(svg)
        assert '3,700' not in said and '4,300' not in said, name


def test_a_label_that_no_longer_fits_stops_the_write(charts, tmp_path):
    payload = _payload()
    payload['net_principal_return']['us']['return_pct'] = 123456.78
    with pytest.raises(ValueError, match='overflow'):
        charts.write_all(payload, assets=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_the_card_moves_and_all_of_it_stops_for_reduced_motion(charts):
    """Light runs each curve in both layouts, and none of it outlives the media query."""
    smil = {f'{SVG}{tag}' for tag in ('animate', 'animateMotion', 'animateTransform', 'set')}
    seen = {}
    for name, svg in charts.render_all(_payload()).items():
        root = ET.fromstring(svg)
        css = ''.join(el.text or '' for el in root.iter(f'{SVG}style'))
        reduced = ''.join(re.findall(r'@media \(prefers-reduced-motion:reduce\)\{((?:[^{}]|\{[^{}]*\})*)\}',
                                     css))
        # SMIL has no media query: every element it drives is one the query removes.
        assert re.search(r'\.pulse\{display:none\}', reduced), name
        driven = [el for el in root.iter() if any(child.tag in smil for child in el)]
        assert all('pulse' in el.attrib.get('class', '').split() for el in driven), name
        # Each book has something travelling its own curve.
        runs = {el.attrib['href'] for el in root.iter(f'{SVG}mpath')}
        assert runs == {'#curve-us', '#curve-hk'}, name
        # Every CSS animation in use is switched off (or hidden) in the query.
        animated = set(re.findall(r'\.([\w-]+)\{animation:', css.replace(reduced, '')))
        used = {cls for el in root.iter() for cls in el.attrib.get('class', '').split()}
        stopped = set(re.findall(r'\.([\w-]+)', ''.join(
            re.findall(r'([^{}]+)\{(?:animation:none|display:none)\}', reduced))))
        assert {'glint', 'drift'} <= animated & used, name
        assert animated & used <= stopped, (name, sorted((animated & used) - stopped))
        # The first frame is the whole figure: what carries information is never animated.
        still = [el for el in root.iter()
                 if el.tag == f'{SVG}text' or el.attrib.get('class') == 'curve']
        assert len(still) == 10
        for el in still:
            assert not any(child.tag in smil for child in el.iter()), name
            assert not set(el.attrib.get('class', '').split()) & (animated | {'pulse'}), name
        seen[name] = (sorted(el.attrib['id'] for el in root.iter() if 'id' in el.attrib),
                      sorted(el.attrib.get('class', '') for el in driven), sorted(animated))
    # One set of definitions for both layouts; only distances differ.
    assert seen['books.svg'] == seen['books-narrow.svg']


def test_the_card_survives_an_img_tag(charts):
    """GitHub shows it through <img>: no script, nothing external, real text."""
    for name, svg in charts.render_all(_payload()).items():
        root = ET.fromstring(svg)
        tags = {el.tag.removeprefix(SVG) for el in root.iter()}
        assert not tags & {'script', 'foreignObject', 'filter', 'image'}, name
        assert root.find(f'{SVG}title') is not None and root.find(f'{SVG}desc') is not None, name
        ET.parse(ROOT / 'site/assets' / name)       # the committed card is well-formed
