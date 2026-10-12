"""Mount the strategy plugins a config declares, and ask them questions.

The `plugins` list of `config/strategy-plugins.json` is the composition: each row names a module and
its config, the way a row in `cordis.patch.yml` names a package for dsh. A row's
module may live outside this package; anything importable that exposes
`apply(ctx, config)` (and optionally `name` and `inject`) is a plugin.

Usage
  clawock strategy-lab list                  # what is mounted and what it provides
  clawock strategy-lab optimize rsi          # walk-forward search; prints a proposal
  clawock strategy-lab optimize rsi --json --output proposal.json
  clawock strategy-lab ledger                # yield per strategy, alternates beside the gate
  clawock strategy-lab evolution rsi         # one strategy's record, run by run
  clawock strategy-lab verify                # the ledger against the lab's boundaries
  clawock strategy-lab sources               # what each signal source declares

`optimize` is research. It writes the file `--output` names and one row in the
lab ledger (`--no-ledger` skips it); its proposal never carries live permission.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from clawock.plugin_host import declarations, live
from clawock.strategy_lab import boundaries, ledger
from clawock.plugin_host import rows as composition
from clawock.plugin_host.kernel import Kernel
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
        composition.mount(kernel, row)
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
    net = report['net_of_cost']
    print(f"  net of cost: excess {net['oos_mean_net_excess']} per session "
          f"{net['oos_net_excess_ci95']} (gross {net['oos_mean_gross_excess']}, "
          f"turnover {net['mean_turnover_per_tranche']})")
    print(f"  PBO {report['pbo'].get('pbo')} ({report['pbo'].get('status')})")
    for item in report['gate']:
        print(f"  [{'pass' if item['passed'] else 'FAIL'}] {item['check']}: "
              f"{item['observed']} (required {item['required']})")
    for alternate in report['alternate_gates']:
        verdict = ('would pass' if alternate['would_pass'] else
                   f"would refuse on {alternate['would_refuse_because']}")
        print(f"  alternate gate {alternate['id']} (not binding, effect "
              f"{alternate['effect']}): {verdict}")
    review = report['live_review']
    print(f"  live review: {'cleared for registration' if review['cleared'] else 'not cleared'}"
          f" (objections {review['objections'] or 'none'}; live_permission stays false)")
    for trial in report['prospective']:
        print(f"  registered {trial['params']} after {trial['after_session']}: "
              f"{trial['sessions']} prospective sessions, mean IC {trial['mean_ic']}")


def _print_ledger(stats: dict) -> None:
    if not stats['strategies']:
        print('the lab ledger is empty: no optimisation has been recorded')
    for strategy, entry in stats['strategies'].items():
        print(f"{strategy}: {entry['candidates']} candidate of "
              f"{entry['distinct_inputs']} distinct inputs ({entry['runs']} runs), "
              f"{entry['cleared']} cleared, "
              f"refused on {entry['refused_by_check'] or 'nothing'}, "
              f"objected to by {entry['objections'] or 'nothing'}")
        for identifier, tally in entry['alternate_gates'].items():
            print(f"  alternate gate {identifier} (not binding): would pass "
                  f"{tally['would_pass']} of {tally['judged']}, disagrees with the "
                  f"registered gate on {tally['disagrees_with_registered']}")


#: What the lab tells the plugins mounted beside it. A listener hears each
#: one before the write it announces and may refuse it by raising: the row is
#: then not written and the strategy is reported as failed. A listener cannot
#: cause a write, because the lab's own checks run whatever it answers.
PROPOSAL = 'strategy-lab/proposal'
REGISTRATION = 'strategy-lab/registration'


def keep(kernel, report: dict) -> dict | None:
    """Record one proposal and register it if cleared; the registration or None."""
    kernel.emit(PROPOSAL, report)
    ledger.append(report)
    if (report.get('live_review') or {}).get('cleared'):
        kernel.emit(REGISTRATION, report)
    return ledger.register(report)


def record(kernel) -> int:
    """The scheduled run: every mounted strategy, into the ledger.

    One strategy failing does not stop the others; the exit status says
    whether any did, or whether the ledger read back afterwards breaks a
    boundary.
    """
    known, failed = ledger.registrations(), 0
    for strategy in kernel.get('strategies').names():
        try:
            report = kernel.get('optimizer').run(strategy, registrations=[
                row for row in known if row['strategy'] == strategy])
            registered = keep(kernel, report)
        except Exception as exc:
            failed += 1
            print(f'{strategy}: not recorded ({type(exc).__name__}: {exc})', file=sys.stderr)
            continue
        review = report['live_review']
        print(f"{strategy}: {report['status']}"
              f"{' on ' + str(report['refused_because']) if report['refused_because'] else ''}, "
              f"objections {review['objections'] or 'none'}, "
              f"{'registered ' + str(registered['params']) if registered else 'nothing registered'}, "
              f"{len(report['prospective'])} earlier registration(s) scored")
    broken = boundaries.verify(ledger.load(), ledger.registrations())
    for line in broken:
        print(f'boundary: {line}', file=sys.stderr)
    return 1 if failed or broken else 0


def evolution(strategy: str, rows: list[dict], registrations: list[dict]) -> dict:
    """One strategy's record in the order it was written.

    Each run is a step: what the gate concluded, on which bars, and what
    changed against the step before. A registration is where a cleared
    candidate started being scored on sessions it had not seen; the latest
    prospective score of each registration is the measurement so far.
    """
    steps, previous = [], None
    for row in rows:
        if row['strategy'] != strategy:
            continue
        bars = row.get('bars') or {}
        step = {
            'recorded_at': row['recorded_at'], 'code': row.get('code'),
            'status': row['status'], 'refused_because': row['refused_because'],
            'registered_params': row['registered_params'],
            'selected_params': row['selected_params'],
            'tickers': bars.get('tickers'), 'bars_digest': bars.get('digest'),
            'names_by_basis': {basis: len(names)
                               for basis, names in (bars.get('basis') or {}).items()},
            'oos_ic_ci95': row['measured']['oos_ic_ci95'],
            'cleared': bool((row.get('live_review') or {}).get('cleared')),
            'coverage_sensitivity': row.get('coverage_sensitivity'),
            'changed': [] if previous is None else [
                key for key in ('status', 'selected_params', 'registered_params', 'tickers',
                                'bars_digest')
                if previous[key] != (row[key] if key in row else bars.get(
                    'digest' if key == 'bars_digest' else key))],
        }
        steps.append(step)
        previous = step
    trials = []
    for registration in registrations:
        if registration['strategy'] != strategy:
            continue
        scores = [trial for row in rows if row['strategy'] == strategy
                  for trial in row.get('prospective') or []
                  if trial['params'] == registration['params']
                  and trial['after_session'] == registration['after_session']]
        trials.append({
            'params': registration['params'], 'registered_at': registration['registered_at'],
            'after_session': registration['after_session'],
            'cleared_by': registration['cleared_by'], 'live_permission': False,
            'scored_runs': len(scores),
            'latest': scores[-1] if scores else None})
    return {'strategy': strategy, 'live_permission': False, 'steps': steps,
            'registrations': trials}


def _print_evolution(view: dict) -> None:
    if not view['steps']:
        print(f"{view['strategy']}: nothing recorded")
    for step in view['steps']:
        why = f" on {step['refused_because']}" if step['refused_because'] else ''
        print(f"{step['recorded_at']}  {step['status']}{why}  selected {step['selected_params']}  "
              f"IC {step['oos_ic_ci95']}  {step['tickers']} names {step['names_by_basis'] or ''}"
              f"{'  changed: ' + ', '.join(step['changed']) if step['changed'] else ''}")
        narrow = step['coverage_sensitivity']
        if narrow and 'status' in narrow:
            print(f"    on the {narrow['tickers']} adjusted names alone: {narrow['status']}"
                  f"{' on ' + str(narrow['refused_because']) if narrow['refused_because'] else ''}"
                  f", IC {narrow['oos_ic_ci95']} "
                  f"({'the verdict survives' if narrow['verdict_survives'] else 'the verdict does not survive'}"
                  f" without {len(narrow['left_out'])} names the provider has no action on record for)")
    for trial in view['registrations']:
        latest = trial['latest']
        scored = (f"{latest['sessions']} sessions after it, mean IC {latest['mean_ic']}"
                  if latest else 'not scored yet')
        print(f"registered {trial['params']} after {trial['after_session']} "
              f"(live_permission false): {scored}")


def _print_sources(found: dict) -> None:
    for identifier, declaration in found.items():
        print(f"{identifier} ({declaration['family']}): {declaration['summary']}")
        for item in declaration['inputs']:
            print(f"  reads {item['name']}: {item['what']} — {item['source']}")
        for item in declaration['outputs']:
            print(f"  {item['field']}: {item['unit']}; {item['window']}; "
                  f"missing: {item['missing']}")
        print(f"  without its inputs ({declaration['missing']['policy']}): "
              f"{declaration['missing']['detail']}")


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
    optimize.add_argument('--no-ledger', action='store_true',
                          help='do not record this run in the lab ledger')
    sub.add_parser(
        'record', help='optimise every mounted strategy, record the verdicts, '
                       'register what is cleared')
    history = sub.add_parser(
        'ledger', help='recorded verdicts: yield per strategy, alternates beside the gate')
    history.add_argument('--json', action='store_true')
    story = sub.add_parser(
        'evolution', help="one strategy's record: each run, each registration, its score since")
    story.add_argument('strategy')
    story.add_argument('--json', action='store_true')
    sub.add_parser('verify', help="the ledger and registrations against the lab's boundaries")
    described = sub.add_parser(
        'sources', help='every mounted signal source: inputs, outputs, units, missing data')
    described.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)

    if args.action == 'ledger':
        stats = ledger.statistics(ledger.load())
        if args.json:
            print(json.dumps(stats, ensure_ascii=False, indent=2))
        else:
            _print_ledger(stats)
        return 0
    if args.action == 'evolution':
        view = evolution(args.strategy, ledger.load(), ledger.registrations())
        if args.json:
            print(json.dumps(view, ensure_ascii=False, indent=2))
        else:
            _print_evolution(view)
        return 0
    if args.action == 'verify':
        rows, registered = ledger.load(), ledger.registrations()
        broken = boundaries.verify(rows, registered)
        for line in broken:
            print(line, file=sys.stderr)
        print(f'{len(rows)} ledger rows, {len(registered)} registrations: '
              f"{str(len(broken)) + ' boundary violations' if broken else 'within the boundaries'}")
        return 1 if broken else 0

    config = args.config or workspace_root() / CONFIG
    if not config.exists():
        # Book data, like the other `config/*.json`: absent means not set up.
        parser.exit(2, f'no strategy plugins are configured: {config} does not exist\n')
    kernel = mount(load_rows(config))
    try:
        if args.action == 'sources':
            found = dict(live.signal_sources())
            for fiber in kernel.fibers:
                declaration = declarations.of(fiber.plugin)
                if declaration:
                    found.setdefault(declaration['id'], declaration)
            if args.json:
                print(json.dumps(found, ensure_ascii=False, indent=2))
            else:
                _print_sources(found)
            return 0
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
        if args.action == 'record':
            return record(kernel)
        try:
            report = kernel.get('optimizer').run(args.strategy)
        except (KeyError, ValueError) as exc:
            parser.exit(2, f'{exc.args[0]}\n')
        if not args.no_ledger:
            ledger.append(report)  # recorded, not registered: only `record` registers
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
