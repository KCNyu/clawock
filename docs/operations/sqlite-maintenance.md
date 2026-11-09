# SQLite 维护：OpenClaw 记忆索引与共享状态库

本文是 `ops/host/sqlite_maintenance.py` 的运行说明。脚本只处理 OpenClaw 的
两个 SQLite 库，不碰 `portfolio.json`、`memory/` 或任何投资语义。

## Maintenance boundary

The main index uses offline checkpoint and compaction; subsequent runs use
incremental vacuum unless `--full` is requested. The state store is checkpointed
only. KNN oversampling is owned by the manifest's
`ops/host/openclaw-patches/patch-vector-knn-oversample.sh`, which retains the
model-filter underfill widening. Apply it through the
[patch kit](openclaw-patch-kit.md), not directly against installed bundles.

Keep the embedding model, dimension and thread settings independent of database
maintenance. `journal_size_limit` is connection-local and does not fix a reader
blocking checkpoints. Measurements and top-k comparisons for a particular host
belong in the implementing PR, not in a general latency or quality promise.

## 脚本

```bash
# 只读测量：不 checkpoint、不写库、不停 gateway
python3 ops/host/sqlite_maintenance.py --check
python3 ops/host/sqlite_maintenance.py --check --json

# 真正的离线维护：停 gateway → 备份 → checkpoint → auto_vacuum + VACUUM
# → integrity_check → 起 gateway → /health
python3 ops/host/sqlite_maintenance.py --apply

# 维护后先不起 gateway（给同窗口的 dist 补丁/人工检查用）
python3 ops/host/sqlite_maintenance.py --apply --no-restart

# auto_vacuum 已经是 INCREMENTAL 时强制再做一次全量 VACUUM
python3 ops/host/sqlite_maintenance.py --apply --full
```

`--apply` 的顺序与保护：

1. 先跑 `--check`，确认磁盘至少能放下 `3 × 主库 + 256 MiB`（备份 + VACUUM 临时空间）；
2. `systemctl --user stop openclaw-gateway.service`，等它真正 inactive；
3. 扫描 `/proc/*/fd`，主库还有别的进程打开就**中止并重启 gateway**（不硬跑）；
   状态库若仍被 watchdog 持有，最多等 10 秒，然后只跳过状态库、主库照做；
4. 用 SQLite backup API 做一致性备份到
   `/root/backups/openclaw-sqlite/<UTC-stamp>/`，同时写 `manifest.json`（含 SHA-256）；
5. `wal_checkpoint(TRUNCATE)`；主库 `auto_vacuum=INCREMENTAL` + `VACUUM`，
   第二次起走 `PRAGMA incremental_vacuum`；状态库只 checkpoint；
6. `quick_check` +（主库 VACUUM 后）`integrity_check`；
7. 写 JSON 报告到 `/root/logs/sqlite-maintenance/<UTC-stamp>.json`；
8. 起 gateway，等 `/health` 返回 `{"ok":true}`。任何数据库步骤失败都会用备份恢复
   两个库、清掉 `-wal`/`-shm`、再起 gateway，然后以非零退出。

脚本用 `/root/.openclaw/state/sqlite-maintenance.lock` 串行化，重叠执行直接 exit 3。
`--check` 不取锁、不写库，可以在 gateway 正常服务时跑。

### 回滚

自动回滚已经覆盖 `--apply` 内的数据库错误。需要人工恢复时：

```bash
export XDG_RUNTIME_DIR=/run/user/0
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/0/bus
systemctl --user stop openclaw-gateway.service
rm -f /root/.openclaw/agents/main/agent/openclaw-agent.sqlite-{wal,shm}
cp -p /root/backups/openclaw-sqlite/<stamp>/openclaw-agent.sqlite \
      /root/.openclaw/agents/main/agent/openclaw-agent.sqlite
systemctl --user start openclaw-gateway.service
curl -sS http://127.0.0.1:18789/health
```

状态库同理（备份文件名 `openclaw.sqlite`）。补丁回滚用
`python3 ops/host/manage_openclaw_patches.py rollback --receipt <receipt.json>`。

## Recall diagnosis

Compare cold and warm searches separately. A cold call includes provider/model
initialization and first embedding; warm calls still include query embedding,
vector KNN/join, keyword lookup and hybrid merge. A successful sqlite-vec path
does not deserialize every stored JSON vector; that slower path is a fallback
when vector initialization fails. Inspect which path ran before attributing cost.
Database maintenance does not establish a fixed latency or unchanged top-k result
for every installation. Use the saved receipts and measurements for that host.

## 定时执行

- 合同：`config/cron-schedules.json` 的 job `SQLite 维护`，payload profile
  `sqlite-maintenance`（`payload_kind=command`）；
- 时间：`17 4 1 1,4,7,10 *`（Asia/Hong_Kong，1/4/7/10 月 1 日 04:17）；
- 运行时：`openclaw cron` 创建，不手改 cron 存储；`ops/host/sync_cron_payloads.py`
  可核对/修复 payload 漂移；
- 为什么不是直接 `python3 ... --apply`：command job 由 gateway 的进程树启动，
  脚本停 gateway 会把自己一起停掉。合同里的命令先用
  `/usr/bin/systemd-run --user --collect --unit=openclaw-sqlite-maint` 起一个
  transient unit（独立 cgroup），再由它停/起 gateway；unit 的 stdout/stderr
  追加到 `/root/.openclaw/workspace/logs/sqlite-maintenance.log`，结构化报告仍在
  `/root/logs/sqlite-maintenance/`；
- 04:17 在 03:00 dreaming、03:20 commit 之后，08:03 简报之前；美股 watchdog
  已收档，通常没有别的进程持有状态库。若某个 watchdog 仍在跑，脚本会跳过状态库、
  主库照做，不会 fail 整个季度任务；
- 按需触发：`python3 ops/host/sqlite_maintenance.py --check` 显示
  `maintenance recommended` 时手动跑一次。主库的判据是 freelist > 8 MiB、
  WAL > 32 MiB 或 `auto_vacuum=0`；状态库只看 freelist/WAL（它故意保持
  `auto_vacuum=0`）。WAL 超过 100 MiB 优先查长读事务，不要只调
  `journal_size_limit`。

## WAL 与库大小的边界

- **WAL 大**的根因是长读事务让 autocheckpoint/PASSIVE checkpoint 无法前进；
  停掉所有读者后 `TRUNCATE` 才能归零。`journal_size_limit` 是连接级设置，
  既不能阻止读者挡住 checkpoint，也不会在重连后保留，所以它不是修复。
- **库大**的根因是 freelist；只有 `VACUUM`（或 `auto_vacuum=INCREMENTAL` +
  `incremental_vacuum`）能真正把页还给文件系统。`auto_vacuum` 是唯一能持久化的
  那一个，但改了模式仍要一次 `VACUUM` 才生效。
- 季度脚本保证每次跑完 WAL 都是 0，并且能在下一次 WAL 再长起来时用同一套流程处理；
  不要在 gateway 运行时手工 VACUUM。
