"""The README's per-book P&L charts are drawn from the dashboard payload.

`site/tools/build_readme_book_charts.py` turns `dashboard.json` into
`site/assets/book-us.svg` and `book-hk.svg`; the weekly README refresh calls it
from the payload it reads the placeholders from. The payload is not in a test
checkout, so these run the builder on a small synthetic one and pin the three
things a chart of money can get quietly wrong: reading a snapshot column by
position, printing a percentage without the denominator the payload used, and
writing a partial chart when a label no longer fits.
"""
import importlib.util
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


def _text(svg):
    return ' '.join(''.join(el.itertext()) for el in ET.fromstring(svg).iter(f'{SVG}text'))


def test_the_curve_is_read_by_column_name(charts):
    """The packed rows carry no keys; a reordered payload must draw the same curve."""
    reordered = ['hk_realized', 'us_profit', 'date', 'hk_profit', 'us_realized']
    assert charts.series(_payload(reordered), 'us') == charts.series(_payload(), 'us')
    assert [total for _, total, _ in charts.series(_payload(reordered), 'hk')] == [
        -500.0, -9000.0, -4000.0]
    assert charts.render_all(_payload(reordered)) == charts.render_all(_payload())


def test_each_percentage_is_printed_with_the_denominator_the_payload_used(charts):
    rendered = charts.render_all(_payload())
    us, hk = _text(rendered['book-us.svg']), _text(rendered['book-hk.svg'])
    assert '+30.00%' in us and 'US$1,000' in us and 'true_principal' in us
    assert 'US$800' not in us, 'the US chart printed net_principal beside a true_principal return'
    assert '−20.00%' in hk and 'HK$20,000' in hk and 'net_principal' in hk

    # The basis is the payload's, not this file's: give HK a true_principal and
    # the chart must follow it rather than keep the wording it had.
    payload = _payload()
    payload['net_principal_return']['hk'].update(
        return_basis='true_principal', true_principal=25000.0, return_pct=-16.0)
    hk = _text(charts.render_all(payload)['book-hk.svg'])
    assert 'HK$25,000' in hk and 'true_principal' in hk and 'HK$20,000' not in hk


def test_a_label_that_no_longer_fits_stops_the_write(charts, tmp_path):
    payload = _payload()
    payload['net_principal_return']['hk'].update(total_profit=-4e15, net_principal=2e16)
    with pytest.raises(ValueError, match='overflow'):
        charts.write_all(payload, assets=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_the_charts_survive_an_img_tag(charts):
    """GitHub shows them through <img>: no script, nothing external, real text."""
    for name, svg in charts.render_all(_payload()).items():
        root = ET.fromstring(svg)
        tags = {el.tag.removeprefix(SVG) for el in root.iter()}
        assert not tags & {'script', 'foreignObject', 'filter', 'image'}, name
        assert root.find(f'{SVG}title') is not None and root.find(f'{SVG}desc') is not None, name
    for name in charts.BOOKS.values():
        ET.parse(ROOT / 'site/assets' / name[0])    # the committed pair is well-formed


def test_readme_values_carry_sign_denominator_and_basis():
    refresh = _load('ops/growth/refresh_readme_metrics.py', 'refresh_readme_metrics')
    values = refresh._book_values(_payload()['net_principal_return'])
    assert values == {
        'us_return_pct': '+30.00%', 'us_principal': 'US$1,000', 'us_basis': 'true_principal',
        'hk_return_pct': '−20.00%', 'hk_principal': 'HK$20,000', 'hk_basis': 'net_principal',
        'return_basis': 'mixed',
    }
