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
    mark = ROOT / "assets/logo-mark.svg"
    app = ROOT / "assets/icons/app-icon.svg"
    mark_root = ET.parse(mark).getroot()
    app_root = ET.parse(app).getroot()

    assert mark_root.attrib["viewBox"] == "0 0 64 64"
    assert app_root.attrib["viewBox"] == "0 0 64 64"
    for source in (mark.read_text(), app.read_text()):
        assert "M46 15.7A22.5 22.5" in source
        assert "M21.5 31.5l8.8 7.8 17.2-18.8" in source


def test_raster_derivatives_have_exact_declared_sizes():
    expected = {
        "favicon-64.png": (64, 64),
        "apple-touch-icon.png": (180, 180),
        "icon-192.png": (192, 192),
        "icon-512.png": (512, 512),
        "icon-maskable-512.png": (512, 512),
    }
    for filename, size in expected.items():
        assert _png_size(ROOT / "assets/icons" / filename) == size


def test_all_public_shells_use_the_vector_mark():
    index = (ROOT / "index.html").read_text()
    layout = (ROOT / "_layouts/default.html").read_text()
    readmes = (ROOT / "README.md").read_text() + (ROOT / "README.zh.md").read_text()

    assert 'type="image/svg+xml" href="assets/logo-mark.svg"' in index
    assert 'class="brand-mark" src="assets/logo-mark.svg"' in index
    assert "/assets/logo-mark.svg" in layout
    assert readmes.count('src="assets/logo-mark.svg"') == 2
