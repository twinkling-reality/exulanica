/**
 * Who each person of a society last spoke with, so the crowd turns the two toward each other while
 * both stand: by a line said to someone, the one who said it and the one it was said to are each the
 * other's. It is read from the state's heard lines alone (a hearer keeps each line it heard, with who
 * said it and to whom), so the one who spoke is found through the one who heard. A line said to
 * everyone near names nobody, and a bystander who heard a line said to another is in no exchange.
 *
 * A society keeps heard lines by count and never ages them, so only a line said within a few minutes
 * of the state's minute counts: once an exchange is over, its people face as anybody does.
 */
import type { OwnedSocietyState } from './types.js';

/**
 * How many minutes after a line its speaker and the one it was said to still face each other while
 * both stand: an exchange of an ask, an answer and a close runs a minute a line, and two who spoke a
 * few minutes ago and have stood since are still in it.
 */
export const SPOKEN_FACING_MINUTES = 5;

/** Each person's latest partner by a line said to someone within `withinMinutes`, by person id. */
export function spokenPartners(
  state: Pick<OwnedSocietyState, 'tick' | 'inhabitants'>, withinMinutes: number = SPOKEN_FACING_MINUTES,
): ReadonlyMap<string, string> {
  const latest = new Map<string, { readonly tick: number; readonly other: string }>();
  const meet = (one: string, other: string, tick: number): void => {
    const held = latest.get(one);
    if (held === undefined || tick >= held.tick) latest.set(one, { tick, other });
  };
  for (const person of state.inhabitants) {
    for (const line of person.heard ?? []) {
      if (line.to !== person.id || line.from === person.id || state.tick - line.tick > withinMinutes) continue;
      meet(person.id, line.from, line.tick);
      meet(line.from, person.id, line.tick);
    }
  }
  return new Map([...latest].map(([id, { other }]) => [id, other]));
}
