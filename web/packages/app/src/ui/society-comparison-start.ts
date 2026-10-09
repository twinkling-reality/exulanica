/**
 * Starting a comparison of models from the Compare view, and what a started one says of itself.
 *
 * It builds elements and holds no client: the mount hands it what the server offers (the plan
 * route's document) and routes each choice through a handler. The roles, groups, models and seeds
 * it offers are the server's, and so are the most a comparison can cost and what one like it
 * typically cost: the page shows both as written and decides neither. The person states the bound
 * the server enforces; nothing starts until they have. Every refusal is said in words, by the
 * server's code.
 */

import type {
  ComparisonListing,
  ComparisonPlan,
  ComparisonSelection,
  ComparisonStart,
  PlanFigures,
  PlanGroup,
  PlanModel,
  PlanRole,
  StartRequest,
  Refusal,
  StartState,
} from '../society-comparison-api.js';
import { el, replace } from './dom.js';
import { MODEL_REFUSAL_WORDS } from './society-models.js';

/**
 * Why a comparison cannot be started, by the server's code: exactly `START_REFUSALS` in
 * `exulanica/api/society_comparison_start.py`, held to it by society-comparison-words-parity.test.ts.
 */
export const START_REFUSAL_WORDS: Readonly<Record<string, string>> = {
  comparisons_not_set_up: 'Comparisons are not set up on this computer: it holds no seeds to run them on.',
  comparisons_not_played: 'Nothing on this computer runs comparisons, so none can be started.',
  comparisons_not_run_here: 'This server does not ask models for this world, so it cannot run a comparison of it.',
  provider_credential_absent: 'This server has no key for the service that runs the models.',
  comparison_running: 'A comparison of this world is still running. Start the next one when it has finished.',
  comparison_conflict: 'That comparison was already started with other choices. Start it again.',
  engine_takes_no_comparison: 'The people of this world cannot be compared.',
  role_not_hosted: 'Nothing in this world is decided that way.',
  population_over_comparison_bound: 'This world holds more people than a comparison runs.',
  decided_over_comparison_bound: 'A model can decide for fewer of this world\'s people than that in one comparison. Choose a smaller group.',
  role_not_registered: 'That is not something this server lets a model decide.',
  model_not_offered: 'That model is not offered for decisions.',
  model_named_twice: 'Choose two different models, or run the first a second time as the control.',
  model_not_askable_here: 'This server cannot ask that model now.',
  owner_choice_not_askable: 'A model you chose for somebody outside the group cannot be asked here.',
  choice_unknown: 'That group is no longer one of your choices. Choose again.',
  group_empty: 'The group names nobody.',
  group_person_unknown: 'Someone in the group is no longer in this world. Choose again.',
  group_visitor: 'A visitor cannot be in a comparison: every run starts before anybody crossed in. Choose again.',
  group_person_not_in_run: 'Someone in the group was placed after this world\'s people began, so a run would not hold them from its start. Choose again.',
  seeds_out_of_range: 'This server holds fewer seeds than that.',
  bound_out_of_range: 'State a bound above $0 and at most the most the comparison can cost.',
  bound_over_budget: 'This server\'s model budget has too little left for that bound.',
  calls_over_budget: 'This server\'s model budget allows fewer calls than this comparison can make. Choose fewer people, models or seeds.',
  input_not_in_society: 'This world\'s people have no starting point with that number. Choose another.',
  bound_exceeds_grant: 'This workspace\'s spending grant has less left than the bound you set. Set a smaller bound.',
  window_not_offered: 'This world cannot be compared over a whole day here. Compare one hour instead.',
  no_reading_line: 'Comparisons of this kind of world are not offered yet: how long one takes to read has not been measured.',
};

/**
 * Why the server closed a started comparison before every run was played, by `CLOSED_REASONS` in
 * `exulanica/api/society_comparison_worker.py`, held to it by the parity test.
 */
