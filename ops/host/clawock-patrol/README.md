# clawock-patrol 文档地图

这些文件的版本化源在仓库 `ops/host/clawock-patrol/`，用 `ops/host/install_patrol_assets.sh` 装到
`/root/tools/clawock-patrol/`（`--check` / `--rollback`）；supervisor `patrol.sh` 的源是 `ops/host/patrol.sh`，
单独安装。只在本机、不入库的：`steer.md`（kcn 的长期要求，`patrol.sh steer` 写）以及
`/root/logs/clawock-patrol/` 下的全部状态（ledger、drafts、rounds、快照）。

谁在什么时候读哪份：

| 文件 | 读者 | 时机 |
|---|---|---|
| `round-prompt.md` | 每轮模型 | 每轮注入（`patrol.sh render` 替换 `{{ROUND}}` `{{AXIS_TITLE}}` `{{AXIS_BODY}}` `{{HEAD}}` `{{STEER}}`） |
| `closed-lessons.md` | 每轮模型 | 开工必读的八类核对清单；编号被 `gate_issue.py` 的拒绝信息引用，改编号要同步 |
| `hunting-patterns.md` | 每轮模型 | 开工必读：修掉的 issue 反复出在哪八类地方、每类的探针；recent 轮的修复兄弟项核查 |
| `closed-lessons-examples.md` | 模型 | 按需：写「对照已关」或拿不准时 |
| `investigation-guide.md` | 模型 | 按需：调查卡住、判断值不值得提 |
| `issue-format.md` | 模型 | 准备提报时：草稿格式、闸规则、拒绝后怎么办 |
| `axes.tsv` / `rotation` / `surfaces.json` | supervisor / 闸 | 每轮读取，改了不用重启 |
| `gate_issue.py` / `file_issue.sh` | 模型经 `file_issue.sh` 调用 | 提报时；唯一的开 issue 路径 |
| `triage.py` | 闸 | 提报时：分级、标签、去向（单独 issue / 补充到同根因 issue / 汇总）、预算 |
| `filing.py` | 闸；supervisor 每轮结束后 `flush-digest` | 打标签、合成汇总 issue、Telegram 一行；`ensure-labels` / `backfill` 手动用 |
| `patrol_intel.py` | supervisor | 每轮派发前 `brief` 生成 prompt 的「反馈与预算」并写 `feedback.json`；轮次结束 `round-yield` 写进 `rounds.tsv` |
| `peers.json` | peers 轮的模型 | 开源同类对标的候选清单（手维护，闸另核来源仓库仍活跃） |
| `issue-context.py` / `codemap.sh` / `build_codemap.py` | 模型 | 开工时查 open issue、代码地图 |
| `clawock-patrol.service` | systemd | 改了要 `systemctl daemon-reload`，安装脚本不替你做 |

让路与安装：仓库 `ops/host/README.md` § Patrol supervisor。

## 分级与路由（2026-10-01）

闸保证一条发现**是真的**；`triage.py` 决定它**值多少**、去哪。依据是 09-21 到 09-30 的 245 条 `[patrol]` issue：
按 not planned 或无修复关闭的只有约 5%（闸管住了真假），但约三成是文档漂移、样式/对比度、CI 卫生这类小问题，
各开一条、各修一个 PR；19 条是同一根因被修了一处后的第二、第三条（`#2171` → `#2179` 这种）；单日最多 57 条。

- **分级**：草稿写 `## 分级`（严重度 / 领域 / 类型 / 关联），缺了按标题推断。闸只降不拒：P0/P1 必须拿今天的真实产物
  作证，文档与纯样式压到 P3，基础设施面最高 P2，最近被反复按误报关闭的类别压到 P3。规则表在 `issue-format.md`。
- **去向**：P0 总是单独开；P1/P2 在 24 小时预算内单独开（`triage.BUDGET`），超出进汇总；P3 进汇总；`关联:` 指向
  open issue 或与 14 天内 open 的巡检 issue 同一「文件 + 函数 + 领域」时，作为补充评论挂过去（Sentry 式指纹）。
  汇总存 `/root/logs/clawock-patrol/digest/pending.jsonl`，满 15 条或最老一条满 24 小时（约一天一条）由闸或 supervisor 合成一条
  `[patrol] 巡检汇总 …` issue（Renovate 的 Dependency Dashboard 同款），每条带完整证据折叠块。
- **标签**：`patrol`、`severity:P0–P3`、`area:*`、`kind:*`、`lens:<axis>`、`patrol:digest`，以及给关闭者用的
  `patrol:noise`。`filing.py ensure-labels` 建全套，`filing.py backfill` 给存量补标签。
- **反馈回路**：`patrol_intel.py brief` 每轮统计各范围 14 天内的修复/误报，列最近被判误报的 issue，
  把被多次按 not planned / `patrol:noise` 关闭的「领域/类型」写进 `feedback.json`，闸据此降权；recent 轮另附
  「回归观察」：窗口内提交碰过的、已修 issue 引用的文件，连同那条 issue 当时的 RED-CHECK（`regress/<N>.sh`）。
- **peers 轮**：每天一轮读 `peers.json` 里的开源同类项目，只能提 `类型: feature` 的提案（最高 P2，7 天 2 条），
  闸核来源仓库仍活跃、痛点 #N 真实存在、不越产品边界。
- **关闭巡检 issue 的人**：不成立或不值得修，请以 not planned 关闭或加 `patrol:noise`，这是反馈回路唯一的输入。
