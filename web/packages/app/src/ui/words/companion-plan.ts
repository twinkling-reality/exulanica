/**
 * What the Companion says about a plan it prepared: the sheet's words, a refusal by its code and a
 * clarification by its code (`ACTION_REFUSALS` and `CLARIFICATIONS` in
 * `exulanica/selection/action_vocabulary.py`). Two sentences for a refusal, what happened and what to do
 * next (interface-system.md 5). Codes stay in the technical record; a code without words here
 * gets the general pair.
 */

import type { RefusalWords } from '../actions/registry.js';
import type { BudgetDemand, BudgetSheet, Erases, MindCost, MindFacts, PieceEstimate } from '../../companion-actions-api.js';

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
  budget_required: 'How much may this world spend on AI minds in an hour? Say an amount, such as 50 cents an hour, or a number of decisions an hour.',
  budget_ambiguous: 'Which amount did you mean?',
  budget_period: 'A world’s budget for AI minds is by the hour of real time, and I will not work an hour’s figure out of another span. What may it spend in an hour?',
});

/**
 * A question about a budget, with the budget the world has now where the plan states it
 * (`usd_per_hour_microusd`, `decisions_per_hour`), so a new figure is said against the old one.
 */
export function budgetQuestionWords(code: string, facts: Readonly<Record<string, number>>): string {
  const asked = PLAN_CLARIFY_WORDS[code] ?? PLAN_CLARIFY_WORDS['budget_required']!;
  const micro = facts['usd_per_hour_microusd']; const decisions = facts['decisions_per_hour'];
  if (micro === undefined || decisions === undefined) return asked;
  return `${asked} Now it is ${budgetWords((micro / 1_000_000).toFixed(6), decisions)} an hour.`;
}

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

/** A mind step the sheet showed no count or cost of when the plan was confirmed: never sent. */
export const MIND_UNSHOWN: RefusalWords = {
  happened: 'This choice of who decides was not shown with its count and cost when you confirmed, so it was not sent.',
  next: 'Nothing more was changed. Ask for it on its own.',
};

/**
 * Said of a later mind step the plan could not prepare: it was judged as the world stands now,
 * alone, so an earlier step of the same plan that makes room for it is not counted.
 */
export const LATER_MIND_JUDGED_NOW = 'This was checked as the world stands now, before the earlier steps of this plan. If they make room for it, ask for it on its own after them.';

/** A question the plan needs answered in the middle of carrying it out, by its code. */
export function midRunQuestionWords(code: string, facts: Readonly<Record<string, number>>): RefusalWords {
  const question = code === 'too_many_people_for_models' ? tooManyForModelsWords(facts)
    : PLAN_CLARIFY_WORDS[code] ?? PLAN_CLARIFY_WORDS['asset_ambiguous']!;
  return { happened: `This step needs an answer first: ${question}`, next: 'Nothing more was changed. Ask for it on its own.' };
}

/**
 * Said beside a model's cost: an answer the model does not finish (it runs to its length bound) is
 * refused, the being's routine decides that turn, and the provider still bills it.
 */
export const MIND_UNFINISHED_BILLED = 'An answer a model does not finish is still billed.';

/** A mind step's row: "Nemotron 3 Nano 30B decides for every villager", "Knight: their own routine". */
export function mindDetailWords(whom: string, mind: string, routine: boolean): string {
  return routine ? `${whom.charAt(0).toUpperCase()}${whom.slice(1)}: ${mind}` : `${mind} decides for ${whom}`;
}

