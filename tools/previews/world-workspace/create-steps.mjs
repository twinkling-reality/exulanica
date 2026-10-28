// What making a world shows, from what the server serves (DESIGN's frames 20 and 21, rulings N3 to
// N12, L14): the offer to the page's state, a draft's reads to its steps and their times, when to
// read again, the draft read's accounting to what was spent, the cards, each key's fate and the
// made handoff. Pure, so verify-create-steps.mjs checks it in Node; the page draws what it returns.
import { OFFLINE_AFTER_FAILED_READS } from './world-ui-layout.mjs';
import { READ_BACKOFF } from './read-backoff.mjs';
import { CREATE_WORDS, NOTES_WORDS, STEP_WORDS, cardSub, stepTime } from './create-words.mjs';

/** The draft states that are steps, in the server's order; `ready` and `refused` end a draft. */
export const DRAFT_STEPS = Object.freeze(['queued', 'choosing', 'drafting', 'making']);

/**
 * Offer codes that mean no AI model can make a world here (N7: no key, or models not run here;
 * SCOPE risk 5 puts the three host codes with them until DESIGN says otherwise).
 */
export const NO_MODEL_CODES = Object.freeze(['provider_credential_absent', 'kinds_from_people_not_offered']);
/** Offer codes that mean making from words is not offered here for another reason (N25). */
export const NOT_OFFERED_CODES = Object.freeze(['not_authorised', 'world_draft_spending_not_durable', 'world_draft_worker_not_running']);
/** Offer codes that mean the budget for AI models is spent (J22, M11). */
export const BUDGET_CODES = Object.freeze(['budget_exceeded', 'process_budget_spent', 'process_share_spent']);
/** Offer codes that mean spending on AI models is paused here, held closed until an operator acts, not spent (N34). */
export const PAUSED_CODES = Object.freeze(['spending_suspended']);
/** The offer code where the budget has less left than one step of making could cost (N31, A1b), served with both figures. */
export const SHORT_CODE = 'world_draft_bound_exceeds_left';

/**
 * The page's state from the offer read (`GET /worlds/drafts`, raw): 'loading' before it answers;
 * 'following' where this person's draft runs (N12 opens frame 21); 'no-model', 'budget', 'paused'
 * (spending held closed, N34) and 'short' (the budget left is less than one step of making could
 * cost, with both figures, N31, A1b) put the sentence in place
 * of the field and orb (N7); 'refused' carries a code said under the field (N9);
 * 'offered' otherwise.
 */
export function offerState(offer) {
  if (!offer) return { page: 'loading' };
  if (typeof offer.running_draft_id === 'string' && offer.running_draft_id) return { page: 'following', draftId: offer.running_draft_id };
  const code = typeof offer.code === 'string' ? offer.code : null;
  if (offer.offered === true && code === null) return { page: 'offered' };
  if (NO_MODEL_CODES.includes(code)) return { page: 'no-model' };
  if (NOT_OFFERED_CODES.includes(code)) return { page: 'not-offered' };
  if (PAUSED_CODES.includes(code)) return { page: 'paused' };
  if (BUDGET_CODES.includes(code)) return { page: 'budget' };
  // Told apart from a spent budget by its served code and figures, never by the detail's words (N31).
  if (code === SHORT_CODE) {
    const step = offer.operation?.step_usd_at_most, left = offer.left_usd;
    return typeof step === 'string' && typeof left === 'string' ? { page: 'short', stepUsd: step, leftUsd: left } : { page: 'budget' };
  }
  return { page: 'refused', code };
}

/** Whether Create can be pressed: the offer answered with a price, and a word is typed (N2). */
export const canCreate = (offer, words) => offerState(offer).page === 'offered' && typeof words === 'string' && words.trim().length > 0;

/**
 * The steps shown for a draft from its reads so far, oldest first, each { state, elapsed_seconds }
 * as served. Only a state some read served is a step (M14): one never served, or not yet reached,
 * is not shown. A step's time is the served elapsed time at the read that ended it; the running
 * step's is the latest read's. Nothing comes from the page's clock.
 * @returns {{ key: string, words: string, state: 'done' | 'now', time: string }[]}
 */
export function draftSteps(reads) {
  const steps = [];
  for (const read of reads ?? []) {
    const state = read?.state, elapsed = Number(read?.elapsed_seconds);
    if (!Number.isFinite(elapsed)) continue;
    const last = steps.at(-1);
    if (state === 'ready' || state === 'refused') {
      // The read that ends the draft ends its last step; a refused one stays where it stopped.
      if (last) { last.seconds = elapsed; if (state === 'ready') last.state = 'done'; }
      break;
    }
    if (!DRAFT_STEPS.includes(state)) continue;
    if (last?.key === state) { last.seconds = elapsed; continue; }
    // A state already passed, served again out of order, moves nothing back.
    if (steps.some(step => step.key === state)) continue;
    if (last) { last.seconds = elapsed; last.state = 'done'; }
    steps.push({ key: state, words: STEP_WORDS[state], state: 'now', seconds: elapsed });
  }
  return steps.map(({ key, words, state, seconds }) => ({ key, words, state, time: stepTime(seconds) }));
}