export const CLOSED_WORDS: Readonly<Record<string, string>> = {
  claims_spent: 'the server stopped while running it three times in a row, so it was closed',
  comparison_bound_before_seed: 'what was left of the bound you set would not let the next seed finish, so it stopped between seeds and kept those it had played',
  comparison_bound_spent: 'the bound you set was spent',
  comparison_cancelled: 'it was stopped before every run was played',
  process_budget_spent: 'this server\'s model budget had too little left for it',
};

/** Where a started comparison stands, by the server's word for it. */
export const STATE_WORDS: Readonly<Record<StartState, string>> = {
  waiting: 'Waiting for the server to run it',
  running: 'Running',
  finished: 'Finished',
  closed: 'Closed',
};

/** What a role decides for, by the word the registry knows its subjects by. */
export const SUBJECT_WORDS: Readonly<Record<string, string>> = {
  person: 'the people of this world',
};

/** A decimal of US dollars as the server wrote it, with trailing zeros past the cents dropped. */
export function dollars(value: string): string {
  const [whole, fraction = ''] = value.split('.');
  const kept = fraction.replace(/0+$/, '').padEnd(2, '0');
  return `$${whole}.${kept}`;
}

/** Why a start was refused, in words, by the server's code; a code with no words is never shown. */
export function refusalWords(code: string, detail = ''): string {
  return START_REFUSAL_WORDS[code]
    ?? (detail === '' ? 'The server refused it.' : 'The server refused it. Change a choice, or try again later.');
}

/**
 * Why the plan says a start would be refused for spending (`budget_exceeded`, with the durable
 * authority's reason): the plan line a person reads before pressing Start.
 */
export const PLAN_SPENDING_WORDS: Readonly<Record<string, string>> = {
  bound_exceeds_grant: 'The bound you set is more than this workspace\'s allowance grants. Set a lower bound to start.',
  spending_not_granted: 'This workspace has no allowance to spend on these models\' service, so it cannot start.',
  spending_revoked: 'This workspace\'s model allowance was withdrawn, so it cannot start.',
  spending_expired: 'This workspace\'s model allowance has run out of time, so it cannot start.',
  spending_limit_reached: 'This comparison would go over this workspace\'s model allowance, so it cannot start.',
  spending_suspended: 'Spending on models is paused for this workspace, so it cannot start.',
  spending_unavailable: 'The model allowance could not be checked, so it cannot start now. Try again later.',
  spending_scope_missing: 'The request did not say which workspace to spend for, so it cannot start.',
};
const PLAN_OVER_BUDGET = 'This comparison would spend more than this workspace\'s model allowance permits, so it cannot start.';

export function planRefusalWords(refusal: Refusal): string {
  if (refusal.code !== 'budget_exceeded') return refusalWords(refusal.code, refusal.detail);
  const spending = refusal.spending;
  if (spending === undefined) return PLAN_OVER_BUDGET;
  return (spending.detail === null ? undefined : PLAN_SPENDING_WORDS[spending.detail])
    ?? PLAN_SPENDING_WORDS[spending.reason] ?? PLAN_OVER_BUDGET;
}

/**
 * How far a started comparison got, in words: where it stands, its runs, and its spend against its
 * bound, with what a server that stopped was presumed to have spent where there is any.
 */
export function startWords(start: ComparisonStart, runsFinished: number): string {
  const runs = `${runsFinished} of ${start.runsPlanned} runs finished`;
  const presumed = /[1-9]/.test(start.presumedUsd)
    ? `, and ${dollars(start.presumedUsd)} counted for asks a server that stopped may have made`
    : '';
  const spent = `${dollars(start.spentUsd)} of the ${dollars(start.boundUsd)} bound spent${presumed}`;
  const closed = start.closedReason === null ? '' : `, because ${CLOSED_WORDS[start.closedReason] ?? `of a reason this page has no words for (${start.closedReason})`}`;
  return `${STATE_WORDS[start.state]}${closed}: ${runs}; ${spent}.`;
}

/** A listed comparison's progress in words, or null for one the local command ran. */
export function progressWords(listing: ComparisonListing): string | null {
  return listing.start === null ? null : startWords(listing.start, listing.runsFinished);
}