/**
 * What a choice of who decides comes to, said before the yes: how many beings it names, who was
 * left out and why, what a model may cost while the world plays (at most, by the host's own
 * reservation; the world's ceilings over any hour of real time, which is how the host counts
 * them) or that no AI is asked, and whether this server asks models here at all. Choosing asks no
 * model; playing the world does.
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
  // The world's budget for this hour asks nobody now: said first, whatever the role's capability reads.
  if (cost.refusedNow !== null) {
    return `${who} ${BUDGET_REFUSED_NOW[cost.refusedNow] ?? BUDGET_REFUSED_NOW['world_hour_decisions_spent']!} `
      + 'Until then they keep their own routine. The choice is kept.';
  }
  const ceiling = cost.usdPerWorldHour === null ? ''
    : ` This world stops asking models at ${atMostDollarsWords(cost.usdPerWorldHour)}`
      + `${cost.decisionsPerWorldHour === null ? '' : ` or ${cost.decisionsPerWorldHour} decisions`} in any hour of real time, whatever is chosen.`;
  const typical = cost.usdTypical === null ? ' No typical figure is measured for this model here yet.'
    : ` Typically about ${smallDollarsWords(cost.usdTypical)} a minute of this world${cost.typicalIsEstimate ? ', an estimate from a measurement that was cut short' : ', as measured in a world like this one'}.`;
  return `${who} Choosing asks no model. While the world plays, at most ${atMostDollarsWords(cost.usdAtMost)} a minute of this world `
    + `(at most ${atMostDollarsWords(cost.usdPerAnswerAtMost)} each time a being is asked, at most once a minute). `
    + `${MIND_UNFINISHED_BILLED}${typical}${ceiling}`;
}

/** Why a world's budget asks no AI model right now, by the server's own reason. */
const BUDGET_REFUSED_NOW: Readonly<Record<string, string>> = Object.freeze({
  world_hour_decisions_spent: 'This world’s budget of AI decisions for the hour is used up, so no AI model is asked until the hour moves on or the budget is raised.',
  world_hour_spend_spent: 'This world’s budget of money for AI minds this hour is used up, so no AI model is asked until the hour moves on or the budget is raised.',
});

/** A budget's two figures: "$0.50 and 600 decisions". Dollars are never said below themselves. */
export function budgetWords(usdPerHour: string, decisionsPerHour: number): string {
  return `${atMostDollarsWords(usdPerHour)} and ${decisionsPerHour.toLocaleString('en-US')} decision${decisionsPerHour === 1 ? '' : 's'}`;
}

const count = (value: number, one: string, many = `${one}s`): string => `${value.toLocaleString('en-US')} ${value === 1 ? one : many}`;

function demandWords(demand: BudgetDemand, estimate: boolean): string {
  const asks = `about ${count(demand.asksPerRealHour, 'ask')} an hour at this speed${estimate ? ' (an estimate)' : ''}`;
  return demand.minutesCovered >= 60 ? `${asks}, which this budget covers`
    : `${asks}, so this budget is used up after about ${count(demand.minutesCovered, 'minute')} of each hour`;
}

/**
 * What a budget for a world's AI minds comes to, said before the yes, one sentence a line: the
 * budget now (and whose it is: the world's, whoever has it open) and after; which of its two
 * ceilings runs out first, at the typical price of an answer and at the most one can cost, since
 * the server weighs each ask at the most before making it; how long it lasts for the beings a
 * model decides for here, by this world's own head count; what the last hour already holds; and
 * what the server allows above any budget. Where several models decide here no model's figures
 * are set beside another's: the dearest decides, and the words say so.
 */
