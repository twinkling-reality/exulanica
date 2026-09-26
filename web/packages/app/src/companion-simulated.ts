/**
 * The simulated people and places an answer about the world's people names, drawn by this page.
 *
 * The server never puts an inhabitant's name in an answer: it writes `[inhabitant A]` and
 * `[spot A]`, and says which inhabitant and which society target each stands for
 * (`exulanica/selection/society_question.py`). The name is the one the society this page shows
 * gives that person, and a place is named by the person's own object at that target, exactly as the
 * inspector names it. Each is drawn as simulated, never as somebody from the account holder's
 * library, and one this page cannot draw is said in words, never shown as brackets.
 */

import type { SpokenPiece } from './companion-names.js';
import { phrase } from './society-inhabitant-words.js';

/**
 * A simulated placeholder, as the server writes one: `INHABITANT_PLACEHOLDER` and
 * `_SPOT_PLACEHOLDER` in `exulanica/selection/society_question.py`, held equal by
 * `tests/test_companion_simulated_parity.py`.
 */
export const SIMULATED_PLACEHOLDER_SOURCE = '(\\[(?:inhabitant|spot) [A-Z]+\\])';

/** What the page shows of its society: each person's name, and each usable target's label. */
export interface SocietyNames {
  readonly versionId: string;
  readonly people: ReadonlyMap<string, string>;
  readonly spots: ReadonlyMap<string, string>;
}

export interface SimulatedPiece {
  readonly kind: 'simulated';
  readonly text: string;
  readonly placeholder: string;
  readonly subject: 'inhabitant' | 'spot';
  /** The inhabitant or target the placeholder stands for, or null where the answer does not say. */
  readonly id: string | null;
  /** False where this page could not draw it and says so in words. */
  readonly drawn: boolean;
}

export type DrawnPiece = SpokenPiece | SimulatedPiece;

/** What an answer says each simulated placeholder stands for. */
export interface SimulatedReferences {
  readonly inhabitants?: Readonly<Record<string, { readonly versionId: string; readonly inhabitantId: string }>>;
  readonly spots?: Readonly<Record<string, string>>;
}

const startsSentence = (before: string): boolean => before.trim() === '' || /[.!?:]\s+$/.test(before);

/** Each text piece with the simulated placeholders it carries drawn from `society`. */
export function drawSimulated(
  pieces: readonly SpokenPiece[],
  answer: SimulatedReferences,
  society: SocietyNames | null,
): DrawnPiece[] {
  const drawn: DrawnPiece[] = [];
  let before = '';
  for (const piece of pieces) {
    if (piece.kind !== 'text') {
      drawn.push(piece);
      before += piece.text;
      continue;
    }
    let at = 0;
    for (const match of piece.text.matchAll(new RegExp(SIMULATED_PLACEHOLDER_SOURCE, 'g'))) {
      const start = match.index;
      const placeholder = match[0];
      if (start > at) drawn.push({ kind: 'text', text: piece.text.slice(at, start) });
      const subject = placeholder.startsWith('[inhabitant') ? 'inhabitant' : 'spot';
      const reference = subject === 'inhabitant' ? answer.inhabitants?.[placeholder] : undefined;
      const id = subject === 'inhabitant' ? reference?.inhabitantId ?? null : answer.spots?.[placeholder] ?? null;
      const sameSociety = society !== null && (reference === undefined || reference.versionId === society.versionId);
      const name = id === null || !sameSociety
        ? undefined
        : (subject === 'inhabitant' ? society.people : society.spots).get(id);
      const said = name ?? phrase(subject === 'inhabitant' ? 'inhabitant_unresolved' : 'place_gone');
      const text = name === undefined && startsSentence(before + piece.text.slice(0, start))
        ? said.charAt(0).toUpperCase() + said.slice(1)
        : said;
      drawn.push({ kind: 'simulated', text, placeholder, subject, id, drawn: name !== undefined });
      at = start + placeholder.length;
    }
    if (at < piece.text.length) drawn.push({ kind: 'text', text: piece.text.slice(at) });
    before += piece.text;
  }
  return drawn;
}
