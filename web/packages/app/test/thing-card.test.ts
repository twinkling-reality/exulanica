// @vitest-environment happy-dom
// The thing card for a person: what they are, what they are doing, what mind runs them (with the
// AI mark whenever a model is asked), the mind changed in two clicks through Who decides' own
// choose, and where they came from. Expected words come from the design the operator approved
// (deliveries CARD design.md sections 1, 2 and 5) and from the models read's served names.
import { describe, expect, it, vi } from 'vitest';
import { mountThingCard, personCard } from '../src/composition/thing-card-mount.js';
import type { SelectedPerson } from '../src/composition/environment-selection.js';
import type { SocietyModel } from '../src/society-models-api.js';

const model = (name: string, modelId: string, input: string, refusal: string | null = null): SocietyModel => ({
  provider: 'nebius', modelId, name,
  description: `${name}, an open model served on Nebius.`, providerDescription: 'Nebius Token Factory',
  mechanism: 'tool_call', price: { input, output: input }, refusal,
});
const NEMOTRON = model('Nemotron 3 Nano 30B', 'nvidia/nemotron-3-nano-30b', '0.06');
const QWEN = model('Qwen3 235B Instruct', 'Qwen/Qwen3-235B-A22B-Instruct-2507', '0.20');
const MODELS = [NEMOTRON, QWEN];

const note = {
  subject: 'person-0', title: 'Person 0', description: 'A simulated steward, invented for this world.',
  activity: 'Resting at the bench. Because they were tired.', details: [],
};
const about = (mind: SelectedPerson['mind']): SelectedPerson => ({ note, mind });
const run = (held: SocietyModel) => ({ provider: held.provider, modelId: held.modelId, name: held.name });

function mount(models: readonly SocietyModel[] | null = MODELS) {
  const decide = vi.fn(async () => ({
    recorded: true, words: 'One person is now decided by the model you chose, from the next time they choose what to do.',
  }));
  const openDecides = vi.fn(() => 1);
  const compare = vi.fn();
  const card = mountThingCard({ selection: { decide, models: () => models, openDecides }, compare });
  document.body.replaceChildren(card.view.root);
  return { card, decide, openDecides, compare, root: card.view.root };
}
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const click = (root: HTMLElement, action: string, key?: string) => {
  const found = [...root.querySelectorAll<HTMLButtonElement>(`[data-action="${action}"]`)]
    .find((button) => key === undefined || button.dataset['key'] === key);
  expect(found, `${action} ${key ?? ''}`).toBeDefined();
  found!.click();
};