export function budgetSheetWords(sheet: BudgetSheet): string[] {
  const lines: string[] = [];
  const whose = !sheet.now.setByAPerson ? 'what every world starts with'
    : sheet.now.setByYou ? 'you set this' : 'someone with the right to change this world set this';
  lines.push(`Now: ${budgetWords(sheet.now.usdPerHour, sheet.now.decisionsPerHour)} in any hour of real time (${whose}).`);
  const kept = sheet.named.length === 2 ? ''
    : sheet.named.includes('usd_per_hour') ? ' You named the money; the decisions stay as they are.'
      : sheet.named.includes('decisions_per_hour') ? ' You named the decisions; the money stays as it is.' : '';
  lines.push(`After: ${budgetWords(sheet.asked.usdPerHour, sheet.asked.decisionsPerHour)}.${kept}`);
  const money = atMostDollarsWords(sheet.asked.usdPerHour);
  const decisions = count(sheet.asked.decisionsPerHour, 'decision');
  const most = sheet.answersForUsd.atMostPrice; const typical = sheet.answersForUsd.atTypicalPrice;
  // A model that answers for nothing is asked under a budget of no money too: only the decisions
  // bound it. Where every model here is one, the money never runs out; where only some are, no money
  // asks those alone.
  const free = sheet.models.length > 0 && sheet.models.every((model) => model.free);
  const noMoney = Number(sheet.asked.usdPerHour) === 0;
  const nothing = sheet.asked.decisionsPerHour === 0 || (noMoney && !sheet.models.some((model) => model.free));
  // No priced model is asked: how often they would ask, and the hour's refusal by the dearest, are not said.
  const unpriced = nothing || (noMoney && !free);
  if (nothing) {
    lines.push('With nothing to spend, no AI model is asked: everyone follows their own routine. The models you chose are kept.');
  } else if (sheet.minded === 0) {
    lines.push('No being here has an AI model yet, so nothing is asked whatever the budget. Which of the two runs out first depends on the model you choose.');
  } else if (free) {
    lines.push(sheet.models.length === 1
      ? `With ${sheet.models[0]!.name} deciding here: its answers cost nothing, so the money never runs out; only the ${decisions} can.`
      : `The AI models deciding here cost nothing to answer, so the money never runs out; only the ${decisions} can.`);
  } else if (noMoney) {
    lines.push('With no money to spend, only the AI models that cost nothing are asked; people with a priced model follow their own routine. The models you chose are kept.');
  } else if (sheet.models.length === 0 || most === null) {
    lines.push('This server cannot price an answer of the AI model chosen here right now, so which of the two runs out first cannot be said.');
  } else {
    const which = sheet.models.length === 1 ? `With ${sheet.models[0]!.name} deciding here:` : 'Several AI models decide here; by the dearest of them:';
    if (typical === null) {
      lines.push(`${which} if every answer costs the most it can, ${money} pays for about ${count(most, 'answer')}, so ${sheet.binds.atMostPrice === 'usd' ? 'the money' : `the ${decisions}`} would run out first. No typical price is measured for this model here yet.`);
    } else if (sheet.binds.atMostPrice === sheet.binds.atTypicalPrice) {
      lines.push(sheet.binds.atTypicalPrice === 'decisions'
        ? `${which} the ${decisions} run out before the ${money} does, even if every answer costs the most it can.`
        : `${which} the ${money} runs out before the ${decisions} do: after about ${count(typical, 'answer')} at the typical price, ${most.toLocaleString('en-US')} if every answer costs the most it can.`);
    } else {
      lines.push(`${which} at the typical price of an answer the ${decisions} run out first. If answers cost the most they can, the ${money} runs out first, after about ${count(most, 'answer')}. The server sets aside the most before each ask, so both are true.`);
    }
  }
  if (sheet.beings !== null) {
    const here = `This world has ${count(sheet.beings, 'being')}; an AI model decides for ${sheet.minded === 0 ? 'none of them' : sheet.minded}.`;
    // Under a budget that asks no priced model the line above has said who is asked: how often they
    // would ask and how soon nothing runs out is not said again.
    if (sheet.demand === null || unpriced) lines.push(here);
    else {
      const all = sheet.demand.everyone !== null && sheet.demand.everyone.beings !== sheet.demand.minded.beings
        ? ` With that model for all ${sheet.demand.everyone.beings}: ${demandWords(sheet.demand.everyone, sheet.demand.estimate)}.` : '';
      lines.push(`${here} They make ${demandWords(sheet.demand.minded, sheet.demand.estimate)}.${all} When a budget is used up, everyone follows their own routine until the hour moves on.`);
    }
  }
  if (sheet.hourSoFar.decisions > 0) {
    lines.push(`In the last hour this world asked AI models ${count(sheet.hourSoFar.decisions, 'time')}, for ${smallDollarsWords(sheet.hourSoFar.usd)}.`);
  }
  if (sheet.refusedNow !== null && !unpriced) {
    lines.push(`Even under this budget no AI model is asked right now: ${sheet.refusedNow === 'world_hour_spend_spent' ? 'the last hour’s spending already reaches it' : 'the last hour’s decisions already reach it'}. Asking starts again as the hour moves on.`);
  }
  lines.push(sheet.hostRefusal !== null ? 'This server does not ask AI models in this world right now, whatever the budget.'
    : sheet.allowanceBelowBudget && sheet.allowanceLeftUsd !== null
      ? `Your allowance on this server has ${smallDollarsWords(sheet.allowanceLeftUsd)} left in all, which stops the asking before this budget does.`
      : 'This server’s own limits still apply above any budget.');
  lines.push('Setting a budget asks no AI and spends nothing. It is this world’s, for everyone in it, until someone allowed to change it sets another.');
  return lines;
}

