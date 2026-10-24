// @vitest-environment happy-dom
// The label over a looked-at character (r04, tools/previews/world-workspace/character-group.ts): their name, what they
// are doing and, where a model decides for them, the model's chip (DESIGN's aha 19), with its live dot while a run
// asks it, so the world says who has a model before a run and during one.
import { afterEach, describe, expect, it, vi } from 'vitest';

/** What these tests use of the preview modules, which sit outside this package. */
interface LookWords { name: string; doing: string | null; model?: string | null; live?: boolean; quiet?: boolean }
interface LookLabel { readonly root: HTMLElement; set(words: LookWords | null, inspectable: boolean): void }
// A joined path: the test runner still finds the file, and the type checker leaves the preview module out of the program.
// The presence that hands the label its words (character-presence.ts) reads the page's own modules by the page's paths,
// so it is proved on the page.
const group = async (): Promise<{
  lookLabel(options: { scale: () => number; onInspect: () => void }): LookLabel;
  characterGroup(options: { scale: () => number; onAction: (action: string) => void }): { root: HTMLElement; set(content: unknown): void };
}> =>
  import('../../../../tools/previews/world-workspace/' + 'character-group.ts') as never;

afterEach(() => { document.body.replaceChildren(); });

describe('the label over a looked-at character', () => {
  it('carries the chip of the model that decides for them, live while a run asks it, and none without one', async () => {
    const { lookLabel } = await group();
    const label = lookLabel({ scale: () => 1, onInspect: vi.fn() });
    document.body.append(label.root);
    const chip = () => label.root.querySelector('.cg-look-chip') as HTMLElement;
    label.set({ name: 'Ines', doing: 'Walking to the lower pools', model: 'Qwen3 235B Instruct' }, true);
    expect(chip().hidden).toBe(false);
    expect(chip().textContent).toBe('Qwen3 235B Instruct');
    expect(chip().querySelector('.wu-live-dot')).toBeNull();
    label.set({ name: 'Ines', doing: 'Walking to the lower pools', model: 'Qwen3 235B Instruct', live: true }, true);
    expect(chip().querySelector('.wu-live-dot')).not.toBeNull();
    // Someone their routine decides for: no chip, and no dot left over from the last one looked at.
    label.set({ name: 'Teo', doing: 'Waiting by the bench', model: null }, true);
    expect(chip().hidden).toBe(true);
    expect(chip().querySelector('.wu-live-dot')).toBeNull();
  });
});

describe('an outside AI agent looked at and chosen (AG1d)', () => {
  it("names it in the chip's quiet fill, live while its program answers", async () => {
    const { lookLabel } = await group();
    const label = lookLabel({ scale: () => 1, onInspect: vi.fn() });
    document.body.append(label.root);
    const chip = () => label.root.querySelector('.cg-look-chip') as HTMLElement;
    label.set({ name: 'Visitor', doing: 'Talking with Juno Ford', model: 'An outside AI agent', live: true, quiet: true }, true);
    expect(chip().textContent).toBe('An outside AI agent');
    expect(chip().classList.contains('wu-quiet')).toBe(true);
    expect(chip().querySelector('.wu-live-dot')).not.toBeNull();
    // A model's chip after it: the luminous fill again.
    label.set({ name: 'Ines', doing: null, model: 'Qwen3 235B Instruct' }, true);
    expect(chip().classList.contains('wu-quiet')).toBe(false);
  });

  it('draws its own words under the print as text, its declared parts apart from ours', async () => {
    const { characterGroup } = await group();
    const shown = characterGroup({ scale: () => 1, onAction: () => {} });
    document.body.append(shown.root);
    shown.set({ name: 'Visitor', doing: null, said: null, note: null, rows: [], list: null, refused: false, after: null,
      print: 'An outside AI agent decides for the visitor.',
      declared: [{ words: 'In its own words: ', declared: false }, { words: '<b>Scout</b>', declared: true }, { words: '.', declared: false }] });
    const declared = shown.root.querySelector('.cg-declared')!;
    expect(declared.textContent).toBe('In its own words: <b>Scout</b>.');
    expect(declared.querySelector('b')).toBeNull();
    expect([...declared.querySelectorAll('.cg-declared-own')].map((node) => node.textContent)).toEqual(['<b>Scout</b>']);
    expect(shown.root.querySelector('.cg-print')?.nextElementSibling).toBe(declared);
  });
});
