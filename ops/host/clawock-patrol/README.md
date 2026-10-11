# clawock-patrol 文档地图

这些文件的版本化源在仓库 `ops/host/clawock-patrol/`，用 `ops/host/install_patrol_assets.sh` 装到
`/root/tools/clawock-patrol/`（`--check` / `--rollback`）；supervisor `patrol.sh` 的源是 `ops/host/patrol.sh`，
单独安装。只在本机、不入库的：`steer.md`（kcn 的长期要求，`patrol.sh steer` 写）以及
`/root/logs/clawock-patrol/` 下的全部状态（ledger、drafts、rounds、快照）。

谁在什么时候读哪份：

| 文件 | 读者 | 时机 |
|---|---|---|
| `round-prompt.md` | 每轮模型 | 每轮注入（`patrol.sh render` 替换 `{{ROUND}}` `{{AXIS_TITLE}}` `{{AXIS_BODY}}` `{{HEAD}}` `{{STEER}}`） |
| `closed-lessons.md` | 每轮模型 | 开工必读的十类核对清单；编号被 `gate_issue.py` 的拒绝信息引用，改编号要同步 |
| `hunting-patterns.md` | 每轮模型 | 开工必读：修掉的 issue 反复出在哪八类地方、每类的探针；recent 轮的修复兄弟项核查 |
| `closed-lessons-examples.md` | 模型 | 按需：写「对照已关」或拿不准时 |
| `investigation-guide.md` | 模型 | 按需：调查卡住、判断值不值得提 |
| `issue-format.md` | 模型 | 准备提报时：草稿格式、闸规则、拒绝后怎么办 |
| `axes.tsv` / `rotation` / `surfaces.json` | supervisor / 闸 | 每轮读取，改了不用重启 |
| `gate_issue.py` / `file_issue.sh` | 模型经 `file_issue.sh` 调用 | 提报时；唯一的开 issue 路径 |
| `triage.py` | 闸 | 提报时：分级、标签、去向（单独 issue / 补充到同根因 issue / 汇总） |
| `filing.py` | 闸；supervisor 每轮结束后 `flush-digest` | 打标签、合成汇总 issue、Telegram 一行；`ensure-labels` / `backfill` 手动用 |
| `patrol_intel.py` | supervisor | 每轮派发前 `brief` 生成 prompt 的「反馈与提报」并写 `feedback.json`；轮次结束 `round-yield` 写进 `rounds.tsv` |
| `peers.json` | peers 轮的模型 | 开源同类对标的候选清单（手维护，闸另核来源仓库仍活跃） |
| `issue-context.py` / `codemap.sh` / `build_codemap.py` | 模型 | 开工时查 open issue、代码地图 |
| `clawock-patrol.service` | systemd | 改了要 `systemctl daemon-reload`，安装脚本不替你做 |

让路与安装：仓库 `ops/host/README.md` § Patrol supervisor。

## 分级与路由（2026-10-01）

闸保证一条发现**是真的**；`triage.py` 标明严重度和领域，并与已有同根因 issue 去重。
提报数量不限：不按每轮、24 小时、每周或 issue 总数压制发现，P3 也正常提报（kcn 2026-10-11：「还是可以开，
只不过说要提高有价值 issues 的比例」）。P3 多一条证据要求：`代价:` 一行说清不修会怎样；没有这行的闸回 `CANDIDATE`，
退回 ledger 候选（`rounds.tsv` 记 `+N candidate`），补上再交就开。

- **分级**：草稿写 `## 分级`（严重度 / 领域 / 类型 / 关联），缺了按标题推断。闸只降不拒：P0/P1 必须拿今天的真实产物
  作证，文档与纯样式压到 P3，基础设施面最高 P2；14 天内被关成误报的不少于修掉的类别（至少 3 条），其 P2 压到 P3，
  P0/P1 不受反馈回路影响。规则表在 `issue-format.md`。