/** A budget step's row: "$0.50 and 600 decisions an hour". */
export function budgetDetailWords(usdPerHour: string, decisionsPerHour: number): string {
  return `${budgetWords(usdPerHour, decisionsPerHour)} an hour`;
}

/** What a living town taking its newcomers in loses, by the plan's code. */
const TAKE_IN_LOSES: Readonly<Record<string, string>> = Object.freeze({
  day_so_far: 'what everybody has done so far',
  clock_position: 'where the clock stands (their day starts again)',
  playing_and_speed: 'whether the town was playing, and how fast',
  models_chosen: 'the AI models chosen for people',
  looks_saved_for_residents: 'the looks saved for residents',
  comparisons_and_experiments: 'comparisons and experiments run with these people',
  companion_answers: 'the Companion’s answers about them',
});

/** What it keeps, by the plan's code. */
const TAKE_IN_KEEPS: Readonly<Record<string, string>> = Object.freeze({
  people_homes_jobs_roles_shifts: 'the same people, with their homes, jobs, roles and shifts',
  world: 'the world',
  things_placed: 'everything placed in it',
  door_grants_and_programs: 'door grants and programs',
  world_look: 'the world’s look',
});

/** A step that erases, confirmed with nothing shown of what it loses and keeps: never sent. */
export const ERASES_UNSHOWN: RefusalWords = {
  happened: 'What this step erases and what it keeps was not shown when you confirmed, so it was not sent.',
  next: 'Nothing was changed. Ask for it on its own.',
};

/** A budget confirmed with nothing shown of what it comes to here: never sent. */
export const BUDGET_UNSHOWN: RefusalWords = {
  happened: 'What this budget comes to in this world was not shown when you confirmed, so it was not sent.',
  next: 'Nothing was changed. Ask for it on its own.',
};

/**
 * What a step that erases comes to, said before the one yes: what is lost, whole, what stays, and
 * whether anything undoes it. A code this page has no words for is never left out: the loss is
 * then said to be more than the page can name. A way back is said only when the server states one.
 */
export function erasesWords(erases: Erases, minute: number | null): string[] {
  const list = (codes: readonly string[], words: Readonly<Record<string, string>>): { said: string; unknown: boolean } => ({
    said: codes.flatMap((code) => (words[code] === undefined ? [] : [words[code]!])).join('; '),
    unknown: codes.some((code) => words[code] === undefined),
  });
  const lost = list(erases.loses, TAKE_IN_LOSES); const kept = list(erases.keeps, TAKE_IN_KEEPS);
  const day = minute === null || minute <= 0 ? '' : ` Their day so far is ${count(minute, 'minute')} long.`;
  return [
    `The people of this town take the newcomers in and live with them from now on. They stay who they are.${day}`,
    ...(lost.said === '' && !lost.unknown ? []
      : [`Not kept: ${lost.said}${lost.unknown ? `${lost.said === '' ? '' : '; '}and more that this page cannot name` : ''}.`]),
    ...(kept.said === '' ? [] : [`Kept: ${kept.said}.`]),
    erases.undo ? 'This can be taken back.' : 'This cannot be undone.',
  ];
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