/** Whether a started comparison is still to be played or played now, so its reads change. */
export const inProgress = (listing: ComparisonListing): boolean =>
  listing.start !== null && (listing.start.state === 'waiting' || listing.start.state === 'running');

function groupWords(group: PlanGroup): string {
  if (group.kind === 'everyone') return `Everybody (${group.size} ${group.size === 1 ? 'person' : 'people'})`;
  if (group.kind === 'named') return 'People you choose';
  const who = `The ${group.size === 1 ? 'person' : `${group.size} people`}`;
  return group.model === null
    ? `${who} you set to follow their routine`
    : `${who} you chose ${group.model.name} for`;
}

function modelWords(model: PlanModel): string {
  const typical = model.typicalUsdPerPersonHour === null
    ? 'not measured yet'
    : `typically ${dollars(model.typicalUsdPerPersonHour)} a person-hour`;
  const refused = model.refusal === null
    ? ''
    : `: not now, ${MODEL_REFUSAL_WORDS[model.refusal] ?? model.refusal}`;
  return `${model.name} (${typical})${refused}`;
}

/**
 * How many of this world's people a model may decide for in one comparison, in words, where that is
 * fewer than all of them: the server derives it from how long reading a run may take.
 */
export function decidedWords(plan: ComparisonPlan): string | null {
  if (plan.decidedMost >= plan.population) return null;
  return `A model can decide for at most ${plan.decidedMost} of this world's ${plan.population} people in one comparison, so that each of its hours can be replayed and shown within seconds.`;
}

/**
 * For each model arm of a planned comparison that decides for more people than one minute's asks
 * can have answered, in words: the rest of a busy minute follow their routine, and the comparison
 * still runs.
 */
export function minuteWords(figures: PlanFigures): string {
  const said = new Set<string>();
  const lines: string[] = [];
  for (const minute of figures.minutes) {
    if (minute.answersPerMinute === null || minute.decided <= minute.answersPerMinute || said.has(minute.modelId)) continue;
    said.add(minute.modelId);
    lines.push(`${minute.name} can answer about ${minute.answersPerMinute} of the ${minute.decided} people it decides for in one minute; in a minute when more of them have a choice, the rest follow their routine.`);
  }
  return lines.join(' ');
}

/**
 * The least bound that lets a comparison finish, in words, where the server derived one: each ask
 * is held at its model's most until what it cost is known, so a bound near the typical spend stops
 * its runs part way. It promises a finish only where the typical figure was measured on this
 * world's kind of ground; elsewhere it says where it was measured and that it may stop.
 */
export function finishingWords(figures: PlanFigures): string {
  if (figures.suggestedUsd === null || figures.typicalUsd === null) return '';
  const held = 'each ask is held at its most until its cost is known';
  return figures.typicalMatches
    ? ` At least ${dollars(figures.suggestedUsd)} lets it finish, since ${held}.`
    : ` At least ${dollars(figures.suggestedUsd)}, based on recorded comparisons on other grounds; this kind of world has no matching measurement, so that bound may stop it before it finishes, as ${held}.`;
}

/** What the person has chosen so far, or null while something a start needs is not chosen. */
export interface StartChoices {
  readonly role: PlanRole;
  readonly group: PlanGroup;
  readonly first: PlanModel;
  readonly second: PlanModel | null;
  readonly control: boolean;
  readonly seeds: number;
}

/**
 * A group of the people the person names, from everybody the plan offers: the way to compare a
 * group larger than any one of their choices, up to the most a model may decide for.
 */
export function namedGroup(people: readonly { readonly id: string; readonly name: string }[]): PlanGroup {
  return { kind: 'named', choiceSeq: null, size: people.length, people, model: null };
}

/** How many people the person has named, in words, against the most a model may decide for. */
export function namedWords(chosen: number, plan: ComparisonPlan): string {
  const most = Math.min(plan.decidedMost, plan.population);
  if (chosen === 0) return `Choose the people the models decide for, up to ${most}.`;
  if (chosen > most) return `${chosen} chosen: a model can decide for at most ${most} of this world's people in one comparison.`;
  return `${chosen} of at most ${most} chosen.`;
}

