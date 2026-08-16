/**
 * Read-only Typert Remote gateway over a clawock workspace, powering the
 * Decision Studio conversation-view tab in the DSH web GUI.
 *
 * This is a Cordis service plugin: default-export the service class; the
 * profile patch layer inserts one row (`clawock-studio`). The workspace root
 * is `$CLAWOCK_WORKSPACE` when set, otherwise the dsh process cwd.
 */

import { TypertRemoteService, Remote } from '@deepseek-ai/dsh-typert-protocol'
import { listRuns, getRun } from './scan.js'
import { readLedger, readPortfolio, readPlans, readTraces } from './ledger.js'

const workspaceOf = () => process.env.CLAWOCK_WORKSPACE || process.cwd()

/**
 * Standard-method-decorator markers, applied by hand: plain ESM cannot carry
 * `@Remote` decorator syntax without a build step, so we drive the exported
 * decorator factory with a fabricated decorator context. The initializer it
 * schedules is a normal function we run with `this` bound to a live instance
 * after construction; `mark()` keys the private marker table by the instance
 * prototype, exactly as the engine-driven path does.
 */
function markRemote(serviceClass, methodName, exportName) {
  const initializers = []
  const context = {
    kind: 'method',
    name: methodName,
    static: false,
    private: false,
    access: { get: () => serviceClass.prototype[methodName] },
    addInitializer(fn) {
      initializers.push(fn)
    },
  }
  Remote(exportName)(serviceClass.prototype[methodName], context)
  serviceClass.prototype.__clawockRemoteInitializers =
    (serviceClass.prototype.__clawockRemoteInitializers ?? []).concat(initializers)
}

/** Read-only gateway: list prepared runs and fetch one run's full detail. */
export class ClawockStudioGateway extends TypertRemoteService {
  static inject = []

  constructor(ctx) {
    super(ctx, 'clawockStudio')
    for (const initializer of this.__clawockRemoteInitializers) {
      initializer.call(this)
    }
  }

  /** @returns Prepared runs (newest first), with decision/receipt presence flags. */
  list() {
    return { runs: listRuns(workspaceOf()) }
  }

  /**
   * Full detail of one run.
   * @param runId - 32-hex run id; anything else is rejected before any path use.
   * @returns Certified request, current decision artifact and receipt manifest (null when absent).
   */
  get(runId) {
    return getRun(workspaceOf(), runId)
  }

  /** @returns The shared decision ledger (memory/decisions.jsonl), file order. */
  ledger() {
    return readLedger(workspaceOf())
  }

  /** @returns Portfolio summary per book, with the desk's money fields. */
  portfolio() {
    return readPortfolio(workspaceOf())
  }

  /** @returns Recent daily plans, newest first. */
  plans() {
    return readPlans(workspaceOf())
  }

  /**
   * The decision-trace view: real fills as the spine with soft-paired
   * decisions (±3 days) and T+1 verdicts. This is the plugin's single
   * organic view — the dashboard card renders the same contract.
   * @returns `{ trades, rate, rateSource, lastUpdated }`.
   */
  traces() {
    return readTraces(workspaceOf())
  }
}

markRemote(ClawockStudioGateway, 'list', 'list')
markRemote(ClawockStudioGateway, 'get', 'get')
markRemote(ClawockStudioGateway, 'ledger', 'ledger')
markRemote(ClawockStudioGateway, 'portfolio', 'portfolio')
markRemote(ClawockStudioGateway, 'plans', 'plans')
markRemote(ClawockStudioGateway, 'traces', 'traces')

export default ClawockStudioGateway
