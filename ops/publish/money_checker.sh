#!/usr/bin/env bash
# money_checker.sh — locate and run the package-owned money-conservation check.
# SOURCE this; do not run it.
#
# Why this is a file rather than two `command -v clawock` lines: resolving the
# checker is not the same as having it on PATH, and both gates learned that the
# hard way on the same night. The installed console script lives in
# ~/.local/bin, but a job started from the user crontab runs with
# PATH=/usr/bin:/bin. So the nightly gold refresh committed portfolio.json,
# safe_push.sh could not find `clawock`, and the gate fired — correctly, since
# unverifiable money must not be published, but for the wrong reason. The money
# commit then sat unpushed on the live checkout, and because the gate re-runs
# for as long as an unpushed portfolio.json commit exists, it was in front of
# every later push too.
#
# The fallback runs the same package out of the checkout. It is `clawock.cli`
# either way — never a second implementation of the arithmetic, which would
# drift from the real one and quietly bless a book the real one rejects — and it
# names no host path, so a runner, a worktree and a bare cron environment all
# resolve it the same way.
#
# Provides, for the sourcing shell:
#   money_checker_kind <root>   echoes "installed"|"checkout"; non-zero if neither
#   run_money_check <root>      runs the check against <root>; 127 if unresolvable

money_checker_kind() {
  if command -v clawock >/dev/null 2>&1; then
    echo installed
    return 0
  fi
  # Ask the filesystem BEFORE the interpreter. An editable install writes a
  # .pth into site-packages, so `import clawock.cli` succeeds from anywhere on
  # a developer box regardless of PYTHONPATH — this branch answered "checkout"
  # for a root with no `src/` at all, and then verified the book with whatever
  # copy of the package happened to be importable rather than the one being
  # published. Same class as `clawock --version` on an editable install: the
  # answer is about the host, not about the code under test. It is also why the
  # gate's own contract test passed in CI (nothing installed) and failed on the
  # live box (everything installed) — a gate that reports on the machine is not
  # reporting on the contract.
  if [ -n "$1" ] && [ -f "$1/src/clawock/cli.py" ] && PYTHONPATH="$1/src" \
       python3 -c 'import clawock.cli' >/dev/null 2>&1; then
    echo checkout
    return 0
  fi
  return 1
}

run_money_check() {
  # <root> is the repository/workspace whose book is being published. Passing it
  # explicitly matters: the point is to verify the book that is about to go out,
  # not whichever workspace the caller's environment happens to point at.
  local root="$1" kind
  kind="$(money_checker_kind "$root")" || return 127
  if [ "$kind" = installed ]; then
    env "CLAWOCK_WORKSPACE=$root" clawock integrity
  else
    env "CLAWOCK_WORKSPACE=$root" "PYTHONPATH=$root/src" \
        python3 -m clawock.cli integrity
  fi
}
