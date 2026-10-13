/**
 * One recorded decision explained from its records alone: what the decider was told, what it could
 * choose, what it chose, what the engine accepted or refused and why, what a minute applied and
 * when, what changed in the world after, which model served it, how long it took and what it cost.
 *
 * The request and receipt come from `GET /world/versions/{v}/society/decisions/{request_id}`; what
 * a minute did with it comes from that minute's `decision_applied` event (or the models read's
 * latest decision where no event is read); what changed comes from the being's own movement and
 * action events after it. Every sentence states a recorded fact: a proposal is not an action, an
 * applied choice is not movement until an event records it, a timeout is not a routine decision,
 * and nothing here describes a choice as thinking or feeling.
 */

import type { PersonDecision, SocietyDecisionDetail } from '../society-models-api.js';
import { DECISION_WORDS } from '../society-inhabitant-words.js';


/** One event of the society's history, as much of it as a record reads. */
export interface DecisionEvent {
  readonly tick: number;
  readonly order: number;
  /** The event's kind: `decision_applied`, `route_progressed`, `action_completed`, `blocked`... */
  readonly kind: string;
  readonly subjectId: string | null;
  readonly outcome: string | null;
  readonly reason: string | null;
  /** For a `decision_applied` event: the request it closed, and what its minute did with it. */
  readonly requestId: string | null;
  readonly disposition: string | null;
  /** For a `decision_applied` event: the offered option's words it chose, or null. */
  readonly chose: string | null;
  /** The being's walked points in this minute, in millimetres; empty where none is recorded. */
  readonly path: readonly (readonly [number, number])[];
  /** The event as the route served it, for the record's raw view. */
  readonly raw: unknown;
}

/** One page of the events read: newest first, as the route serves it, and the key of the page before. */
export interface DecisionEventsPage {
  readonly events: readonly DecisionEvent[];
  readonly next: string | null;
}

type Held = Readonly<Record<string, unknown>>;

const held = (value: unknown): Held | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Held : null;
const words = (value: unknown): string | null => (typeof value === 'string' && value.trim() !== '' ? value : null);
const whole = (value: unknown): number | null => (Number.isSafeInteger(value) ? value as number : null);
const finite = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const items = (value: unknown): readonly unknown[] => (Array.isArray(value) ? value : []);

function point(value: unknown): readonly [number, number] | null {
  const pair = items(value);
  const x = finite(pair[0]);
  const z = finite(pair[1]);
  return pair.length >= 2 && x !== null && z !== null ? [x, z] : null;
}

/**
 * The events route's page, read leniently: an event this record cannot read is left out rather than
 * failing the record, since the record itself is read on its own route. Throws only where the page
 * is not an events page at all.
 */
export function parseDecisionEvents(value: unknown): DecisionEventsPage {
  const page = held(value);
  if (page === null || !Array.isArray(page['events'])) throw new Error('Invalid society events');
  const events: DecisionEvent[] = [];
  for (const raw of page['events']) {
    const row = held(raw);
    const document = held(row?.['document']);
    const tick = whole(row?.['tick']);
    const kind = words(row?.['event_kind']);
    if (row === null || document === null || tick === null || kind === null) continue;
    events.push({
      tick,
      order: whole(document['order']) ?? 0,
      kind,
      subjectId: words(row['subject_id']),
      outcome: words(document['outcome']),
      reason: words(document['reason']),
      requestId: words(document['request_id']),
      disposition: words(document['disposition']),
      chose: words(document['chose']),
      path: items(document['motion_path_mm']).flatMap((one) => {
        const at = point(one);
        return at === null ? [] : [at];
      }),
      raw,
    });
  }
  return { events, next: words(page['next']) };
}

export interface DecisionRecordView {
  readonly requestId: string;
  readonly subjectId: string | null;
  /** The minute whose state the decider was shown. */
  readonly askedAt: number | null;
  /** The model the world asked, by the name the models read gives it where it is the same model. */
  readonly asked: string | null;
  /** What it was told, summarised from the recorded input. */
  readonly told: readonly string[];
  readonly options: readonly { readonly label: string; readonly chosen: boolean }[];
  /** The offered option it answered with, or null where it answered none. */
  readonly chosen: string | null;
  /** A line it proposed to say, which is said only if the minute applies the choice. */
  readonly line: string | null;
  /** Whether the engine accepted the answer, and why, in a sentence. */
  readonly answer: string;
  /** What a minute did with it, in a sentence. */
  readonly applied: string;
  /** The minute that applied it, or null where none has. */
  readonly appliedAt: number | null;
  readonly changed: readonly string[];
  readonly limits: readonly string[];
  readonly servedModel: string;
  readonly responseTime: string | null;
  readonly tokens: string;
  readonly cost: string;
}

