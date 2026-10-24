// The words of Compare (DESIGN's frames 12a, 12b and r12, rulings C1 and C2, WORDS.md): a character's
// recorded decisions asked again, exactly as they were asked (D1), of a second model and once more of
// the model that made them. Nothing they choose is applied. The count and the most it can cost are
// the server's offer (GET .../people/{id}/asks-again), never a number here. verify-compare-words.mjs
// holds these.
import { amount, possessive } from './character-words.mjs';

export const COMPARE_WORDS = Object.freeze({
  compare: 'Compare',
  compareThisMoment: 'Compare this moment',
  thisDecision: 'Ask this decision again',
  askedOnce: 'Asked once of each. Nothing they choose happens in the world.',
  perMillion: 'Per million tokens',
  choose: 'Choose',
  stop: 'Stop',
  back: 'Back',
  earlierLater: 'Earlier, later',
  whatEachChose: 'What each chose',
  asRecorded: 'As recorded',
  different: 'Another choice',
  same: 'Same choice',
  notAsked: 'Not asked',
  again: 'again',
  sameMoments: who => `The same moments, exactly as ${possessive(who.within)} model was told them. Nothing in the world changed.`,
  sameMoment: who => `The same moment, exactly as ${possessive(who.within)} model was told it. Nothing in the world changed.`,
});

/** "Ask Teo's last 12 decisions again"; from one decision, "Ask this decision again". */
export function askLine(who, count, single = false) {
  if (single) return COMPARE_WORDS.thisDecision;
  return count === 1 ? `Ask ${possessive(who.within)} last decision again` : `Ask ${possessive(who.within)} last ${count} decisions again`;
}

/** Under the Big line: who is asked. */
export const explanation = (who, recorded) =>
  `Each is asked exactly as ${possessive(who.within)} model was asked it, of the model you choose and once more of ${recorded}. Nothing in the world changes.`;

/** The orb's figure before the asks: "At most $0.01". */
export const atMost = usd => `At most ${amount(usd)}`;

/** While the asks run (C2): "Asking 5 of 24 · $0.0008 of $0.01". */
export const asking = (done, total, spentUsd, mostUsd) => `Asking ${done} of ${total} · ${amount(spentUsd)} of ${amount(mostUsd)}`;

/** With nothing to ask (C4): the offer holds no decisions. */
export const nothingToAsk = who => `${who.start} has no decisions to ask again yet. Run ${possessive(who.within)} model first.`;

/** With nothing to ask (C4): the offer holds decisions and refuses every one; from one decision, that one. */
export const cannotAskAgain = (who, single = false) =>
  single ? 'This decision cannot be asked again here.' : `${possessive(who.start)} last decisions cannot be asked again here.`;

/** The result's over-label: "Teo · 12 decisions, 06:41 to 06:52 · Day 1" (times where the society keeps a clock). */
export function resultOver({ who, count, from = null, to = null, day = null }) {
  const span = from && to ? (from === to ? `, ${from}` : `, ${from} to ${to}`) : '';
  const parts = [who.title, `${count} ${count === 1 ? 'decision' : 'decisions'}${span}`];
  if (day) parts.push(`Day ${day}`);
  return parts.join(' · ');
}

/** The result's title: "Teo's last 12 decisions, asked again"; one moment: "Teo's decision, asked again". */
export function resultTitle(who, count, single = false) {
  if (single) return `${possessive(who.start)} decision, asked again`;
  return count === 1 ? `${possessive(who.start)} last decision, asked again` : `${possessive(who.start)} last ${count} decisions, asked again`;
}

/** "Spent $0.0030 asking again". */
export const spentAsking = usd => `Spent ${amount(usd)} asking again`;

/**
 * The result's small sentence (r12): how the moments were asked, then what asking again spent: "The same moments,
 * exactly as Teo's model was told them. Nothing in the world changed. Spent $0.003 asking again."
 */
export const resultSub = (sub, spent) => [sub, spent ? `${spent.replace(/\.$/u, '')}.` : ''].filter(Boolean).join(' ');

/** "At 06:43 · 3 of 12" (where the society keeps no clock, "3 of 12"); one moment, "At 06:43" or nothing (C3). */
export const atMoment = (hhmm, index, count) =>
  [hhmm ? `At ${hhmm}` : null, count > 1 ? `${index + 1} of ${count}` : null].filter(Boolean).join(' · ');

/** A model's name for the rerun lane and chip: "Nemotron 3 Nano 30B, again". */
export const again = name => `${name}, ${COMPARE_WORDS.again}`;

/**
 * What one answer chose, as the decision page words a choice: the choice's own words, or, for a line
 * said, "Said to Ines: “…”" ("Said: “…”" with nobody named).
 */
