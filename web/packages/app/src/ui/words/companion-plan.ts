/**
 * What the Companion says about a plan it prepared: the sheet's words, a refusal by its code and a
 * clarification by its code (`ACTION_REFUSALS` and `CLARIFICATIONS` in
 * `exulanica/selection/action_plan.py`). Two sentences for a refusal, what happened and what to do
 * next (interface-system.md 5). Codes stay in the technical record; a code without words here
 * gets the general pair.
 */

import type { RefusalWords } from '../actions/registry.js';
import type { MindCost, MindFacts, PieceEstimate } from '../../companion-actions-api.js';

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
  /** A step asking one of the world's beings, waiting for the minute that can take it. */
  nextMinute: 'At the world’s next minute',
  /** A step asking a being to go where every place is taken this minute: `{place}` with its article. */
  freePlace: 'Waiting for a free place at {place}.',
  /** The same step while the world is paused: it waits for the person to move the world on. */
  pausedMinute: 'At the world’s next minute: the world is paused, so play it or move it on a minute.',
});

/** A step that waited for the world's next minute and saw none come. */
export const PLAN_WAITED: RefusalWords = {
  happened: 'The world did not move on, so this step was not sent.',
  next: 'Play the world, or move it on a minute, then ask again.',
};

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
  kind_ambiguous: 'Which kind of thing did you mean?',
  anchor_ambiguous: 'Which one should it go beside?',
  being_required: 'Who should do it?',
  being_ambiguous: 'Who did you mean?',
  place_required: 'Where should they go?',
  place_ambiguous: 'Which place did you mean?',
  thing_ambiguous: 'Which thing did you mean?',
  whom_required: 'Who should it decide for? Choose a group here, or select someone in the world and ask again.',
  whom_ambiguous: 'Who did you mean?',
  mind_required: 'Which mind should decide for them?',
  mind_ambiguous: 'Which mind did you mean?',
  too_many_people_for_models: 'That is more beings than AI models run in this world at once. Who instead?',
});

/**
 * The question a choice past the world's bound asks, with its figures where the plan states them:
 * how many were asked for, how many AI models may run here at once, and how many they run now.
 */
export function tooManyForModelsWords(facts: Readonly<Record<string, number>>): string {
  const asked = facts['asked']; const bound = facts['bound']; const running = facts['run_now'];
  if (asked === undefined || bound === undefined) return PLAN_CLARIFY_WORDS['too_many_people_for_models']!;
  const now = running === undefined || running === 0 ? '' : `, and ${running} ${running === 1 ? 'has' : 'have'} one already`;
  return `You asked for ${asked}, and AI models decide for at most ${bound} beings here at once${now}. Who instead?`;
}

/**
 * A question asked of one slot rather than of the code's usual one: `being_required` on a give or
 * take's other being (`with_id`) asks who receives or lets go, not who acts.
 */
export const PLAN_CLARIFY_SLOT_WORDS: Readonly<Record<string, string>> = Object.freeze({
  'being_required:with_id': 'Who is the other person? Click them in the world, then ask again.',
});

/** A step asking a being to use their hands, by act: `{subject}`, `{thing}`, `{with}` filled in. */
export const PLAN_HANDS_WORDS: Readonly<Record<string, string>> = Object.freeze({
  pick_up: '{subject}, pick up the {thing}',
  put_down: '{subject}, put down the {thing}',
  give: '{subject}, give the {thing} to {with}',
  take: '{subject}, take the {thing} from {with}',
});

/** Why some of a group were left out of a choice, by the models route's own code. */
const MIND_LEFT_OUT: Readonly<Record<string, string>> = Object.freeze({
  being_played: 'someone is playing them',
  decided_from_outside: 'a program from outside this world decides for them',
  decider_not_allowed: 'their kind cannot be given this kind of mind',
  person_not_in_this_world: 'they are not here any more',
  subject_chosen_under_another_role: 'a model already decides for them in another way',
});

