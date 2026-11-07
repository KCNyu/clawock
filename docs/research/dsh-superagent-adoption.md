# Dispatch design provenance: `dsh-superagent-prototype`

The public DeepSeek Harness research prototype
[`deepseek-ai/dsh-superagent-prototype`](https://github.com/deepseek-ai/dsh-superagent-prototype/tree/6337fc8)
(TypeScript, MIT; inspected revision `6337fc8`) supplied two useful concepts:
an explicit mandate and a stage determined by what a task waits for.
The operational contract lives in [task-queue.md](../architecture/task-queue.md),
not in this research note. Initial implementation and historical validation are
in [#3231](https://github.com/KCNyu/clawock/pull/3231); the notification policy
correction is in [#3237](https://github.com/KCNyu/clawock/pull/3237).

## Adopted concepts and owners

| Concept | Local owner | Boundary it preserves |
|---|---|---|
| Immutable mandate: why work is authorized, scope, policy version and permitted actions | `ops/host/agent-dispatch/mandate.py`, created by `dispatch.sh`; [Mandate](../architecture/task-queue.md#mandate) | Natural-language briefs alone do not enforce restart restrictions. The refresh/restart wrappers check the machine-readable mandate and record denials. This is a wrapper guard, not a root-process sandbox. |
| Structured stage and person-action field | `run-agent.sh` classification; `task_queue_ops.py` summary; [runner fields](../architecture/task-queue.md#runner-fields-the-chip-reads) | `NEEDS` describes an action, not a reason to suppress delivery. Missing model output remains unknown rather than inferred from prose. |
| Completion notices independent of attention | `run-agent.sh` finish; [notifications](../architecture/task-queue.md#notifications) | A clean `DONE` still notifies and wakes the origin unless `--notify none`; cancellation sends its notice without a wake turn. The prototype's attention-based silence policy was not retained. |

The relevant prototype sources are `src/core/model.ts`, `src/core/stage.ts`,
`src/policy.ts` and `src/executor/dsh.ts`, with authorization and execution rationale
in `docs/002-authorization.md` and `docs/003-execution.md`. They explain provenance;
current local fields, flags and stage ordering must be read from the local owner.

## Deliberately not adopted

| Prototype mechanism | Reason / existing owner |
|---|---|
| A second web panel | The dsh task chip and `/dispatch-list` already expose this queue. Another panel adds a reader obligation without a new consumer. |
| General Source/Thread/Trigger/Correlation router | Dispatch and scheduling already have explicit owners. A generalized event layer has no second implementation here. |
| Candidate acceptance assessment and `off`/`observe`/`auto` modes | Dispatch is already an explicit accept by a person or named automated caller. Patrol's filing gate is a separate owner; this research does not authorize automatic acceptance. |
| Per-ticket executor directories, worker slots and deployment DB | systemd task units, `task_queue_ops.py`, agent locks, installers and `limits.env` already supply that lifecycle. |
| Versioned prompt override store and panel | The executable dispatch contract and repository/host guidance own instructions. The mandate records the policy version; another store would duplicate ownership. |
| Context subscription as authority | Appended materials do not widen a mandate's allowed actions. Scope expansion needs explicit authorization; no automatic scope-language revalidation is implemented. |
| Executor-level auto-merge policy | Repository `AGENTS.md` and required CI own merge permission. |
| Prototype model routing assumptions | It has no quota layer equivalent to this host's quota handling and model chains. Its executor shape cannot replace those controls. |

Keep these distinctions when considering future adoption. A prototype feature list
is not evidence that this desk needs another management layer. Check current code
and tests for implementation state; historical command transcripts and superseded
notification behavior belong with the linked PRs.
