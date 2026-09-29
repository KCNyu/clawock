/**
 * `/dispatch-list [N]` — the agent-dispatch queue of this host as one chat reply: what runs,
 * what waits and where, and the N (default 5) most recently ended tasks.
 *
 * Glue only. Everything it prints is `task_queue_ops.py board` (read-only), the same versioned
 * entry the dsh task chip reads; this file parses no task directory and decides no order.
 * It is installed next to that entry (ops/host/install_task_queue_ops.sh), so the two always
 * come from the same install. Registered commands bypass the model; only allowlisted senders
 * may run it (requireAuth defaults to true). Telegram's menu shows it as /dispatch_list —
 * OpenClaw matches `-` and `_` alike.
 */
import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";
import type { OpenClawPluginApi } from "openclaw/plugin-sdk";

const OPS = fileURLToPath(new URL("../task_queue_ops.py", import.meta.url));
const TIMEOUT_MS = 20_000;
const USAGE = "用法：/dispatch-list [最近结束条数 0-20，默认 5]";

function board(recent: number): Promise<string> {
  return new Promise((resolve) => {
    execFile("python3", [OPS, "board", "--recent", String(recent)], { timeout: TIMEOUT_MS },
      (error, stdout, stderr) => {
        const text = String(stdout ?? "").trim();
        if (!error && text) return resolve(text);
        const why = String(stderr ?? "").trim().slice(-300) || (error ? error.message : "empty output");
        resolve(`派发队列读取失败：${why}`);
      });
  });
}

export default function register(api: OpenClawPluginApi): void {
  api.registerCommand({
    name: "dispatch-list",
    description: "查看本机 agent-dispatch 任务队列",
    acceptsArgs: true,
    handler: async (ctx) => {
      const arg = ctx.args?.trim() ?? "";
      if (arg !== "" && !/^\d{1,2}$/.test(arg)) return { text: USAGE };
      return { text: await board(arg === "" ? 5 : Number(arg)) };
    },
  });
}