describe('the thing card for a person', () => {
  it('leads with who they are, what they are doing and the mind that runs them, marked AI', () => {
    const { card, root } = mount();
    expect(card.view.show('person-0', about({ running: run(QWEN), words: 'Qwen3 235B Instruct, which you chose.' }))).toBe(true);
    expect(root.querySelector('h3')?.textContent).toBe('Person 0');
    expect(root.querySelector('.thing-card-summary')?.textContent).toBe('A simulated steward, invented for this world.');
    expect(root.querySelector('.thing-card-now')?.textContent).toBe('NowResting at the bench. Because they were tired.');
    expect(root.querySelector('.thing-card-mind-name')?.textContent).toBe('Qwen3 235B Instruct');
    // The mark beside the title and beside the mind: the letters AI, and who runs it in words.
    const marks = [...root.querySelectorAll<HTMLElement>('.thing-card-mark')];
    expect(marks.map((mark) => [mark.textContent, mark.getAttribute('aria-label')])).toEqual([
      ['AI', 'run by an AI model, Qwen3 235B Instruct'],
      ['AI', 'run by an AI model, Qwen3 235B Instruct'],
    ]);
    expect(root.textContent).toContain('Came from');
    expect(root.textContent).toContain('One of the people who live in this world.');
  });

  it('wears no mark where their routine decides, and says why a chosen model is not asked', () => {
    const { card, root } = mount();
    card.view.show('person-0', about({ running: null, words: 'Their own routine.' }));
    expect(root.querySelector('.thing-card-mark')).toBeNull();
    expect(root.querySelector('.thing-card-mind-name')?.textContent).toBe('Their own routine');
    expect(root.textContent).toContain('What they would do anyway. No AI is asked.');
    const refused = 'Their own routine for now, because this server asks no model. You chose Qwen3 235B Instruct.';
    card.view.show('person-0', about({ running: null, words: refused }));
    expect(root.querySelector('.thing-card-mark')).toBeNull();
    expect(root.textContent).toContain(refused);
  });

  it('changes their mind in two clicks, by Who decides\' own choose, and says what came of it', async () => {
    const { card, root, decide } = mount();
    card.view.show('person-0', about({ running: null, words: 'Their own routine.' }));
    click(root, 'card.mind.change');
    const choices = [...root.querySelectorAll<HTMLButtonElement>('[data-action="card.mind.choose"]')];
    expect(choices.map((choice) => choice.querySelector('.thing-card-choice-name')?.textContent))
      .toEqual(['Their own routine', 'Nemotron 3 Nano 30B', 'Qwen3 235B Instruct']);
    // The one running now is marked and cannot be chosen again; the cost words are Who decides'.
    expect(choices[0]!.disabled).toBe(true);
    expect(choices.map((choice) => choice.querySelector('.thing-card-now-badge, .thing-card-badge')?.textContent))
      .toEqual(['Now', 'Lowest cost', 'About 3 times the lowest cost']);
    click(root, 'card.mind.choose', `nebius ${NEMOTRON.modelId}`);
    await settle();
    expect(decide).toHaveBeenCalledWith({
      role: 'people', subjectIds: ['person-0'], model: { provider: 'nebius', modelId: NEMOTRON.modelId },
    });
    expect(root.querySelector('.thing-card-outcome')?.textContent)
      .toBe('One person is now decided by the model you chose, from the next time they choose what to do.');
    expect(root.querySelector('[data-action="card.mind.choose"]')).toBeNull();
  });

  it('gives a person back their routine with no model', async () => {
    const { card, root, decide } = mount();
    card.view.show('person-0', about({ running: run(QWEN), words: 'Qwen3 235B Instruct, which you chose.' }));
    click(root, 'card.mind.change');
    click(root, 'card.mind.choose', 'routine');
    await settle();
    expect(decide).toHaveBeenCalledWith({ role: 'people', subjectIds: ['person-0'], model: null });
  });

  it('opens every mind in this world with this person chosen, and Compare one link deeper', () => {
    const { card, root, openDecides, compare } = mount();
    card.view.show('person-0', about({ running: null, words: 'Their own routine.' }));
    click(root, 'card.mind.all');
    expect(openDecides).toHaveBeenCalledWith({ role: 'people', subjectIds: ['person-0'] });
    click(root, 'card.mind.compare');
    expect(compare).toHaveBeenCalledTimes(1);
  });

  it('offers no change where nobody here can be run by a model', () => {
    const { card, root } = mount(null);
    card.view.show('person-0', about(null));
    expect(root.querySelector('[data-action="card.mind.change"]')).toBeNull();
    expect(root.querySelector('[data-action="card.mind.compare"]')).toBeNull();
    expect(root.textContent).toContain('The people of this world follow their own routine. No AI is asked.');
  });

  it('keeps an open choice across a refresh of the same person, and closes it for another', () => {
    const { card, root } = mount();
    card.view.show('person-0', about({ running: null, words: 'Their own routine.' }));
    click(root, 'card.mind.change');
    card.view.show('person-0', about({ running: null, words: 'Their own routine.' }));
    expect(root.querySelector('[data-action="card.mind.choose"]')).not.toBeNull();
    card.view.show('person-1', about({ running: null, words: 'Their own routine.' }));
    expect(root.querySelector('[data-action="card.mind.choose"]')).toBeNull();
  });

  it('builds the same words without a page, from what Selected knows', () => {
    const built = personCard('person-0', about({ running: run(NEMOTRON), words: 'Nemotron 3 Nano 30B, which you chose.' }), MODELS);
    expect(built.mark).toEqual({ kind: 'ai', text: 'AI', label: 'run by an AI model, Nemotron 3 Nano 30B' });
    expect(built.mind?.line).toBe('An open model served on Nebius.');
    expect(built.mind?.choices.find((choice) => choice.now)?.name).toBe('Nemotron 3 Nano 30B');
  });
});