export function choseWords({ chose = null, line = null, to = null }) {
  const text = typeof line === 'string' && line.trim() ? line.trim() : null;
  if (text) return to ? `Said to ${to}: “${text}”` : `Said: “${text}”`;
  return typeof chose === 'string' && chose ? chose.charAt(0).toUpperCase() + chose.slice(1) : null;
}

/**
 * The tag right of an answer: the recorded one "As recorded"; an asked one "Same choice" where it chose the
 * recorded option (whatever words it said with it) and "Another choice" where it did not; none unasked. It says what it
 * compares: never "Same" beside other words (H1).
 */
export function answerTag(answer) {
  if (answer.recorded) return COMPARE_WORDS.asRecorded;
  if (!answer.asked) return null;
  return answer.same ? COMPARE_WORDS.same : COMPARE_WORDS.different;
}

const unasked = Object.freeze({ asked: false, chose: null, line: null, costUsd: null, same: null });

/**
 * The moments of a comparison, oldest first: each offered decision the server could ask again, with
 * its recorded answer and the two asks made of it, the chosen model's (`other`) and the recorded
 * model's once more (`again`), each `{ asked, chose, line, costUsd, same }`, `same` meaning it chose
 * the recorded option. `answers` maps a request id to the asks read back, `{ other, again }`.
 */
export function compareMoments(decisions, answers) {
  return decisions.filter(decision => decision.askUsd !== null).map(decision => {
    const pair = answers.get(decision.requestId) ?? {};
    const of = ask => ask ? { asked: true, chose: ask.chose ?? null, line: ask.line ?? null, costUsd: ask.costUsd ?? null, same: (ask.chose ?? null) === (decision.chose ?? null) } : unasked;
    return { requestId: decision.requestId, tick: decision.baseTick, recorded: { chose: decision.chose, line: decision.line }, other: of(pair.other), again: of(pair.again) };
  });
}

/** How often each set of asks chose the recorded option, over the moments it was asked. */
export function sameCounts(moments, which) {
  const asked = moments.filter(moment => moment[which].asked);
  return { asked: asked.length, same: asked.filter(moment => moment[which].same).length };
}

/** What was spent asking, summed from the answers' own costs (an unknown cost counts as nothing yet). */
export function spentOf(moments) {
  return moments.reduce((sum, moment) => sum + ['other', 'again'].reduce((part, which) => part + (Number(moment[which].costUsd) || 0), 0), 0);
}

/**
 * The band's marks for one lane (f12b): one per moment, `said` where the answer was a line,
 * `differs` where an asked answer did not choose the recorded option, `hollow` where it was not asked.
 */
export function laneMarks(moments, which) {
  return moments.map(moment => {
    const answer = which === 'recorded' ? { asked: true, line: moment.recorded.line, same: true } : moment[which];
    return { said: Boolean(answer.asked && answer.line), differs: Boolean(answer.asked && answer.same === false), hollow: !answer.asked };
  });
}

/**
 * "What each chose" (C2, C3): how often the second model chose as the recorded one did, over the
 * moments it was asked, and, faint, how often the same model chose as before, or that it could not be
 * asked again (`againRefused`). Never which is better, never "0 of" or "1 of 1": all, none or some,
 * with "asked" where some moments were not. One moment has no such lines; its rows' tags say it.
 */
export function whatEachChose({ recordedName, otherName, other, again: rerun, count, againRefused = false }) {
  const asked = n => `${n} ${n === 1 ? 'moment' : 'moments'}${n === count ? '' : ' asked'}`;
  const every = n => n === 1 ? `the one moment${count === 1 ? '' : ' asked'}` : `all ${asked(n)}`;
  const lines = [];
  if (count < 2) return lines;
  if (other.asked > 0) {
    lines.push(other.same === other.asked ? `${otherName} chose as ${recordedName} did at ${every(other.asked)}.`
      : other.same === 0 ? `${otherName} chose differently from ${recordedName} at ${every(other.asked)}.`
      : `${otherName} chose as ${recordedName} did at ${other.same} of ${asked(other.asked)}.`);
  }
  if (againRefused) lines.push(`${recordedName} could not be asked again here.`);
  else if (rerun.asked > 0) {
    lines.push(rerun.same === rerun.asked ? `Asked again, ${recordedName} chose as before at ${every(rerun.asked)}.`
      : rerun.same === 0 ? `Asked again, ${recordedName} chose differently at ${every(rerun.asked)}, so a difference here can be chance.`
      : `Asked again, ${recordedName} chose as before at ${rerun.same} of ${rerun.asked === count ? count : asked(rerun.asked)}: a small difference can be chance.`);
  }
  return lines;
}

/** "Use Qwen3 235B Instruct for Teo". */
export const useFor = (name, who) => `Use ${name} for ${who.within}`;
