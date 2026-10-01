// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { designedLook, validateLook, type CharacterLook } from '@exulanica/atlas-react/playcanvas';
import { CHARACTER_CATALOG, DESIGNED_LOOKS, SERVED_PEOPLE } from './served-people.js';
import { buildLookEditor } from '../src/ui/character-look-editor.js';
import { lookInCatalog, lookOverBase, sameLook } from '../src/character-look.js';
import { editableChoice } from '../src/composition/character.js';

function setup() {
  const onChange = vi.fn<(look: CharacterLook) => void>();
  const editor = buildLookEditor(CHARACTER_CATALOG, DESIGNED_LOOKS, onChange);
  document.body.replaceChildren(editor.sections.body, editor.sections.face, editor.sections.style);
  const within = (control: string) => [...document.querySelectorAll<HTMLButtonElement>(`[data-control="${control}"] button`)];
  const button = (control: string, text: string) => within(control).find((node) => node.textContent === text)!;
  return { editor, onChange, within, button };
}

describe('catalog look editor', () => {
  it('offers exactly what the catalog declares for the current body', () => {
    const { editor, within } = setup();
    const family = CHARACTER_CATALOG.families[0]!;
    const base = family.bases.find((candidate) => candidate.baseId === editor.look.baseId)!;
    expect(within('outfit').map((node) => node.textContent)).toEqual(base.parts.filter((part) => part.slot === 'outfit').map((part) => part.label));
    expect(within('base').map((node) => node.textContent)).toEqual(family.bases.map((candidate) => candidate.label));
    expect(within('designed').map((node) => node.textContent)).toEqual(DESIGNED_LOOKS.looks.map((entry) => entry.label));
    expect(within('skin')).toHaveLength(base.materials['skin']!.length);
    expect(within('hairColour').map((node) => node.getAttribute('aria-label'))).toEqual(family.colours['hairColour']!.map((colour) => colour.label));
    expect(document.body.textContent).toContain('cannot scan your face');
  });

  it('places every control on the step, in the order and with the words the catalog declares', () => {
    const { editor } = setup();
    const family = CHARACTER_CATALOG.families[0]!;
    const base = family.bases.find((candidate) => candidate.baseId === editor.look.baseId)!;
    const choices = (slot: string) => {
      const declared = family.slots.find((candidate) => candidate.slot === slot)!;
      if (declared.kind === 'part') return base.parts.filter((part) => part.slot === slot).length + (declared.optional ? 1 : 0);
      if (declared.kind === 'material') return base.materials[slot]!.length;
      return family.colours[slot]!.length;
    };
    for (const section of ['body', 'face', 'style'] as const) {
      const expected = [
        ...family.slots.filter((slot) => slot.section === section && choices(slot.slot) > 1).map((slot) => ({ key: slot.slot, order: slot.order })),
        ...family.parameters.filter((parameter) => parameter.section === section).map((parameter) => ({ key: parameter.key, order: parameter.order })),
      ].sort((a, b) => a.order - b.order).map((entry) => entry.key);
      const shown = [...editor.sections[section].querySelectorAll<HTMLElement>('[data-control], [data-parameter]')]
        .map((node) => node.dataset['control'] ?? node.dataset['parameter']!)
        .filter((key) => key !== 'designed' && key !== 'base');
      expect(shown, section).toEqual(expected);
    }
    // A body offers one pair of eyes and one set of lashes: neither is a choice.
    expect(document.querySelector('[data-control="eyes"]')).toBeNull();
    expect(document.querySelector('[data-control="lashes"]')).toBeNull();
    const fullness = family.parameters.find((parameter) => parameter.key === 'fullness')!;
    expect(document.querySelector('[data-parameter="fullness"]')!.closest('label')!.querySelector('output')!.textContent).toBe(fullness.wording!.neutral);
  });

  it('moves a control when the catalog moves it, with no code of its own', () => {
    const moved = JSON.parse(JSON.stringify(CHARACTER_CATALOG)) as typeof CHARACTER_CATALOG;
    const brows = moved.families[0]!.slots.find((slot) => slot.slot === 'brows')! as { section: string; order: number };
    brows.section = 'style';
    brows.order = 1;
    const editor = buildLookEditor(moved, DESIGNED_LOOKS, () => undefined);
    expect(editor.sections.face.querySelector('[data-control="brows"]')).toBeNull();
    expect(editor.sections.style.querySelector('[data-control]')!.getAttribute('data-control')).toBe('brows');
  });

  it('changes one choice at a time and always hands over a valid look', () => {
    const { editor, onChange, button, within } = setup();
    const outfit = within('outfit').find((node) => node.getAttribute('aria-pressed') === 'false')!;
    const label = outfit.textContent;
    outfit.click();
    const changed = onChange.mock.lastCall![0];
    expect(() => validateLook(CHARACTER_CATALOG, changed)).not.toThrow();
    expect(button('outfit', label!).getAttribute('aria-pressed')).toBe('true');
    button('hairColour', 'Auburn').click();
    expect(onChange.mock.lastCall![0].colours['hairColour']).toBe('auburn');
    const height = document.querySelector<HTMLInputElement>('[data-parameter="heightMillimetres"]')!;
    height.value = '1850';
    height.dispatchEvent(new Event('input'));
    expect(onChange.mock.lastCall![0].parameters['heightMillimetres']).toBe(1850);
    // The dragged slider is the same element afterwards.
    expect(document.querySelector('[data-parameter="heightMillimetres"]')).toBe(height);
    for (const [look] of onChange.mock.calls) expect(() => validateLook(CHARACTER_CATALOG, look)).not.toThrow();
    expect(editor.look).toEqual(onChange.mock.lastCall![0]);
  });

  it('keeps shared choices when the body changes and takes that body default for the rest', () => {
    const suit = designedLook(DESIGNED_LOOKS, 'suit-masculine');
    const over = lookOverBase(CHARACTER_CATALOG, DESIGNED_LOOKS, suit, 'feminine');
    const feminine = designedLook(DESIGNED_LOOKS, DESIGNED_LOOKS.defaults.bases['feminine']!);
    expect(over.baseId).toBe('feminine');
    // No feminine dark suit exists, so clothing comes from the feminine default; shoes carry over.
    expect(over.parts['outfit']).toBe(feminine.parts['outfit']);
    expect(over.parts['shoes']).toBe('feminine/shoes/shoes04');
    expect(over.colours).toEqual(suit.colours);
    expect(over.materials['eyeColour']).toBe(suit.materials['eyeColour']);
    const base = CHARACTER_CATALOG.families[0]!.bases.find((candidate) => candidate.baseId === 'feminine')!;
    expect(over.parameters['heightMillimetres']).toBe(Math.min(base.heightMillimetres.max, suit.parameters['heightMillimetres']!));
    expect(() => validateLook(CHARACTER_CATALOG, over)).not.toThrow();
    const { editor, button } = setup();
    editor.setLook(suit);
    button('base', 'Feminine body').click();
    expect(editor.look).toEqual(over);
  });

  it('keeps keyboard focus on the chosen control when the controls redraw', () => {
    const { within } = setup();
    const shoes = within('shoes').find((node) => node.getAttribute('aria-pressed') === 'false')!;
    const label = shoes.textContent;
    shoes.focus();
    shoes.click();
    expect((document.activeElement as HTMLElement).textContent).toBe(label);
    expect(document.activeElement?.closest('[data-control]')?.getAttribute('data-control')).toBe('shoes');
  });
});

