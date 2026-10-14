const text = value => typeof value === 'string' && value.trim() ? value : null;
const list = value => Array.isArray(value) ? value : [];
const sentence = words => words.charAt(0).toUpperCase() + words.slice(1).replace(/[.!?]?$/, match => match || '.');

/** A base tick is an input, never evidence that the next minute was consumed. */
export function decisionSummaryWords(summary, reasonWords = {}) {
  if (!summary) return 'No model decision is recorded.';
  const reason = sentence(reasonWords[summary.dispositionReason || summary.reason] || 'No plain-language reason is available.');
  if (summary.disposition === 'applied') return `Applied at minute ${summary.consumedTick}: ${summary.chose || 'the recorded choice'}.`;
  const input = `Based on minute ${summary.baseTick}.`;
  if (summary.status === 'accepted' && !summary.disposition) return `${input} Accepted; application has not been recorded.`;
  return `${input} ${summary.status === 'accepted' ? 'Not applied. ' : ''}${reason}${summary.consumedTick === null ? ' No world action was applied from this answer.' : ''}`;
}

/** Explain stored facts without inventing intent or treating validation as application. */
export function explainDecision(data, summary, { actionWords = {}, reasonWords = {} } = {}) {
  const context = data.request.context || {}, receipt = data.decision;
  if (summary && summary.requestId !== data.request.request_id) throw Error('The decision summary changed.');
  const reason = code => sentence(reasonWords[code] || (code ? `Reason recorded as ${code}.` : 'No reason was recorded.'));
  const options = list(context.options).filter(option => text(option.label));
  const chosen = text(receipt?.proposal?.label);
  const status = receipt?.status;
  const disposition = summary?.disposition;
  const result = !receipt ? 'Awaiting a recorded answer.'
    : status !== 'accepted' ? `Not accepted. ${reason(receipt.reason)}`
    : disposition === 'applied' ? 'Applied by the world.'
    : disposition ? `Not applied. ${reason(summary.dispositionReason || summary.reason)}`
    : 'Accepted; application has not been recorded in this read.';
  const inputs = [];
  if (Number.isInteger(context.tick)) inputs.push(`World minute ${context.tick}.`);
  if (text(context.being?.summary)) inputs.push(context.being.summary);
  if (text(context.doing?.kind)) inputs.push(`Activity: ${actionWords[context.doing.kind] || context.doing.kind}.`);
  if (context.under_way === true) inputs.push('An action was already underway.');
  if (Number.isFinite(context.need_milli)) inputs.push(`Recorded tiredness: ${context.need_milli} of 1000${Number.isFinite(context.rest_at_need_milli) ? `; routine rest threshold ${context.rest_at_need_milli}` : ''}.`);
  if (text(context.last_activity)) inputs.push(`Last place used: ${context.last_activity}.`);
  if (Array.isArray(context.holding)) inputs.push(context.holding.length ? `Holding: ${context.holding.join(', ')}.` : 'Holding nothing.');
  const surroundings = context.surroundings;
  if (text(surroundings?.at?.words)) inputs.push(`At: ${surroundings.at.words}.`);
  for (const being of list(surroundings?.beings)) {
    if (!text(being.who)) continue;
    inputs.push([being.who, Number.isFinite(being.metres) ? `${being.metres} m away` : null,
      text(being.doing), being.hears_you === true ? 'can hear this character' : null,
      list(being.holding).length ? `holding ${being.holding.join(', ')}` : null].filter(Boolean).join('; ') + '.');
  }
  for (const thing of list(surroundings?.things)) {
    if (text(thing.what)) inputs.push([thing.what, Number.isFinite(thing.metres) ? `${thing.metres} m away` : null,
      ...list(thing.good_for)].filter(Boolean).join('; ') + '.');
  }
  if (surroundings?.more_beings > 0 || surroundings?.more_things > 0) inputs.push('Additional surroundings were outside this input’s detail limit.');
  for (const line of list(context.heard)) if (text(line.line)) inputs.push(`Heard ${text(line.from) ? `from ${line.from}` : ''}${Number.isFinite(line.minutes_ago) ? ` ${line.minutes_ago} minutes ago` : ''}: “${line.line}”`);
  for (const line of list(context.said)) if (text(line.line)) inputs.push(`Previously said${Number.isFinite(line.minutes_ago) ? ` ${line.minutes_ago} minutes ago` : ''}: “${line.line}”`);
  const remembered = context.remembers;
  if (remembered) {
    const count = ['beings', 'places', 'handed'].reduce((sum, key) => sum + list(remembered[key]).length, 0);
    inputs.push(count === 1 ? '1 memory entry was also included; inspect the recorded inputs for its complete contents.'
      : count ? `${count} memory entries were also included; inspect the recorded inputs for their complete contents.` : 'No memory entries were included.');
  }
  const limitations = [];
  if (options.length && options.every(option => option.kind === 'wait' || option.kind === 'carry_on')) limitations.push('The recorded options offered only waiting or continuing the current action.');
  else if (options.length && !options.some(option => option.kind === 'target')) limitations.push('No destination was offered in this decision. Other offered actions may still cause movement.');
  if (chosen && receipt?.proposal?.option?.kind === 'wait') limitations.push('Waiting was the recorded choice. This record does not explain the model’s private reasoning.');
  const provider = receipt?.provider;
  return { chosen, result, inputs, options, limitations, line: text(receipt?.proposal?.line),
    servedModel: text(provider?.served_model_id), latencyMs: Number.isFinite(provider?.latency_ms) ? provider.latency_ms : null,
    calls: Array.isArray(provider?.calls) ? provider.calls.length : null,
    cost: text(provider?.cost_usd), costKnown: provider?.cost_known === true };
}
