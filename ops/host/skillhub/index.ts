import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { OpenClawPluginApi } from "openclaw/plugin-sdk";

function configuredString(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

// The document owns the rules; config owns registry names and commands.
export function renderPolicy(document: string, config: Record<string, unknown>): string {
  const section = document.split("## Operator configured rules\n")[1]?.split("\n## ")[0];
  const rules = section?.trim().split("\n") ?? [];
  if (rules.length !== 6 || rules.some((line, i) => !line.startsWith(`${i + 1}. `))) {
    throw new Error("skillhub policy document must contain exactly six numbered rules");
  }
  const values: Record<string, string> = {
    primaryCli: configuredString(config.primaryCli, "skillhub"),
    fallbackCli: configuredString(config.fallbackCli, "clawhub"),
    primaryLabel: configuredString(config.primaryLabel, "domestic registry"),
    fallbackLabel: configuredString(config.fallbackLabel, "public registry"),
  };
  const rendered = rules.join("\n").replace(/\{\{(\w+)\}\}/g, (_, key: string) => {
    if (!(key in values)) throw new Error(`Unknown skillhub policy variable: ${key}`);
    return values[key];
  });
  const extraNote = configuredString(config.extraNote, "");
  return "Skills store policy (operator configured):\n" + rendered +
    (extraNote ? `\n7. ${extraNote}` : "");
}

export default function register(api: OpenClawPluginApi) {
  const config = api.pluginConfig ?? {};
  const workspace = api.config.agents?.defaults?.workspace ?? api.resolvePath("~/.openclaw/workspace");
  const document = readFileSync(resolve(workspace, "docs/operations/skills-store-policy.md"), "utf8");
  const policy = renderPolicy(document, config);

  // Stable system context, never transcript/user context. Do not keep a "seen
  // session" set: native providers rebuild the system prompt on every run,
  // and a skipped contribution would silently drop all six rules on turn 2.
  api.on("before_prompt_build", async () => ({ prependSystemContext: policy }), { priority: 80 });
}