/** One decision a being's record view can open: its request and how it is listed. */
export interface KnownDecision {
  readonly requestId: string;
  /** The minute it is listed by: asked at for the latest, applied in for one an event names. */
  readonly minute: number;
  readonly words: string;
}

/** A being's recorded movement and actions after a decision, in sentences. */
export interface DecisionChange {
  readonly lines: readonly string[];
  /** Metres walked along the recorded path, by minute; empty where it did not move. */
  readonly walked: readonly { readonly minute: number; readonly metres: number }[];
}


const sentence = (text: string): string => {
  const trimmed = text.trim();
  const capital = trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
  return /[.!?]$/.test(capital) ? capital : `${capital}.`;
};

/** A reason code in the words catalog's words, or the code itself said as a code. */
const why = (code: string | null): string =>
  code === null ? 'no reason was recorded' : DECISION_WORDS[code] ?? `of a reason recorded as ${code}`;

const metres = (millimetres: number): number => Math.round(millimetres / 1000);

function pathLength(path: readonly (readonly [number, number])[]): number {
  let total = 0;
  for (let index = 1; index < path.length; index += 1) {
    const [x0, z0] = path[index - 1]!;
    const [x1, z1] = path[index]!;
    total += Math.hypot(x1 - x0, z1 - z0);
  }
  return total;
}

/** What finishing an action is called, by the event's outcome code, said of "it". */
const FINISHED: Readonly<Record<string, string>> = {
  rest_completed: 'finished resting',
  stand_completed: 'finished standing a while',
  visit_completed: 'finished visiting',
  talk_completed: 'finished talking',
  move_completed: 'finished walking',
  idle_completed: 'finished waiting',
};

/**
 * What the being's own events record from the minute that applied a decision until the next
 * decision a minute applied to it: how far it walked by minute, where it arrived, what it began and
 * finished. `activity` is the chosen option's activity, named where an action began.
 */
export function decisionChange(
  events: readonly DecisionEvent[], subjectId: string, requestId: string, appliedAt: number, activity: string | null = null,
): DecisionChange {
  const own = events
    .filter((event) => event.subjectId === subjectId && event.tick >= appliedAt)
    .sort((a, b) => a.tick - b.tick || a.order - b.order);
  const nextDecision = own.find((event) => event.kind === 'decision_applied' && event.requestId !== requestId
    && event.tick > appliedAt && event.disposition === 'applied');
  const window = own.filter((event) => nextDecision === undefined || event.tick < nextDecision.tick);
  const until = nextDecision === undefined ? 'in the minutes read since' : `until its next applied decision, in minute ${nextDecision.tick}`;
  const lines: string[] = [];
  const walked: { minute: number; metres: number }[] = [];
  let start: readonly [number, number] | null = null;
  let end: readonly [number, number] | null = null;
  for (const event of window) {
    if (event.kind !== 'route_progressed') continue;
    const length = pathLength(event.path);
    if (length <= 0) continue;
    walked.push({ minute: event.tick, metres: Math.max(1, metres(length)) });
    start ??= event.path[0]!;
    end = event.path.at(-1)!;
  }
  if (start !== null && end !== null) {
    const total = walked.reduce((sum, one) => sum + one.metres, 0);
    const parts = walked.map((one) => `${one.metres} m in minute ${one.minute}`).join(', ');
    lines.push(`Walked about ${total} m along its recorded path (${parts}), ending about ${metres(Math.hypot(end[0] - start[0], end[1] - start[1]))} m in a straight line from where it started.`);
  } else {
    lines.push(`No movement was recorded for it from minute ${appliedAt} ${until}: it stayed where it was.`);
  }
  for (const event of window) {
    if (event.kind === 'route_progressed' && event.reason === 'arrived_at_access_node') lines.push(`Arrived in minute ${event.tick}.`);
    if (event.outcome === 'action_started') {
      lines.push(`In minute ${event.tick} it began ${activity === null ? 'what it came to do' : `the chosen activity (${activity.replaceAll('_', ' ')})`}.`);
    }
    if (event.kind === 'action_completed' && event.outcome !== null) {
      lines.push(`In minute ${event.tick} it ${FINISHED[event.outcome] ?? event.outcome.replaceAll('_', ' ')}.`);
    }
  }
  if (nextDecision !== undefined && start !== null) lines.push(`Its next applied decision was in minute ${nextDecision.tick}.`);
  return { lines: dedupe(lines), walked };
}

