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
