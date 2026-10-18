"""Compose original dsh screenshot excerpts without stretching or redrawing UI.

Two figures: `dsh-task-tour.svg` (the queue to one task's history) and
`dsh-panel-tour.svg` (the panel's close: patrol and the seven-day stats card,
then the two pages they open). Run with --check to verify the committed SVGs.
Crop coordinates refer to the committed PNGs; every full original stays linked
beside its figure in README.
"""
import argparse
import base64
from html import escape
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / 'assets'


def render():
    parts = ['''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1016" height="1480" viewBox="0 0 1016 1480" role="img" aria-labelledby="title desc">
<title id="title">From the dsh queue to a task's history</title>
<desc id="desc">Annotated excerpts from two historical live-host captures, not a desktop screenshot or synchronized task state. Original proportions are preserved. Queue outcomes, append delivery and notification receipts answer different questions.</desc>
<defs>''']
    for key, name, width, height in [('queue', 'dsh-dispatch-queue.png', 800, 3000), ('detail', 'dsh-task-detail.png', 758, 4480)]:
        data = base64.b64encode((ASSETS / name).read_bytes()).decode()
        parts.append(f'<image id="{key}" width="{width}" height="{height}" xlink:href="data:image/png;base64,{data}"/>')
    parts.append('''</defs><style>text{font-family:Arial,sans-serif;fill:#263544}.title{font-size:30px;font-weight:700}.head{font-size:22px;font-weight:700}.body{font-size:18px}.note{font-size:16px;fill:#576575}</style>
<rect width="1016" height="1480" rx="24" fill="#f3f6f9"/>
<rect x="24" y="140" width="472" height="1250" rx="18" fill="white"/>
<rect x="520" y="140" width="472" height="1250" rx="18" fill="white"/>''')

    def text(x, y, value, cls='body'):
        parts.append(f'<text x="{x}" y="{y}" class="{cls}">{escape(value)}</text>')

    def crop(key, x, y, source_y, source_h, source_w):
        # Same scale on both axes; nested SVG clips rather than distorts.
        h = 440 * source_h / source_w
        parts.append(f'<svg x="{x}" y="{y}" width="440" height="{h:g}" viewBox="0 {source_y} {source_w} {source_h}" overflow="hidden"><use xlink:href="#{key}"/></svg>')

    text(32, 52, 'From the queue to a task’s history', 'title')
    text(32, 88, 'Real interface excerpts • two historical captures • original proportions', 'body')
    text(32, 116, 'Read the queue, inspect instructions, then separate the result from its delivery.', 'note')
    text(40, 180, '01 / Find the work', 'head')
    text(40, 212, 'Allowance windows sit above each agent’s queue.')
    crop('queue', 40, 235, 0, 795, 800)
    text(40, 714, '02 / Read the outcome', 'head')
    text(40, 746, 'Outcome chips and send receipts are separate.')
    crop('queue', 40, 770, 1700, 840, 800)
    text(40, 1280, 'The queue and detail show different tasks.', 'note')
    text(40, 1308, 'Amounts and states belong to those captures.', 'note')
    text(40, 1348, 'Full originals are linked below the figure.', 'note')
    text(536, 180, '03 / Check the appended instruction', 'head')
    text(536, 212, 'Submit with the runner; inspect delivery here.')
    crop('detail', 536, 235, 650, 385, 758)
    text(536, 502, '04 / Follow the recorded events', 'head')
    text(536, 534, 'Submission → continuation → delivery → end')
    crop('detail', 536, 552, 1950, 1300, 758)
    text(32, 1426, 'Completed work can still have a failed notification.', 'head')
    text(32, 1458, 'This task finished; its timeline records WeChat sent and Telegram failed. Older tasks may have gaps.', 'body')
    parts.append('</svg>')
    return '\n'.join(parts) + '\n'


