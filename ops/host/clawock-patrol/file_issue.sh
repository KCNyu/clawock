#!/usr/bin/env bash
# The only way a patrol round files an issue: /root/tools/clawock-patrol/file_issue.sh <draft.md>
# GATE_DRY_RUN=1 runs every check without filing. Issues opened any other way are flagged by patrol.sh.
exec python3 /root/tools/clawock-patrol/gate_issue.py "$@"
