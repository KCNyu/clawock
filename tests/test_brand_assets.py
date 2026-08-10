"""Brand asset contract: one vector system, deterministic raster derivatives."""
import struct
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    assert header[12:16] == b"IHDR"
    return struct.unpack(">II", header[16:24])


def test_vector_brand_sources_are_valid_and_keep_the_canonical_geometry():
    mark = ROOT / "site/assets/logo-mark.svg"
    app = ROOT / "site/assets/icons/app-icon.svg"
    mark_root = ET.parse(mark).getroot()
    app_root = ET.parse(app).getroot()

    assert mark_root.attrib["viewBox"] == "0 0 64 64"
    assert app_root.attrib["viewBox"] == "0 0 64 64"
    for source in (mark.read_text(), app.read_text()):
        assert "M8 13C22 9 40 16 55 28C42 24 28 25 17 32C12 27 9 21 8 13Z" in source
        assert "M56 51C42 55 24 48 9 36C22 40 36 39 47 32C52 37 55 43 56 51Z" in source
        assert 'shape-rendering="geometricPrecision"' in source
        assert 'id="bull-blue"' in source


def test_mono_lockup_keeps_the_canonical_geometry_and_inherits_color():
    mono = ROOT / "site/assets/logo-mark-mono.svg"
    root = ET.parse(mono).getroot()
    source = mono.read_text()
    assert root.attrib["viewBox"] == "0 0 64 64"
    # Single-color lockup: same saddle paths, no gradient, colored via currentColor.
    assert "M8 13C22 9 40 16 55 28C42 24 28 25 17 32C12 27 9 21 8 13Z" in source
    assert "M56 51C42 55 24 48 9 36C22 40 36 39 47 32C52 37 55 43 56 51Z" in source
    assert 'fill="currentColor"' in source
    assert "linearGradient" not in source


def test_wordmark_lockup_keeps_the_canonical_geometry_and_carries_the_name():
    lockup = ROOT / "site/assets/logo-lockup.svg"
    root = ET.parse(lockup).getroot()
    source = lockup.read_text()
    # Wide mark+wordmark lockup for the README header: same saddle geometry and
    # adaptive two-tone treatment as the mark, with the "clawock" wordmark baked
    # in so mark and name stay aligned wherever CSS can't run (GitHub, npm, IDEs).
    assert root.attrib["viewBox"] == "4 7 208 50"
    assert "M8 13C22 9 40 16 55 28C42 24 28 25 17 32C12 27 9 21 8 13Z" in source
    assert "M56 51C42 55 24 48 9 36C22 40 36 39 47 32C52 37 55 43 56 51Z" in source
    assert 'shape-rendering="geometricPrecision"' in source
    assert 'id="bull-blue"' in source
    assert ">clawock</text>" in source


def test_raster_derivatives_have_exact_declared_sizes():
    expected = {
        "favicon-64.png": (64, 64),
        "apple-touch-icon.png": (180, 180),
        "icon-192.png": (192, 192),
        "icon-512.png": (512, 512),
        "icon-maskable-512.png": (512, 512),
    }
    for filename, size in expected.items():
        assert _png_size(ROOT / "site/assets/icons" / filename) == size


def test_all_public_shells_use_the_vector_mark():
    index = (ROOT / "site/index.html").read_text()
    layout = (ROOT / "site/_layouts/default.html").read_text()
    readmes = (ROOT / "README.md").read_text() + (ROOT / "README.zh.md").read_text()

    # Header wordmark uses the adaptive two-tone mark; the SVG favicon uses the
    # self-contained squircle so it reads on any tab color (Chrome ignores
    # prefers-color-scheme in favicons, which would strand a black bear on a dark tab).
    assert 'type="image/svg+xml" href="assets/icons/app-icon.svg"' in index
    assert 'class="brand-mark" src="assets/logo-mark.svg"' in index
    assert "/assets/logo-mark.svg" in layout
    assert "/assets/icons/app-icon.svg" in layout
    # Both READMEs must show the vector lockup rather than a raster. Matched on
    # the asset, not on the exact string: README.md is the packaged PyPI
    # description and had to go absolute (relative paths do not resolve there),
    # while README.zh.md is GitHub-only and stays relative. Pinning the literal
    # `src="site/..."` would have made this test enforce the broken form.
    assert readmes.count('site/assets/logo-lockup.svg"') == 2
    assert 'logo-lockup.png' not in readmes
