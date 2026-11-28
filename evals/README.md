# Brief harness behavior evaluations

Run `python3 evals/run.py --trials 3` from a checkout installed with the
`test` extra. Use `--track regression` or `--track capability` for one set.
CI's required validation includes both for code edits, including skills and
cron payloads.

The case registry refers to existing fixture graders and records their Git
line provenance. The regression track includes incidents such as stale prose
paired with fresh numbers, leaked private-topic text, watchdog delivery
masking a publication failure, and repair tools turning a delivered cron red.
It also includes negative guards derived from those production boundaries.
The capability track checks an accepted fallback, bounded context, resolvable
citations and staged skill delivery. The citation dimension has its own score.

Every trial starts a fresh process on the same inputs. For each test method,
all parameter instances must succeed for that trial to pass. A skipped grader
counts as a failure. Pass@k counts a case with any passing trial and pass^k
counts a case only when all trials pass. This offline suite measures the
deterministic harness and instruction contracts. Future live model graders
need a separate track with recorded outputs and human calibration.

The baseline on the post-split commit had 22 regression and 4 capability
cases, including 6 citation cases, with pass@3 and pass^3 equal to 1.0.