const dedupe = (lines: readonly string[]): string[] => [...new Set(lines)];

function told(context: Held): string[] {
  const inputs: string[] = [];
  const tick = whole(context['tick']);
  if (tick !== null) inputs.push(`World minute ${tick}.`);
  const being = held(context['being']);
  const kind = words(being?.['kind']);
  const summary = words(being?.['summary']);
  if (kind !== null) inputs.push(`It was described as: ${kind}.`);
  if (summary !== null) inputs.push(sentence(summary));
  const doing = held(context['doing']);
  const doingKind = words(doing?.['kind']);
  if (doingKind !== null) inputs.push(`What it was doing: ${doingKind.replaceAll('_', ' ')}.`);
  if (context['under_way'] === true) inputs.push('An action was already under way.');
  const need = whole(context['need_milli']);
  const restAt = whole(context['rest_at_need_milli']);
  if (need !== null) inputs.push(`Tiredness ${need} of 1000${restAt === null ? '' : `; its routine rests from ${restAt}`}.`);
  const last = words(context['last_activity']);
  if (last !== null) inputs.push(`The last place it used: ${last}.`);
  if (Array.isArray(context['holding'])) {
    const holding = items(context['holding']).flatMap((one) => words(one) ?? []);
    inputs.push(holding.length === 0 ? 'Holding nothing.' : `Holding ${holding.join(', ')}.`);
  }
  const surroundings = held(context['surroundings']);
  const at = words(held(surroundings?.['at'])?.['words']);
  if (at !== null) inputs.push(`Where it was: ${at}.`);
  for (const one of items(surroundings?.['beings'])) {
    const near = held(one);
    const who = words(near?.['who']);
    if (near === null || who === null) continue;
    const metresAway = finite(near['metres']);
    inputs.push(sentence([
      who,
      metresAway === null ? null : `${metresAway} m away`,
      words(near['doing']),
      near['hears_you'] === true ? 'can hear it' : near['hears_you'] === false ? 'cannot hear it' : null,
    ].filter((part) => part !== null).join('; ')));
  }
  for (const one of items(surroundings?.['things'])) {
    const thing = held(one);
    const what = words(thing?.['what']);
    if (thing === null || what === null) continue;
    const metresAway = finite(thing['metres']);
    inputs.push(sentence([what, metresAway === null ? null : `${metresAway} m away`,
      ...items(thing['good_for']).flatMap((use) => words(use) ?? [])].filter((part) => part !== null).join('; ')));
  }
  if ((whole(surroundings?.['more_beings']) ?? 0) > 0 || (whole(surroundings?.['more_things']) ?? 0) > 0) {
    inputs.push('More of its surroundings were left out of what it was told, beyond the input\'s limit.');
  }
  for (const one of items(context['heard'])) {
    const heard = held(one);
    const line = words(heard?.['line']);
    if (heard === null || line === null) continue;
    const from = words(heard['from']);
    const ago = whole(heard['minutes_ago']);
    inputs.push(`Heard${from === null ? '' : ` from ${from}`}${ago === null ? '' : ` ${ago} minutes before`}: “${line}”`);
  }
  for (const one of items(context['said'])) {
    const said = held(one);
    const line = words(said?.['line']);
    if (said === null || line === null) continue;
    const ago = whole(said['minutes_ago']);
    inputs.push(`It had said${ago === null ? '' : ` ${ago} minutes before`}: “${line}”`);
  }
  const remembers = held(context['remembers']);
  if (remembers !== null) {
    const count = ['beings', 'places', 'handed'].reduce((sum, key) => sum + items(remembers[key]).length, 0);
    inputs.push(count === 0
      ? 'It was told no memories.'
      : `It was told ${count} remembered ${count === 1 ? 'entry' : 'entries'} from what happened here; the full input below lists them.`);
  }
  return inputs;
}

