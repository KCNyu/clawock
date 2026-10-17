import { type Translate } from './copy.ts';
import { type PanelInput } from './panel.ts';
import { formatWeixinTables, type WeixinTableMode } from './weixin-tables.ts';
/** Test seam: the hook is three lines, the layout itself lives in src/weixin-tables.ts. */
export { formatWeixinTables };
/** What OpenClaw hands a `message_sending` handler (the fields this entry reads). */
export interface MessageSendingEvent {
    content: string;
    to?: string;
    metadata?: Record<string, unknown>;
}
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
    on?(name: 'message_sending', handler: (event: MessageSendingEvent) => {
        content?: string;
    } | void): void;
}
/** `weixinTables` accepts the three modes (or a `{ mode }` object) and falls back to `auto`. */
export declare function weixinTableMode(value: unknown): WeixinTableMode;
/** The reply for one read of both halves (the test seam: tests/decision_studio_plugin.spec.js compares it with the panel). */
export declare function dispatchListText(input: PanelInput, t: Translate, now: number): string;
export default function register(api: OpenClawCommandApi): void;
