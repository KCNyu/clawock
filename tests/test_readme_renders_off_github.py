"""README.md is the PyPI project page, where relative paths do not resolve.

`pyproject.toml` sets `readme = "README.md"`, so this file is shipped verbatim as
the package's `long_description` and rendered at
https://pypi.org/project/clawock/ . GitHub resolves `site/assets/social-card.png`
against the repository; PyPI has no repository to resolve it against, so every
relative reference renders broken there.

2026-08-10, the day v0.1.0 was published: the description carried six relative
image paths — including the logo and the hero card, the first two things a
visitor sees — and seventeen relative document links. Exactly one asset,
`dashboard.gif`, already used an absolute raw URL, which says someone hit this
before and fixed the one they were looking at.

This is not a style rule. Until PyPI, README.md was only ever rendered by GitHub
and relative paths were correct. Publishing gave the file a second audience, and
this test is what remembers that.
"""
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / 'README.md'

ASSET_SUFFIXES = ('.svg', '.png', '.gif', '.jpg', '.jpeg', '.webp')


def _references(text):
    """Every link and image target in the document."""
    return (re.findall(r'\]\(([^)\s]+)', text)
            + re.findall(r'(?:src|href)="([^"]+)"', text))


def _relative(targets):
    return [t for t in targets
            if not t.startswith(('http://', 'https://', '#', 'mailto:'))]


def test_the_readme_has_no_relative_references():
    targets = _references(README.read_text())
    assert targets, 'no links found — this assertion must not pass vacuously'
    assert _relative(targets) == [], (
        'these render broken on the PyPI project page, which is now a published '
        'product surface'
    )


def test_assets_point_at_raw_not_the_blob_viewer():
    """A `github.com/.../blob/...` URL serves an HTML page, so an <img> using one
    shows nothing. Assets have to come from raw.githubusercontent.

    The host is parsed rather than substring-matched: `https://evil.example/
    ?x=raw.githubusercontent.com` contains the string and is not the host, so a
    substring check is both a weaker test and the pattern CodeQL flags.
    """
    text = README.read_text()
    for target in _references(text):
        if target.endswith(ASSET_SUFFIXES) and target.startswith('http'):
            assert urlparse(target).hostname == 'raw.githubusercontent.com', target


def test_the_readme_is_what_the_package_ships():
    """If the packaged readme is ever pointed somewhere else, the rule above
    stops protecting the thing it was written for and this says so."""
    pyproject = (ROOT / 'pyproject.toml').read_text()
    assert re.search(r'^readme\s*=\s*"README\.md"', pyproject, re.M), (
        'this test guards README.md because that is the packaged description'
    )


def test_the_zh_readme_is_not_packaged_and_may_stay_relative():
    """The rule is about the published surface, not about tidiness. README.zh.md
    is only ever rendered by GitHub, where relative paths are correct and follow
    the branch you are viewing — so it is deliberately not held to this."""
    pyproject = (ROOT / 'pyproject.toml').read_text()
    assert 'README.zh.md' not in re.findall(r'^readme\s*=.*$', pyproject, re.M)[0]


@pytest.mark.parametrize('needle', ['logo-lockup.svg', 'social-card.png',
                                    'shadow-backtest.png', 'dashboard.gif',
                                    'product-architecture.svg'])
def test_the_images_that_were_broken_are_still_absolute(needle):
    """Named individually because these are the ones a visitor sees first, and a
    generic rule is easy to satisfy while quietly dropping an image."""
    text = README.read_text()
    matches = [t for t in _references(text) if t.endswith(needle)]
    assert matches, f'{needle} is no longer referenced by the README'
    for target in matches:
        assert target.startswith('https://raw.githubusercontent.com/'), target
