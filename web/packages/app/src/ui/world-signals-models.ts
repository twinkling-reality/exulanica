/** The traffic-light role in a saved world's Who decides panel. */

import type { ModelRef } from '../society-models-api.js';
import type { SignalChoice, SignalRole } from '../world-models-api.js';
import { el, replace } from './dom.js';

const optionValue = (model: ModelRef): string => `${model.provider} ${model.modelId}`;
const optionModel = (value: string): ModelRef | null => {
  const space = value.indexOf(' ');
  return space < 0 ? null : { provider: value.slice(0, space), modelId: value.slice(space + 1) };
};
const at = (second: number): string => new Date(second * 1000).toLocaleTimeString([], {
  hour: 'numeric', minute: '2-digit',
});

const refusalWords: Readonly<Record<string, string>> = {
  models_not_run_here: 'this server is not enabled to ask models for this world',
  provider_credential_absent: 'this server has no key for that model service',
  process_budget_spent: 'this server has spent its model budget',
  process_share_spent: 'this server has reached the part of its budget kept for other work',
  model_no_longer_offered: 'the chosen model is no longer offered',
  provider_changed: 'the model service has changed',
  provider_not_admitted: 'this server cannot reach that model service',
};
const why = (code: string): string => refusalWords[code] ?? `the model is unavailable (${code})`;

export function signalChoiceWords(choice: SignalChoice | undefined, refusal: string | null): string {
  if (choice === undefined) return 'Fixed timing decides this light.';
  if (choice.model === null) return choice.status === 'pending' && choice.runningModel !== null
    ? `${choice.runningModel.name} continues until fixed timing begins at ${at(choice.effectiveSecond)}.`
    : 'Fixed timing decides this light.';
  const unavailable = refusal ?? choice.refusal;
  if (choice.status === 'pending') return `${choice.model.name} is scheduled from ${at(choice.effectiveSecond)}. ${choice.runningModel === null ? 'Fixed timing' : choice.runningModel.name} continues until a decision is sealed.`;
  if (choice.status === 'preparing') return `Fixed timing decides this light while ${choice.model.name} has no sealed decision.`;
  if (choice.status === 'active' && unavailable === null) return `${choice.model.name} runs this light. Its first sealed decision took effect at ${at(choice.activeSecond ?? choice.effectiveSecond)}.`;
  if (choice.status === 'active') return `${choice.model.name} has a sealed decision, but fixed timing handles choices while ${why(unavailable ?? 'model_unavailable')}.`;
  return 'Fixed timing decides this light.';
}

export interface SignalModelsSection {
  readonly root: HTMLElement;
  render(view: SignalRole | null, busy: boolean, message: string): void;
}

export function buildSignalModels(handlers: {
  readonly onChoose: (signalId: string, model: ModelRef | null) => void;
}): SignalModelsSection {
  const heading = el('h4', { text: 'Traffic lights' });
  const about = el('p', { class: 'world-help', text:
    'At a high street crossing, a chosen model can keep one green for a second when a vehicle is near. '
    + 'The fixed plan sets the minimum green, amber and all-red intervals. Every answer is checked '
    + 'by the traffic step and replayed from the recorded choice.' });
  const host = el('p', { class: 'society-models-host', role: 'status' });
  const signal = el('select', { 'aria-label': 'Traffic light' }) as HTMLSelectElement;
  const signalLabel = el('label', { class: 'society-models-model' }, [
    document.createTextNode('Traffic light '), signal,
  ]);
  const model = el('select', { 'aria-label': 'Who decides this traffic light' }) as HTMLSelectElement;
  const modelLabel = el('label', { class: 'society-models-model' }, [
    document.createTextNode('Decided by '), model,
  ]);
  const choose = el('button', { type: 'button', text: 'Use for this traffic light' }) as HTMLButtonElement;
  const result = el('p', { class: 'society-models-result', role: 'status', 'aria-live': 'polite' });
  const statuses = el('ul', { class: 'society-models-summaries' });
  choose.addEventListener('click', () => {
    if (signal.value) handlers.onChoose(signal.value, optionModel(model.value));
  });
  const root = el('div', { class: 'world-signal-models', hidden: true }, [
    heading, about, host, signalLabel, modelLabel, choose, result, statuses,
  ]);

  const render = (view: SignalRole | null, busy: boolean, message: string): void => {
    root.hidden = view === null || !view.available || view.subjects.length === 0;
    result.textContent = message;
    if (root.hidden || view === null) return;
    const previousSignal = signal.value;
    const previousModel = model.value;
    replace(signal, view.subjects.map((subject) => el('option', {
      value: subject.signalId, text: subject.label,
    })));
    signal.value = [...signal.options].some((option) => option.value === previousSignal)
      ? previousSignal : view.subjects[0]!.signalId;
    replace(model, [
      el('option', { value: '', text: 'Fixed timing' }),
      ...view.models.map((entry) => el('option', {
        value: optionValue(entry), text: entry.name,
        title: entry.description,
      })),
    ]);
    if ([...model.options].some((option) => option.value === previousModel)) model.value = previousModel;
    const refusal = view.hostRefusal;
    host.textContent = refusal === null
      ? 'This server prepares model decisions before a traffic minute is shown.'
      : `Fixed timing continues because ${why(refusal)}.`;
    signal.disabled = busy;
    model.disabled = busy;
    choose.disabled = busy;
    choose.textContent = busy ? 'Choosing…' : 'Use for this traffic light';
    const choices = new Map(view.choices.map((choice) => [choice.subjectId, choice]));
    replace(statuses, view.subjects.map((subject) => el('li', {
      text: `${subject.label}: ${signalChoiceWords(choices.get(subject.signalId), refusal)}`,
    })));
  };
  return { root, render };
}
