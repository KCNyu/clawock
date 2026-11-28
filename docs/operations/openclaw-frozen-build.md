# Frozen OpenClaw build

The desk runs OpenClaw `2026.7.1-2` from the `kcn/7.1-maint` branch of
[KCNyu/openclaw](https://github.com/KCNyu/openclaw/tree/kcn/7.1-maint).
Freeze the deployment by full commit. Keep upstream as a manual source for
reviewed security cherry-picks. Automatic upstream synchronization and version
upgrades are disabled for this deployment.

1. Build the approved source commit in the fork's KCN maintenance CI. Take the
   tarball, `COMMIT` and `SHA256SUMS` from the same successful run. CI installs
   the tarball and verifies its package version and `dist/build-info.json`.
2. Verify the download checksum and the full build commit on the host before
   unpacking. Stage a candidate in `.openclaw-kcn-<commit>`. Check the version,
   directory name, build-info and dependency compatibility before activation.
3. Run the candidate's Weixin, llama-cpp and Codex plugin checks, memory search
   and one isolated cron slot. Save the exit codes and output. Switch at an idle
   gateway with the project restart entry point. Repeat runtime checks and verify
   dashboard data. Keep the previously verified selection available for recovery.

Configure host extensions with their respective installers in [host operations](../../ops/host/README.md).
The fork owns runtime behavior, including dreaming, recall and provider policy.
