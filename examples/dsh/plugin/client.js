/**
 * clawock-dsh browser bundle: the Decision Studio conversation-view tab.
 *
 * Shape contract (dsh-client-modules): the file registers one lazy CJS
 * factory through `window.__ModuleLoader__.load({ id, factory })`; the
 * factory's `require` resolves externals from the web shell's module graph
 * (`@deepseek-ai/dsh-client-runtime/client`, `react`). This file is the
 * shipped artifact — hand-authored, no build step. The model builder is
 * exported as a test seam (`_buildStudioModel`).
 */
window.__ModuleLoader__.load({
  id: 'clawock-dsh',
  factory: (require) => {
    var module = { exports: {} }
    var exports = module.exports
    var clientRuntime = require('@deepseek-ai/dsh-client-runtime/client')
    var React = require('react')
    var useEffect = React.useEffect
    var useState = React.useState
    var h = React.createElement

    /** Pure projection of one run's files into what the tab renders. */
    function _buildStudioModel(run) {
      if (run === null || run.request === null) {
        return { empty: true, subject: null, gates: null, decision: null, receipt: null }
      }
      var request = run.request
      var decision = run.decision
      var manifest = run.manifest
      return {
        empty: false,
        runId: run.runId,
        subject: request.subject ?? (decision && decision.subject) ?? null,
        asOf: request.as_of ?? null,
        task: request.task ?? null,
        workflow: request.workflow ?? null,
        gates: (request.workflow && request.workflow.parameters) ?? null,
        documents: (request.context && request.context.documents) ?? [],
        evidence: (decision && decision.evidence) ?? [],
        debate: (decision && decision.debate) ?? null,
        thesis: (decision && decision.thesis) ?? null,
        action: decision ? decision.decision : null,
        receiptStatus: manifest ? 'published' : null,
        generationId: manifest ? manifest.generation_id : null,
      }
    }

    var CARD = { margin: '12px 0', padding: '14px 16px', border: '1px solid #243048', borderRadius: '12px', background: '#161d2e' }
    var GREEN = '#2ecc71'
    var RED = '#e74c3c'
    var MUTED = '#8a94a8'

    function Row(props) {
      return h('div', { style: { margin: '4px 0', color: props.muted ? MUTED : '#e8edf5', fontSize: 13 } }, props.label ? h('span', { style: { color: MUTED, marginRight: 8 } }, props.label) : null, props.value)
    }

    function GateRow(props) {
      return h('div', { style: { display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid #1d2740' } },
        h('span', { style: { color: MUTED, fontSize: 13 } }, props.name),
        h('span', { style: { fontSize: 13 } }, String(props.value)))
    }

    function EvidenceRow(props) {
      var color = props.stance === 'opposing' ? RED : GREEN
      return h('div', { style: { padding: '6px 0', borderBottom: '1px solid #1d2740' } },
        h('div', {}, h('span', { style: { color: color, fontWeight: 700, marginRight: 8 } }, props.stance),
          h('span', { style: { fontSize: 13 } }, props.summary)),
        h('div', { style: { color: MUTED, fontSize: 12 } }, props.source + ' · ' + props.sourceClass + ' · ' + props.observedAt))
    }

    function ReceiptBanner(props) {
      var published = props.status === 'published'
      return h('div', { style: { marginTop: 12, padding: '10px 14px', borderRadius: 10, border: '1px solid ' + (published ? GREEN : RED), background: published ? '#10241a' : '#241010' } },
        h('span', { style: { color: published ? GREEN : RED, fontWeight: 800, marginRight: 10 } }, published ? 'PUBLISHED' : 'REJECTED'),
        h('span', { style: { fontSize: 12, color: MUTED } }, 'run_id ' + props.runId + (props.generationId ? ' · generation ' + props.generationId : ' · no receipt yet')))
    }

    /** The conversation.view tab: run list + selected run detail. */
    function DecisionStudio(props) {
      var pair = useState({ runs: [], selected: null, detail: null, loading: true, error: null })
      var state = pair[0]
      var setState = pair[1]
      var sessionId = props.sessionId
      useEffect(function () {
        var alive = true
        setState(function (current) { return Object.assign({}, current, { loading: true, error: null }) })
        props.list().then(function (result) {
          if (!alive) return
          setState(function (current) { return Object.assign({}, current, { runs: result.runs, loading: false }) })
        }, function (error) {
          if (!alive) return
          setState(function (current) { return Object.assign({}, current, { error: String(error && error.message ? error.message : error), loading: false }) })
        })
        return function () { alive = false }
      }, [sessionId])

      // Full detail is fetched per selection: list rows are cheap snapshots,
      // the request/decision/receipt payloads live in the node half.
      useEffect(function () {
        var selected = state.selected
        if (!selected) {
          setState(function (current) { return Object.assign({}, current, { detail: null }) })
          return
        }
        var alive = true
        setState(function (current) { return Object.assign({}, current, { detail: null }) })
        props.get(selected).then(function (detail) {
          if (!alive) return
          setState(function (current) { return Object.assign({}, current, { detail: detail }) })
        }, function (error) {
          if (!alive) return
          setState(function (current) { return Object.assign({}, current, { detail: null, error: String(error && error.message ? error.message : error) }) })
        })
        return function () { alive = false }
      }, [state.selected])

      var loading = state.loading
      var error = state.error
      var runs = state.runs
      var selectedId = state.selected
      var detail = state.detail

      if (error) return h('div', { style: CARD }, h('span', { style: { color: RED } }, 'Decision Studio: ' + error))
      if (loading) return h('div', { style: CARD }, 'Loading clawock runs…')

      var detailView = null
      if (detail) {
        var model = _buildStudioModel(detail)
        if (!model.empty) {
          detailView = h('div', { style: CARD },
            h('div', { style: { fontSize: 14, fontWeight: 700, marginBottom: 8 } },
              model.subject ? model.subject.ticker + ' (' + model.subject.market + '/' + model.subject.currency + ')' : 'unknown subject'),
            h(Row, { label: 'run_id', value: model.runId, muted: true }),
            h(Row, { label: 'as_of', value: model.asOf || '—' }),
            h('div', { style: { marginTop: 8 } },
              h('div', { style: { color: MUTED, fontSize: 12, letterSpacing: '0.08em' } }, 'GATES'),
              (model.gates ? Object.keys(model.gates).map(function (key) {
                return h(GateRow, { key: key, name: key, value: model.gates[key] })
              }) : null)),
            h('div', { style: { marginTop: 10 } },
              h('div', { style: { color: MUTED, fontSize: 12, letterSpacing: '0.08em' } }, 'DEBATE'),
              (model.evidence || []).map(function (row) {
                return h(EvidenceRow, { key: row.id, stance: row.stance, summary: row.summary, source: row.source, sourceClass: row.source_class, observedAt: row.observed_at })
              })),
            h('div', { style: { marginTop: 10 } },
              h('div', { style: { color: MUTED, fontSize: 12, letterSpacing: '0.08em' } }, 'THESIS'),
              h(Row, { value: model.thesis ? model.thesis.statement : '—' }),
              model.action ? h(Row, { label: 'action', value: model.action.action + ' · confidence ' + (model.thesis ? model.thesis.confidence : '—') }) : null),
            h(ReceiptBanner, { status: model.receiptStatus || 'rejected', runId: model.runId, generationId: model.generationId }))
        }
      }

      return h('div', { style: { padding: 4 } },
        h('div', { style: { color: MUTED, fontSize: 12, marginBottom: 6 } }, 'clawock runs in this workspace (' + runs.length + ')'),
        runs.map(function (run) {
          var ticker = (run.subject && run.subject.ticker) || (run.decisionSubject && run.decisionSubject.ticker) || run.runId
          var status = run.receiptPresent ? 'published' : 'no receipt'
          var label = ticker + ' · ' + status + (run.decisionPresent ? ' · decision' : '')
          return h('button', {
            key: run.runId,
            onClick: function () { setState(function (current) { return Object.assign({}, current, { selected: run.runId }) }) },
            style: {
              display: 'block', width: '100%', textAlign: 'left', margin: '4px 0', padding: '8px 10px',
              border: '1px solid ' + (run.runId === selectedId ? GREEN : '#243048'),
              borderRadius: 8, background: run.runId === selectedId ? '#1b2a45' : '#161d2e', color: '#e8edf5', cursor: 'pointer', fontSize: 13,
            },
          }, label, '  ', h('span', { style: { color: MUTED } }, run.asOf || ''))
        }),
        detailView)
    }

    /** Minimal strict codecs (no zod external in the module table). */
    var passthroughSchema = { parse: function (value) { return value } }
    var stringSchema = {
      parse: function (value) {
        if (typeof value !== 'string') throw new Error('expected a string')
        return value
      },
    }

    /** Client projection of the clawockStudio Remote face, mounted explicitly. */
    var TYPERT_REMOTE = {
      package: 'clawock-dsh',
      descriptors: [{
        id: 'clawock-dsh#clawockStudio/list',
        service: 'clawockStudio',
        namespace: 'clawockStudio',
        method: 'list',
        invocation: { kind: 'direct' },
        parameters: [],
        result: {
          mode: 'strict',
          typeSymbol: 'clawock-dsh#clawockStudio/list:result',
          schema: passthroughSchema,
        },
      }, {
        id: 'clawock-dsh#clawockStudio/get',
        service: 'clawockStudio',
        namespace: 'clawockStudio',
        method: 'get',
        invocation: { kind: 'direct' },
        parameters: [{
          name: 'runId',
          wire: 'runId',
          source: 'json',
          codec: {
            mode: 'strict',
            typeSymbol: 'clawock-dsh#clawockStudio/get:runId',
            schema: stringSchema,
          },
        }],
        result: {
          mode: 'strict',
          typeSymbol: 'clawock-dsh#clawockStudio/get:result',
          schema: passthroughSchema,
        },
      }],
    }

    /** Services required by the registration and the mounted Remote face. */
    var inject = ['slots', 'remote']

    /** Register the Decision Studio tab into the conversation view ring. */
    async function apply(ctx) {
      await ctx.remote.$mount(TYPERT_REMOTE)
      var studioRemote = ctx.get('remote.clawockStudio')
      ctx.slots.inject('conversation.view', function () {
        return ctx.slots.register({
          name: 'conversation.view',
          id: 'decision-studio',
          order: 30,
          label: function () { return 'Decision Studio' },
          inject: function () {
            var call = async function (method, args) {
              var result = await studioRemote[method].apply(studioRemote, args)
              if (!result.ok) {
                throw new Error('clawockStudio.' + method + ' failed: ' + result.error.code + ': ' + result.error.message)
              }
              return result.value
            }
            return {
              list: function () { return call('list', []) },
              get: function (runId) { return call('get', [runId]) },
            }
          },
        }, DecisionStudio)
      })
    }

    module.exports = { apply: apply, inject: inject, _buildStudioModel: _buildStudioModel }
    return module.exports
  },
})
