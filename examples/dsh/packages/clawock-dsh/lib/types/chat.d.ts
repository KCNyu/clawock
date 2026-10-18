import { type Translate } from './copy.ts';
import { type PanelInput } from './panel.ts';
import { type StatsOptions } from './taskqueue.ts';
import type { TaskStats } from './types.ts';
/** The slice of OpenClaw's plugin API this entry uses (the SDK's own types are not a dependency of this package). */
export interface OpenClawCommandApi {
    pluginConfig?: Record<string, unknown>;
    registerCommand(command: {
        name: string;
        description: string;
        acceptsArgs?: boolean;
        handler: (ctx: {
            args?: string;
            config?: {
                env?: unknown;
                agents?: {
                    defaults?: {
                        workspace?: string;
                    };
                };
            };
        }) => Promise<{
            text: string;
        }>;
    }): void;
}
/** The reply for one read of both halves (the test seam: tests/decision_studio_plugin.spec.js compares it with the panel). */
export declare function dispatchListText(input: PanelInput, t: Translate, now: number): string;
/**
 * `/dispatch-stats` arguments: `7d`/`30d` (a rolling window), `all` (every retained task),
 * a `YYYY-MM-DD` since-date, and `patrol` to include patrol rounds. The default is the chip's
 * own window (the last seven days, patrol excluded). null = an argument this surface does not
 * accept; the answer is the usage line, never a silent fallback.
 */
export declare function parseStatsArgs(raw: string): StatsOptions | null;
/** The `/dispatch-stats` reply: the chip's stats fold as one message. */
export declare function dispatchStatsText(stats: TaskStats | null | undefined, t: Translate): string;
export default function register(api: OpenClawCommandApi): void;