describe('a look saved over another revision of its catalog', () => {
  // The next revision: one feminine hairstyle withdrawn and one hair colour added.
  type Draft = { families: { bases: { baseId: string; parts: { partId: string }[] }[]; colours: Record<string, { key: string; label: string; rgb: string }[]> }[] };
  const draft = structuredClone(CHARACTER_CATALOG) as unknown as Draft;
  const feminineBase = draft.families[0]!.bases.find((base) => base.baseId === 'feminine')!;
  feminineBase.parts = feminineBase.parts.filter((part) => part.partId !== 'feminine/hair/long01');
  draft.families[0]!.colours['hairColour']!.push({ key: 'copper', label: 'Copper', rgb: '#9c5a2e' });
  const catalog = draft as unknown as typeof CHARACTER_CATALOG;
  const feminine = designedLook(DESIGNED_LOOKS, DESIGNED_LOOKS.defaults.bases['feminine']!);
  const longHair: CharacterLook = { ...feminine, parts: { ...feminine.parts, hair: 'feminine/hair/long01' }, colours: { hairColour: 'auburn' } };

  it('keeps every choice the revision still offers and takes the body default for the rest', () => {
    const moved = lookInCatalog(catalog, DESIGNED_LOOKS, longHair);
    expect(moved.parts['hair']).toBe(feminine.parts['hair']);
    expect({ ...moved, parts: { ...moved.parts, hair: null } }).toEqual({ ...longHair, parts: { ...longHair.parts, hair: null } });
    expect(() => validateLook(catalog, moved)).not.toThrow();
    expect(() => validateLook(catalog, longHair)).toThrow(/long01/);
  });

  it('is the same look when the revision still offers all of it, and the player default for a family it lacks', () => {
    const offered = { ...longHair, parts: { ...longHair.parts, hair: 'feminine/hair/braid01' }, colours: { hairColour: 'copper' } };
    expect(lookInCatalog(catalog, DESIGNED_LOOKS, offered)).toEqual(offered);
    expect(lookInCatalog(catalog, DESIGNED_LOOKS, { ...offered, familyId: 'another-people/v1' }))
      .toEqual(designedLook(DESIGNED_LOOKS, DESIGNED_LOOKS.defaults.player));
  });

  it('opens in the studio as that look, and says when it is not the look the world wears', () => {
    const served = { ...SERVED_PEOPLE, catalog };
    const opened = editableChoice(served, { kind: 'catalog', look: longHair });
    expect(opened.moved).toBe(true);
    expect(opened.choice.kind === 'catalog' && sameLook(opened.choice.look, lookInCatalog(catalog, DESIGNED_LOOKS, longHair))).toBe(true);
    expect(editableChoice(served, { kind: 'catalog', look: feminine })).toEqual({ choice: { kind: 'catalog', look: feminine }, moved: false });
    expect(editableChoice(served, { kind: 'abstract' })).toEqual({ choice: { kind: 'abstract' }, moved: false });
  });
});