/** The selection the choices make, as the plan route and the start route take it. */
export function selectionOf(choices: StartChoices): ComparisonSelection {
  const { group } = choices;
  return {
    role: choices.role.key,
    group: group.kind === 'owner_choice' && group.choiceSeq !== null
      ? { kind: group.kind, choiceSeq: group.choiceSeq }
      : group.kind === 'named'
        ? { kind: group.kind, people: (group.people ?? []).map((person) => person.id) }
        : { kind: group.kind },
    models: [choices.first, ...(choices.second === null ? [] : [choices.second])]
      .map((model) => ({ provider: model.provider, modelId: model.modelId })),
    control: choices.control,
    seeds: choices.seeds,
  };
}

/** A bound as the person typed it, when it is one the server may take: above zero, at most the most. */
export function boundOf(typed: string, mostUsd: string): string | null {
  const value = typed.trim().replace(/^\$/, '');
  if (!/^\d{1,6}(\.\d{1,8})?$/.test(value)) return null;
  const amount = Number(value);
  return amount > 0 && amount <= Number(mostUsd) ? value : null;
}

export interface ComparisonStartForm {
  readonly root: HTMLElement;
  /** Show what the server offers, and the plan or refusal of what is chosen. */
  showPlan(plan: ComparisonPlan): void;
  /** Say a start is under way, or was refused, in words. */
  status(kind: 'starting' | 'refused', words: string): void;
}

