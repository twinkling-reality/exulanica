// The words of making a world (DESIGN's frames 20 to 22, WORDS.md "Making a world" and rulings N1
// to N20): the page draws them, and verify-create-words.mjs holds each one to WORDS.md. A server's
// code, `meaning` or `detail` is never shown; a code maps to one of these sentences.
import { amount } from './character-words.mjs';
import { NOTE_WORDS } from './world-words.mjs';

export const CREATE_WORDS = Object.freeze({
  wordmark: 'exulanica',
  title: 'Create a world',
  describeIt: 'Describe it',
  /** Today's placeholder, kept in the faint ink while the field is empty (N2). */
  placeholder: 'A harbour with fishing boats, a market on the quay and a lighthouse',
  create: 'Create',
  orStartFrom: 'Or start from',
  noModelFree: 'No AI model · Free',
  blank: 'Blank',
  buildItYourself: 'Build it yourself',
  /** Blank's sub-line where the workspace's blank world already exists: Blank reopens it (N27). */
  opensMyWorldAgain: 'Opens My world again',
  yourWorlds: 'Your worlds',
  start: 'Start',
  loading: 'Reading what you can make here…',
  creating: 'Creating your world',
  leave: 'You can leave this page. It carries on, and it waits in Your worlds.',
  beingMade: 'Being made…',
  madeFromYourWords: 'Made from your words',
  inIt: 'In it',
  set: 'Set',
  notInItYet: 'Not in it yet',
  spent: 'Spent',
  /** No AI model to make a world (N7): no key, or models not run here. */
  noModel: 'Making a world from your words needs an AI model, and none is connected here. You can still start from these:',
  /** The budget for AI models is spent (N7, J22, M11). */
  budgetSpent: 'The budget for AI models here is spent. You can still start from these:',
  /** Making from words is not offered here for a reason that is not a missing model (N25). */
  notOffered: 'Making a world from your words isn’t offered here. You can still start from these:',
  offline: NOTE_WORDS.offline,
});

/**
 * The server's draft states as steps (WORDS.md frame 21, N8, N11). A state the server does not
 * serve is not shown; "Drawing its land" waits for a land stage the draft read does not serve yet.
 */
export const STEP_WORDS = Object.freeze({
  queued: 'Waiting to start',
  choosing: 'Worked out what to make',
  drafting: 'Planning the place',
  making: 'Building it',
  land: 'Drawing its land',
});

/** The refusals' sentences (build sheet section 3, N8, N15), each said wherever it happened. */
export const REFUSAL_WORDS = Object.freeze({
  notAPlace: 'These words don’t describe a place, so no world could be made from them. Try a place and what is in it.',
  modelFailed: 'The AI model didn’t answer, so nothing was made. Try again in a minute.',
  worldLimit: 'You have as many worlds as one person can keep. Remove one in Your worlds to make another.',
  priceChanged: 'The price changed before it started. Here is the new most it can spend.',
  failed: 'Something went wrong while making it, so nothing was made. Try again.',
  hourlyLimit: 'You’ve started as many worlds as you can this hour. Try again later.',
  busy: 'A world is being made already. It waits in Your worlds when it’s done.',
  capacity: 'This computer is busy making other worlds. Try again in a few minutes.',
  budget: 'The budget for AI models here is spent.',
  tooSlow: 'The AI model took too long, so nothing was made. Try again.',
  interrupted: 'Making stopped part way, so nothing was kept. Try again.',
  /** N25: an offer without a price; said in the plain ink while the offer is read again. */
  priceUnavailable: 'The price can’t be read right now. Trying again.',
  tileBudget: 'You’ve reached today’s limit for new worlds. Try again tomorrow.',
  notDrafted: 'No world could be made from these words. Try again, or say it another way.',
});

/** Which sentence each served code says; any other code says `failed` (N8, "anything else"). */
export const REFUSAL_BY_CODE = Object.freeze({
  world_not_a_place: 'notAPlace',
  world_draft_model_failed: 'modelFailed',
  kind_draft_model_failed: 'modelFailed',
  world_limit_reached: 'worldLimit',
  world_draft_price_expired: 'priceChanged',
  world_draft_operation_changed: 'priceChanged',
  world_draft_bound_too_small: 'priceChanged',
  world_draft_failed: 'failed',
  kind_draft_failed: 'failed',
  kind_work_unavailable: 'failed',
  kind_draft_limit: 'hourlyLimit',
  kind_draft_busy: 'busy',
  kind_draft_capacity: 'capacity',
  budget_exceeded: 'budget',
  process_budget_spent: 'budget',
  process_share_spent: 'budget',
  world_draft_unanswered: 'tooSlow',
  kind_draft_unanswered: 'tooSlow',
  world_draft_interrupted: 'interrupted',
  world_draft_price_unavailable: 'priceUnavailable',
  tile_budget_reached: 'tileBudget',
  world_not_drafted: 'notDrafted',
});

