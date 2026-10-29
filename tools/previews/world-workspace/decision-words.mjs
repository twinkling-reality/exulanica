// The words of one decision (DESIGN's frame 10 and its redraw r10, WORDS.md): when it was asked and what came of it,
// what the character's model was told, in sections, and the choices it had. Read from the recorded
// request's context (exulanica.society-decision-context/v2) as the server stored it; a field a
// context does not carry leaves its line or section out. The stored text itself is the Full record.
// What came of a choice is the choice account's verdict (web/packages/app/src/decision-record.ts),
// passed in, so the page and the account never disagree. verify-decision-words.mjs holds these.
import { amount, finer, possessive } from './character-words.mjs';
import { personalityRecordLines } from './personality-words.mjs';
import {
  TRAJECTORY_PROFILE,
  TRAJECTORY_WORDS,
  decisionTrajectoryRecord,
  downloadTrajectoryJsonl,
  serializeTrajectoryJsonl,
  trajectoryFilename,
  trajectorySummaryWords,
} from './trajectory-export.mjs';
import { worldTime } from './world-clock.mjs';

export {
  TRAJECTORY_PROFILE,
  TRAJECTORY_WORDS,
  decisionTrajectoryRecord,
  downloadTrajectoryJsonl,
  serializeTrajectoryJsonl,
  trajectoryFilename,
  trajectorySummaryWords,
};

export const DECISION_WORDS = Object.freeze({
  personality: 'Personality',
  whereWhen: 'Location & Time',
  /** After the world's title in Where and when: whose words the title is (DESIGN 11:25). */
  heard: 'Heard',
  remembers: 'Remembers',
  chosen: 'Chosen',
  /** A choice the world had moved past before it could happen (U3). */
  chosenNotDone: 'Not Applied',
  fullRecord: 'Raw Prompt',
  earlierLater: 'Previous / Next',
  inspect: 'Decision',
  reading: 'Reading the decision…',
  unread: 'This decision could not be read. Try again.',
  rest: 'Rest',
  neededNow: 'needed now',
  notNeededYet: 'not needed yet',
  trainingData: TRAJECTORY_WORDS.trainingData,
  exportTrajectories: TRAJECTORY_WORDS.exportTrajectories,
  counterfactualPairs: TRAJECTORY_WORDS.counterfactualPairs,
  verifiedDecisions: TRAJECTORY_WORDS.verifiedDecisions,
});

/** At most this many lines of what is remembered; the rest are in the Full record. */
export const REMEMBERED_LINES = 4;
/** At most this many lines heard, the newest, in the order they were told; the rest are in the Full record (D4). */
export const HEARD_LINES = 3;

const plain = value => typeof value === 'string' && value.trim() ? value.trim() : null;
const capital = words => words.charAt(0).toUpperCase() + words.slice(1);
const sentence = words => { const text = plain(words); return text ? capital(text).replace(/[.!?]?$/u, end => end || '.') : null; };
const list = value => Array.isArray(value) ? value : [];

/**
 * Over what the decider was told: "What Teo's model was told"; on a decision a person playing Teo made, "What the
 * person playing Teo was shown" (DESIGN, WORDS.md R5b); on one an outside program made, "What Teo's outside program
 * was told" (WORDS.md R5c: a machine is told, a person is shown). `decider` is 'person', 'external', 'model' or null.
 */
export const toldLabel = (_who, _decider = null) => 'Context';

/** "Status", "Nearby". */
export const howIsLabel = _who => 'Status';
export const nearLabel = _who => 'Nearby';

/** "Teo's Choices (9)". */
export const choicesLabel = (who, count) => `${possessive(who.start)} Choices (${count})`;

/**
 * The over-label: "06:52 · Day 1 · Teo said to Ines", "06:52 · Day 1" for a chosen action, and the
 * said part alone where the society keeps no clock. `at` is worldTime's answer for the minute asked.
 */
export function overLabel({ at, who, said = false, to = null }) {
  const parts = at ? [at.hhmm, `Day ${at.day}`] : [];
  if (said) parts.push(plain(to) ? `${who.start} said to ${plain(to)}` : `${who.start} said`);
  return parts.join(' · ');
}

