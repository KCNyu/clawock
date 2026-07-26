const result = await tools.call('exec', {
  command: 'python3 /root/.openclaw/workspace/scripts/data/intraday_delta_gate.py --market us'
});
const raw = String(result?.result?.details?.aggregated ?? result?.result?.stdout ?? '');
let snap;
try {
  snap = JSON.parse(raw.trim());
} catch {
  json({ fire: true, message: 'Delta gate failed open: invalid snapshot.', state: trigger.state });
  exit();
}
const prev = trigger.state ?? {};
const priorPrices = prev.prices ?? {};
const materiallyRepriced = Object.entries(snap.prices ?? {}).some(([ticker, row]) => {
  const old = priorPrices[ticker];
  if (!old || !old.price) return true;
  return Math.abs(row.price / old.price - 1) >= 0.01 ||
    Math.abs((row.pct_1d ?? 0) - (old.pct_1d ?? 0)) >= 1.0;
});
const evaluations = (prev.evaluationsSinceReasoning ?? 0) + 1;
const conditionChanged = prev.conditionHash !== snap.condition_hash;
const forced = !prev.conditionHash || prev.session !== snap.session || evaluations >= 6;
const fire = !snap.market_closed &&
  Boolean(snap.error || conditionChanged || materiallyRepriced || forced);
const reasons = [
  snap.error ? `gate_error:${snap.error}` : '',
  conditionChanged ? 'condition_delta' : '',
  materiallyRepriced ? 'material_reprice' : '',
  forced ? 'scheduled_forced_review' : ''
].filter(Boolean);
if (!fire) {
  const state = snap.market_closed ? 'market_closed' : 'no_change';
  await tools.call('exec', {
    command: `python3 /root/.openclaw/workspace/scripts/data/intraday_delta_gate.py --market us --record ${state} --slot ${snap.slot} --reason unchanged --state-hash ${snap.condition_hash}`
  });
}
json({
  fire,
  message: fire ? `Intraday delta trigger: ${reasons.join(', ')}. Snapshot slot=${snap.slot}.` : undefined,
  state: {
    conditionHash: snap.condition_hash,
    prices: snap.prices,
    session: snap.session,
    lastSlot: snap.slot,
    evaluationsSinceReasoning: fire ? 0 : evaluations
  }
});