/** US dollars from a decimal string, small sums kept: "$0.25", "$0.0031", "under $0.0001". */
function smallDollarsWords(usd: string): string {
  const value = Number(usd);
  if (value >= 0.01) return `$${value.toFixed(2)}`;
  return value < 0.0001 ? 'under $0.0001' : `$${value.toFixed(4)}`;
}

/**
 * A bound in US dollars, never said below itself: rounded up at the precision shown (cents from a
 * cent up, a hundredth of a cent below), so "at most $0.02" holds for a bound of $0.0149.
 */
export function atMostDollarsWords(usd: string): string {
  // Counted in whole digits of the decimal string, so no binary fraction can round a bound down.
  const [whole = '0', fraction = ''] = usd.split('.');
  const up = (places: number): string => {
    const kept = Number(`${whole}${fraction.padEnd(places, '0').slice(0, places)}`);
    const more = /[1-9]/u.test(fraction.slice(places));
    return ((kept + (more ? 1 : 0)) / 10 ** places).toFixed(places);
  };
  const value = Number(usd);
  if (value >= 0.01) return `$${up(2)}`;
  return value <= 0 ? '$0.00' : `$${up(4)}`;
}

/** A later mind step that names more beings when it is sent than the sheet showed: never sent. */
export const MIND_GREW: RefusalWords = {
  happened: 'This world changed since you checked the plan: that choice would now name more beings than you were shown.',
  next: 'Nothing more was changed. Ask again to see what it comes to now.',
};

/** A question the plan needs answered in the middle of carrying it out, by its code. */
export function midRunQuestionWords(code: string, facts: Readonly<Record<string, number>>): RefusalWords {
  const question = code === 'too_many_people_for_models' ? tooManyForModelsWords(facts)
    : PLAN_CLARIFY_WORDS[code] ?? PLAN_CLARIFY_WORDS['asset_ambiguous']!;
  return { happened: `This step needs an answer first: ${question}`, next: 'Nothing more was changed. Ask for it on its own.' };
}

/** A mind step's row: "Nemotron 3 Nano 30B decides for every villager", "Knight: their own routine". */
export function mindDetailWords(whom: string, mind: string, routine: boolean): string {
  return routine ? `${whom.charAt(0).toUpperCase()}${whom.slice(1)}: ${mind}` : `${mind} decides for ${whom}`;
}

/**
 * What a choice of who decides comes to, said before the yes: how many beings it names, who was
 * left out and why, what a model may cost while the world plays (at most, by the host's own
 * reservation; the world's hourly ceilings) or that no AI is asked, and whether this server asks
 * models here at all. Choosing asks no model; playing the world does.
 */
export function mindChoiceWords(facts: MindFacts, cost: MindCost | null, routine: boolean): string {
  const count = `${facts.subjects} being${facts.subjects === 1 ? '' : 's'}`;
  const left = Object.entries(facts.leftOut).map(([code, number]) =>
    `${number} left out because ${MIND_LEFT_OUT[code] ?? 'they cannot be chosen for now'}`);
  const who = `This is for ${count}${left.length === 0 ? '' : ` (${left.join('; ')})`}.`;
  if (routine) return `${who} No AI is asked and nothing is spent.`;
  if (facts.hostRefusal !== null || facts.modelRefusal !== null) {
    return `${who} This server does not ask this model here now, so they keep their own routine until it does. The choice is kept.`;
  }
  if (cost === null) return `${who} Choosing asks no model. While the world plays, each is asked at their own choices, which can cost money.`;
  const ceiling = cost.usdPerWorldHour === null ? ''
    : ` This world stops asking models at ${smallDollarsWords(cost.usdPerWorldHour)}`
      + `${cost.decisionsPerWorldHour === null ? '' : ` or ${cost.decisionsPerWorldHour} decisions`} an hour, whatever is chosen.`;
  const typical = cost.usdTypical === null ? ' No typical figure is measured for this world yet.'
    : ` Typically about ${smallDollarsWords(cost.usdTypical)}.`;
  return `${who} Choosing asks no model. While the world plays, at most ${atMostDollarsWords(cost.usdAtMost)} a simulated minute `
    + `(at most ${atMostDollarsWords(cost.usdPerAnswerAtMost)} each time a being is asked, at most once a minute).${typical}${ceiling}`;
}