/** The title: the words said, in quotes, or what was chosen as the choices list says it. */
export function decisionTitle({ line = null, chose = null }) {
  if (plain(line)) return `“${plain(line)}”`;
  return plain(chose) ? capital(plain(chose)) : '';
}

/**
 * Under the title: the answer's time and cost, "0.9 s · $0.0003", and for a verdict
 * other than done its own sentence. A done decision says nothing more: the head names the minute it
 * was done in, and the chosen mark what was done. `verdict` is the choice account's { kind, words };
 * a part not recorded is left out.
 */
export function resultLines({ verdict, latencyMs = null, costUsd = null, costKnown = true }) {
  const parts = [answeredIn(latencyMs), costWords(costUsd, costKnown)].filter(Boolean);
  return { done: parts.length ? capital(parts.join(' · ')) : null, verdict: verdict?.kind === 'applied' ? null : plain(verdict?.words) };
}

/**
 * How long the answer took: "0.9 s"; under a tenth of a second has no figure of its own at one decimal,
 * "under 0.1 s" (DESIGN's W5). Null where no time is recorded.
 */
export function answeredIn(latencyMs) {
  if (!Number.isFinite(latencyMs)) return null;
  return latencyMs < 100 ? 'under 0.1 s' : `${(latencyMs / 1000).toFixed(1)} s`;
}

/** What the answer cost: "$0.0003", or "At most $0.0014" where only its bound is known; null where unrecorded. */
export function costWords(costUsd, costKnown = true) {
  if (costUsd === null || costUsd === undefined || !amount(costUsd)) return null;
  return `${costKnown ? '' : 'At most '}${amount(costUsd)}`;
}

/** The record page's own words (DESIGN's r10): the moment card's label and who decided, T7's words where no model did. */
export const DECISION_FLOW_WORDS = Object.freeze({
  whatHappened: 'Outcome',
  decidedBy: '',
  decidedByPerson: 'A person playing',
  decidedByProgram: 'An outside program',
  /** An outside AI agent at the door decided (AG1d 4): who decided and nothing else, as D5 holds for a model. */
  decidedByAgent: 'An outside AI agent',
});

/**
 * A model's decision with no usable answer (U3, DESIGN's WORDS.md 12:57): its receipt states no proposal, and the
 * routine acted. It was asked where its receipt names a provider (an attempt left this computer), not asked where it
 * names none. An asked receipt refused before its next ask was asked again after an answer that was not an action,
 * since only such an answer is asked again. These are the reasons each such line names.
 */
export const UNANSWERED_REASONS = Object.freeze({
  money: Object.freeze(['spending_limit_reached', 'process_budget_spent', 'process_share_spent', 'world_hour_spend_spent']),
  noTime: Object.freeze(['no_time_to_ask', 'unanswered_in_its_minute']),
  notAgain: Object.freeze(['spending_not_granted', 'spending_revoked', 'spending_expired', 'spending_suspended', 'spending_unavailable',
    'spending_scope_missing', 'request_refused', 'provider_not_admitted', 'provider_credential_absent', 'model_no_longer_offered',
    'world_hour_decisions_spent']),
});

/** Such a decision's own words under the ring and in its head: no usable answer, or a choice the world moved past. */
export const UNANSWERED_WORDS = Object.freeze({
  none: 'No Usable Answer', late: 'Chose Too Late', routine: 'Routine Fallback', notAsked: 'Not Asked',
});

/** Why a model was not asked, in four words or fewer, by its receipt's reason; absent where the reason has none. */
const NOT_ASKED = Object.freeze({
  ...Object.fromEntries(UNANSWERED_REASONS.money.map(reason => [reason, 'Over the money left'])),
  ...Object.fromEntries(UNANSWERED_REASONS.noTime.map(reason => [reason, 'No time to ask'])),
  spending_suspended: 'Spending was paused',
  ...Object.fromEntries(['spending_not_granted', 'spending_revoked', 'spending_expired', 'spending_scope_missing'].map(reason => [reason, 'Spending was not open'])),
  spending_unavailable: 'Spending check failed',
  provider_credential_absent: 'Its service not connected',
  provider_not_admitted: 'Not allowed here',
  model_no_longer_offered: 'No longer offered here',
  model_unavailable: 'The model was unavailable',
  model_call_failed: 'The call failed',
  request_refused: 'Refused before sending',
  provider_configuration_changed: "The model's settings changed",
  world_hour_decisions_spent: 'Hourly limit reached',
  decision_context_changed: 'The world moved on',
});