- **去向**：P0–P3 都单独开 issue（P3 须带 `代价:`，否则退回候选）；`关联:` 指向 open issue 或与 14 天内 open 的巡检 issue
  同一「文件 + 函数 + 领域」时，作为补充评论挂过去（Sentry 式指纹）。取消数量限制前留下的
  `/root/logs/clawock-patrol/digest/pending.jsonl` 下次收尾立即提报，不等条数或年龄。
- **标签**：`patrol`、`severity:P0–P3`、`area:*`、`kind:*`、`lens:<axis>`、`patrol:digest`，以及给关闭者用的
  `patrol:noise`。`filing.py ensure-labels` 建全套，`filing.py backfill` 给存量补标签。
- **反馈回路**：`patrol_intel.py brief` 每轮统计各范围 14 天内的修复/误报，列最近被判误报的 issue，
  把被关成 not planned / `patrol:noise` 不少于修掉的「领域/类型」写进 `feedback.json`，闸据此降权；recent 轮另附
  「回归观察」：窗口内非运行时、非 tests/ 编辑碰过的、已修 issue 引用的文件，连同那条 issue 当时的 RED-CHECK（`regress/<N>.sh`）。
- **peers 轮**：每天一轮读 `peers.json` 里的开源同类项目，只能提 `类型: feature` 的提案（最高 P2，数量不限），
  闸核来源仓库仍活跃、痛点 #N 真实存在、不越产品边界。
- **关闭巡检 issue 的人**：不成立或不值得修，请以 not planned 关闭或加 `patrol:noise`，这是反馈回路唯一的输入。

旧 `priority:P1–P3` 是竞品提案的实现优先级，不能按同号直接转换为缺陷严重度。现行 issue 使用
`severity:`；退役旧标签时先保留标签描述及关联 issue 的归档，再移除旧标签，已有严重度保持原值。

提报到 GitHub 的第三方引用由 `github_text.py` 强制清理并验证，覆盖标题、正文、评论及旧汇总。
项目名用纯文本，借鉴机制用自己的话说明；外部链接只留在仓库文档/peers.json，来源活跃核验仍在私下进行。

## 产出质量怎么量（2026-10-11）

目标是提高真金（钱/仓位/决策数字错、成品没发、闸假绿/假红）在提报里的比例，不是减少 issue。三个读数都从
`gh issue list --label patrol` 和 `rounds.tsv` 算，基线是 10-01..10-11：

| 读数 | 怎么算 | 基线 | 目标 |
|---|---|---|---|
| **P0+P1 每完成轮（硬闸）** | `severity:P0,P1` 条数 / `rounds.tsv` 里 ok、unverified 的轮数 | 0.16（38/235） | **不低于 0.16** |
| 新 issue 里 P3 占比 | 按创建日，`severity:P3` / 全部 | 30%（119/400） | 低于 10% |
| P0–P2 被关成误报 | 已关的 P0–P2 里 not planned 或 `patrol:noise` 的占比 | 10-01..06 9%，10-07..11 24% | 不高于 10% |

第一行是硬闸：任何对 prompt、闸、轮换表或模型池的改动，如果让它掉到 0.16 以下，就算 P3 占比达标也算失败，撤回。
P3 占比要靠分子变大（更多 P0/P1）和 P3 自己带上代价来降，不能靠不提。

分母的口径：「完成轮」是 supervisor 记成 ok/unverified 的轮次，不管是哪个模型收尾、它接手时前面失败过几次。
所以空壳轮（排在池尾的模型接手一个已经卡死多次的会话，报 DONE 而一条没提）会把这个数往下拉：10-10..10-11 的 31 个
完成轮里 14 轮是当时排第 6 的模型收尾的、12 轮空手，那两天的读数 0.10（3/31）里去掉这 14 轮是 0.12（2/17）。
读数变差时先按 `result.env` 的 `MODEL_USED` 和 `ATTEMPTS` 拆开看，再怀疑 prompt。模型池的顺序与依据在
`ops/host/agent-dispatch/opencode-fallback-models`。