function answerWords(receipt: Held | null): string {
  if (receipt === null) return 'No answer is recorded yet.';
  const reason = words(receipt['reason']);
  switch (receipt['status']) {
    case 'accepted': return `The engine accepted the answer: ${why(reason)}.`;
    case 'rejected': return `The engine refused the answer: ${why(reason)}.`;
    case 'unavailable': return `There was no usable answer: ${why(reason)}. This is not a decision by the model or by the routine.`;
    default: return `The answer is recorded as ${String(receipt['status'])}: ${why(reason)}.`;
  }
}

function appliedWords(
  accepted: boolean, answered: boolean, consumedAt: number | null, disposition: string | null, reason: string | null,
): string {
  if (!answered) return 'Nothing has been applied: no answer is recorded yet.';
  if (consumedAt === null) {
    return accepted
      ? 'Not applied yet: no minute has acted on it.'
      : 'Nothing was applied from it. No minute has taken it up yet.';
  }
  if (!accepted) return `Nothing was applied from it. Minute ${consumedAt} went on without it, so its routine decided that minute.`;
  if (disposition === 'applied') return `Applied in minute ${consumedAt}.`;
  if (disposition === 'superseded') return `Not applied in minute ${consumedAt}, because ${why(reason)}, and that came first.`;
  return `Not applied in minute ${consumedAt}, because ${why(reason)}, so its routine decided that minute.`;
}

function costWords(provider: Held | null): string {
  if (provider === null) return 'No model call is recorded.';
  const usd = words(provider['cost_usd']);
  if (provider['cost_known'] === true) return usd === null ? 'Recorded as known, with no amount.' : `$${usd}, as reported for the call.`;
  return usd === null
    ? 'Not known.'
    : `Not known. The ledger charged its reservation of $${usd}, the most the call can have cost.`;
}

function tokenWords(provider: Held | null): string {
  const calls = items(provider?.['calls']).map(held).filter((call): call is Held => call !== null);
  // A call that did not report its tokens leaves the total unknown, however the receipt sums it.
  if (provider === null || calls.some((call) => call['prompt_tokens'] === null || call['completion_tokens'] === null)) {
    return 'Not reported.';
  }
  const input = whole(provider['prompt_tokens']);
  const output = whole(provider['completion_tokens']);
  if (input === null || output === null) return 'Not reported.';
  const reasoning = calls.reduce((sum, call) => sum + (whole(call['reasoning_tokens']) ?? 0), 0);
  return `${input} in, ${output} out${reasoning > 0 ? ` (${reasoning} of them reasoning)` : ''}.`;
}

/** The served model, never the requested one: the receipt's, or the one every call reported. */
function servedWords(provider: Held | null): string {
  const served = words(provider?.['served_model_id']);
  if (served !== null) return served;
  const calls = items(provider?.['calls']).flatMap((one) => words(held(one)?.['served_model']) ?? []);
  const unique = [...new Set(calls)];
  return unique.length === 1 ? unique[0]! : 'Not reported.';
}

/**
 * Explain one record. `latest` is the being's latest decision from the models read, used for what a
 * minute did only when it names this request; `events` are those read, newest or oldest first.
 */