/**
 * Under the ring where nothing was sent, why, where the line under the head does not already say it: "Spending was
 * paused"; null for the money and the time, which that line names, and for a reason with no words.
 */
export function notAskedWhy(reason) {
  if (UNANSWERED_REASONS.money.includes(reason) || UNANSWERED_REASONS.noTime.includes(reason)) return null;
  return Object.hasOwn(NOT_ASKED, reason ?? '') ? NOT_ASKED[reason] : null;
}

/**
 * The head's small print for a model's decision whose choice was not taken, the model's name its own part:
 * "Nemotron 3 Ultra 550B · No Usable Answer · Routine Fallback"; where nothing was sent, "Nemotron 3 Ultra 550B · Not
 * Asked · Routine Fallback"; a choice the world had moved past, "Qwen3 235B · Chose Too Late · Routine
 * Fallback". Nothing where no model is named.
 */
export function unansweredParts({ model = null, asks = 0, late = false } = {}) {
  const name = plain(model);
  if (!name) return [];
  if (!late && asks < 1) return [{ model: name }, ` · ${UNANSWERED_WORDS.notAsked} · ${UNANSWERED_WORDS.routine}`];
  return [{ model: name }, ` · ${late ? UNANSWERED_WORDS.late : UNANSWERED_WORDS.none} · ${UNANSWERED_WORDS.routine}`];
}

/**
 * Under the ring for an asked decision with no usable answer, what the asks sent took and cost: "Asked once in 2.1 s ·
 * $0.0121", "Asked twice in 4.3 s · $0.0242", "At most" where only the bound is known.
 */
export function askedPrint({ asks = 1, latencyMs = null, costUsd = null, costKnown = true } = {}) {
  const times = asks === 1 ? 'once' : asks === 2 ? 'twice' : `${asks} times`;
  const took = !Number.isFinite(latencyMs) ? '' : latencyMs < 100 ? ' in under 0.1\u00a0s' : ` in ${(latencyMs / 1000).toFixed(1)}\u00a0s`;
  const cost = costUsd === null || costUsd === undefined || !amount(costUsd) ? null : `${costKnown ? '' : 'At most '}${finer(costUsd)}`;
  return [`Asked ${times}${took}`, cost].filter(Boolean).join(' · ');
}

/**
 * Why the routine acted for a decision with no usable answer, under the head's small print (U3): by the receipt's reason
 * and whether it was asked, "Asking it failed."
 */
export function unansweredWhy({ asks = 0, reason = null }) {
  const has = kind => UNANSWERED_REASONS[kind].includes(reason);
  if (asks < 1) return `${has('money') ? 'Asking it would have gone over the money left' : has('noTime') ? 'There was no time to ask it' : 'It could not be asked just then'}.`;
  const off = 'Its answer was not one of the actions';
  const why = has('money') ? `${off}, and asking it again would have gone over the money left`
    : reason === 'no_time_to_ask' ? `${off}, and there was no time to ask it again`
      : has('notAgain') ? `${off}, and it could not be asked again just then`
        : reason === 'model_timed_out' ? 'It did not answer in time'
          : reason === 'answer_not_offered' ? (asks > 1 ? 'Its answers were not among the actions' : off)
            : reason === 'model_call_failed' || reason === 'model_unavailable' ? 'Asking it failed'
              : reason === 'provider_configuration_changed' ? "The model's settings changed while it was asked"
                : reason === 'decision_context_changed' ? 'The world had moved on while it was asked'
                  : 'Its answer could not be used';
  return `${why}.`;
}

/** A turn an outside program did not answer at all (AG1d 5): its program silent past the deadline, or not connected. */
export const NO_ANSWER = Object.freeze(['no_answer_in_time', 'decider_disconnected']);

/** The head's small print for an outside AI agent's turn whose choice was not taken (AG1d 5): "An outside AI
 * agent · No Answer · Routine Fallback"; one whose answer came back and could not be used, "... · No Usable Answer ·
 * ...". */
export function agentUnansweredParts(reason) {
  return [`${DECISION_FLOW_WORDS.decidedByAgent} · ${NO_ANSWER.includes(reason) ? 'No Answer' : UNANSWERED_WORDS.none} · ${UNANSWERED_WORDS.routine}`];
}