export function planRefusalWords(code: string): RefusalWords {
  return PLAN_REFUSAL_WORDS[code] ?? PLAN_REFUSED;
}

/** A span of seconds in words: "under a minute", "about 1 minute", "about 12 minutes". */
function minutesWords(seconds: number): string {
  if (seconds < 45) return 'under a minute';
  const minutes = Math.max(1, Math.round(seconds / 60));
  return `about ${minutes} minute${minutes === 1 ? '' : 's'}`;
}

/** US dollars from a decimal string: "$0.05", or "under $0.01". */
function dollarsWords(usd: string): string {
  const value = Number(usd);
  return value < 0.01 ? 'under $0.01' : `$${value.toFixed(2)}`;
}

/**
 * What new pieces would take, said before the yes (GEN's estimate, unchanged): the time while the
 * piece maker runs and if it has to start, the cost typically and at most on the provider, and where
 * the figures come from. Nothing is asked or spent until the person confirms.
 */
export function pieceEstimateWords(estimate: PieceEstimate): string {
  const pieces = `${estimate.items} new piece${estimate.items === 1 ? '' : 's'}`;
  const time = `${minutesWords(estimate.allSecondsWarm)} while the piece maker runs (the first in ${minutesWords(estimate.firstSecondsWarm)}), `
    + `and ${minutesWords(estimate.coldStartSeconds)} more if it has to start`;
  const cost = `about ${dollarsWords(estimate.usdTypical)}, at most ${dollarsWords(estimate.usdWorstCase)}, on ${estimate.providerLabel}`;
  const basis = estimate.basis.kind === 'measured_runs'
    ? `figures from ${estimate.basis.runs} measured run${estimate.basis.runs === 1 ? '' : 's'} of ${estimate.basis.items} pieces`
    : 'figures from the piece maker\'s table, not from measured runs';
  return `${pieces}: ${time}; ${cost} (${basis}). Nothing is made or spent until you confirm.`;
}

/**
 * The codes that mean the world moved on since the page read it. A prepare says so as a refused
 * plan (`stale_version`), never as an error; a sent step's own route says so with 409
 * `stale_structural_base`, `stale_object_base` or `stale_saved_world_entry` (a version edit) or
 * `stale_society_state` (a society action or control).
 */
export const STALE_PREPARE_CODES: ReadonlySet<string> = new Set([
  'stale_version', 'stale_structural_base', 'stale_object_base', 'stale_saved_world_entry', 'stale_society_state',
]);

/** The named errors a prepare itself can fail with, in words. */
const PREPARE_ERROR_WORDS: Readonly<Record<string, RefusalWords>> = Object.freeze({
  unknown_reference: {
    happened: 'This world, or something the step names, is no longer there.',
    next: 'Reload the page, then ask again.',
  },
  unavailable_asset: {
    happened: 'That object’s files are not available right now.',
    next: 'Choose another object, or ask again later.',
  },
});

/** A prepare the server refused outright, by what it said: never "the world changed" unless it did. */
export const PREPARE_FAILED: RefusalWords = {
  happened: 'The world did not take the step I prepared.',
  next: 'Reload the page, then ask again, or make the change yourself.',
};

/** A prepare that reached no server answer at all. */
export const PREPARE_UNREACHED: RefusalWords = {
  happened: 'I could not reach the world to prepare this step.',
  next: 'Check the connection, then ask again.',
};

/**
 * Why a prepare failed, by the server's code where it gave one (`status` set): a stale world's
 * codes say the world changed, a code with words of its own says those, any other says the world
 * did not take the step, and its code stays in the record; no answer at all says so.
 */
export function prepareFailureWords(failure: { readonly status: number; readonly code: string } | null): RefusalWords {
  if (failure === null) return PREPARE_UNREACHED;
  if (STALE_PREPARE_CODES.has(failure.code)) return PLAN_REFUSAL_WORDS['stale_version']!;
  return PREPARE_ERROR_WORDS[failure.code] ?? PLAN_REFUSAL_WORDS[failure.code] ?? PREPARE_FAILED;
}
