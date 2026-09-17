/**
 * Controls for a catalog look, built from the catalog itself.
 *
 * Every control is a declared slot, material, colour or parameter of the family: adding a
 * hairstyle or a garment to the catalog adds a button here and never a code path. A change always
 * yields a whole, valid look over one body. Choosing the other body keeps every choice that body
 * also offers and takes that body's designed default for the rest.
 */
import type { CharacterCatalog, CharacterLook, DesignedLooks } from '@exulanica/atlas-react/playcanvas';
import { checkedLook, designedLook, lookOverBase, sameLook } from '../character-look.js';
import { el, replace } from './dom.js';

type Family = CharacterCatalog['families'][number];
type Base = Family['bases'][number];

export interface LookEditorSections {
  readonly body: HTMLElement;
  readonly face: HTMLElement;
  readonly style: HTMLElement;
}

export function buildLookEditor(catalog: CharacterCatalog, looks: DesignedLooks, onChange: (look: CharacterLook) => void) {
  const family: Family = catalog.families[0]!;
  let look: CharacterLook = designedLook(looks, looks.defaults.player);
  const sections: LookEditorSections = {
    body: el('div', { class: 'character-look-body' }),
    face: el('div', { class: 'character-look-face' }),
    style: el('div', { class: 'character-look-style' }),
  };
  const base = (): Base => family.bases.find((candidate) => candidate.baseId === look.baseId)!;
  const materialLabel = (id: string): string => family.materials.find((material) => material.materialId === id)?.label ?? id;

  function change(next: CharacterLook, rerender = true): void {
    look = checkedLook(catalog, next);
    if (rerender) render();
    onChange(next);
  }

  function group(title: string, name: string, children: readonly Node[], note?: string): HTMLElement {
    return el('div', { class: 'character-look-group', role: 'group', 'aria-label': title, 'data-control': name }, [
      el('h3', { text: title }), ...(note ? [el('p', { class: 'character-session-note', text: note })] : []), ...children,
    ]);
  }

  function choice(label: string, pressed: boolean, select: () => void, swatch?: string): HTMLButtonElement {
    const button = el('button', { type: 'button', text: label, 'aria-pressed': String(pressed), class: swatch ? 'character-swatch' : undefined });
    if (swatch) {
      button.style.setProperty('--swatch', swatch);
      button.setAttribute('aria-label', label);
    }
    button.addEventListener('click', select);
    return button;
  }

  function slider(label: string, key: string, min: number, max: number, step: number, value: number, format: (value: number) => string): HTMLElement {
    const input = el('input', { type: 'range', min, max, step, value, 'aria-label': label, 'data-parameter': key });
    const output = el('output', { text: format(value) });
    input.addEventListener('input', () => {
      output.textContent = format(Number(input.value));
      // A slider being dragged keeps its element; nothing else on the page depends on its value.
      change({ ...look, parameters: { ...look.parameters, [key]: Number(input.value) } }, false);
    });
    return el('label', { class: 'character-look-slider' }, [el('span', { text: label }), input, output]);
  }

  function partButtons(slot: string): Node[] {
    const declared = family.slots.find((candidate) => candidate.slot === slot)!;
    const buttons = base().parts
      .filter((part) => part.slot === slot)
      .map((part) => choice(part.label, look.parts[slot] === part.partId, () => change({ ...look, parts: { ...look.parts, [slot]: part.partId } })));
    if (declared.optional) buttons.push(choice(`No ${declared.label.toLowerCase()}`, look.parts[slot] === null, () => change({ ...look, parts: { ...look.parts, [slot]: null } })));
    return buttons;
  }

  function render(): void {
    // Keep keyboard focus on the same control across a re-render.
    const active = typeof document === 'undefined' ? null : document.activeElement;
    const focusGroup = active?.closest?.('[data-control]')?.getAttribute('data-control') ?? null;
    const focusLabel = active instanceof HTMLButtonElement ? active.textContent : null;
    renderSections();
    if (focusGroup !== null && focusLabel !== null) {
      const again = [sections.body, sections.face, sections.style]
        .flatMap((section) => [...section.querySelectorAll<HTMLButtonElement>(`[data-control="${focusGroup}"] button`)])
        .find((button) => button.textContent === focusLabel);
      again?.focus();
    }
  }

  function renderSections(): void {
    const current = base();
    const shape = (key: string) => family.parameters.find((parameter) => parameter.key === key)!;
    replace(sections.body, [
      group('Start from', 'designed', looks.looks.map((entry) => choice(entry.label, sameLook(entry.look, look), () => change(entry.look)))),
      group('Body', 'base', family.bases.map((candidate) => choice(candidate.label, candidate.baseId === look.baseId, () => change(lookOverBase(catalog, looks, look, candidate.baseId))))),
      slider('Height', 'heightMillimetres', current.heightMillimetres.min, current.heightMillimetres.max, 10, look.parameters['heightMillimetres']!, (value) => `${Math.round(value / 10)} cm`),
      slider(shape('fullness').label, 'fullness', shape('fullness').min, shape('fullness').max, 50, look.parameters['fullness']!, (value) => (value === 0 ? 'Average' : value > 0 ? 'Fuller' : 'Slimmer')),
      slider(shape('muscle').label, 'muscle', shape('muscle').min, shape('muscle').max, 50, look.parameters['muscle']!, (value) => (value === 0 ? 'Average' : value > 0 ? 'More defined' : 'Softer')),
      group('Skin', 'skin', (current.materials['skin'] ?? []).map((id, index) => {
        const material = family.materials.find((candidate) => candidate.materialId === id)!;
        return choice(`Skin tone ${index + 1}`, look.materials['skin'] === id, () => change({ ...look, materials: { ...look.materials, skin: id } }), material.averageColour);
      })),
      el('p', { class: 'character-session-note', text: 'Body shape and height are choices for a fictional person, not measurements of anyone.' }),
    ]);
    replace(sections.face, [
      group('Eye colour', 'eyeColour', (current.materials['eyeColour'] ?? []).map((id) =>
        choice(materialLabel(id), look.materials['eyeColour'] === id, () => change({ ...look, materials: { ...look.materials, eyeColour: id } })))),
      group('Brows', 'brows', partButtons('brows')),
      el('div', { class: 'character-likeness-note' }, [el('h3', { text: 'From a photo or camera' }),
        el('p', { text: 'Not available yet. This preview cannot scan your face or fit your likeness from an image.' })]),
    ]);
    replace(sections.style, [
      group('Hair', 'hair', partButtons('hair')),
      group('Hair colour', 'hairColour', (family.colours['hairColour'] ?? []).map((colour) =>
        choice(colour.label, look.colours['hairColour'] === colour.key, () => change({ ...look, colours: { ...look.colours, hairColour: colour.key } }), colour.rgb))),
      group('Clothing', 'outfit', partButtons('outfit')),
      group('Shoes', 'shoes', partButtons('shoes')),
    ]);
  }

  render();
  return {
    sections,
    get look(): CharacterLook { return look; },
    setLook(next: CharacterLook): void {
      look = checkedLook(catalog, next);
      render();
    },
  };
}