/** When to read the draft again (ms): at the interval it names; never once it ended (null). */
export function pollDelay(read) {
  const after = read?.poll_after_seconds;
  if (read?.state === 'ready' || read?.state === 'refused' || after === null || after === undefined) return null;
  return Number.isFinite(Number(after)) && Number(after) >= 0 ? Number(after) * 1000 : null;
}

/**
 * After a read: how many have failed in a row, whether to say offline (L14: one failed read retries
 * quietly; only reads that keep failing say so) and when to read again, at least the served interval.
 */
export function afterRead(failed, ok, intervalMs, rule = READ_BACKOFF) {
  const failures = ok ? 0 : failed + 1;
  const backoff = failures === 0 ? 0 : Math.min(rule.maximumMs, rule.firstMs * 2 ** (failures - 1));
  return { failed: failures, offline: failures >= OFFLINE_AFTER_FAILED_READS, retryMs: Math.max(intervalMs ?? 0, backoff) };
}

/**
 * What a draft spent so far, from the draft read's raw `accounting` (exulanica.world-draft-
 * accounting/v1): reported and reconciled are spent; held and dispatched are not known yet.
 */
export function spentOf(accounting) {
  if (!accounting || typeof accounting !== 'object') return null;
  const usd = key => { const value = Number(accounting[key]); return Number.isFinite(value) && value > 0 ? value : 0; };
  // Served to eight places; summed back to eight, so float error never shows as a cent.
  const sum = (a, b) => Math.round((usd(a) + usd(b)) * 1e8) / 1e8;
  return { spentUsd: sum('reported_usd', 'reconciled_usd'), unknownUsd: sum('held_usd', 'unknown_liability_usd') };
}

/**
 * The cards under "Or start from" (N3): the server's recipes, then the workspace's kinds, each
 * { key, name, picture, priceUsd } as served, then Blank last. None is named in code but Blank,
 * which says it opens the workspace's blank world again once that world holds something its person
 * placed (N27, C4b): a newcomer's My world, made with the install, still reads "Build it yourself · Free".
 */
export function startCards(recipes = [], kinds = [], { blankHolds = false } = {}) {
  const served = [...recipes, ...kinds]
    .filter(card => card && typeof card.key === 'string' && typeof card.name === 'string' && card.name.trim())
    .map(card => ({ key: card.key, name: card.name, sub: cardSub(card.priceUsd), picture: typeof card.picture === 'string' ? card.picture : null, blank: false }));
  const sub = blankHolds ? CREATE_WORDS.opensMyWorldAgain : CREATE_WORDS.buildItYourself;
  return [...served, { key: 'blank', name: CREATE_WORDS.blank, sub, picture: null, blank: true }];
}

/** The next card's index for an arrow (K2), held at the ends. */
export const moveChoice = (index, count, by) => Math.max(0, Math.min(count - 1, index + by));

/**
 * Where Tab takes the focus so it stays within Create (C6): from the page's last stop to its first, and with Shift
 * from its first (or from the page itself, which holds the focus while a world is made) to its last; null lets the
 * browser move between the stops in between. `stops` are the page's own Tab stops in document order.
 */
export function wrapStop(stops, at, back) {
  if (stops.length === 0) return null;
  const index = stops.indexOf(at);
  if (index < 0) return back ? stops[stops.length - 1] : stops[0];
  if (back) return index === 0 ? stops[stops.length - 1] : null;
  return index === stops.length - 1 ? stops[0] : null;
}

/**
 * What a key does on frames 20 and 21 (spec 9, K2, K7, K8, N5, N6). `state`: { page: 'create' |
 * 'creating', focus: 'field' | 'box' | 'card' | 'button' | 'page', canCreate }. Fates:
 * - 'create' Enter in the field with words to make, or on the web notes box; 'start' Enter on a card; 'previous', 'next';
 * - 'leave' Esc, once, for Your worlds, the words kept (N6); on 21 the making carries on;
 * - 'type' the field takes the key as text (Shift+Enter a new line), and the page does nothing;
 * - 'quiet' a combination with Cmd or Ctrl: the browser keeps it (the field's undo), the page does nothing;
 * - 'pass' Tab, Enter or Space on a focused button, and Space on the web notes box, as anywhere;
 * - 'silence' anything else: the old shell's N H K I M O R G P Backspace ? among them.
 */