/** Why the routine acted for such a turn (AG1d 5), under the head's small print: "It did not answer in time." */
export function agentUnansweredWhy(reason = null) {
  return reason === 'no_answer_in_time' ? 'It did not answer in time.' : reason === 'decider_disconnected' ? 'It was not connected.'
    : 'Its answer could not be used.';
}

/** Over the column of choices (r10): "Teo's Choices", "The resident's Choices". */
export const choicesOver = who => `${possessive(who.start)} Choices`;

/** Under the decision's ring, after who decided (r10): "Chose 1 of 9". */
export const choseOneOf = count => `Chose 1 of ${count}`;

/**
 * The head's small print (r10) as parts, a model's name its own part ({ model }) so the page keeps it on one line: who
 * decided and nothing else (D5), "Nemotron 3 Nano 30B", "A person playing", "An outside
 * program" (`decider` 'person' or 'external', T7); nothing where no one is named.
 */
export function decidedByParts({ decider = null, model = null } = {}) {
  const who = decider === 'person' ? DECISION_FLOW_WORDS.decidedByPerson : decider === 'external' ? DECISION_FLOW_WORDS.decidedByProgram
    : decider === 'agent' ? DECISION_FLOW_WORDS.decidedByAgent : null;
  return who ? [who] : plain(model) ? [...(DECISION_FLOW_WORDS.decidedBy ? [DECISION_FLOW_WORDS.decidedBy] : []), { model: plain(model) }] : [];
}

/**
 * Under the ring, by the choice they paid for (D5): the answer's time and its cost, "0.1 s · $0.0001",
 * "1.3 s · At most $0.0014" where only its bound is known; a part not recorded is left out, null with neither.
 */
export function ringPrint({ latencyMs = null, costUsd = null, costKnown = true } = {}) {
  const cost = costWords(costUsd, costKnown);
  // A figure never breaks across lines under the ring (DESIGN 04:04): "0.1 s" keeps a no-break space.
  const time = answeredIn(latencyMs)?.replace(/ s$/u, '\u00a0s');
  const parts = [time ? capital(time) : null, cost].filter(Boolean);
  return parts.length ? parts.join(' · ') : null;
}

/**
 * One need as the model was told it, words first (ruling J14): the catalog's label, "needed now"
 * above the level people see to it at, "not needed yet" at or below it, then the number.
 */
export function needLine(label, milli, seenToAt) {
  if (!plain(label) || !Number.isFinite(milli)) return null;
  const level = Number.isFinite(seenToAt) && milli > seenToAt ? DECISION_WORDS.neededNow : DECISION_WORDS.notNeededYet;
  return `${capital(plain(label))}: ${level} (${Math.round(milli)} of 1000).`;
}

const away = (metres, who) => !Number.isFinite(metres) ? null : metres === 0 ? `beside ${who.within}` : `${Math.round(metres)} m away`;
const ago = minutes => !Number.isFinite(minutes) ? null : minutes === 0 ? 'this minute' : minutes === 1 ? '1 minute ago' : `${minutes} minutes ago`;

/**
 * "On the glass terraces · 06:54 · Day 1": where the model was told the character stood and the
 * minute it was told (a town's clock is the coming minute; a garden is told "minute 4").
 */
function whereWhen(context) {
  // A garden's spot is told as its words and what it is good for: "resting (others can rest at it)".
  const at = context?.surroundings?.at;
  const spot = plain(at?.words) ? [plain(at.words), plain(at.good_for) ? `(${plain(at.good_for)})` : null].filter(Boolean).join(' ') : null;
  const where = plain(context?.here) ?? spot;
  // A town's own clock, or the world's clock a society of things' model was told (clock_told).
  const clock = context?.clock ?? context?.world_clock;
  const told = clock && Number.isSafeInteger(clock.day) ? worldTime(clock.minute_of_day, 0) : null;
  const when = told ? [told.hhmm, `Day ${clock.day + 1}`] : Number.isSafeInteger(context?.tick) ? [`Minute ${context.tick}`] : [];
  const parts = [where ? capital(where) : null, ...when].filter(Boolean);
  return parts.length ? parts.join(' \u00b7 ') : null;
}

