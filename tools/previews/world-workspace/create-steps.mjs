// What making a world shows, from what the server serves (DESIGN's frames 20 and 21, rulings N3 to
// N12, L14): the offer to the page's state, a draft's reads to its steps and their times, when to
// read again, the draft read's accounting to what was spent, the cards, each key's fate and the
// made handoff. Pure, so verify-create-steps.mjs checks it in Node; the page draws what it returns.
import { OFFLINE_AFTER_FAILED_READS } from './world-ui-layout.mjs';
import { READ_BACKOFF } from './read-backoff.mjs';
import { CREATE_WORDS, STEP_WORDS, cardSub, stepTime } from './create-words.mjs';

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
 * which says it opens the workspace's blank world again where that world exists (N27).
 */
export function startCards(recipes = [], kinds = [], { blankExists = false } = {}) {
  const served = [...recipes, ...kinds]
    .filter(card => card && typeof card.key === 'string' && typeof card.name === 'string' && card.name.trim())
    .map(card => ({ key: card.key, name: card.name, sub: cardSub(card.priceUsd), picture: typeof card.picture === 'string' ? card.picture : null, blank: false }));
  const sub = blankExists ? CREATE_WORDS.opensMyWorldAgain : CREATE_WORDS.buildItYourself;
  return [...served, { key: 'blank', name: CREATE_WORDS.blank, sub, picture: null, blank: true }];
}

/** The next card's index for an arrow (K2), held at the ends. */
export const moveChoice = (index, count, by) => Math.max(0, Math.min(count - 1, index + by));

/**
 * What a key does on frames 20 and 21 (spec 9, K2, K7, K8, N5, N6). `state`: { page: 'create' |
 * 'creating', focus: 'field' | 'card' | 'button' | 'page', canCreate }. Fates:
 * - 'create' Enter in the field with words to make; 'start' Enter on a card; 'previous', 'next';
 * - 'leave' Esc, once, for Your worlds, the words kept (N6); on 21 the making carries on;
 * - 'type' the field takes the key as text (Shift+Enter a new line), and the page does nothing;
 * - 'quiet' a combination with Cmd or Ctrl: the browser keeps it (the field's undo), the page does nothing;
 * - 'pass' Tab, and Enter or Space on a focused button, as anywhere;
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
 * The made note's columns in order (N13), each { label, value }; an empty one is left out.
 * @param {{ inIt?: string | null, set?: string | null, notInItYet?: string | null, spent?: string | null }} values
 * @returns {{ label: string, value: string }[]}
 */
export function madeColumns({ inIt = null, set = null, notInItYet = null, spent = null }) {
  return [[CREATE_WORDS.inIt, inIt], [CREATE_WORDS.set, set], [CREATE_WORDS.notInItYet, notInItYet], [CREATE_WORDS.spent, spent]]
    .filter(([, value]) => typeof value === 'string' && value.trim())
    .map(([label, value]) => ({ label, value }));
}

/**
 * The handoff written for `entryId` once its draft is ready, or once Blank opened it: `build` opens
 * the world in build mode with no banner and no note (N4).
 */
export const writeMade = (entryId, columns, { build = false } = {}) => JSON.stringify({ entryId, columns, ...(build ? { build: true } : {}) });

/** The handoff read back for `entryId`, or null where it names another world or is not well formed. */
export function readMade(text, entryId) {
  try {
    const value = JSON.parse(text ?? 'null');
    if (!value || value.entryId !== entryId || !Array.isArray(value.columns)) return null;
    const labels = new Set([CREATE_WORDS.inIt, CREATE_WORDS.set, CREATE_WORDS.notInItYet, CREATE_WORDS.spent]);
    const columns = value.columns.filter(one => one && labels.has(one.label) && typeof one.value === 'string' && one.value.trim())
      .map(one => ({ label: one.label, value: one.value }));
    return { entryId, columns, build: value.build === true };
  } catch {
    return null;
  }
}