export function explainDecisionRecord(
  detail: SocietyDecisionDetail,
  latest: PersonDecision | null,
  events: readonly DecisionEvent[] | null,
): DecisionRecordView {
  const request = detail.request;
  const receipt = detail.decision;
  const requestId = words(request['request_id']) ?? '';
  const subjectId = words(request['subject_id']);
  const context = held(request['context']) ?? {};
  const config = held(request['provider_config']);
  const summary = latest !== null && latest.requestId === requestId ? latest : null;
  const event = events?.find((one) => one.kind === 'decision_applied' && one.requestId === requestId) ?? null;
  const consumedAt = event?.tick ?? summary?.consumedTick ?? null;
  const disposition = event?.disposition ?? summary?.disposition ?? null;
  const dispositionReason = event !== null ? event.reason : summary?.dispositionReason ?? summary?.disposition ?? null;
  const proposal = held(receipt?.['proposal']);
  const option = held(proposal?.['option']);
  const chosen = words(proposal?.['label']);
  const accepted = receipt?.['status'] === 'accepted';
  const offered = items(context['options']).flatMap((one) => {
    const label = words(held(one)?.['label']);
    return label === null ? [] : [{ label, kind: words(held(one)?.['kind']) }];
  });
  const appliedAt = accepted && disposition === 'applied' ? consumedAt : null;
  const requestedModel = words(config?.['model_id']);
  const provider = held(receipt?.['provider']);
  const latency = finite(provider?.['latency_ms']);

  const limits: string[] = [];
  if (offered.length > 0 && offered.every((one) => one.kind === 'wait' || one.kind === 'carry_on')) {
    limits.push('It was offered only waiting or carrying on.');
  } else if (offered.length > 0 && !offered.some((one) => one.kind === 'target')) {
    limits.push('No destination was offered this time; other options could still move it.');
  }
  if (accepted && words(option?.['kind']) === 'wait') limits.push('Waiting is a valid answer: it chose to stay where it was for the minute.');
  limits.push('The record keeps what it was told and what it answered, not why. It says nothing of what the model weighed.');


  let changed: readonly string[];
  if (appliedAt === null || subjectId === null) {
    changed = [accepted && consumedAt === null ? 'Nothing has changed from it yet.' : 'Nothing changed in the world from this answer.'];
  } else if (events === null) {
    changed = ['What changed after it could not be read.'];
  } else if (!events.some((one) => one.tick <= appliedAt)) {
    changed = [`The events of minute ${appliedAt} are older than this read, so what changed is not shown.`];
  } else {
    const change = decisionChange(events, subjectId, requestId, appliedAt, words(option?.['activity']));
    changed = change.lines;
    if (change.walked.length > 0) limits.push('Positions are recorded once per minute: when within a minute it arrived is not recorded.');
  }

  return {
    requestId,
    subjectId,
    askedAt: whole(request['base_tick']),
    // Named as the models read names it where the being's latest decision asked the same model.
    asked: latest !== null && latest.modelId === requestedModel ? latest.name : requestedModel,
    told: told(context),
    options: offered.map((one) => ({ label: one.label, chosen: one.label === chosen })),
    chosen,
    line: words(proposal?.['line']),
    answer: answerWords(receipt),
    applied: appliedWords(accepted, receipt !== null, consumedAt, disposition, dispositionReason),
    appliedAt,
    changed,
    limits,
    servedModel: servedWords(provider),
    responseTime: latency === null ? null : `${(latency / 1000).toFixed(2)} s`,
    tokens: tokenWords(provider),
    cost: costWords(provider),
  };
}


/**
 * The being's decisions this read knows of, newest first: the latest from the models read, then
 * each one a minute's decision event names. There is no route that lists every decision, so an
 * older one no event in the read names is not listed.
 */
export function knownDecisions(
  subjectId: string, latest: PersonDecision | null, events: readonly DecisionEvent[],
): readonly KnownDecision[] {
  const known = new Map<string, KnownDecision>();
  if (latest !== null && latest.subjectId === subjectId && latest.requestId !== undefined) {
    known.set(latest.requestId, {
      requestId: latest.requestId,
      minute: latest.baseTick,
      words: `Asked at minute ${latest.baseTick}: ${latest.chose === null ? 'no option chosen' : `“${latest.chose}”`}`,
    });
  }
  for (const event of events) {
    if (event.kind !== 'decision_applied' || event.subjectId !== subjectId || event.requestId === null) continue;
    if (known.has(event.requestId)) continue;
    const outcome = event.disposition === 'applied' ? 'applied' : `not applied (${event.disposition ?? 'unrecorded'})`;
    known.set(event.requestId, {
      requestId: event.requestId,
      minute: event.tick,
      words: `Minute ${event.tick}, ${outcome}: ${event.chose === null ? 'no option chosen' : `“${event.chose}”`}`,
    });
  }
  return [...known.values()].sort((a, b) => b.minute - a.minute);
}
