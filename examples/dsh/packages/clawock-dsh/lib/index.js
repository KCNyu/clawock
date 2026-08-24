import { createBalanceService, createClaudeService, createMinimaxService } from "./balance.js";
import { getRun, listRuns } from "./scan.js";
import { readLedger, readPlans, readPortfolio, readTraces } from "./ledger.js";
import { createTraceCache, workspaceKeyOf, workspaceSignature } from "./freshness.js";
import { Remote, TypertRemoteService } from "@deepseek-ai/dsh-typert-protocol";
//#region src/index.ts
/**
* Read-only Typert Remote gateway over a clawock workspace, powering the
* Decision Mind conversation-view tab in the DSH web GUI.
*
* Official Cordis service plugin: `apply` registers the service through
* `ctx.plugin` (the profile patch layer inserts the plugin row), `@Remote`
* decorators mark the Remote face, and the Typert generator emits the Host
* reflection + client Remote contribution at build time. The workspace root
* is `$CLAWOCK_WORKSPACE` when set, otherwise the dsh process cwd.
*/
var __runInitializers = function(thisArg, initializers, value) {
	var useValue = arguments.length > 2;
	for (var i = 0; i < initializers.length; i++) value = useValue ? initializers[i].call(thisArg, value) : initializers[i].call(thisArg);
	return useValue ? value : void 0;
};
var __esDecorate = function(ctor, descriptorIn, decorators, contextIn, initializers, extraInitializers) {
	function accept(f) {
		if (f !== void 0 && typeof f !== "function") throw new TypeError("Function expected");
		return f;
	}
	var kind = contextIn.kind, key = kind === "getter" ? "get" : kind === "setter" ? "set" : "value";
	var target = !descriptorIn && ctor ? contextIn["static"] ? ctor : ctor.prototype : null;
	var descriptor = descriptorIn || (target ? Object.getOwnPropertyDescriptor(target, contextIn.name) : {});
	var _, done = false;
	for (var i = decorators.length - 1; i >= 0; i--) {
		var context = {};
		for (var p in contextIn) context[p] = p === "access" ? {} : contextIn[p];
		for (var p in contextIn.access) context.access[p] = contextIn.access[p];
		context.addInitializer = function(f) {
			if (done) throw new TypeError("Cannot add initializers after decoration has completed");
			extraInitializers.push(accept(f || null));
		};
		var result = (0, decorators[i])(kind === "accessor" ? {
			get: descriptor.get,
			set: descriptor.set
		} : descriptor[key], context);
		if (kind === "accessor") {
			if (result === void 0) continue;
			if (result === null || typeof result !== "object") throw new TypeError("Object expected");
			if (_ = accept(result.get)) descriptor.get = _;
			if (_ = accept(result.set)) descriptor.set = _;
			if (_ = accept(result.init)) initializers.unshift(_);
		} else if (_ = accept(result)) {
			if (kind === "field") initializers.unshift(_);
			else descriptor[key] = _;
		}
	}
	if (target) Object.defineProperty(target, contextIn.name, descriptor);
	done = true;
};
const workspaceOf = () => process.env.CLAWOCK_WORKSPACE || process.cwd();
/**
* The row config apply() hands to the next gateway instance. Module-level
* on purpose and safe: apply() assigns it synchronously before ctx.plugin
* constructs the service, and the balance method reads it lazily on first
* use — a plugin reload therefore gets its own value and nothing serves
* config past its lifetime.
*/
let pendingConfig = {};
let ClawockStudioGateway = (() => {
	let _classSuper = TypertRemoteService;
	let _instanceExtraInitializers = [];
	let _list_decorators;
	let _get_decorators;
	let _ledger_decorators;
	let _portfolio_decorators;
	let _plans_decorators;
	let _traces_decorators;
	let _balance_decorators;
	return class ClawockStudioGateway extends _classSuper {
		static {
			const _metadata = typeof Symbol === "function" && Symbol.metadata ? Object.create(_classSuper[Symbol.metadata] ?? null) : void 0;
			_list_decorators = [Remote];
			_get_decorators = [Remote];
			_ledger_decorators = [Remote];
			_portfolio_decorators = [Remote];
			_plans_decorators = [Remote];
			_traces_decorators = [Remote];
			_balance_decorators = [Remote];
			__esDecorate(this, null, _list_decorators, {
				kind: "method",
				name: "list",
				static: false,
				private: false,
				access: {
					has: (obj) => "list" in obj,
					get: (obj) => obj.list
				},
				metadata: _metadata
			}, null, _instanceExtraInitializers);
			__esDecorate(this, null, _get_decorators, {
				kind: "method",
				name: "get",
				static: false,
				private: false,
				access: {
					has: (obj) => "get" in obj,
					get: (obj) => obj.get
				},
				metadata: _metadata
			}, null, _instanceExtraInitializers);
			__esDecorate(this, null, _ledger_decorators, {
				kind: "method",
				name: "ledger",
				static: false,
				private: false,
				access: {
					has: (obj) => "ledger" in obj,
					get: (obj) => obj.ledger
				},
				metadata: _metadata
			}, null, _instanceExtraInitializers);
			__esDecorate(this, null, _portfolio_decorators, {
				kind: "method",
				name: "portfolio",
				static: false,
				private: false,
				access: {
					has: (obj) => "portfolio" in obj,
					get: (obj) => obj.portfolio
				},
				metadata: _metadata
			}, null, _instanceExtraInitializers);
			__esDecorate(this, null, _plans_decorators, {
				kind: "method",
				name: "plans",
				static: false,
				private: false,
				access: {
					has: (obj) => "plans" in obj,
					get: (obj) => obj.plans
				},
				metadata: _metadata
			}, null, _instanceExtraInitializers);
			__esDecorate(this, null, _traces_decorators, {
				kind: "method",
				name: "traces",
				static: false,
				private: false,
				access: {
					has: (obj) => "traces" in obj,
					get: (obj) => obj.traces
				},
				metadata: _metadata
			}, null, _instanceExtraInitializers);
			__esDecorate(this, null, _balance_decorators, {
				kind: "method",
				name: "balance",
				static: false,
				private: false,
				access: {
					has: (obj) => "balance" in obj,
					get: (obj) => obj.balance
				},
				metadata: _metadata
			}, null, _instanceExtraInitializers);
			if (_metadata) Object.defineProperty(this, Symbol.metadata, {
				enumerable: true,
				configurable: true,
				writable: true,
				value: _metadata
			});
		}
		static inject = ["credentials"];
		/**
		* cordis mixes the injected services onto the instance at construction;
		* this type-only declaration types `this.credentials` without a cast,
		* and `declare` fields emit nothing at runtime.
		*/
		/**
		* Signature-keyed trace cache per workspace (see freshness.ts). Owned by the
		* service instance rather than module scope: a module-level cache would
		* outlive plugin stop/update (the module stays in the process cache), so a
		* stopped plugin could keep serving a stale enriched view through a new
		* instance. Instance lifetime follows the fiber; a hit still costs µs.
		*/
		tracesCache = (__runInitializers(this, _instanceExtraInitializers), createTraceCache());
		/**
		* Per-provider balance services, built lazily on first use — instance-scoped
		* like tracesCache, and constructed here rather than in the constructor so
		* the gateway constructor keeps the exact super(ctx, serviceKey) shape.
		*/
		balanceServices = null;
		constructor(ctx, config = {}) {
			super(ctx, "clawockStudio");
		}
		/** @returns Prepared runs (newest first), with decision/receipt presence flags. */
		list() {
			return { runs: listRuns(workspaceOf()) };
		}
		/**
		* Full detail of one run.
		* @param runId - 32-hex run id; anything else is rejected before any path use.
		* @returns Certified request, current decision artifact and receipt manifest (null when absent).
		*/
		get(runId) {
			return getRun(workspaceOf(), runId);
		}
		/** @returns The shared decision ledger (memory/decisions.jsonl), file order. */
		ledger() {
			return readLedger(workspaceOf());
		}
		/** @returns Portfolio summary per book, with the desk's money fields. */
		portfolio() {
			return readPortfolio(workspaceOf());
		}
		/** @returns Recent daily plans, newest first. */
		plans() {
			return readPlans(workspaceOf());
		}
		/**
		* The decision-trace view: real fills as the spine with soft-paired
		* decisions (±3 days) and T+1 verdicts. Cached by workspace-freshness
		* signature — the enriched result is rebuilt only when portfolio.json /
		* snapshots / decisions.jsonl actually changed; a hit returns in µs.
		* Every result carries `workspaceKey` (opaque hash) and `signature` so the
		* client can cache across tab mounts and re-fetch only on a real change.
		*/
		traces() {
			const ws = workspaceOf();
			const signature = workspaceSignature(ws);
			const hit = this.tracesCache.get(ws, signature);
			if (hit !== void 0) return hit;
			const value = {
				workspaceKey: workspaceKeyOf(ws),
				signature,
				...readTraces(ws)
			};
			this.tracesCache.set(ws, signature, value);
			return value;
		}
		/**
		* The header chip's answer: every provider's official endpoint, each
		* answered with that adapter's own key. In-band by design — never throws;
		* per-provider statuses 'no-key' / 'failed' / 'stale' carry a Chinese
		* message and a stale read keeps the last good snapshot. A provider with
		* no key configured is an honest row, not a hidden one.
		* @param force - bypass the TTL caches (the manual refresh button).
		*/
		async balance(force) {
			if (this.balanceServices === null) this.balanceServices = {
				deepseek: createBalanceService({ credentials: credentialsOf(this.ctx) }, {
					baseUrl: pendingConfig.balanceBaseUrl,
					threshold: pendingConfig.balanceThreshold,
					refreshMs: pendingConfig.balanceRefreshMs
				}),
				minimax: createMinimaxService({ credentials: credentialsOf(this.ctx) }, {
					baseUrl: pendingConfig.minimaxBaseUrl,
					keyRef: pendingConfig.minimaxKeyRef,
					lowPct: pendingConfig.minimaxLowPct,
					openclawConfigPath: pendingConfig.minimaxOpenclawConfigPath
				}),
				claude: createClaudeService({ credentials: credentialsOf(this.ctx) }, {
					credentialsPath: pendingConfig.claudeCredentialsPath,
					usageUrl: pendingConfig.claudeUsageUrl,
					lowPct: pendingConfig.claudeLowPct
				})
			};
			const [deepseek, minimax, claude] = await Promise.all([
				this.balanceServices.deepseek.get(force),
				this.balanceServices.minimax.get(force),
				this.balanceServices.claude.get(force)
			]);
			return {
				providers: [
					{
						provider: "deepseek",
						label: "DeepSeek",
						result: deepseek
					},
					{
						provider: "minimax",
						label: "MiniMax",
						result: minimax
					},
					{
						provider: "claude",
						label: "Claude",
						result: claude
					}
				],
				refreshMs: Math.min(deepseek.refreshMs, minimax.refreshMs, claude.refreshMs)
			};
		}
	};
})();
/**
* Services the profile mixes into this plugin's context (the function-
* plugin form — the class's `static inject` is its type mirror). The
* gateway reaches the credential seam through `this.ctx.credentials`.
*/
const inject = ["credentials"];
/**
* Typed access to the injected credentials seam. Deliberately a cast, not
* an import of @deepseek-ai/dsh-credentials: that package's cordis
* augmentation would register this package in the typert host face and
* fail the Remote-artifacts gate (see balance.ts).
*/
function credentialsOf(ctx) {
	return ctx.credentials;
}
const name = "clawock-dsh";
function apply(ctx, config = {}) {
	pendingConfig = config;
	ctx.plugin(ClawockStudioGateway, config);
}
//#endregion
export { ClawockStudioGateway, apply, inject, name };
