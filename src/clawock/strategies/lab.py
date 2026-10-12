"""Mount the strategy plugins a config declares, and ask them questions.

`config/strategy-plugins.json` is the composition: each row names a module and
its config, the way a row in `cordis.patch.yml` names a package for dsh. A row's
module may live outside this package; anything importable that exposes
`apply(ctx, config)` (and optionally `name` and `inject`) is a plugin.

Usage
  clawock strategy-lab list                  # what is mounted and what it provides
  clawock strategy-lab optimize rsi          # walk-forward search; prints a proposal
  clawock strategy-lab optimize rsi --json --output proposal.json

`optimize` is research. It reads stored bars, writes only the file `--output`
names, and its proposal never carries live permission.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

from clawock.strategies.kernel import Kernel
from clawock.workspace import workspace_root

CONFIG = Path('config') / 'strategy-plugins.json'


def load_rows(path: Path) -> list[dict]:
    doc = json.loads(Path(path).read_text(encoding='utf-8'))
    if doc.get('schema_version') != 1:
        raise ValueError(f'{path}: schema_version must be 1')
    rows = doc.get('plugins')
    if not isinstance(rows, list) or not all(
            isinstance(row, dict) and isinstance(row.get('module'), str) for row in rows):
        raise ValueError(f'{path}: plugins must be a list of rows naming a module')
    return rows


def mount(rows) -> Kernel:
    """One fiber per row. Row order is not load order: `inject` decides that."""
    kernel = Kernel()
    for row in rows:
        kernel.plugin(importlib.import_module(row['module']), row.get('config'))
    return kernel


def _print_proposal(report: dict) -> None:
    walk = report['walk_forward']
    print(f"{report['strategy']}: {report['status']}  "
          f"(live_permission: {str(report['live_permission']).lower()}, "
          f"{report['evidence_grade']})")
    print(f"  registered {report['registered_params']}")
    print(f"  selected   {report['selected_params']}  "
          f"of {report['search']['configurations']} configurations")
    print(f"  objective  {report['objective']}")
    print(f"  sample     {report['sample']['sessions']} sessions "
          f"{report['sample']['first']} .. {report['sample']['last']}, "
          f"bars {report['sample']['bars'].get('adjustment')}")
    print(f"  walk-forward over {walk['oos_sessions']} out-of-sample sessions: "
          f"selected IC {walk['oos_mean_ic_selected']} {walk['oos_ic_ci95']}, "
          f"registered IC {walk['oos_mean_ic_registered']}, "
          f"lift {walk['oos_mean_lift']} {walk['oos_lift_ci95']}")
    print(f"  PBO {report['pbo'].get('pbo')} ({report['pbo'].get('status')})")
    for item in report['gate']:
        print(f"  [{'pass' if item['passed'] else 'FAIL'}] {item['check']}: "
              f"{item['observed']} (required {item['required']})")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog='clawock strategy-lab', description=__doc__.split('\n\n')[0])
    parser.add_argument('--config', type=Path,
                        help=f'plugin rows (default: <workspace>/{CONFIG})')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('list', help='mounted plugins, services and strategies')
    optimize = sub.add_parser(
        'optimize', help='walk-forward parameter search; prints a proposal')
    optimize.add_argument('strategy')
    optimize.add_argument('--json', action='store_true')
    optimize.add_argument('--output', type=Path, help='also write the proposal here')
    args = parser.parse_args(argv)

    config = args.config or workspace_root() / CONFIG
    if not config.exists():
        # Book data, like the other `config/*.json`: absent means not set up.
        parser.exit(2, f'no strategy plugins are configured: {config} does not exist\n')
    kernel = mount(load_rows(config))
    try:
        if args.action == 'list':
            providers = kernel.services()
            for fiber in kernel.fibers:
                provided = sorted(k for k, owner in providers.items() if owner == fiber.name)
                waiting = f" waiting for {fiber.missing}" if fiber.missing else ''
                print(f"{fiber.name}: {fiber.state}{waiting}  "
                      f"inject={list(fiber.inject)} provides={provided}")
            if 'strategies' in providers:
                registry = kernel.get('strategies')
                for strategy in registry.names():
                    spec = registry.get(strategy)
                    print(f"strategy {strategy}: params={spec.params} space={spec.space}")
            return 0
        if 'optimizer' not in kernel.services():
            pending = {fiber.name: fiber.missing for fiber in kernel.fibers if fiber.missing}
            parser.exit(2, f'no optimizer is mounted; waiting plugins: {pending}\n')
        try:
            report = kernel.get('optimizer').run(args.strategy)
        except (KeyError, ValueError) as exc:
            parser.exit(2, f'{exc.args[0]}\n')
        if args.output:
            args.output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            _print_proposal(report)
        return 0
    finally:
        kernel.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
