/**
 * Who decides for the people of a person's own saved world: their own routine, or a model the
 * world's owner chooses for one of them or for a group.
 *
 * It builds elements and holds no client, as the inhabitants panel does: the mount hands it the
 * server's models read and the people, and routes a choice through a handler. Everything it says
 * about a decision is read from the server's receipts: which model was asked, what it chose, and
 * what the minute did with it, or why the person's routine decided instead.
 */

import type {
  ModelDecisionSummary,
  ModelRef,
  NamedModelRef,
  PersonDecision,
  SocietyModel,
  SocietyModels,
} from '../society-models-api.js';
import { DECISION_WORDS } from '../society-inhabitant-words.js';
import { el, replace, setText } from './dom.js';
import './society-models.css';

/**
 * Why this host asks no model for this world's people, by `HOST_REFUSALS` in
 * `decision_host.py`: the section and the inspector each say it in a sentence.
 */
export const HOST_REFUSAL_WORDS: Readonly<Record<string, string>> = {
  models_not_run_here: 'this server does not ask models for this world\'s people',
  provider_credential_absent: 'this server has no key for a model service',
  process_budget_spent: 'this server has spent its model budget until it restarts',
  process_share_spent: 'this server\'s model budget is down to the part kept for its other work, until it restarts',
};

/**
 * Why a person's chosen model is not asked here while this host asks others, by `MODEL_REFUSALS`
 * in `decision_host.py`.
 */
export const MODEL_REFUSAL_WORDS: Readonly<Record<string, string>> = {
  model_no_longer_offered: 'the model you chose is no longer offered for decisions',
  provider_changed: 'the service that runs the model you chose has changed, so choose it again to use it',
  provider_not_admitted: 'this server may not reach the service that runs the model you chose',
  provider_credential_absent: 'this server has no key for the service that runs the model you chose',
  process_budget_spent: 'this server has too little of its model budget left to ask the model you chose, until it restarts',
  process_share_spent: 'this server\'s model budget, less the part kept for its other work, is too little to ask the model you chose, until it restarts',
  question_changed_by_rules: 'this world\'s rules would change the question each person is asked, since a name you saved shares a word with it',
};

/** Why a choice was not recorded, by the code the models route refuses it with. */
export const CHOICE_REFUSAL_WORDS: Readonly<Record<string, string>> = {
  engine_takes_no_model_choice: 'The people of this world cannot be run by a model.',
  person_not_in_this_world: 'Someone you chose is no longer in this world. Look again, then choose again.',
  person_named_twice: 'The same person was named twice. Choose again.',
  model_not_declared: 'That model is not one this server knows.',
  model_not_offered: 'That model is not offered for decisions.',
  model_not_askable: 'That model cannot be asked for a decision here.',
  too_many_model_people: 'That would put more people under models than this world allows.',
  choice_key_reused: 'That choice was already sent with different people. Choose again.',
  subject_chosen_under_another_role: 'That subject is already assigned to a model under another kind of decision.',
};

const decisionWords = (code: string): string =>
  DECISION_WORDS[code] ?? 'of a reason this page cannot name yet';
const sentence = (words: string): string => words.charAt(0).toUpperCase() + words.slice(1);

/** Why this host asks nobody's model here, or null when it asks them. */
function hostReason(refusal: string | null): string | null {
  return refusal === null ? null : HOST_REFUSAL_WORDS[refusal] ?? 'this server does not ask models here';
}

/** What the section says of this host: that it asks the models chosen, or why it asks none. */
export function hostWords(refusal: string | null): string {
  const why = hostReason(refusal);
  return why === null
    ? 'This server asks the models you choose before each simulated minute.'
    : `${sentence(why)}, so everyone here follows their own routine for now.`;
}

/**
 * Who decides for a person now, in words: the model chosen for them while this host asks it, and
 * otherwise their own routine, for now and why, whenever their model is not asked here.
 */
export function choiceWords(view: SocietyModels, subjectId: string): string {
  const choice = view.choices.find((held) => held.subjectId === subjectId);
  if (choice === undefined || choice.model === null) return 'Their own routine.';
  const { name } = choice.model;
  const why = hostReason(view.hostRefusal) ?? (choice.refusal === null
    ? null
    : MODEL_REFUSAL_WORDS[choice.refusal] ?? `the model you chose is not asked here (${choice.refusal})`);
  return why === null ? `${name}, which you chose.` : `Their own routine for now, because ${why}. You chose ${name}.`;
}

/**
 * What the section says once a choice is recorded, from the read that follows it: that the model
 * decides for them from their next choice, or that their routine does for now, and why, whenever
 * this host would not ask it.
 */