def render_panel():
    """The bottom of the panel and the two pages it opens, at original proportions."""
    sources = [('queue', 'dsh-dispatch-queue.png', 800, 3000), ('stats', 'dsh-stats-layer.png', 792, 1584),
               ('patrol', 'dsh-patrol-page.png', 792, 3636)]
    parts = ['''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1016" height="1600" viewBox="0 0 1016 1600" role="img" aria-labelledby="title desc">
<title id="title">The close of the dsh panel: patrol, seven days of tasks, and the pages they open</title>
<desc id="desc">Annotated excerpts from three live-host captures taken on 2026-10-18, not a desktop screenshot or one synchronized state. Original proportions are preserved. The queue capture is in English; the stats and patrol pages were captured with the Chinese locale.</desc>
<defs>''']
    for key, name, width, height in sources:
        data = base64.b64encode((ASSETS / name).read_bytes()).decode()
        parts.append(f'<image id="{key}" width="{width}" height="{height}" xlink:href="data:image/png;base64,{data}"/>')
    parts.append('''</defs><style>text{font-family:Arial,sans-serif;fill:#263544}.title{font-size:30px;font-weight:700}.head{font-size:22px;font-weight:700}.body{font-size:18px}.note{font-size:16px;fill:#576575}</style>
<rect width="1016" height="1600" rx="24" fill="#f3f6f9"/>
<rect x="24" y="140" width="472" height="1364" rx="18" fill="white"/>
<rect x="520" y="140" width="472" height="1364" rx="18" fill="white"/>''')
    widths = {key: width for key, _, width, _ in sources}

    def text(x, y, value, cls='body'):
        parts.append(f'<text x="{x}" y="{y}" class="{cls}">{escape(value)}</text>')

    def crop(key, x, y, source_y, source_h):
        # Same scale on both axes, as in render(): nested SVG clips rather than distorts.
        source_w = widths[key]
        h = 440 * source_h / source_w
        parts.append(f'<svg x="{x}" y="{y}" width="440" height="{h:g}" viewBox="0 {source_y} {source_w} {source_h}" overflow="hidden"><use xlink:href="#{key}"/></svg>')

    text(32, 52, 'The close of the panel', 'title')
    text(32, 88, 'Real interface excerpts • three captures from one day • original proportions', 'body')
    text(32, 116, 'Two summaries close the queue; each opens a page of its own.', 'note')
    text(40, 180, '01 / Patrol and the week', 'head')
    text(40, 212, 'One patrol row, one stats card, the ops footer.')
    crop('queue', 40, 235, 2540, 460)
    text(40, 534, '02 / Open the stats card', 'head')
    text(40, 566, 'Seven days, stacked by provider; then each agent.')
    crop('stats', 40, 590, 0, 1584)
    text(536, 180, '03 / Open patrol', 'head')
    text(536, 212, 'Four numbers first, then every round.')
    crop('patrol', 536, 235, 0, 945)
    text(536, 798, '04 / Read the coverage', 'head')
    text(536, 830, 'Open issues by area; rounds by lens.')
    crop('patrol', 536, 854, 1640, 745)
    for i, line in enumerate(('The stats and patrol pages use the', 'Chinese locale. The card and the chart',
                              'were read at different times that', 'day, so their totals differ. Full',
                              'originals are linked below the figure.')):
        text(536, 1320 + i * 28, line, 'note')
    text(32, 1546, 'Tokens and cost are frozen when a task ends; cost is an API list-price estimate.', 'head')
    text(32, 1578, 'Patrol rounds are left out of the week. The footer turns red when the installed ops entry differs.', 'body')
    parts.append('</svg>')
    return '\n'.join(parts) + '\n'


FIGURES = {'dsh-task-tour.svg': render, 'dsh-panel-tour.svg': render_panel}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    stale = []
    for name, draw in FIGURES.items():
        target, result = ASSETS / name, draw()
        if not target.exists() or target.read_text() != result:
            stale.append((target, result))
    if args.check:
        return int(bool(stale))
    for target, result in stale:
        target.write_text(result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