export function createKey(event, state) {
  const { page = 'create', focus = 'page', canCreate: ready = false } = state ?? {};
  if (event.metaKey || event.ctrlKey) return 'quiet';
  if (event.code === 'Escape') return event.repeat ? 'silence' : 'leave';
  if (event.code === 'Tab') return 'pass';
  if (focus === 'button' && (event.code === 'Enter' || event.code === 'NumpadEnter' || event.code === 'Space')) return 'pass';
  if (page !== 'create') return 'silence';
  if (focus === 'field') {
    if ((event.code === 'Enter' || event.code === 'NumpadEnter') && !event.shiftKey && !event.altKey) return ready && !event.repeat ? 'create' : 'silence';
    return 'type';
  }
  if (focus === 'box') {
    // The web notes box: Space ticks it, and Enter creates as from the field, as a form's box does.
    if (event.code === 'Space') return 'pass';
    if ((event.code === 'Enter' || event.code === 'NumpadEnter') && !event.shiftKey && !event.altKey) return ready && !event.repeat ? 'create' : 'silence';
  }
  if (focus === 'card') {
    // Space starts as Enter does: a card is a native button (N23); Space is not drawn.
    if (event.code === 'Enter' || event.code === 'NumpadEnter' || event.code === 'Space') return event.repeat ? 'silence' : 'start';
    if (event.code === 'ArrowLeft') return 'previous';
    if (event.code === 'ArrowRight') return 'next';
  }
  return 'silence';
}

/** What the page hands the opening world after a world is made, under this key in sessionStorage. */
export const MADE_HANDOFF_KEY = 'exulanica.made.v1';

/**
 * The handoff written for `entryId` once its draft is ready, or once Blank opened it: its made note's one line
 * (create-words.mjs's madeLine), or none; `build` opens the world in build mode with no banner and no note (N4).
 */
export const writeMade = (entryId, line, { build = false } = {}) => JSON.stringify({ entryId, line, ...(build ? { build: true } : {}) });

/** The handoff read back for `entryId`, or null where it names another world or is not well formed. */
export function readMade(text, entryId) {
  try {
    const value = JSON.parse(text ?? 'null');
    if (!value || value.entryId !== entryId) return null;
    return { entryId, line: typeof value.line === 'string' && value.line.trim() ? value.line : null, build: value.build === true };
  } catch {
    return null;
  }
}

/** The notes request's steps the page shows, in their order: the searches' plan, the searches and the reading. */
export const NOTES_STEPS = Object.freeze(['plan', 'search', 'read']);

/**
 * The notes' steps on frame 21 (WORDS.md "Web notes in Create, the words", item 3), from the request's served steps:
 * a running step is the one now, a done one done, a missed one drawn as not done with its time (item 4), and one
 * still waiting or skipped is not shown. `seconds` holds each step's time as the page saw it, by step: the request
 * states no times, so they are the page's own reads'.
 * @returns {{ key: string, words: string, state: 'done' | 'now' | 'next', time: string }[]}
 */
export function notesSteps(steps, seconds = {}) {
  const shown = [];
  for (const key of NOTES_STEPS) {
    const step = (steps ?? []).find((one) => one?.step === key);
    const state = step?.state === 'done' ? 'done' : step?.state === 'running' ? 'now' : step?.state === 'missed' ? 'next' : null;
    if (state === null) continue;
    shown.push({ key, words: NOTES_WORDS.steps[key], state, time: stepTime(Number(seconds[key] ?? 0)) });
  }
  return shown;
}

/**
 * What came of a finished notes request: `notes` where it kept notes to draft with, `nothing` where its searches
 * kept none, `notMade` where it failed, expired or was stopped; null while it runs.
 */
export function notesOutcome(request) {
  const status = request?.status;
  if (status === 'complete' || status === 'partial') return (request.notes?.length ?? 0) > 0 ? 'notes' : 'nothing';
  if (status === 'failed' || status === 'cancelled' || status === 'withdrawn' || status === 'expired') return 'notMade';
  return null;
}

/** Where notes do not come, the line in their place (item 4): from the request's outcome or the draft's own reason. */
export function notesNotUsedLine(outcome, code = null) {
  if (code === 'reference_not_for_this_tool') return NOTES_WORDS.notReached;
  if (outcome === 'nothing' || code === 'reference_has_no_notes') return NOTES_WORDS.nothingFound;
  return NOTES_WORDS.notMade;
}

/**
 * What a draft with web notes spent and may spend (items 3 and 5): the draft's own, with what the notes' model calls
 * spent as the draft read states it; where it states none (a request that kept no bundle), the notes' most is
 * counted as not known yet, so the line never reads as complete.
 */
export function withNotesSpent(spent, notesSpentUsd, notesMostUsd) {
  if (spent === null) return null;
  const known = notesSpentUsd !== null && notesSpentUsd !== undefined;
  const add = (a, b) => Math.round((Number(a) + Number(b ?? 0)) * 1e8) / 1e8;
  return { spentUsd: add(spent.spentUsd, known ? notesSpentUsd : 0), unknownUsd: add(spent.unknownUsd, known ? 0 : notesMostUsd) };
}
