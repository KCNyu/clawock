#!/usr/bin/env bash
# clawock commit-identity whitelist — sourced by pre-commit and pre-push.
#
# 2026-08-27: one commit was authored as `kcn@users.noreply.github.com`
# (bare username noreply, no numeric ID prefix); GitHub attributed it to a
# stranger's account of the same name. Only these identities are valid:
#   KCNyu <shengyu.li.evgeny@gmail.com>
#   KCNyu <45508369+KCNyu@users.noreply.github.com>
#   any    <ID+user@users.noreply.github.com>  (github-actions[bot],
#            dependabot[bot], and other ID-prefixed noreply accounts)

IDENTITY_RE='^[0-9]+\+[^@]+@users\.noreply\.github\.com$'

_identity_ok() {
  local email="$1"
  [ "$email" = "shengyu.li.evgeny@gmail.com" ] && return 0
  [ "$email" = "45508369+KCNyu@users.noreply.github.com" ] && return 0
  printf '%s' "$email" | grep -qE "$IDENTITY_RE" && return 0
  return 1
}

# check_identities "<Name <email>>" ... — prints violations, returns 1 if any.
check_identities() {
  local bad=0 ident email
  for ident in "$@"; do
    email="$(printf '%s' "$ident" | sed -n 's/^.*<\([^>]*\)>.*$/\1/p')"
    if ! _identity_ok "$email"; then
      echo "    ✗ unrecognized commit identity <$email>"
      echo "      valid: KCNyu (shengyu.li.evgeny@gmail.com) or"
      echo "      <ID>+<user>@users.noreply.github.com (ID-prefixed noreply only)"
      bad=1
    fi
  done
  return $bad
}
