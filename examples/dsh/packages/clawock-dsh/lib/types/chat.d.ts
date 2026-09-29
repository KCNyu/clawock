import { type Translate } from './copy.ts';
import { type PanelInput } from './panel.ts';
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
export default function register(api: OpenClawCommandApi): void;
