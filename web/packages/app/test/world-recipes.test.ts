// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { buildWorldRecipes } from '../src/ui/world-recipes.js';
import { attachWorldDescription } from '../src/composition/world-description.js';
import { parseWorldSpecification } from '../src/world-specification.js';
import type { SavedWorldEntry } from '../src/world-entry-api.js';
import { servedSpecification } from './world-specification-document.js';

/**
 * Making a world: the presets the served document offers, a control for each adjustable value,
 * the page's statement of a refusal before anything is sent, and `setValues`, which loads a preset
 * and values from elsewhere and checks them as a person's edit is checked.
 */

function panel(served: Record<string, unknown> = servedSpecification()) {
  const made: { preset: string; values: Record<string, number | string> }[] = [];
  const opened: SavedWorldEntry[] = [];
  const entry = { entryId: 'made' } as SavedWorldEntry;
  const built = buildWorldRecipes({
    specification: async () => parseWorldSpecification(served),
    make: vi.fn(async (preset, values) => {
      made.push({ preset: preset.key, values: { ...values } });
      return entry;
    }),
    open: async (chosen) => { opened.push(chosen); },
    onClose: () => undefined,
  });
  document.body.replaceChildren(built.root);
  return { built, made, opened };
}

const settle = async (): Promise<void> => {
  for (let turn = 0; turn < 10; turn += 1) await Promise.resolve();
};

