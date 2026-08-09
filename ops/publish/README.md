# Publishing operations

The only git/data-plane publication implementation for the repository.
`publish_generation.sh` is the shared generation entry point;
`safe_push.sh` is the shared protected-branch push path. Callers may delegate
here but must not copy identity selection, retry, or deploy logic elsewhere.