export function recordedWords(view: SocietyModels | null, people: readonly string[], model: ModelRef | null): string {
  const one = people.length === 1;
  const who = one ? 'One person' : `${people.length} people`;
  if (model === null) return `${who} ${one ? 'now follows' : 'now follow'} their own routine, from the next time they choose what to do.`;
  const refused = view?.choices.find((held) => people.includes(held.subjectId) && held.refusal !== null)?.refusal ?? null;
  const why = hostReason(view?.hostRefusal ?? null) ?? (refused === null
    ? null
    : MODEL_REFUSAL_WORDS[refused] ?? `the model you chose is not asked here (${refused})`);
  if (why === null) return `${who} ${one ? 'is' : 'are'} now decided by the model you chose, from the next time they choose what to do.`;
  return `The model you chose is recorded for ${one ? 'one person' : who.toLowerCase()}, but they follow their own routine for now, because ${why}.`;
}

/** A person's latest decision and what came of it, in words, or null before their first. */
export function decisionWordsFor(view: SocietyModels, subjectId: string): string | null {
  const decision = view.latest.find((held) => held.subjectId === subjectId);
  return decision === undefined ? null : latestDecisionWords(decision);
}

export function latestDecisionWords(decision: PersonDecision): string {
  const { name } = decision;
  // The routine decided in the decision's own minute when the model was not followed, however
  // late its receipt was closed; a followed decision is told by the minute that took it up.
  const minute = `At simulated minute ${decision.status !== 'accepted' || decision.consumedTick === null
    ? decision.baseTick + 1
    : decision.consumedTick}`;
  if (decision.status !== 'accepted') {
    return `${minute}, their routine decided: ${name} was not followed because ${decisionWords(decision.reason)}.`;
  }
  const chose = `${name} chose “${decision.chose ?? 'an action'}”`;
  if (decision.disposition === null) return `${chose}. They act on it at the next simulated minute.`;
  if (decision.disposition === 'applied') return `${minute}, ${chose}, and they did it.`;
  const why = decisionWords(decision.dispositionReason ?? decision.disposition);
  // A person's own request, or another decision, came first: neither is their routine.
  if (decision.disposition === 'superseded') return `${minute}, ${chose}, but ${why}, and that came first.`;
  return `${minute}, ${chose}, but ${why}, so their routine decided.`;
}

/**
 * What one model's decisions came to, in a sentence. Each decision not acted on is counted once
 * under why, as the server counts it: the receipt's reason when the model was not followed, or
 * what the minute found when it was followed and could not be acted on.
 */
export function summaryWords(summary: ModelDecisionSummary): string {
  const { name } = summary;
  const decisions = summary.decisions === 1 ? 'one decision' : `${summary.decisions} decisions`;
  const pending = summary.byDisposition['pending'] ?? 0;
  const notActed = summary.decisions - summary.applied - pending;
  const reasons = Object.entries(summary.notActedOn).map(([code, n]) => `${n} because ${decisionWords(code)}`);
  const why = reasons.length > 0 ? ` (${reasons.join('; ')})` : '';
  const waiting = pending === 0 ? '' : `, ${pending} waiting for the next minute`;
  // Rounded up: an answer within 835 ms came within 0.9 s, never within 0.8 s.
  const seconds = (ms: number): string => `${(Math.ceil(ms / 100) / 10).toFixed(1)} s`;
  const timing = summary.latencyP50Ms === null
    ? ''
    : ` Half its answers came within ${seconds(summary.latencyP50Ms)}, 95 in 100 within ${seconds(summary.latencyP95Ms ?? summary.latencyP50Ms)}.`;
  const cost = summary.asked === 0 ? '' : ` Cost ${summary.costKnown ? '' : 'at most '}$${summary.costUsd}.`;
  return `${name}: ${decisions}, ${summary.applied} acted on${waiting}, ${notActed} not acted on${why}.${timing}${cost}`;
}

/** A person this section can choose for, as the mount names them. */
export interface ChoosablePerson {
  readonly id: string;
  readonly name: string;
}

/** What the traffic-light role's card says: how many lights, and who runs them, in a few words. */
export interface RoleSummary {
  readonly count: number;
  readonly words: string;
}

export interface SocietyModelsSection {
  readonly root: HTMLElement;
  readonly choose: HTMLButtonElement;
  /** The model the cards have chosen, as its option value: empty for their own routine. */
  readonly model: { value: string };
  render(state: {
    readonly view: SocietyModels | null;
    readonly people: readonly ChoosablePerson[];
    readonly busy: boolean;
    /** What the last choice or read came to, or empty. */
    readonly message: string;
  }): void;
  /** The traffic-light role's card, or null where this world offers that role nothing. */
  setSignals(summary: RoleSummary | null): void;
  /** Untick everyone, once a choice for them is recorded. */
  clearPeople(): void;
}