/** The start controls. Every choice is a handler: the form asks nothing of the server itself. */
export function buildComparisonStartForm(handlers: {
  readonly onSelection: (selection: ComparisonSelection) => void;
  readonly onStart: (request: StartRequest) => void;
  /** A fresh id for a start, so sending the same start again is answered with it. */
  readonly newId: () => string;
}): ComparisonStartForm {
  const root = el('section', { class: 'comparison-start', 'aria-labelledby': 'comparison-start-title' });
  let offered: ComparisonPlan | null = null;
  let chosen: StartChoices | null = null;
  let startId = handlers.newId();
  /** The bound as the person typed it, kept while the plan is asked for again. */
  let typed = '';
  /** The people the person named for a group of their own, by id, kept across plans. */
  const named = new Set<string>();
  /**
   * What the controls were built from, and what a plan's answer changes in place: the plan line and
   * whether Start is available. A plan of the same offer never rebuilds the controls, so nobody loses
   * what they are typing or clicking while it arrives.
   */
  let built: { readonly offer: string; readonly update: (plan: ComparisonPlan) => void } | null = null;
  const offerOf = (plan: ComparisonPlan): string =>
    JSON.stringify([plan.refusal, plan.running, plan.roles, plan.seedsAvailable, plan.population, plan.decidedMost, plan.people]);

  const render = (plan: ComparisonPlan): void => {
    built = null;
    const title = el('h3', { id: 'comparison-start-title', text: 'Start a comparison' });
    if (plan.refusal !== null) {
      replace(root, [title, el('p', { class: 'comparison-start-refusal', text: refusalWords(plan.refusal.code) })]);
      return;
    }
    if (plan.running !== null) {
      replace(root, [title, el('p', { text: 'A comparison of this world is running. Its progress is in the list below.' })]);
      return;
    }
    const role = chosen?.role ?? plan.roles[0];
    if (role === undefined || role.models.length === 0) {
      replace(root, [title, el('p', { text: 'This server offers no model a comparison of this world could ask.' })]);
      return;
    }
    const askable = role.models.filter((model) => model.refusal === null);
    const pick = (models: readonly PlanModel[], held: PlanModel | null | undefined): PlanModel | null =>
      held === null || held === undefined ? null : models.find((model) => model.modelId === held.modelId) ?? null;
    const groups = plan.people.length === 0
      ? role.groups
      : [...role.groups, namedGroup(plan.people.filter((person) => named.has(person.id)))];
    const group = groups.find((held) => held.kind === chosen?.group.kind && held.choiceSeq === chosen?.group.choiceSeq)
      ?? groups[0]!;
    const first = pick(askable, chosen?.first) ?? askable[0] ?? null;
    const second = pick(askable, chosen?.second);
    const seeds = Math.min(Math.max(1, chosen?.seeds ?? 1), Math.max(1, plan.seedsAvailable));
    const current: StartChoices | null = first === null ? null
      : { role, group, first, second: second?.modelId === first.modelId ? null : second, control: chosen?.control ?? false, seeds };
    chosen = current;

    const option = (value: string, words: string, selected: boolean, disabled = false) =>
      el('option', { value, text: words, selected, disabled });
    const groupSelect = el('select', { class: 'comparison-start-group', 'aria-label': 'Who the models decide for' },
      groups.map((held, index) => option(String(index), groupWords(held), held === group)));
    const namedLine = el('p', { class: 'comparison-start-named-count', 'aria-live': 'polite' });
    const namedBoxes = plan.people.map((person) => {
      const box = el('input', { type: 'checkbox', value: person.id, checked: named.has(person.id) });
      return { person, box, label: el('label', { class: 'comparison-start-person' }, [box, el('span', { text: person.name })]) };
    });
    const namedField = el('fieldset', { class: 'comparison-start-named' }, [
      el('legend', { text: 'The people the models decide for' }),
      namedLine,
      el('div', { class: 'comparison-start-people' }, namedBoxes.map((held) => held.label)),
    ]);
    const namingPicked = () => groups[Number(groupSelect.value)]?.kind === 'named';
    const showNamed = () => {
      namedField.hidden = !namingPicked();
      namedLine.textContent = namedWords(named.size, plan);
    };
    const modelSelect = (label: string, held: PlanModel | null, none: string | null) => el('select', {
      class: 'comparison-start-model', 'aria-label': label,
    }, [
      ...(none === null ? [] : [option('', none, held === null)]),
      ...role.models.map((model) => option(model.modelId, modelWords(model), model.modelId === held?.modelId, model.refusal !== null)),
    ]);
    const firstSelect = modelSelect('First model', first, null);
    const secondSelect = modelSelect('Second model', current?.second ?? null, 'No second model');
    const control = el('input', { type: 'checkbox', class: 'comparison-start-control', checked: current?.control ?? false });
    const seedInput = el('input', {
      type: 'number', class: 'comparison-start-seeds', min: 1, max: Math.max(1, plan.seedsAvailable),
      value: seeds, 'aria-label': 'Seeds',
    });
    const bound = el('input', {
      type: 'text', inputmode: 'decimal', class: 'comparison-start-bound', placeholder: '0.05',
      'aria-label': 'Stop spending at, in US dollars', value: typed,
    });
    const start = el('button', { type: 'button', class: 'comparison-start-button', text: 'Start the comparison', disabled: true });
    const note = el('p', { class: 'comparison-start-note', 'aria-live': 'polite' });
    const planLine = el('p', { class: 'comparison-start-plan' });
    const minuteLine = el('p', { class: 'comparison-start-minutes' });
    const decided = decidedWords(plan);

    /** The plan whose figures the line shows and Start is judged by: the newest answer. */
    let latest = plan;
    const enable = () => {
      const figures = latest.plan;
      start.disabled = figures === null || latest.planRefusal !== null || boundOf(bound.value, figures.mostUsd) === null
        || (chosen?.group.kind === 'named' && named.size === 0);
    };
    const update = (answer: ComparisonPlan) => {
      latest = answer;
      const figures = answer.plan;
      planLine.textContent = answer.planRefusal !== null
        ? planRefusalWords(answer.planRefusal)
        : figures === null
          ? 'Choose what to compare.'
          : `${figures.runs} runs of one simulated hour. It could cost at most ${dollars(figures.mostUsd)}, if every person were asked every minute and every answer were as long as allowed. `
            + (figures.typicalUsd === null
              ? 'No recorded comparison measured what one like it typically costs.'
              : figures.typicalMatches
                ? `One like it typically costs about ${dollars(figures.typicalUsd)}, as measured in a recorded comparison.`
                : `The reference cost is about ${dollars(figures.typicalUsd)}, using the highest measured per-person-hour cost for each model on other grounds. This kind of world has no matching cost measurement.`)
            + finishingWords(figures);
      bound.placeholder = figures?.suggestedUsd ?? '0.05';
      // Until the person types a bound, it is the least that lets one like it finish.
      if (typed === '') bound.value = figures?.suggestedUsd ?? '';
      if (figures === null) planLine.removeAttribute('title');
      else planLine.title = figures.typicalRecord;
      minuteLine.textContent = figures === null || answer.planRefusal !== null ? '' : minuteWords(figures);
      minuteLine.hidden = minuteLine.textContent === '';
      enable();
    };
    const changed = () => {
      const picked = groups[Number(groupSelect.value)] ?? groups[0]!;
      const group = picked.kind === 'named'
        ? namedGroup(plan.people.filter((person) => named.has(person.id)))
        : picked;
      const first = role.models.find((model) => model.modelId === firstSelect.value) ?? null;
      const second = role.models.find((model) => model.modelId === secondSelect.value) ?? null;
      if (first === null) return;
      chosen = { role, group, first, second, control: control.checked, seeds: Math.max(1, Number(seedInput.value) || 1) };
      showNamed();
      startId = handlers.newId();
      handlers.onSelection(selectionOf(chosen));
    };
    for (const input of [groupSelect, firstSelect, secondSelect, control, seedInput]) input.addEventListener('change', changed);
    for (const { person, box } of namedBoxes) {
      box.addEventListener('change', () => {
        if (box.checked) named.add(person.id);
        else named.delete(person.id);
        namedLine.textContent = namedWords(named.size, plan);
        if (namingPicked()) changed();
      });
    }
    showNamed();
    bound.addEventListener('input', () => {
      typed = bound.value;
      enable();
    });
    start.addEventListener('click', () => {
      const figures = latest.plan;
      if (chosen === null || figures === null) return;
      const boundUsd = boundOf(bound.value, figures.mostUsd);
      if (boundUsd === null) return;
      start.disabled = true;
      handlers.onStart({ ...selectionOf(chosen), comparisonId: startId, boundUsd });
    });
    update(plan);
    replace(root, [
      title,
      el('p', { class: 'comparison-start-role', text: `The models decide for ${SUBJECT_WORDS[role.subject] ?? role.subject}, one simulated hour on each seed, beside their own routine and waiting.` }),
      el('div', { class: 'comparison-start-fields' }, [
        el('label', {}, [el('span', { text: 'Who' }), groupSelect]),
        namedField,
        el('label', {}, [el('span', { text: 'First model' }), firstSelect]),
        el('label', {}, [el('span', { text: 'Second model' }), secondSelect]),
        el('label', { class: 'comparison-start-check' }, [control, el('span', { text: 'Run the first model a second time, to see how much it differs from itself' })]),
        el('label', {}, [el('span', { text: `Seeds (at most ${plan.seedsAvailable})` }), seedInput]),
      ]),
      ...(decided === null ? [] : [el('p', { class: 'comparison-start-decided', text: decided })]),
      planLine,
      minuteLine,
      el('div', { class: 'comparison-start-go' }, [
        el('label', {}, [el('span', { text: 'Stop spending at $' }), bound]),
        start,
      ]),
      note,
    ]);
    built = { offer: offerOf(plan), update };
    // Controls built from what the server offers show a choice, the person's or the first offered:
    // its plan is asked for at once, so the line never says less than the controls show.
    if (current !== null && plan.plan === null && plan.planRefusal === null) {
      handlers.onSelection(selectionOf(current));
    }
  };

  return {
    root,
    showPlan(plan) {
      offered = plan;
      if (built !== null && built.offer === offerOf(plan)) built.update(plan);
      else render(plan);
    },
    status(kind, words) {
      const note = root.querySelector<HTMLElement>('.comparison-start-note');
      if (note !== null) note.textContent = words;
      const button = root.querySelector<HTMLButtonElement>('.comparison-start-button');
      if (button !== null && kind === 'refused' && offered !== null) button.disabled = false;
    },
  };
}