describe('the panel that makes a world', () => {
  it('offers each preset and a control for each adjustable value, and makes the one chosen', async () => {
    const { built, made, opened } = panel();
    await settle();
    const choices = [...built.root.querySelectorAll<HTMLButtonElement>('[data-recipe]')];
    expect(choices.map((choice) => choice.textContent)).toEqual(['A small town', 'A market town']);
    choices[0]!.click();
    const controls = [...built.root.querySelectorAll<HTMLInputElement>('[data-parameter]')];
    // Only adjustable values get a control; the fixed depth and driving side do not.
    expect(controls.map((control) => control.getAttribute('data-parameter'))).toEqual(['city_extent_x_mm', 'block_length_mm']);
    const length = controls[1]!;
    // Two tiles take cross streets at most 120 m apart, so that is the most the control offers.
    expect([length.min, length.max, length.step, length.value]).toEqual(['90000', '120000', '10000', '90000']);
    expect(built.root.querySelector('output')?.textContent).toBe('256 m');
    length.value = '120000';
    length.dispatchEvent(new Event('input'));
    // A person making the town three tiles long moves the block length's range to what three tiles
    // take, and the length they set moves to its nearest end; back at two tiles it moves again.
    const town = controls[0]!;
    town.value = '384000';
    town.dispatchEvent(new Event('input'));
    expect([length.min, length.max, length.value]).toEqual(['130000', '140000', '130000']);
    town.value = '256000';
    town.dispatchEvent(new Event('input'));
    expect([length.min, length.max, length.value]).toEqual(['90000', '120000', '120000']);
    const make = built.root.querySelector<HTMLButtonElement>('.world-recipes-make')!;
    expect(make.disabled).toBe(false);
    make.click();
    await settle();
    expect(made).toEqual([{ preset: 'small_town', values: { city_extent_x_mm: 256000, block_length_mm: 120000 } }]);
    expect(opened).toHaveLength(1);
  });

  it('loads values from elsewhere and checks them as a person\'s edit is checked', async () => {
    const { built, made } = panel();
    const refused = await built.setValues('market_town', { block_length_mm: 150000 });
    expect(refused).toMatchObject({ code: 'specification_value_out_of_range', key: 'block_length_mm' });
    const make = built.root.querySelector<HTMLButtonElement>('.world-recipes-make')!;
    expect(make.disabled).toBe(true);
    expect(built.root.getAttribute('data-specification-state')).toBe('specification_value_out_of_range');
    expect(built.root.querySelector('.world-recipes-status')?.textContent).toContain('90000 to 140000 mm in steps of 10000');
    make.click();
    await settle();
    expect(made).toEqual([]);

    expect(await built.setValues('market_town', { block_depth_mm: 52000 })).toMatchObject({ code: 'specification_value_unknown' });
    // The market town is three tiles long, whose blocks are at least 130 m: values from elsewhere
    // are checked, never moved.
    expect(await built.setValues('market_town', { block_length_mm: 90000 })).toMatchObject({
      code: 'specification_values_disagree', key: 'block_length_mm',
    });
    expect(built.root.querySelector<HTMLInputElement>('[data-parameter="block_length_mm"]')!.min).toBe('130000');
    expect(await built.setValues('a_town_nobody_offers', {})).toMatchObject({ code: 'unknown_world_recipe' });

    expect(await built.setValues('market_town', { block_length_mm: 130000 })).toBeNull();
    expect(built.root.getAttribute('data-specification-state')).toBe('admitted');
    const length = built.root.querySelector<HTMLInputElement>('[data-parameter="block_length_mm"]')!;
    expect(length.value).toBe('130000');
    expect(built.root.querySelector<HTMLButtonElement>('[data-recipe="market_town"]')?.getAttribute('aria-pressed')).toBe('true');
    make.click();
    await settle();
    expect(made).toEqual([{ preset: 'market_town', values: { city_extent_x_mm: 384000, block_length_mm: 130000 } }]);
  });

  it('words a choice by the label the server states and a share out of a thousand', async () => {
    const served = servedSpecification();
    const values = served['values'] as Record<string, unknown>[];
    values.push(
      { key: 'cross_street_hierarchy', label: 'The other cross streets', kind: 'choice', unit: 'key', adjustable: true,
        choices: ['local_street', 'narrow_street'], choice_labels: ['Local street', 'Narrow street'], requires: [],
        reason: 'Measured: local or narrow.' },
      { key: 'typology_weight_shophouse_permille', label: 'Share of shophouses', kind: 'integer', unit: 'permille',
        adjustable: true, minimum: 0, maximum: 1000, step: 50, requires: [], reason: 'Authored: a weight among kinds.' },
    );
    for (const preset of served['presets'] as { values: Record<string, unknown> }[]) {
      preset.values['cross_street_hierarchy'] = 'local_street';
      preset.values['typology_weight_shophouse_permille'] = 500;
    }
    const { built } = panel(served);
    await settle();
    built.root.querySelector<HTMLButtonElement>('[data-recipe="small_town"]')!.click();
    const select = built.root.querySelector<HTMLSelectElement>('[data-parameter="cross_street_hierarchy"]')!;
    expect([...select.options].map((option) => [option.value, option.textContent])).toEqual([
      ['local_street', 'Local street'], ['narrow_street', 'Narrow street'],
    ]);
    const output = (key: string) => built.root.querySelector(`[data-parameter="${key}"]`)!.parentElement!.querySelector('output')!.textContent;
    expect(output('cross_street_hierarchy')).toBe('Local street');
    select.value = 'narrow_street';
    select.dispatchEvent(new Event('input'));
    expect(output('cross_street_hierarchy')).toBe('Narrow street');
    expect(output('typology_weight_shophouse_permille')).toBe('500 of 1,000');
    // A choice's labels must match its choices one for one, or the document is refused.
    const broken = servedSpecification();
    (broken['values'] as Record<string, unknown>[]).push({ ...values.at(-2)!, choice_labels: ['Local street'] });
    expect(() => parseWorldSpecification(broken)).toThrow('choice labels');
  });
});

describe('focus when Create a world opens', () => {
  const open = (specification: () => Promise<ReturnType<typeof parseWorldSpecification>>) => {
    const onClose = vi.fn();
    const built = buildWorldRecipes({
      specification, make: vi.fn(), open: vi.fn(async () => undefined), onClose,
    });
    document.body.replaceChildren(built.root);
    return { built, onClose };
  };
  const escape = (): void => {
    (document.activeElement ?? document.body).dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  };

  it('is inside the sheet from the moment it opens, so Escape closes it', () => {
    // The served document has not arrived: the only button is hidden Create this town and Close.
    const { built, onClose } = open(() => new Promise(() => undefined));
    built.focus();
    expect(built.root.contains(document.activeElement)).toBe(true);
    expect((document.activeElement as HTMLElement).closest('[hidden]')).toBeNull();
    escape();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('moves to Describe it once it is attached, the main way in', async () => {
    const served = servedSpecification();
    const { built } = open(async () => parseWorldSpecification(served));
    built.focus();
    attachWorldDescription(built, {
      credentials: { baseUrl: 'http://127.0.0.1:1', token: 'test' } as never,
      specification: async () => served as never,
    });
    await settle();
    expect(document.activeElement?.classList.contains('world-description-input')).toBe(true);
  });
});