/** The routine's option, and each model's: its provider and identifier, which hold no space. */
const ROUTINE = '';
const optionValue = (ref: ModelRef): string => `${ref.provider} ${ref.modelId}`;
function optionModel(value: string): ModelRef | null {
  const space = value.indexOf(' ');
  return space < 0 ? null : { provider: value.slice(0, space), modelId: value.slice(space + 1) };
}

const priceOf = (model: SocietyModel): number | null =>
  model.price === null ? null : Number(model.price.input) + Number(model.price.output);

/**
 * How a model's served price compares with the cheapest model offered beside it, in a few words,
 * or null where the read names no price. Input and output prices are added, which ranks models the
 * way a decision's short question and short answer spend; the card's title states both exactly.
 */
export function costWords(model: SocietyModel, models: readonly SocietyModel[]): string | null {
  const own = priceOf(model);
  if (own === null) return null;
  const lowest = Math.min(...models.map(priceOf).filter((held): held is number => held !== null));
  if (own <= lowest) return 'Lowest cost';
  const times = own / lowest;
  return times < 1.5 ? 'Near the lowest cost' : `About ${Math.round(times)} times the lowest cost`;
}

/** The served price in words, for a card's title. */
export function priceWords(model: SocietyModel): string {
  return model.price === null
    ? 'This server names no price for this model.'
    : `US$${model.price.input} per million tokens it reads, US$${model.price.output} per million it writes.`;
}

/**
 * A model's served description as its card's line. The manifest's description opens with the
 * model's own name, which the card already shows above it, so that opening is left out.
 */
export function modelLine(model: SocietyModel): string {
  const opening = `${model.name}, `;
  return model.description.startsWith(opening) ? sentence(model.description.slice(opening.length)) : model.description;
}

const peopleWords = (n: number): string => (n === 1 ? 'one person' : `${n} people`);

/** What the primary button says for the cards and people chosen. */
export function chooseWords(model: NamedModelRef | null, chosen: number, busy: boolean): string {
  if (busy) return 'Choosing…';
  if (chosen === 0) return 'Choose people to decide for';
  if (model === null) return `Give ${peopleWords(chosen)} their own routine`;
  return `Let ${model.name} decide for ${peopleWords(chosen)}`;
}

/** What the People card says of who decides for the people here now. */
export function peopleRoleWords(view: SocietyModels, people: readonly ChoosablePerson[]): string {
  const present = new Set(people.map((person) => person.id));
  const byModel = new Map<string, { name: string; n: number }>();
  for (const choice of view.choices) {
    if (choice.model === null || !present.has(choice.subjectId)) continue;
    const key = optionValue(choice.model);
    const held = byModel.get(key) ?? { name: choice.model.name, n: 0 };
    byModel.set(key, { ...held, n: held.n + 1 });
  }
  if (byModel.size === 0) return 'Their own routine';
  const counted = [...byModel.values()];
  const decided = counted.reduce((sum, held) => sum + held.n, 0);
  return counted.length === 1 ? `${decided} by ${counted[0]!.name}` : `${decided} by ${counted.length} models`;
}

