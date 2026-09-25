/**
 * Which way a person faces while performing an activity, by the activity's key.
 *
 * One entry per activity a society states, each naming a rule:
 * - `place`: toward the object they use, across their place, as the kind's use states it, or on a
 *   seat the way the seat faces;
 * - `partner`: toward the person their state names as their partner (`goal.partner_id`);
 * - `held`: the way they last walked, as anyone standing still faces.
 *
 * An activity with no entry is drawn facing as `held` does, and the crowd names it
 * (`activity-has-no-facing`), so an activity a society adds is drawn as today until it has one.
 */
export type FacingRule = 'place' | 'partner' | 'held';

export const ACTIVITY_FACING: Readonly<Record<string, FacingRule>> = {
  rest: 'place',
  visit: 'place',
  talk: 'partner',
  stand: 'held',
  idle: 'held',
  move: 'held',
};

/** The facing rule an activity is drawn with, or null where none is stated. */
export function facingRule(activity: string): FacingRule | null {
  return Object.hasOwn(ACTIVITY_FACING, activity) ? ACTIVITY_FACING[activity]! : null;
}
