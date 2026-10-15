// The words of one decision (DESIGN's frame 10, WORDS.md): when it was asked and what came of it,
// what the character's model was told, in sections, and the choices it had. Read from the recorded
// request's context (exulanica.society-decision-context/v2) as the server stored it; a field a
// context does not carry leaves its line or section out. The stored text itself is the Full record.
// What came of a choice is the choice account's verdict (web/packages/app/src/decision-record.ts),
// passed in, so the page and the account never disagree. verify-decision-words.mjs holds these.
import { amount, possessive } from './character-words.mjs';
import { personalityRecordLines } from './personality-words.mjs';
import { worldTime } from './world-clock.mjs';

export const DECISION_WORDS = Object.freeze({
  personality: 'Personality, as you wrote it',
  whereWhen: 'Where and when',
  heard: 'Heard',
  remembers: 'Remembers',
  chosen: 'Chosen',
  fullRecord: 'Full record',
  earlierLater: 'Earlier, later',
  inspect: 'Inspect decision',
  reading: 'Reading the decision…',
  unread: 'This decision could not be read. Try again.',
  rest: 'Rest',
  neededNow: 'needed now',
  notNeededYet: 'not needed yet',
});

/** At most this many lines of what is remembered; the rest are in the Full record. */
export const REMEMBERED_LINES = 4;

const plain = value => typeof value === 'string' && value.trim() ? value.trim() : null;
const capital = words => words.charAt(0).toUpperCase() + words.slice(1);
const sentence = words => { const text = plain(words); return text ? capital(text).replace(/[.!?]?$/u, end => end || '.') : null; };
const list = value => Array.isArray(value) ? value : [];

/** "What Teo's model was told". */
export const toldLabel = who => `What ${possessive(who.within)} model was told`;

/** "How Teo is", "Near the resident". */
export const howIsLabel = who => `How ${who.within} is`;
export const nearLabel = who => `Near ${who.within}`;

/** "Teo's choices (9)". */
export const choicesLabel = (who, count) => `${possessive(who.start)} choices (${count})`;

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
 * Under the title. Done: "Done at 06:53 · answered in 0.9 s · cost $0.0003" ("Done" where the
 * society keeps no clock). Any other verdict: its own sentence, then "Answered in 0.9 s · cost
 * $0.0003". `verdict` is the choice account's { kind, words }; a part not recorded is left out.
 */
export function resultLines({ verdict, doneAt = null, latencyMs = null, costUsd = null, costKnown = true }) {
  const parts = [];
  // Under a tenth of a second has no figure of its own at one decimal (DESIGN's W5).
  if (Number.isFinite(latencyMs)) parts.push(latencyMs < 100 ? 'answered in under 0.1 s' : `answered in ${(latencyMs / 1000).toFixed(1)} s`);
  if (costUsd !== null && costUsd !== undefined && amount(costUsd)) parts.push(`${costKnown ? 'cost' : 'cost at most'} ${amount(costUsd)}`);
  if (verdict?.kind === 'applied') return { done: [doneAt ? `Done at ${doneAt}` : 'Done', ...parts].join(' · '), verdict: null };
  return { done: parts.length ? capital(parts.join(' · ')) : null, verdict: plain(verdict?.words) };
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
  const clock = context?.clock;
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
  const add = (label, lines, apart = false) => { const kept = lines.filter(Boolean); if (kept.length) sections.push({ label, lines: kept, apart }); };
  add(DECISION_WORDS.personality, personalityRecordLines(context?.character) ?? []);
  add(DECISION_WORDS.whereWhen, [whereWhen(context)]);
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
  add(DECISION_WORDS.heard, list(context?.heard).filter(item => plain(item.line))
    .map(item => `${[plain(item.from) ?? 'Someone', ago(item.minutes_ago)].filter(Boolean).join(', ')}: “${plain(item.line)}”`));
  const remembers = context?.remembers;
  if (remembers) {
    const lines = [
      ...list(remembers.beings).filter(being => plain(being.who)).map(being => sentence([`${being.who}, met ${ago(being.met_minutes_ago) ?? ''}`.trim(), being.here === false ? 'no longer here' : null].filter(Boolean).join(', '))),
      ...list(remembers.places).filter(place => plain(place.words)).map(place => sentence(`${place.words}, ${ago(place.last_minutes_ago) ?? ''}`.replace(/, $/u, ''))),
    ];
    const handed = list(remembers.handed).length;
    const shown = lines.slice(0, REMEMBERED_LINES);
    const more = lines.length - shown.length + handed;
    if (more > 0) shown.push(`And ${more} more in the Full record.`);
    add(DECISION_WORDS.remembers, shown);
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
