/**
 * What a person reads when a small square cannot be placed: what happened, and what they can do.
 *
 * One sentence pair for each code the server declares (`ARRANGEMENT_REFUSALS`, read by a test from
 * `exulanica/world/arrangements.py`). Each second sentence names something the person can do, and
 * every one says the world was left as it was, because a refused arrangement writes nothing.
 */

import { ApiError } from '@exulanica/graph-client';

import { isArrangementRefusal, type ArrangementRefusal } from '../arrangement-api.js';
import { problemDetail } from '../world-objects-api.js';
import { explainCompositionFailure, type CompositionExplanation } from './composition-preview.js';

const WORDS: Readonly<Record<ArrangementRefusal, readonly [string, string]>> = Object.freeze({
  arrangement_unknown: [
    'This world does not offer that arrangement.',
    'Nothing was changed. Reload the world to see what it offers.',
  ],
  arrangement_needs_authored_ground: [
    'A small square can only stand in a world built on its own ground, like one you started yourself.',
    'Nothing was changed. Start a world of your own to add one there.',
  ],
  arrangement_outside_ground: [
    'There is not room for the square here: part of it would stand past the edge of the ground people walk on.',
    'Nothing was changed. Turn toward the middle of your world, or walk closer to it, and try again.',
  ],
  arrangement_covers_arrival: [
    'The square would stand where people arrive in this world.',
    'Nothing was changed. Turn away from the arrival point, or walk further from it, and try again.',
  ],
  arrangement_overlaps: [
    'Something already stands where the square would go, or where people stand to use it.',
    'Nothing was changed. Turn toward open ground, or take that object away first, and try again.',
  ],
  stale_base: [
    'This world changed while you were deciding.',
    'Nothing was changed. What is shown is current; check again.',
  ],
  source_invalidated: [
    'The place this version was built on was deleted.',
    'Nothing was changed, and nothing more can be added to this version.',
  ],
  asset_bytes_unavailable: [
    'The objects in the square are not stored on this server.',
    'Nothing was changed. Try again once they are stored.',
  ],
  invalid_placement: [
    'The world did not accept where the square would stand.',
    'Nothing was changed. Move a few steps and try again.',
  ],
  subject_already_present: [
    'Part of the square is already in this world.',
    'Nothing was changed. Check again to place a new one.',
  ],
});

/** The words for one refusal code, or the generic pair for a code this client does not know. */
export function explainArrangementRefusal(
  code: string,
  detail: string | null = null,
): CompositionExplanation {
  const [happened, next] = isArrangementRefusal(code)
    ? WORDS[code]
    : ['The world refused to place the square.', 'Nothing was changed.'];
  return Object.freeze({ happened, next, code, detail, outcome: 'unchanged' as const });
}

/** A thrown failure: a named refusal in its own words, anything else as a composition says it. */
export function explainArrangementFailure(
  error: unknown,
  phase: 'preview' | 'apply',
): CompositionExplanation {
  if (error instanceof ApiError && error.code === 'arrangement_refused') {
    return explainArrangementRefusal(problemDetail(error));
  }
  return explainCompositionFailure(error, phase);
}

/** Refusals a fresh check can clear: a newer base, or a new identity for what would be added. */
export const RECHECKABLE_ARRANGEMENT_REFUSALS: ReadonlySet<string> = new Set([
  'stale_base',
  'subject_already_present',
]);
