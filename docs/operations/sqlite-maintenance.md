# SQLite 维护：OpenClaw 记忆索引与共享状态库

本文是 `ops/host/sqlite_maintenance.py` 的运行说明，并记录 2026-11-07
在本机的第一次实测。脚本只处理 OpenClaw 的两个 SQLite 库，不碰
`portfolio.json`、`memory/` 或任何投资语义。

## 结论：本机该做什么、按什么顺序

| 顺序 | 项目 | 本机是否做 | 实测收益（2026-11-07） | 风险 / 边界 |
|---|---|---|---|---|
| 1 | 主索引离线 `wal_checkpoint(TRUNCATE)` + `auto_vacuum=INCREMENTAL` + `VACUUM` | 做，一次 | 主库 415,707,136 → 385,810,432 B（396.4 → 367.9 MiB，−28.5 MiB）；freelist 7,256 → 0 页；页数 101,491 → 94,192；WAL 归零 | gateway 停 1–2 分钟；VACUUM 需要约 2× 库大小的临时空间；失败自动回滚到备份 |
| 2 | 共享状态库 `wal_checkpoint(TRUNCATE)` | 做，每次 | WAL 4,136,512 → 0 B；freelist 12 页（48 KiB）不动；库大小 73.7 MiB 不变 | 只 checkpoint，不 VACUUM；12 个空闲页不值得重写 73.7 MiB。若将来 freelist 变大再单独评估 |
| 3 | KNN oversample 8 → 1 的 dist 补丁 | 做，一次（升级后由 patch kit 重放） | 热召回 139.9 → 119.5 ms；其中 sqlite-vec KNN 39.1 → 24.9 ms | 一行常量；多模型索引仍由现有 underfill widening 兜底；质量不变（见性能文档） |
| 4 | 季度/按需执行 | 做 | 04:17 HKT，1/4/7/10 月 1 日；用 `openclaw cron` 的 command job | command job 用 `systemd-run` 脱离 gateway cgroup，否则“停 gateway”会把任务自己杀掉 |

**不要做**：不升级 OpenClaw（2026.7.1-2 没有 `--session-sqlite` /
`state-sqlite compact`）；不把 `journal_size_limit` 当成持久设置（它是连接级的，
重连读回 -1）；不改 embedding 模型或 768 维；不引入 Elasticsearch 或任何常驻大内存
组件；不把 embedding 线程从 1 调大（node-llama-cpp 在本机多线程路径有已知死锁，
补丁注释记录了 2026-07-08 的根因）。

### 为什么先做 1，而不是先改代码

维护前热召回的中位数是 **347.7 ms**，其中 sqlite-vec KNN 占 **242.6 ms**；
`VACUUM` 后同一份代码、同一个查询集降到 **139.9 ms / 39.1 ms**。这说明大头不是
“算力不够”，而是 101,491 页、7,256 页 freelist 的库让 26 MB 向量表在页间跳读。
先 compaction 再谈查询侧优化，顺序不能反。

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

## 2026-11-07 第一次执行记录

执行时间 02:33 HKT（UTC 2026-11-06T18:33Z），`--apply --no-restart`，
随后装 dist 补丁、起 gateway。

| 指标 | 维护前 | 维护后 |
|---|---|---|
| 主库文件 | 415,707,136 B（396.4 MiB） | 385,810,432 B（367.9 MiB） |
| 主库页数 / freelist | 101,491 / 7,256 | 94,192 / 0 |
| 主库 WAL | 0 B | 0 B |
| `auto_vacuum` | 0（OFF） | 2（INCREMENTAL） |
| `quick_check` / `integrity_check` | ok | ok / ok |
| 状态库文件 | 77,266,944 B | 77,266,944 B |
| 状态库 WAL | 4,136,512 B | 0 B |
| 状态库 freelist | 12 页 | 12 页 |
| 可用磁盘 | 10,631,983,104 B | 10,173,095,936 B（备份占 493 MB，主库缩 29.9 MB） |

报告：`/root/logs/sqlite-maintenance/20261106T183233Z.json`
备份：`/root/backups/openclaw-sqlite/20261106T183233Z/`（两个库 + `manifest.json`）

第一次尝试（02:30Z）在“停 gateway 后检查句柄”这一步主动中止：状态库仍被
`clawock-intraday-watchdog` 持有，脚本没有做任何 checkpoint、没有产生备份，
直接重启 gateway 并写失败报告。这是预期行为：宁可让 watchdog 跑完，也不在
有读事务时硬 truncate。随后 watchdog 退出，第二次顺利通过。

### 起回来后的验证

- `/health`：`{"ok":true,"status":"live"}`；`systemctl --user is-active` = active。
- `openclaw memory status --agent main --json`：493 文件 / 8,697 切片 / 768 维，
  `dirty=false`，`indexIdentity.status=valid`，vector 与 FTS 都 available。
- 真实 `memory_search`（走 gateway，不是 CLI 的临时 manager）：
  中文查询「记忆索引 SQLite 压缩」命中 5 条，第一条
  `memory/2026-07-27-pre-open.md:160`；第一次 `managerMs=1658`、`searchMs=6595`，
  第二次同一 gateway `managerMs=1`、`searchMs=499`。第一次是冷启（模型加载 +
  首次 embedding），第二次是热路径。

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
  `auto_vacuum=0`，12 个空闲页不值得重写 73.7 MiB）。WAL 超过 100 MiB
  优先查长读事务，不要只调 `journal_size_limit`。

## 与 WAL 事实的关系

派发时的线索是主库 WAL 370 MB。实际执行时主库 WAL 已经是 0：00:49 的 gateway
重启触发了 OpenClaw 自己的 close checkpoint（`configureSqliteWalMaintenance`
默认 `TRUNCATE`），把旧 WAL 截掉了；但 7,256 页 freelist 和 101,491 页的文件
还在。也就是说：

- **WAL 大**的根因是长读事务让 autocheckpoint/PASSIVE checkpoint 无法前进；
  停掉所有读者后 `TRUNCATE` 才能归零。`journal_size_limit` 是连接级设置，
  既不能阻止读者挡住 checkpoint，也不会在重连后保留，所以它不是修复。
- **库大**的根因是 freelist；只有 `VACUUM`（或 `auto_vacuum=INCREMENTAL` +
  `incremental_vacuum`）能真正把页还给文件系统。`auto_vacuum` 是唯一能持久化的
  那一个，但改了模式仍要一次 `VACUUM` 才生效。
- 本次主库 WAL 的即时收益是 0 B，不是 370 MB；季度脚本保证每次跑完都是 0，
  并且能在下一次 WAL 再长起来时用同一套流程处理。

召回性能的完整测量、优化表和质量对比见
[`memory-recall-performance.md`](memory-recall-performance.md)。
