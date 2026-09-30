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
