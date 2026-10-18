"""Compose original dsh screenshot excerpts without stretching or redrawing UI.

Run with --check to verify the committed SVG. Crop coordinates refer to the
committed PNGs; both full originals remain linked beside the figure in README.
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    target = ASSETS / 'dsh-task-tour.svg'
    result = render()
    if args.check:
        return int(not target.exists() or target.read_text() != result)
    target.write_text(result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
