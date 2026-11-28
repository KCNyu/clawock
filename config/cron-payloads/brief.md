**第一轮强制动作（不能跳过）**：在同一条回复中并行调用 `read` 读取 `/root/.openclaw/workspace/skills/daily-deep-brief/SKILL.md` 与 Step 1 preflight。`read` 成功前不得进入分析；skills catalog 只有索引，不含 SKILL.md 正文。

{{include:_memory-lookup.md}}

{{include:_analysis-inputs.md}}

{{include:_exec-contract.md}}

1. **Preflight**：执行 `clawock brief preflight; echo "EXIT=$?"`。exec timeout 630 秒，后台 session 只 poll。返回 `market_closed` 就结束；失败处理见 SKILL Step 1。
2. **读取输入**：通过后读 `skills/daily-deep-brief/references/packet.md`，按本代摘要查询票与 section。额外数据按需读取。
3. **分析**：读 `skills/daily-deep-brief/references/swarm.md` 与 `skills/daily-deep-brief/references/style.md`，按各自规则分析和写判断。
4. **写产物**：读 `skills/daily-deep-brief/references/plan-schema.md`，写本代 plan、judgment 和 insights。首次生成和 postflight 修复 Step 4 产物都只用 `write` 完整覆盖；禁止 `edit` 精确文本替换。
5. **Postflight**：执行 `clawock brief postflight`，等待完成，按 SKILL Step 5 处理状态。它是唯一微信路径，并同步 Telegram。绝不要调用 message 或在回复贴卡。