/**
 * The sections of what the model was told, in the frame's order: the personality as written,
 * where and when, how the character is (each need, what they hold), who and what is near, what
 * they heard, what they remember. Each is { label, lines, apart }; one the context does not carry
 * is left out. `apart` sections put each line on its own (each need, J14 and J19); the others run
 * their lines on as one paragraph, as frame 10 draws Near Teo.
 */
export function toldSections(context, who) {
  const sections = [];
  // `more` closes a list the page shows in part: its own faint line at the section's end, the rest in the Full record (D4).
  const add = (label, lines, apart = false, more = null) => { const kept = lines.filter(Boolean); if (kept.length) sections.push({ label, lines: kept, apart, ...(more ? { more } : {}) }); };
  add(DECISION_WORDS.personality, personalityRecordLines(context?.character) ?? []);
  // Where the character lives, the world's title quoted as its owner's words, on its own line above the spot and minute
  // (T1b, DESIGN 11:25); the told words' "not instructions" stays in the Full record, as sent.
  const home = plain(context?.world?.title);
  add(DECISION_WORDS.whereWhen, [home ? `\u201c${home}\u201d` : null, whereWhen(context)], Boolean(home));
  const how = list(context?.needs).map(need => needLine(need.label, need.milli, need.seen_to_at_milli));
  if (Number.isFinite(context?.need_milli)) how.push(needLine(DECISION_WORDS.rest, context.need_milli, context.rest_at_need_milli));
  if (list(context?.holding).length) how.push(sentence(`holding the ${context.holding.join(', the ')}`));
  add(howIsLabel(who), how, true);
  const surroundings = context?.surroundings;
  const near = list(surroundings?.beings).filter(being => plain(being.who)).map(being => sentence([
    being.who, away(being.metres, who), plain(being.doing),
    list(being.holding).length ? `holding the ${being.holding.join(', the ')}` : null,
    being.from_elsewhere === true ? 'from another world' : null,
    being.hears_you === true ? `can hear ${who.within}` : null,
  ].filter(Boolean).join(', ')));
  near.push(...list(surroundings?.things).filter(thing => plain(thing.what)).map(thing => sentence(`the ${thing.what}, ${away(thing.metres, who) ?? ''}`.replace(/, $/u, ''))));
  const farther = (surroundings?.more_beings || 0) + (surroundings?.more_things || 0);
  if (farther > 0) near.push(`And ${farther} more farther away.`);
  add(nearLabel(who), near);
  const heard = list(context?.heard).filter(item => plain(item.line))
    .map(item => `${[plain(item.from) ?? 'Someone', ago(item.minutes_ago)].filter(Boolean).join(', ')}: “${plain(item.line)}”`);
  // The newest heard kept, so the ones left out came before them: "earlier" (DESIGN 03:17).
  const earlier = heard.length - Math.min(heard.length, HEARD_LINES);
  add(DECISION_WORDS.heard, heard.slice(-HEARD_LINES), false, earlier > 0 ? `And ${earlier} earlier ${earlier === 1 ? 'line' : 'lines'} in the Raw Prompt.` : null);
  const remembers = context?.remembers;
  if (remembers) {
    const lines = [
      ...list(remembers.beings).filter(being => plain(being.who)).map(being => sentence([`${being.who}, met ${ago(being.met_minutes_ago) ?? ''}`.trim(), being.here === false ? 'no longer here' : null].filter(Boolean).join(', '))),
      ...list(remembers.places).filter(place => plain(place.words)).map(place => sentence(`${place.words}, ${ago(place.last_minutes_ago) ?? ''}`.replace(/, $/u, ''))),
    ];
    const handed = list(remembers.handed).length;
    const shown = lines.slice(0, REMEMBERED_LINES);
    const more = lines.length - shown.length + handed;
    add(DECISION_WORDS.remembers, shown, false, more > 0 ? `And ${more} more in the Raw Prompt.` : null);
  }
  return sections;
}

/** The numbered choices, the chosen one marked, by the label the receipt names. */
export function choiceRows(context, chose) {
  return list(context?.options).filter(option => plain(option.label))
    .map((option, index) => ({ number: index + 1, words: capital(plain(option.label)), chosen: option.label === chose }));
}

/** The minute a recorded decision was asked in, for the over-label: its base tick's time. */
export const askedAt = (baseTick, startMinute) => worldTime(baseTick, startMinute);
