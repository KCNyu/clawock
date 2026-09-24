"""The screenshot pipeline is two halves that agree on a filename, and nothing held that.

`shoot_dashboard.js` writes per-tab scroll frames; `assemble_dashboard_gif.py`
globs them back. Until #754 the pair was ungated end to end: `site/tools/` was in
no workflow trigger, in no `Detect code changes` lane, and in no syntax check
(`find src ops` did not reach it), and no test imported or ran either file. The
only thing that executed them was the weekly `screenshot-refresh` cron — which
commits what they produce. A rename on one side, or a seventh tab on the other,
would surface on a Sunday inside a job that writes to master.

These are behavioural where they can be: the assembler really runs, on real PNGs,
and the GIF is inspected. The two cross-file contracts (frame naming, tab count)
are read out of the sources, because the JS half cannot be imported from pytest.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops" / "ci"))
import push_scope  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "site" / "tools"
SHOOT = (TOOLS / "shoot_dashboard.js").read_text(encoding="utf-8")
ASSEMBLER = TOOLS / "assemble_dashboard_gif.py"
ASSEMBLER_SRC = ASSEMBLER.read_text(encoding="utf-8")


def _tabs_in_shoot():
    match = re.search(r"const TABS = \[([^\]]+)\]", SHOOT)
    assert match, "shoot_dashboard.js no longer declares a TABS list"
    return [name.strip().strip("'\"") for name in match.group(1).split(",")]


def _tab_count_in_assembler():
    # The count used to be three bare `range(6)` literals and this helper read
    # one of them. The seventh tab turned the literal into a fact the shooter and
    # the assembler share, so the declared constant is what is checked now.
    match = re.search(r"^TAB_COUNT\s*=\s*(\d+)", ASSEMBLER_SRC, re.MULTILINE)
    assert match, ("assemble_dashboard_gif.py no longer declares TAB_COUNT — the "
                   "tab count has to be stated once rather than repeated per loop")
    return int(match.group(1))


def test_the_two_halves_agree_on_how_many_tabs_there_are():
    """A seventh tab in the shooter makes the assembler exit 1, next Sunday.

    `_load_tab` calls `sys.exit(1)` when a tab has no frames, so adding a tab to
    `TABS` alone fails the GIF build — and adding one to the assembler alone
    silently drops the last tab from the animation. The dashboard's own count is
    checked against the markup in `test_dashboard_tabs_a11y`, which counts the
    real buttons rather than a literal, so this pair only has to agree with each
    other.
    """
    assert len(_tabs_in_shoot()) == _tab_count_in_assembler(), (
        f"shoot_dashboard.js shoots {_tabs_in_shoot()} "
        f"({len(_tabs_in_shoot())} tabs) but the assembler iterates "
        f"{_tab_count_in_assembler()}")


def test_the_frame_names_one_half_writes_are_the_names_the_other_half_reads():
    """The coupling is a filename, so assert on a filename, not on two regexes."""
    written = re.findall(r"screenshot\(\{ path: `\$\{FRAME_DIR\}/([^`]+)`", SHOOT)
    assert written, "shoot_dashboard.js no longer writes frames into FRAME_DIR"

    glob_pattern = re.search(r'glob\.glob\(os\.path\.join\(FRAME_DIR, f"([^"]+)"\)',
                             ASSEMBLER_SRC)
    assert glob_pattern, "the assembler no longer globs FRAME_DIR"
    sort_key = re.search(r'int\(re\.search\(r"([^"]+)", p\)', ASSEMBLER_SRC)
    assert sort_key, "the assembler no longer sorts frames by their index"

    # Render both sides for tab 3, frame 7, and check the produced name is the
    # name the other side accepts.
    for template in written:
        name = (template.replace("${i}", "3").replace("${j}", "7")
                        .replace("${steps}", "7")
                        .replace("_0.png", "_0.png"))
        assert re.fullmatch(r"f\d+_\d+\.png", name), (
            f"frame name {name!r} is not the f<tab>_<index>.png the assembler reads")
        assert re.fullmatch(glob_pattern.group(1).replace("{i}", r"\d+")
                            .replace("*", r"\d+"), name), (
            f"{name!r} does not match the assembler's glob "
            f"{glob_pattern.group(1)!r}")
        assert re.search(sort_key.group(1), name), (
            f"{name!r} carries no index the assembler can sort by")


def test_the_assembler_really_builds_a_gif_from_real_frames(tmp_path):
    """Runs the committed script, on PNGs, into a temp path — no fake tree.

    Copying the file elsewhere to test it was the old workaround and it proved
    nothing about the committed one; `GIF_OUT` (#754) is what makes this possible.
    """
    Image = pytest.importorskip("PIL.Image", reason="Pillow is the assembler's only dep")
    ImageChops = pytest.importorskip("PIL.ImageChops")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")

    frames = tmp_path / "frames"
    frames.mkdir()
    tabs = len(_tabs_in_shoot())
    buttons = [{"left": 100 + tab * 100, "top": 20,
                "right": 180 + tab * 100, "bottom": 60}
               for tab in range(tabs)]
    (frames / "capture-manifest.json").write_text(json.dumps({
        "chrome": {"width": 1280, "height": 80, "buttons": buttons},
    }))
    for tab in range(tabs):
        for index in range(2):
            # 1280x800 like the real desktop capture, so the 960 downscale is exercised.
            colour = (10 + tab * 30, 40 + index * 60, 90)
            image = Image.new("RGB", (1280, 800), colour)
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, 1279, 79), fill="white")
            draw.rectangle(tuple(buttons[tab].values()), fill="blue")
            image.save(frames / f"f{tab}_{index}.png")

    out = tmp_path / "dashboard.gif"
    done = subprocess.run(
        [sys.executable, str(ASSEMBLER)],
        env={**os.environ, "FRAME_DIR": str(frames), "GIF_OUT": str(out)},
        capture_output=True, text=True, timeout=300,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert out.is_file(), done.stdout + done.stderr

    built = Image.open(out)
    assert built.width == 960, (
        f"OW is the README's desktop budget; the GIF came out {built.width}px wide")
    # Six tabs × (hold + one scroll frame) plus the horizontal tweens between
    # them: the exact count is the assembler's business, but it must be an
    # animation, not a single frame, and every tab must be represented.
    assert getattr(built, "n_frames", 1) > tabs, (
        f"only {getattr(built, 'n_frames', 1)} frames for {tabs} tabs")
    for index in range(built.n_frames):
        built.seek(index)
        assert built.disposal_method == 1, f"frame {index} clears the previous frame"
        nav = built.convert("RGB").crop((0, 0, 960, 60))
        if index == 0:
            first_nav = nav
        difference = ImageChops.difference(first_nav, nav)
        mask = ImageDraw.Draw(difference)
        for box in buttons:
            mask.rectangle(tuple(round(box[key] * .75) for key in
                                 ("left", "top", "right", "bottom")), fill="black")
        assert difference.getbbox() is None, f"frame {index} moved the fixed navigation"
    assert f"{tabs} tabs" in done.stdout or "frames" in done.stdout, done.stdout


def test_the_committed_gif_path_stays_the_default():
    """`GIF_OUT` is a test seam, not a relocation: the cron passes nothing."""
    assert 'os.environ.get("GIF_OUT")' in ASSEMBLER_SRC
    assert 'os.path.join(ROOT, "site", "assets", "dashboard.gif")' in ASSEMBLER_SRC
    workflow = (ROOT / ".github" / "workflows" / "screenshot-refresh.yml").read_text()
    assert "GIF_OUT" not in workflow, (
        "the publishing workflow must keep writing the committed path")


def test_the_tooling_is_inside_the_regression_gate():
    """The gate this file exists to close — assert the wiring, not just the tests."""
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "'site/tools/**'" in workflow, "site/tools is outside the push trigger"
    assert "site/tools/*" in push_scope.CODE_GLOBS, (
        "site/tools is outside the classifier's code lane")
    assert "find src ops site/tools" in workflow, (
        "the Python syntax check does not reach site/tools")
    assert "node --check" in workflow, "the two JS tools are not syntax-checked"
