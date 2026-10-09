**Exec 契约（退出码；简报、报告、盘中共用这一份）**
任何一条 exec 非零退出都会把整轮 cron 记成 error，哪怕产物已经投递。两类命令处理方式不同：
- **探测「东西在不在」的命令必须整条链退出 0。** `ls`/`grep`/`head`/`test`、读可能还没产生的文件，找不到是正常答案：给这条探测自己兜底，`ls X 2>/dev/null || true`。`2>/dev/null` 只吞 stderr、不改退出码；`;` 链的退出码是最后一条的。
- **业务步骤**（`clawock … preflight` / `postflight` 等产出产物的命令）结果必须原样可见：不接管道（`cmd | tail` 之后的 `$?` 是 tail 的），不补 `|| true` / `; true`。要让非零退出不判红，只允许末尾加 `; echo "EXIT=$?"`；输出太长就重定向到文件再 `tail` 文件。
- 业务步骤的结果只看 `EXIT` 和 stdout 的 `status`。`EXIT=1` 以 stdout 为准：context 已产出就是带告警完成，继续。`EXIT=2`、`status` 为 `fail` / `preflight_failed`，或该有的 context / 结果 JSON 没出现，就是失败：preflight 失败时最终回复写明步骤、EXIT 与最后一行错误后结束本轮，不进入分析、不调 postflight；postflight `fail` 按该步骤的修复规则处理。不要换一条命令去「确认它其实成功了」。