export function buildSocietyModels(handlers: {
  readonly onChoose: (people: readonly string[], model: ModelRef | null) => void;
  /** The traffic-light role's own section, shown under its card. */
  readonly signals?: HTMLElement;
}): SocietyModelsSection {
  const title = el('h3', { class: 'society-models-title', text: 'Who runs this world' });
  const roleCard = (role: string): { card: HTMLButtonElement; count: HTMLElement; words: HTMLElement } => {
    const count = el('span', { class: 'society-models-role-count' });
    const words = el('span', { class: 'society-models-role-words' });
    const card = el('button', {
      type: 'button', role: 'tab', class: 'society-models-role', 'data-role': role, 'aria-selected': 'false',
    }, [count, words]) as HTMLButtonElement;
    return { card, count, words };
  };
  const peopleRole = roleCard('people');
  const signalRole = roleCard('signals');
  signalRole.card.hidden = true;
  const roles = el('div', { class: 'society-models-roles', role: 'tablist', 'aria-label': 'What is decided' }, [
    peopleRole.card, signalRole.card,
  ]);
  const lead = el('p', {
    class: 'society-models-lead',
    text: 'Pick an open model to decide what some of the people here do. Every decision is checked '
      + 'before anyone acts on it and kept in this world\'s history, so you can swap the model and '
      + 'compare what changed.',
  });
  const about = el('details', { class: 'society-models-about' }, [
    el('summary', { text: 'How a model decides' }),
    el('p', {
      class: 'world-help',
      text: 'Each person follows their own routine unless you choose a model to decide for them. A '
        + 'model is asked only when their routine would choose what to do next, and it picks among '
        + 'what their routine would let them do then: go to a place with room for them, stand a while '
        + 'nearby, stop to talk with someone near who is free to, or wait where they are. Every answer '
        + 'is checked before anyone acts on it. What it chose is kept in this world\'s history and '
        + 'replayed from there, never asked again.',
    }),
  ]);
  const host = el('p', { class: 'society-models-host', role: 'status' });
  const cards = el('fieldset', { class: 'society-models-choices' });
  const peopleList = el('div', { class: 'society-models-people-list' });
  const everyone = el('button', {
    type: 'button', class: 'society-models-everyone', text: 'Choose everyone', 'data-action': 'people.decides.everyone',
  }) as HTMLButtonElement;
  const limit = el('p', { class: 'society-models-limit' });
  const peopleSet = el('fieldset', { class: 'society-models-people' }, [
    el('legend', { text: 'People' }), limit, everyone, peopleList,
  ]);
  const choose = el('button', {
    type: 'button', class: 'society-models-choose', text: chooseWords(null, 0, false), 'data-action': 'people.decides.choose',
  }) as HTMLButtonElement;
  const result = el('p', { class: 'society-models-result', role: 'status', 'aria-live': 'polite' });
  const summariesHeading = el('h4', { text: 'What each model decided', hidden: true });
  const summaries = el('ul', { class: 'society-models-summaries', hidden: true });
  const checked = new Set<string>();
  let shown: SocietyModels | null = null;
  let picked = ROUTINE;
  let rendered: Parameters<SocietyModelsSection['render']>[0] | null = null;
  let tab: 'people' | 'signals' = 'people';
  /** The role a person picked, kept while it is offered; otherwise people come first. */
  let pickedTab: 'people' | 'signals' | null = null;
  /** Whether the read says these people can be decided for by a model. */
  let takes = false;

  const pickedModel = (): NamedModelRef | null => {
    const ref = optionModel(picked);
    if (ref === null) return null;
    const named = shown?.models.find((held) => held.provider === ref.provider && held.modelId === ref.modelId);
    return named ?? { ...ref, name: ref.modelId };
  };
  const reflectChoose = () => {
    const busy = rendered?.busy ?? false;
    choose.disabled = busy || checked.size === 0;
    setText(choose, chooseWords(pickedModel(), checked.size, busy));
  };
  const model = {
    get value(): string { return picked; },
    set value(next: string) {
      picked = next;
      for (const radio of cards.querySelectorAll<HTMLInputElement>('input[type=radio]')) radio.checked = radio.value === next;
      reflectChoose();
    },
  };
  everyone.addEventListener('click', () => {
    for (const box of peopleList.querySelectorAll<HTMLInputElement>('input[type=checkbox]')) {
      box.checked = true;
      checked.add(box.value);
    }
    reflectChoose();
  });
  choose.addEventListener('click', () => handlers.onChoose([...checked].sort(), optionModel(picked)));
  const peopleGroup = el('div', {
    class: 'society-models-people-group', role: 'tabpanel', 'aria-label': 'People',
  }, [
    lead, host, cards, peopleSet,
    // Kept in view at the panel's foot while the cards and people above it scroll.
    el('div', { class: 'society-models-action' }, [choose, result]),
    about, summariesHeading, summaries,
  ]);
  const signalsGroup = handlers.signals === undefined
    ? null
    : el('div', { class: 'society-models-signals-group', role: 'tabpanel', 'aria-label': 'Traffic lights', hidden: true }, [handlers.signals]);
  const root = el('section', { class: 'society-models', 'aria-label': 'Who decides', hidden: true }, [
    title, roles, peopleGroup, ...(signalsGroup === null ? [] : [signalsGroup]),
  ]);
  const showTab = () => {
    const signalsOffered = !signalRole.card.hidden;
    tab = (pickedTab === 'signals' && signalsOffered) || (!takes && signalsOffered) ? 'signals' : 'people';
    peopleRole.card.setAttribute('aria-selected', String(tab === 'people'));
    signalRole.card.setAttribute('aria-selected', String(tab === 'signals'));
    peopleGroup.hidden = !takes || tab !== 'people';
    if (signalsGroup !== null) signalsGroup.hidden = tab !== 'signals';
    root.hidden = !takes && signalRole.card.hidden;
  };
  peopleRole.card.addEventListener('click', () => { pickedTab = 'people'; showTab(); });
  signalRole.card.addEventListener('click', () => { pickedTab = 'signals'; showTab(); });
  showTab();

  const modelCard = (value: string, name: string, line: string, cost: string | null, titleText: string) => {
    const radio = el('input', { type: 'radio', name: 'society-model', value }) as HTMLInputElement;
    radio.checked = value === picked;
    radio.addEventListener('change', () => { if (radio.checked) model.value = value; });
    return el('label', { class: 'society-models-card', title: titleText }, [
      radio,
      el('span', { class: 'society-models-card-name', text: name }),
      el('span', { class: 'society-models-card-line', text: line }),
      ...(cost === null ? [] : [el('span', { class: 'society-models-card-cost', text: cost })]),
    ]);
  };

  const render: SocietyModelsSection['render'] = (state) => {
    rendered = state;
    const { view, people, busy, message } = state;
    takes = view !== null && view.takesModelChoices;
    peopleRole.card.hidden = !takes;
    result.textContent = message;
    showTab();
    if (view === null || !takes) return;
    setText(peopleRole.count, `People · ${people.length}`);
    setText(peopleRole.words, peopleRoleWords(view, people));
    setText(host, hostWords(view.hostRefusal));
    // The cards are rebuilt only when the models change, so a choice in progress is kept.
    if (shown === null || shown.models !== view.models) {
      if (picked !== ROUTINE && !view.models.some((entry) => optionValue(entry) === picked)) picked = ROUTINE;
      replace(cards, [
        el('legend', { text: 'Decided by' }),
        modelCard(ROUTINE, 'Their own routine', 'What each person would do anyway. No model is asked.', null, 'Their own routine'),
        ...view.models.map((entry) => modelCard(
          optionValue(entry),
          entry.name,
          entry.refusal === null
            ? modelLine(entry)
            : `${modelLine(entry)} Not asked here: ${decisionWords(entry.refusal)}.`,
          costWords(entry, view.models),
          `${entry.description} ${entry.providerDescription} ${priceWords(entry)}`,
        )),
      ]);
    }
    shown = view;
    const present = new Set(people.map((person) => person.id));
    for (const id of [...checked]) if (!present.has(id)) checked.delete(id);
    replace(peopleList, people.map((person) => {
      const box = el('input', { type: 'checkbox', value: person.id }) as HTMLInputElement;
      box.checked = checked.has(person.id);
      box.disabled = busy;
      box.addEventListener('change', () => {
        if (box.checked) checked.add(person.id); else checked.delete(person.id);
        reflectChoose();
      });
      const label = el('label', {}, [
        box,
        el('span', { class: 'society-models-person-name', text: person.name }),
        el('span', { class: 'society-models-person-decider', text: choiceWords(view, person.id) }),
      ]);
      label.dataset['subjectId'] = person.id;
      return label;
    }));
    for (const radio of cards.querySelectorAll<HTMLInputElement>('input[type=radio]')) radio.disabled = busy;
    everyone.disabled = busy || people.length === 0;
    reflectChoose();
    limit.textContent = `A model can decide for at most ${view.modelPeopleMaximum} people here at once.`;
    summariesHeading.hidden = view.byModel.length === 0;
    summaries.hidden = view.byModel.length === 0;
    const window = view.decisionsCounted >= view.decisionsMaximum
      ? [el('li', { class: 'world-help', text: `Counted over the latest ${view.decisionsMaximum} decisions.` })]
      : [];
    replace(summaries, [
      ...view.byModel.map((summary) => {
        const item = el('li', { text: summaryWords(summary) });
        item.dataset['modelId'] = summary.modelId;
        return item;
      }),
      ...window,
    ]);
  };

  const setSignals: SocietyModelsSection['setSignals'] = (summary) => {
    signalRole.card.hidden = summary === null;
    if (summary !== null) {
      setText(signalRole.count, `Traffic lights · ${summary.count}`);
      setText(signalRole.words, summary.words);
    }
    showTab();
  };

  const clearPeople = () => {
    checked.clear();
    for (const box of peopleList.querySelectorAll<HTMLInputElement>('input[type=checkbox]')) box.checked = false;
    reflectChoose();
  };

  return { root, choose, model, render, setSignals, clearPeople };
}

/** Why a choice was refused, in words; the code stays available to the caller. */
export function choiceRefusalWords(code: string, detail: string): string {
  return CHOICE_REFUSAL_WORDS[code] ?? (detail.length > 0
    ? 'The choice was not recorded. Try again, or choose another model.'
    : 'The choice was not recorded.');
}
