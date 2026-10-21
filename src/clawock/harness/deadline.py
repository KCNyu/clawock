"""Wall-clock supervision for a preflight and all of its subprocesses."""
import os
import signal
import subprocess


def run_bounded(argv, *, timeout, cwd, env=None):
    """Stream output; stop the process group before returning a timeout."""
    with subprocess.Popen(argv, cwd=cwd, env=env, start_new_session=os.name == 'posix') as child:
        try:
            return child.wait(timeout=timeout)
        except BaseException:
            # Workers in a ThreadPoolExecutor can be waiting on subprocesses.
            # Killing only the collector leaves those writers alive after the
            # failure context is published, so stop the entire process group.
            if os.name == 'posix':
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                child.kill()
            child.wait()
            raise


def supervise_preflight(module, argv, *, workspace, job, slot, started, shipped):
    """Record collector deaths outside the collector, including SIGKILL.

    The worker owns normal terminal outcomes. The parent only fills a missing
    outcome for this attempt, and never alters a previously delivered slot.
    """
    import sys
    from clawock.automation import workflow_outcomes

    command = [sys.executable, '-u', '-c',
               f'from {module} import _collect; import sys; '
               'raise SystemExit(_collect(sys.argv[1:]))',
               *(sys.argv[1:] if argv is None else argv)]
    code = run_bounded(command, timeout=None, cwd=workspace,
                       env={**os.environ, 'CLAWOCK_PREFLIGHT_STARTED_AT': started.isoformat()})
    if code and not shipped:
        died = (f'signal {signal.Signals(-code).name}'
                if -code in set(signal.Signals) else f'exit {code}')
        workflow_outcomes.record_stage(
            job, 'preflight', 'failed', slot=slot, reason='preflight_crashed',
            detail=f'collector ended without an outcome ({died})', return_code=code,
            unless_terminal_since=started)
    return code
