// @vitest-environment happy-dom
// The model gallery's page (G2, tools/previews/world-workspace/model-gallery.ts): M on a chosen person opens it over the
// world; its rows in their groups, the model in focus opened at the right, the keys. A number chooses at once through
// the host's own write and the page closes; Esc closes it unchanged; a refused write keeps it with its words.
import { afterEach, describe, expect, it, vi } from 'vitest';

type Json = Record<string, any>;
interface Gallery { open(row: Json): void; close(): void; key(event: KeyboardEvent): boolean; readonly isOpen: boolean }
// A joined path: the test runner still finds the file, and the type checker leaves the preview module out of the program.
const module = async (): Promise<{ mountModelGallery(hooks: Json): Gallery }> =>
  import('../../../../tools/previews/world-workspace/' + 'model-gallery.ts') as Promise<{ mountModelGallery(hooks: Json): Gallery }>;

const mark = '<img src=x onerror="window.ranMarkup = true">';
const card = { maker: 'NVIDIA', parameters: { total: '30B', active: '3.5B' }, licence: 'NVIDIA Nemotron Open Model License',
  says: 'A general purpose reasoning and chat model.', source: `https://huggingface.co/nvidia/model/blob/${'0'.repeat(40)}/README.md`, readOn: '2026-10-23' };
const read = {
  takesModelChoices: true, requestTokensAtMost: 7200, decisionsCounted: 3, decisionsMaximum: 2000,
  models: [
    { provider: 'nebius_token_factory', providerDescription: 'Nebius Token Factory, which serves open models.', modelId: 'nvidia/nano', name: 'Nemotron 3 Nano 30B',
      mechanism: 'tool_call', price: { input: '0.06', output: '0.24' }, card, contextWindowTokens: 262144, decisionMostUsd: '0.00540000', attemptMostUsd: '0.00270000' },
  ],
  byModel: [{ provider: 'nebius_token_factory', modelId: 'nvidia/nano', decisions: 3, costMedianUsd: '0.00010224', costsCounted: 3 }],
  runnerModels: [{ name: `tiny${mark}`, state: 'checking' }],
};
const row = { key: 'teo', scene: { id: 'teo' } };

async function mounted(write = vi.fn(async () => read)) {
  const root = document.createElement('div');
  document.body.append(root);
  const hooks = {
    root, read: () => read, still: () => null, portrait: () => null, fromServer: () => false,
    about: () => ({ who: { title: 'Teo', start: 'Teo', within: 'Teo', named: true }, doing: 'Resting at the bench', current: null }),
    write, refusal: () => 'This model cannot decide for Teo here.', chosen: vi.fn(), closed: vi.fn(),
  };
  const gallery = (await module()).mountModelGallery(hooks);
  gallery.open(row);
  return { root, gallery, hooks };
}

const press = (gallery: Gallery, code: string) => gallery.key(new KeyboardEvent('keydown', { code }));
const all = (root: ParentNode, selector: string) => [...root.querySelectorAll(selector)].map((node) => node.textContent);

afterEach(() => { document.body.replaceChildren(); });

describe('the model gallery page (G2)', () => {
  it('opens over the world with its head, its groups and the model in focus, every name drawn as text', async () => {
    const { root } = await mounted();
    expect(root.querySelector('.wu-g2-title')?.textContent).toBe('Choose an AI model for Teo');
    expect(all(root, '.wu-g2-label')).toEqual(['On this computer, free', 'With your Nebius key', 'No AI model']);
    expect(all(root, '.wu-g2-row:not(.faint) .wu-g2-name')).toEqual(['Nemotron 3 Nano 30B', 'RoutineCurrent']);
    expect(all(root, '.wu-g2-row:not(.faint) .wu-g2-cost')).toEqual(['about $0.0001 a decision', 'Free']);
    // A runner's model being checked stands faint, its name as text, never markup.
    expect(all(root, '.wu-g2-row.faint .wu-g2-name')).toEqual([`tiny${mark} · Checking that it can decide for a person here…`]);
    expect(root.querySelector('img')).toBeNull();
    // The focus opens on the first model with its maker's words; its detail says what the read holds.
    expect(root.querySelector('.wu-g2-row[aria-current="true"] .wu-g2-name')?.textContent).toBe('Nemotron 3 Nano 30B');
    expect(root.querySelector('.wu-g2-dname')?.textContent).toBe('Nemotron 3 Nano 30B');
    expect(root.querySelector('.wu-g2-link')?.getAttribute('href')).toBe(card.source);
    expect(all(root, '.wu-g2-fk')).toEqual(['Size', 'Reads', 'Licence', 'Runs on', 'A decision', 'In this world']);
  });

  it('chooses at once by a number through the host\'s write, then closes; Esc closes unchanged', async () => {
    const { gallery, hooks } = await mounted();
    press(gallery, 'Digit1');
    await vi.waitFor(() => expect(hooks.closed).toHaveBeenCalledTimes(1));
    expect(hooks.write).toHaveBeenCalledWith(row, read.models[0], expect.any(String));
    expect(hooks.chosen).toHaveBeenCalledWith(read);
    expect(gallery.isOpen).toBe(false);
    const again = await mounted();
    press(again.gallery, 'ArrowDown');
    press(again.gallery, 'Escape');
    expect(again.hooks.write).not.toHaveBeenCalled();
    expect(again.hooks.closed).toHaveBeenCalledTimes(1);
  });

  it('keeps the page with the refusal in its words where the write is refused, and Enter chooses the routine', async () => {
    const refused = vi.fn(async () => { throw { code: 'decided_from_outside' }; });
    const { root, gallery, hooks } = await mounted(refused);
    press(gallery, 'ArrowDown');
    press(gallery, 'Enter');
    await vi.waitFor(() => expect(root.querySelector('.wu-g2-refused')?.textContent).toBe('This model cannot decide for Teo here.'));
    expect(refused).toHaveBeenCalledWith(row, null, expect.any(String));
    expect(gallery.isOpen).toBe(true);
    expect(hooks.closed).not.toHaveBeenCalled();
    // A refusal stays at the card's bottom with its action row, never scrolled away with the card's words.
    expect(root.querySelector('.wu-g2-refused')!.closest('.wu-g2-scroll')).toBeNull();
  });

  it('scrolls the list and the card\'s words in their own columns, its action row and keys outside them (DESIGN 1026)', async () => {
    const { root } = await mounted();
    const words = root.querySelector('.wu-g2-detail .wu-g2-scroll')!;
    expect(all(words, '.wu-g2-fk')).toContain('Licence');
    for (const fixed of ['.wu-g2-act', '.wu-g2-keys']) expect(root.querySelector(fixed)!.closest('.wu-g2-scroll, .wu-g2-list')).toBeNull();
    expect(root.querySelector('.wu-g2-keys')!.closest('.wu-g2-body')).toBeNull();
    // The person at the head: their portrait, or the first letter of their name until one exists.
    expect(root.querySelector('.wu-g2-head .wu-hr-orb')?.textContent).toBe('T');
  });
});
