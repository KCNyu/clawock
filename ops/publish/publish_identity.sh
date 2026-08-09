#!/usr/bin/env bash
# publish_identity.sh — select the publishing identity. SOURCE this; do not run it.
#
# A protected master must still accept scheduled data writers, and from 2026-08-05
# there is a second publication target (the orphan data branch, #314). Both go out
# under the same deploy-key identity, so the selection lives in one file rather
# than being restated by every publisher: `safe_push.sh` sources it, and so does
# `publish_dashboard.sh` before it publishes a generation to the data branch.
#
# Sets, for the sourcing shell:
#   PUBLISH_SSH_KEY   path to the key in use, or empty for "whatever git is configured with"
#   PUBLISH_REMOTE    remote to push to — an ssh URL when a deploy key was selected
#   GIT_SSH_COMMAND   exported, so any git child process inherits the identity
#
# Registers its own EXIT trap to wipe an ephemeral key file. That is deliberate:
# the Actions secret is materialised on disk for the duration of a push, and a
# caller that forgot to clean it up would leave a write-enabled deploy key in the
# runner's temp directory.

# shellcheck disable=SC2034  # PUBLISH_REMOTE is read by the sourcing shell.
PUBLISH_SSH_KEY=""
PUBLISH_REMOTE=""
_PUBLISH_TEMP_SSH_KEY=""

if [ -n "${CLAWOCK_PUBLISH_SSH_KEY:-}" ]; then
  # GitHub-hosted workflows receive a write-enabled deploy key through this
  # secret; using the deploy key lets the repository ruleset distinguish
  # automation from the shared KCNyu identity used by interactive sessions.
  _PUBLISH_TEMP_SSH_KEY=$(mktemp)
  chmod 600 "$_PUBLISH_TEMP_SSH_KEY"
  printf '%s\n' "$CLAWOCK_PUBLISH_SSH_KEY" > "$_PUBLISH_TEMP_SSH_KEY"
  PUBLISH_SSH_KEY="$_PUBLISH_TEMP_SSH_KEY"
elif [ "$(git rev-parse --show-toplevel 2>/dev/null)" = "/root/.openclaw/workspace" ] && \
     [ -r "/root/.ssh/clawock_runtime_publish" ]; then
  # The live OpenClaw checkout uses a separate deploy key. Interactive agents
  # work in isolated worktree paths, so they never inherit this bypass.
  PUBLISH_SSH_KEY="/root/.ssh/clawock_runtime_publish"
fi

if [ -n "$PUBLISH_SSH_KEY" ]; then
  export GIT_SSH_COMMAND="ssh -i $PUBLISH_SSH_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
  PUBLISH_REMOTE="${CLAWOCK_PUBLISH_REMOTE:-git@github.com:KCNyu/clawock.git}"
fi

if [ -n "$_PUBLISH_TEMP_SSH_KEY" ]; then
  trap 'test -z "$_PUBLISH_TEMP_SSH_KEY" || { : > "$_PUBLISH_TEMP_SSH_KEY"; unlink "$_PUBLISH_TEMP_SSH_KEY"; }' EXIT
fi
