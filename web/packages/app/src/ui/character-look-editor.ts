/**
 * Controls for a catalog look, built from the catalog itself.
 *
 * Every control is a declared slot, material, colour or parameter of the family, placed on the
 * studio step, in the order and with the words the catalog gives it: adding a hairstyle, a garment,
 * a slot or a parameter to the catalog adds a control here and never a code path. A slot the body
 * offers one choice for is not offered as a choice. A change always yields a whole, valid look over
 * one body. Choosing the other body keeps every choice that body also offers and takes that body's
 * designed default for the rest.
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

  type Offered =
    | { readonly kind: 'slot'; readonly key: string; readonly shown: Family['slots'][number] }
    | { readonly kind: 'parameter'; readonly key: string; readonly shown: Family['parameters'][number] };

  /** Every slot and parameter the family declares, in the section and order it declares them. */
  function offered(section: string): Offered[] {
    const all: Offered[] = [
      ...family.slots.map((shown) => ({ kind: 'slot' as const, key: shown.slot, shown })),
      ...family.parameters.map((shown) => ({ kind: 'parameter' as const, key: shown.key, shown })),
    ];
    return all
      .filter((entry) => entry.shown.section === section)
      .sort((a, b) => a.shown.order - b.shown.order || (a.key < b.key ? -1 : 1));
  }

  function parameterControl(parameter: Family['parameters'][number]): HTMLElement {
    const bounds = parameter.unit === 'mm' ? base().heightMillimetres : parameter;
    const wording = parameter.wording;
    const format = (value: number): string => {
      if (parameter.unit === 'mm') return `${Math.round(value / 10)} cm`;
      if (wording) return value === 0 ? wording.neutral : value > 0 ? wording.positive : wording.negative;
      return String(value);
    };
    return slider(parameter.label, parameter.key, bounds.min, bounds.max, parameter.step ?? 1, look.parameters[parameter.key]!, format);
  }

  /** A slot's control, or null when the current body offers only one choice for it. */
  function slotControl(slot: Family['slots'][number]): HTMLElement | null {
    const swatch = slot.display === 'swatch';
    switch (slot.kind) {
      case 'part': {
        const buttons = partButtons(slot.slot);
        return buttons.length > 1 ? group(slot.label, slot.slot, buttons) : null;
      }
      case 'material': {
        const ids = base().materials[slot.slot] ?? [];
        if (ids.length < 2) return null;
        return group(slot.label, slot.slot, ids.map((id) => {
          const material = family.materials.find((candidate) => candidate.materialId === id)!;
          return choice(materialLabel(id), look.materials[slot.slot] === id,
            () => change({ ...look, materials: { ...look.materials, [slot.slot]: id } }), swatch ? material.averageColour : undefined);
        }));
      }
      case 'colour': {
        const colours = family.colours[slot.slot] ?? [];
        if (colours.length < 2) return null;
        return group(slot.label, slot.slot, colours.map((colour) =>
          choice(colour.label, look.colours[slot.slot] === colour.key,
            () => change({ ...look, colours: { ...look.colours, [slot.slot]: colour.key } }), swatch ? colour.rgb : undefined)));
      }
      default: {
        const unknown: never = slot.kind;
        throw new TypeError(`The studio has no control for a ${String(unknown)} slot`);
      }
    }
  }

  function controls(section: string): HTMLElement[] {
    return offered(section).flatMap((entry) => {
      const node = entry.kind === 'parameter' ? parameterControl(entry.shown) : slotControl(entry.shown);
      return node ? [node] : [];
    });
  }

  function renderSections(): void {
    replace(sections.body, [
      group('Start from', 'designed', looks.looks.map((entry) => choice(entry.label, sameLook(entry.look, look), () => change(entry.look)))),
      group('Body', 'base', family.bases.map((candidate) => choice(candidate.label, candidate.baseId === look.baseId, () => change(lookOverBase(catalog, looks, look, candidate.baseId))))),
      ...controls('body'),
      el('p', { class: 'character-session-note', text: 'Body shape and height are choices for a fictional person, not measurements of anyone.' }),
    ]);
    replace(sections.face, [
      ...controls('face'),
      el('div', { class: 'character-likeness-note' }, [el('h3', { text: 'From a photo or camera' }),
        el('p', { text: 'Not available yet. This preview cannot scan your face or fit your likeness from an image.' })]),
    ]);
    replace(sections.style, controls('style'));
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
