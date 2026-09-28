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
| `issue-context.py` / `codemap.sh` / `build_codemap.py` | 模型 | 开工时查 open issue、代码地图 |
| `clawock-patrol.service` | systemd | 改了要 `systemctl daemon-reload`，安装脚本不替你做 |

让路与安装：仓库 `ops/host/README.md` § Patrol supervisor。