/** The sentence for a refusal's code; never the code, its `meaning` or its `detail`. */
export function refusalWords(code) {
  const key = typeof code === 'string' && Object.hasOwn(REFUSAL_BY_CODE, code) ? REFUSAL_BY_CODE[code] : 'failed';
  return REFUSAL_WORDS[key];
}

/** The field's count (N1): "86 of 1000" from the first letter; an empty field has none. */
export function countWords(length, limit) {
  return length > 0 ? `${length} of ${limit}` : null;
}

/** A limit in dollars rounded up to the cent, as WORLDMAKING says the offer's figure ("$1.43"). */
export function ceilingAmount(usd) {
  const value = Number(usd);
  if (!Number.isFinite(value) || value <= 0) return amount(0);
  return amount(Math.ceil(value * 100 - 1e-9) / 100);
}

/** The line under the field with the offer's most (frame 20). */
export const priceLine = maximumUsd =>
  `An AI model makes it from your words: at most ${ceilingAmount(maximumUsd)}, and you see what it really spent.`;

/** Starts left this hour, shown only when three or fewer remain (N19); none left is a refusal. */
export function startsLeftLine(left) {
  if (!Number.isSafeInteger(left) || left <= 0 || left > 3) return null;
  return left === 1 ? '1 more world can be started this hour.' : `${left} more worlds can be started this hour.`;
}

/** A card's sub-line (N3, N23): free and drawn without a model, or the served price, a line of its own. */
export const cardSub = priceUsd => Number(priceUsd) > 0 ? `At most ${amount(priceUsd)}` : CREATE_WORDS.noModelFree;

/** A step's time (N11): "1 s", "59 s", "1 min 4 s"; a whole minute "2 min". */
export function stepTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '';
  const whole = Math.floor(seconds), minutes = Math.floor(whole / 60), rest = whole % 60;
  if (minutes === 0) return `${rest} s`;
  return rest === 0 ? `${minutes} min` : `${minutes} min ${rest} s`;
}

/** What is known spent, with a part not known yet (N10, as a run says it, J5). */
function spentSoFar(spentUsd, unknownUsd) {
  const spent = amount(spentUsd);
  return Number(unknownUsd) > 0 ? `${spent}, and up to ${amount(unknownUsd)} not known yet` : spent;
}

/** The made note's Spent value (frame 22): "$0.31 of the $1.43 set aside", with a part not known yet. */
export const madeSpent = ({ spentUsd, unknownUsd = 0 }, maximumUsd) =>
  `${amount(spentUsd)} of the ${ceilingAmount(maximumUsd)} set aside${Number(unknownUsd) > 0 ? `, and up to ${amount(unknownUsd)} not known yet` : ''}`;

/** Under frame 21's steps, live (N10): "Spent $0.12 of the $1.43 set aside". */
export const spendLine = (spent, maximumUsd) => `Spent ${madeSpent(spent, maximumUsd)}`;

/** Under a refusal where anything was spent (N9): "Spent $0.02 before it stopped." */
export const refusalSpent = ({ spentUsd, unknownUsd = 0 }) =>
  Number(spentUsd) > 0 || Number(unknownUsd) > 0 ? `Spent ${spentSoFar(spentUsd, unknownUsd)} before it stopped.` : null;

const quoted = words => words.map(phrase => `“${phrase}”`).join(', ');
const capital = words => words.charAt(0).toUpperCase() + words.slice(1);
const lower = words => words.charAt(0).toLowerCase() + words.slice(1);

/**
 * The made note's Set value (TERRAIN's WORDING.md, N13, N26): the Set line without its "Set" and its
 * full stop, and without "You can change this later in Design.", starting with a capital as every
 * value in the note does. A setting taken: its titles (every one after the first in lower case),
 * then the land, then the words. `land` is the draft read's served `land` ({ title, chosen_by,
 * words, fell_back }); `setting` its `setting` ({ parts, words }). Null for a town, or a server that
 * makes places level (no `land`).
 */
export function setValue(land, setting = null) {
  if (!land || typeof land.title !== 'string') return null;
  if (land.fell_back) return `On level ground, since this place did not fit the land ${land.title}`;
  if (setting && Array.isArray(setting.parts) && setting.parts.length > 0) {
    const titles = setting.parts.map((part, at) => (at === 0 ? capital(part.title) : lower(part.title))).join(', ');
    return `${titles}, ${land.title}, for your words ${quoted(setting.words ?? [])}`;
  }
  if (land.chosen_by === 'words' && Array.isArray(land.words) && land.words.length > 0) return `${capital(land.title)}, for your words ${quoted(land.words)}`;
  return capital(land.title);
}
