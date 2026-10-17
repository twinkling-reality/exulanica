// The words of a run and the figures it is opened with (DESIGN's frames 08 and 09, WORDS.md). A run
// is what the server calls a living session: one capped stretch of playback in which the models
// chosen for characters are asked. Choosing a model asks nothing; only a run does. Why a run ended is
// the server's sentence (SESSION_CLOSED_WORDS), the one wording History and a world's pull request
// also read. verify-run-words.mjs holds these words to the server's codes.
import { amount, possessive } from './character-words.mjs';

export const RUN_WORDS = Object.freeze({
  run: 'Run',
  stop: 'Stop',
  running: 'Running',
  left: 'left',
  back: 'Back',
  pause: 'Pause',
  stopsByItself: 'It stops by itself, or when you press Stop.',
});

/** Why a run could not start or stop, by the server's code (spec 8.8). */
export const RUN_REFUSALS = Object.freeze({
  session_already_open: 'A run is already on. Stop it first.',
  society_not_paused: 'The world is playing. Pause it first, then run.',
  stale_society_state: 'The world changed a moment ago. Press Run again.',
  session_request_reused: 'That run already started with other limits. Press Run again.',
  invalid_session_limits: 'These limits are not allowed here.',
  session_unknown: 'That run has already ended.',
});

/** Why a run is not offered before anything is sent, by the host's refusal code (spec 8.8). */
export const NOT_CONNECTED = Object.freeze({
  provider_credential_absent: 'No AI model is connected here.',
  process_budget_spent: 'The budget for AI models here is spent.',
  process_share_spent: 'The budget for AI models here is spent.',
});

/** The refusal whose card also offers [P] Pause. */
export const PAUSE_FIRST = 'society_not_paused';

/** The words for a refused run by its code; any other code says nothing started. */
export function runRefusalWords(code) {
  if (Object.hasOwn(RUN_REFUSALS, code)) return RUN_REFUSALS[code];
  return Object.hasOwn(NOT_CONNECTED, code) ? NOT_CONNECTED[code] : 'The run did not start. Nothing was spent.';
}

/** The run a person starts with Run: ten minutes of real time, at most US$0.05. */
export const DEFAULT_RUN = Object.freeze({ wallSeconds: 600, usd: '0.05000000' });
/** The server's largest figures for a session (SESSION_MAXIMA in exulanica/world/society_sessions.py). */
const MAXIMA = Object.freeze({ minutes: 1440, decisions: 10_000, calls: 10_000 });

/**
 * The limits of the default run on a world whose minute takes `intervalMs` of real time, for
 * `askers` characters with a model: as many world minutes as ten real minutes play, and room for
 * each of those characters to be asked twice a minute (and each ask to retry once), so the time and
 * the spending are what stop it.
 */
export function defaultRunLimits(intervalMs, askers) {
  const minutes = Math.min(MAXIMA.minutes, Math.max(1, Math.ceil((DEFAULT_RUN.wallSeconds * 1000) / intervalMs)));
  const decisions = Math.min(MAXIMA.decisions, Math.max(1, minutes * 2 * Math.max(1, askers)));
  return Object.freeze({ wallSeconds: DEFAULT_RUN.wallSeconds, minutes, decisions, usd: DEFAULT_RUN.usd, calls: Math.min(MAXIMA.calls, decisions * 2) });
}

const minutesWords = seconds => { const count = Math.round(seconds / 60); return `${count} ${count === 1 ? 'minute' : 'minutes'}`; };

/** The question card's title: "Run for 10 minutes". */
export const runFor = limits => `Run for ${minutesWords(limits.wallSeconds)}`;

/** The most a run may spend: "At most $0.05" heads the card; "at most $0.05" sits in a line. */
export const atMost = (limits, start = false) => `${start ? 'At' : 'at'} most ${amount(limits.usd)}`;

/** The page's Run line: "10 minutes · at most $0.05". */
export const runLength = limits => `${minutesWords(limits.wallSeconds)} · ${atMost(limits)}`;

/** What a run does, said of the chosen character. */
export const whoDecides = who => `${possessive(who.start)} model decides. Everyone else keeps their routine.`;

/** "9:13", the time left of an open run, from `now` (milliseconds). */
export function timeLeft(endsBy, now) {
  const seconds = Math.max(0, Math.round((Date.parse(endsBy) - now) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

/** The Running strip's words for an open run. */
export function stripWords(run, now) {
  return Object.freeze({ running: RUN_WORDS.running, timeLeft: timeLeft(run.endsBy, now), left: RUN_WORDS.left,
    spent: amount(run.used.usd), of: `of ${amount(run.limits.usd)}`, stop: RUN_WORDS.stop });
}

/**
 * Who a run asks, as the world screen's pill says it (r09, J28's names): each character whose choice is
 * a model, as `called` calls them ({ start, within }), the first opening the sentence. "Teo's model is
 * deciding", "Teo's and Ines's models are deciding", "Teo's, Ines's and the resident's models are
 * deciding"; past three, how many; with nobody known, that the world runs.
 */
export function decidingWords(whos) {
  const list = whos ?? [];
  if (list.length === 0) return RUN_WORDS.running;
  if (list.length > 3) return `${list.length} models are deciding`;
  const names = list.map((who, at) => possessive(at === 0 ? who.start : who.within));
  if (names.length === 1) return `${names[0]} model is deciding`;
  return `${names.slice(0, -1).join(', ')} and ${names.at(-1)} models are deciding`;
}

/** The pill's run line (r09): who decides, the time left and the spending, "Teo's model is deciding · 9:13 left · $0.0011 of $0.05". */
export function pillRunLine(run, now, whos) {
  return [decidingWords(whos), runningLine(run, now)].join(' · ');
}

/** The page's line while a run is on: "9:13 left · $0.0011 of $0.05" (the strip and the orb say it runs; DESIGN's J9). */
export function runningLine(run, now) {
  return [`${timeLeft(run.endsBy, now)} ${RUN_WORDS.left}`, `${amount(run.used.usd)} of ${amount(run.limits.usd)}`].join(' · ');
}

/** What a closed run spent, with what is not settled yet. */
export function spentWords(run) {
  const spent = amount(run.used.usd);
  return run.used.unresolved?.count > 0 ? `${spent}, and up to ${amount(run.used.unresolved.usd)} not known yet` : spent;
}

/** The note after a run: the server's sentence for why it ended, then what it spent. */
export function endedNote(run) {
  return `${run.closedReasonWords} Spent ${spentWords(run)}.`;
}
