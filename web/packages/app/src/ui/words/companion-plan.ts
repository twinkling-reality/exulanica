/**
 * What the Companion says about a plan it prepared: the sheet's words, a refusal by its code and a
 * clarification by its code (`ACTION_REFUSALS` and `CLARIFICATIONS` in
 * `exulanica/selection/action_plan.py`). Two sentences for a refusal, what happened and what to do
 * next (interface-system.md 5). Codes stay in the technical record; a code without words here
 * gets the general pair.
 */

import type { RefusalWords } from '../actions/registry.js';

export const PLAN_WORDS = Object.freeze({
  title: 'Check this plan',
  intro: 'Your Companion would do this, in order. Nothing changes until you confirm.',
  spends: 'Carrying this out can ask a model you chose, which can cost money.',
  spendsNot: 'Carrying this out asks no model.',
  confirm: 'Confirm',
  cancel: 'Cancel',
  close: 'Close',
  spoken: 'Here is what I would do. Check it, then confirm.',
  done: 'Done. Every step happened.',
  /** `{done}` of `{all}` steps. */
  partly: 'Partly done: {done} of {all} steps happened.',
  none: 'Nothing was changed.',
  pausedOffer: 'The world is paused. Play it again when you want it to run.',
  notReached: 'Not reached',
  notDone: 'Not done',
  didHappen: 'Done',
  notSentRoute: 'This step was not sent: it names another change than the one it says.',
  unsentLabel: 'A step I cannot send',
  clarifyTitle: 'One question first',
});

/** The general pair, for a refusal code this table has no words for. */
export const PLAN_REFUSED: RefusalWords = {
  happened: 'I could not turn that into a change I can make here.',
  next: 'Try saying it another way, or make the change yourself.',
};

/** A plan the server refused, by its code. */
export const PLAN_REFUSAL_WORDS: Readonly<Record<string, RefusalWords>> = Object.freeze({
  stale_version: {
    happened: 'This world changed while I was reading what you asked.',
    next: 'Ask again and I will plan against what it is now.',
  },
  action_not_offered: {
    happened: 'That is not a change I can make in this world.',
    next: 'Look at what you can do here: ask “what can I do here?”',
  },
  action_unsupported: {
    happened: 'That is not a change this kind of world takes.',
    next: 'Look at what you can do here: ask “what can I do here?”',
  },
  action_unavailable: {
    happened: 'That change is not available in this world right now.',
    next: 'Something it needs is not ready yet, such as people living here.',
  },
  action_not_permitted: {
    happened: 'Your access does not include that change.',
    next: 'Ask the owner of this workspace.',
  },
  not_in_catalogue: {
    happened: 'That is not one of the objects I can place.',
    next: 'Open Add object to see the ones there are.',
  },
  not_understood: PLAN_REFUSED,
  not_drafted: PLAN_REFUSED,
  preview_blocked: {
    happened: 'That change cannot be made where you are pointing.',
    next: 'Point somewhere else in this world, then ask again.',
  },
  no_change: {
    happened: 'The world is already that way.',
    next: 'Nothing needed to change.',
  },
});

/** A plan that needs one more answer first, by its code. */
export const PLAN_CLARIFY_WORDS: Readonly<Record<string, string>> = Object.freeze({
  asset_ambiguous: 'Which object did you mean?',
  object_ambiguous: 'Which object did you mean?',
  object_required: 'Which object should change? Select it in the world, then ask again.',
  arrangement_ambiguous: 'Which arrangement did you mean?',
  origin_role_required: 'Is it invented for this world, or connected to something you experienced?',
  placement_required: 'Where should it go? Stand where you want it and face that way, then ask again.',
  viewer_required: 'Where should it go? Stand where you want it, then ask again.',
  speed_required: 'How fast should the world play?',
  minutes_required: 'How many minutes should the world move on, from 1 to 10?',
  region_required: 'Which place should the people come into?',
});

export function planRefusalWords(code: string): RefusalWords {
  return PLAN_REFUSAL_WORDS[code] ?? PLAN_REFUSED;
}
