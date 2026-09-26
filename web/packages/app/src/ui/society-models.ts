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
  PersonDecision,
  SocietyModels,
} from '../society-models-api.js';
import { DECISION_WORDS } from '../society-inhabitant-words.js';
import { el, replace } from './dom.js';
import './society-models.css';

/**
 * Why this host asks no model for this world's people, by `HOST_REFUSALS` in
 * `society_person_decisions.py`: the section and the inspector each say it in a sentence.
 */
export const HOST_REFUSAL_WORDS: Readonly<Record<string, string>> = {
  models_not_run_here: 'this server does not ask models for this world\'s people',
  provider_credential_absent: 'this server has no key for a model service',
  process_budget_spent: 'this server has spent its model budget until it restarts',
  process_share_spent: 'this server\'s model budget is down to the part kept for its other work, until it restarts',
};

/**
 * Why a person's chosen model is not asked here while this host asks others, by `MODEL_REFUSALS`
 * in `society_person_decisions.py`.
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
};

const decisionWords = (code: string): string =>
  DECISION_WORDS[code] ?? `of a reason this page has no words for (${code})`;
const sentence = (words: string): string => words.charAt(0).toUpperCase() + words.slice(1);

/** Why this host asks nobody's model here, or null when it asks them. */
function hostReason(refusal: string | null): string | null {
  return refusal === null ? null : HOST_REFUSAL_WORDS[refusal] ?? `this server does not ask models here (${refusal})`;
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

export interface SocietyModelsSection {
  readonly root: HTMLElement;
  readonly choose: HTMLButtonElement;
  readonly model: HTMLSelectElement;
  render(state: {
    readonly view: SocietyModels | null;
    readonly people: readonly ChoosablePerson[];
    readonly busy: boolean;
    /** What the last choice or read came to, or empty. */
    readonly message: string;
  }): void;
}

/** The routine's option, and each model's: its provider and identifier, which hold no space. */
const ROUTINE = '';
const optionValue = (ref: ModelRef): string => `${ref.provider} ${ref.modelId}`;
function optionModel(value: string): ModelRef | null {
  const space = value.indexOf(' ');
  return space < 0 ? null : { provider: value.slice(0, space), modelId: value.slice(space + 1) };
}

export function buildSocietyModels(handlers: {
  readonly onChoose: (people: readonly string[], model: ModelRef | null) => void;
}): SocietyModelsSection {
  const heading = el('h4', { text: 'Who decides for them' });
  const about = el('p', {
    class: 'world-help',
    text: 'Each person follows their own routine unless you choose a model to decide for them. A '
      + 'model is asked only when their routine would choose what to do next. It picks a place '
      + 'with room for them to go to, or waiting where they are, and every answer is checked before '
      + 'anyone acts on it. What it chose is kept in this world\'s history and replayed from there, '
      + 'never asked again.',
  });
  const host = el('p', { class: 'society-models-host', role: 'status' });
  const model = el('select', { 'aria-label': 'Who decides' }) as HTMLSelectElement;
  const modelLabel = el('label', { class: 'society-models-model' }, [document.createTextNode('Decided by '), model]);
  const peopleList = el('fieldset', { class: 'society-models-people' });
  const everyone = el('button', { type: 'button', text: 'Choose everyone' }) as HTMLButtonElement;
  const choose = el('button', { type: 'button', text: 'Use for the chosen people' }) as HTMLButtonElement;
  const limit = el('p', { class: 'world-help' });
  const result = el('p', { class: 'society-models-result', role: 'status', 'aria-live': 'polite' });
  const summariesHeading = el('h4', { text: 'What each model decided', hidden: true });
  const summaries = el('ul', { class: 'society-models-summaries', hidden: true });
  const checked = new Set<string>();
  let shown: SocietyModels | null = null;
  everyone.addEventListener('click', () => {
    for (const box of peopleList.querySelectorAll<HTMLInputElement>('input[type=checkbox]')) {
      box.checked = true;
      checked.add(box.value);
    }
    choose.disabled = checked.size === 0;
  });
  choose.addEventListener('click', () => handlers.onChoose([...checked].sort(), optionModel(model.value)));
  const root = el('section', { class: 'society-models', 'aria-label': 'Who decides for them', hidden: true }, [
    heading, about, host, modelLabel, peopleList, everyone, choose, limit, result, summariesHeading, summaries,
  ]);

  const render: SocietyModelsSection['render'] = ({ view, people, busy, message }) => {
    root.hidden = view === null || !view.takesModelChoices;
    result.textContent = message;
    if (view === null || !view.takesModelChoices) return;
    host.textContent = hostWords(view.hostRefusal);
    // The options are rebuilt only when the models change, so a choice in progress is kept.
    if (shown === null || shown.models !== view.models) {
      const previous = model.value;
      replace(model, [
        el('option', { value: ROUTINE, text: 'Their own routine' }),
        ...view.models.map((entry) => el('option', {
          value: optionValue(entry),
          text: entry.refusal === null
            ? entry.name
            : `${entry.name} (not asked here: ${decisionWords(entry.refusal)})`,
          title: `${entry.description} ${entry.providerDescription}`,
        })),
      ]);
      if ([...model.options].some((option) => option.value === previous)) model.value = previous;
    }
    shown = view;
    const present = new Set(people.map((person) => person.id));
    for (const id of [...checked]) if (!present.has(id)) checked.delete(id);
    replace(peopleList, [
      el('legend', { text: 'People' }),
      ...people.map((person) => {
        const box = el('input', { type: 'checkbox', value: person.id }) as HTMLInputElement;
        box.checked = checked.has(person.id);
        box.addEventListener('change', () => {
          if (box.checked) checked.add(person.id); else checked.delete(person.id);
          choose.disabled = busy || checked.size === 0;
        });
        const label = el('label', {}, [box, document.createTextNode(` ${person.name} · ${choiceWords(view, person.id)}`)]);
        label.dataset['subjectId'] = person.id;
        return label;
      }),
    ]);
    model.disabled = busy;
    everyone.disabled = busy || people.length === 0;
    choose.disabled = busy || checked.size === 0;
    choose.textContent = busy ? 'Choosing…' : 'Use for the chosen people';
    limit.textContent = `A model can decide for at most ${view.modelPeopleMaximum} people in this world at once.`;
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

  return { root, choose, model, render };
}

/** Why a choice was refused, in words; the code stays available to the caller. */
export function choiceRefusalWords(code: string, detail: string): string {
  return CHOICE_REFUSAL_WORDS[code] ?? `The choice was not recorded. ${detail}`;
}
