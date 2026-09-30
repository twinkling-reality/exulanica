/**
 * Making a world: the presets the server offers and a control for every value a person may change,
 * all read from one served document (`GET /worlds/specification`, `../world-specification.ts`).
 *
 * Choosing a preset shows its values. A person changes any adjustable one within the range the
 * document states (a slider for a number, a list for a key), and each control says why its range is
 * what it is. A slider offers its effective range: where another value narrows it (a town three
 * tiles long takes longer blocks), moving that value narrows the slider, and a value the person set
 * outside the narrowed range moves to its nearest end, so the controls never offer a pair the
 * document refuses. Before anything is sent the page states the refusal the server would give values the
 * ranges do not admit (`refusalOf`, by the server's codes and words); "Make this town" sends the
 * preset and its values (`POST /worlds/generated`), and the server decides and names any refusal.
 * `setValues` sets a preset and values the same way from elsewhere, such as a model drafting a
 * specification from a person's words: it loads them into the controls and checks them exactly as
 * a person's edit is checked, so the controls never hold a value the page has not checked.
 */

import type { SavedWorldEntry } from '../world-entry-api.js';
import {
  effectiveRange,
  refusalOf,
  type SpecificationPreset,
  type SpecificationRefusal,
  type SpecificationValue,
  type WorldSpecification,
} from '../world-specification.js';
import { fill, say } from './copy.js';
import { el } from './dom.js';

/** Why `setValues` did not load values, by the server's codes. */
export type WorldRecipesRefusal =
  | SpecificationRefusal
  | { readonly code: 'unknown_world_recipe'; readonly key: string; readonly detail: string };

export interface WorldRecipesPanel {
  readonly root: HTMLElement;
  /**
   * Choose the preset `presetKey` and set `values` for its adjustable parameters, checked as a
   * person's edit is. Resolves to the refusal the server would give, or null when every value is
   * inside its range; the controls then hold the values, and "Make this town" sends them.
   */
  setValues(
    presetKey: string,
    values: Readonly<Record<string, number | string>>,
  ): Promise<WorldRecipesRefusal | null>;
}

/** A value as a person reads it: millimetres in metres, a share in thousandths out of a thousand, a
 * key by its words where the server states them, anything else as its number or key. */
function shown(value: SpecificationValue, chosen: number | string): string {
  if (value.unit === 'mm' && typeof chosen === 'number') {
    return fill('worldRecipes.metres', { metres: String(chosen / 1000) });
  }
  if (value.unit === 'permille' && typeof chosen === 'number') {
    return fill('worldRecipes.permille', { thousandths: String(chosen) });
  }
  if (typeof chosen === 'string') return choiceWords(value, chosen);
  return String(chosen);
}

/** A choice in words: its label where the server states one, else its key. */
function choiceWords(value: SpecificationValue, choice: string): string {
  const index = value.choices?.indexOf(choice) ?? -1;
  return index >= 0 && value.choiceLabels !== null ? value.choiceLabels[index]! : choice;
}

export function buildWorldRecipes(options: {
  readonly specification: () => Promise<WorldSpecification>;
  readonly make: (
    preset: SpecificationPreset,
    values: Readonly<Record<string, number | string>>,
  ) => Promise<SavedWorldEntry>;
  readonly open: (entry: SavedWorldEntry) => Promise<void>;
  readonly onClose: () => void;
}): WorldRecipesPanel {
  const status = el('p', { class: 'world-recipes-status', role: 'status', 'aria-live': 'polite',
    text: say('worldRecipes.loading') });
  const list = el('div', { class: 'world-recipes-list' });
  const controls = el('div', { class: 'world-recipes-values', hidden: true });
  const make = el('button', { type: 'button', class: 'world-recipes-make', text: say('worldRecipes.make'), hidden: true });
  const close = el('button', { type: 'button', class: 'world-recipes-close', text: say('worldRecipes.close') });
  close.addEventListener('click', () => options.onClose());
  const root = el('section', {
    class: 'world-recipes', role: 'dialog', 'aria-label': say('worldRecipes.heading'),
  }, [
    el('h2', { text: say('worldRecipes.heading') }),
    el('p', { text: say('worldRecipes.introduction') }),
    list,
    controls,
    status,
    el('div', { class: 'world-recipes-actions' }, [make, close]),
  ]);

  let specification: WorldSpecification | null = null;
  let preset: SpecificationPreset | null = null;
  // The values the controls hold: the preset's, with every change a person or `setValues` made.
  let chosen: Record<string, number | string> = {};
  let refusal: WorldRecipesRefusal | null = null;
  let making = false;

  const check = (): void => {
    refusal = specification === null ? null : refusalOf(specification, chosen);
    make.disabled = making || refusal !== null;
    if (!making) {
      status.textContent = refusal === null ? '' : fill('worldRecipes.refused', { reason: refusal.detail });
    }
    root.setAttribute('data-specification-state', refusal === null ? 'admitted' : refusal.code);
  };

  // Each number's slider and the words beside it, by key, so a change narrows the others in place.
  let sliders = new Map<string, { readonly input: HTMLInputElement; readonly output: HTMLOutputElement }>();

  /** Give every number's slider its effective range; with `snap`, move a value outside it inside. */
  const narrow = (snap: boolean): void => {
    if (specification === null) return;
    for (const value of specification.values) {
      const slider = sliders.get(value.key);
      if (slider === undefined) continue;
      const range = effectiveRange(value, chosen);
      slider.input.min = String(range.minimum);
      slider.input.max = String(range.maximum);
      const current = chosen[value.key];
      if (snap && typeof current === 'number' && (current < range.minimum || current > range.maximum)) {
        const inside = current < range.minimum ? range.minimum : range.maximum;
        chosen = { ...chosen, [value.key]: inside };
        slider.input.value = String(inside);
        slider.output.textContent = shown(value, inside);
      }
    }
  };

  const renderValues = (): void => {
    controls.replaceChildren();
    sliders = new Map();
    if (specification === null || preset === null) return;
    for (const value of specification.values.filter((one) => one.adjustable)) {
      const current = chosen[value.key] ?? value.value ?? '';
      const output = el('output', { text: shown(value, current) });
      let input: HTMLInputElement | HTMLSelectElement;
      if (value.kind === 'choice') {
        input = el('select', { 'aria-label': value.label, 'data-parameter': value.key },
          value.choices!.map((choice) => el('option', {
            value: choice, text: choiceWords(value, choice), selected: choice === current,
          })));
      } else {
        const range = effectiveRange(value, chosen);
        input = el('input', {
          type: 'range', min: String(range.minimum), max: String(range.maximum), step: String(range.step),
          value: String(current), 'aria-label': value.label, 'data-parameter': value.key,
        });
        sliders.set(value.key, { input, output });
      }
      input.addEventListener('input', () => {
        const next = value.kind === 'choice' ? input.value : Number(input.value);
        chosen = { ...chosen, [value.key]: next };
        output.textContent = shown(value, next);
        narrow(true);
        check();
      });
      controls.append(el('label', { class: 'world-recipes-value', title: value.reason }, [
        el('span', { text: value.label }), input, output,
        el('small', { class: 'world-recipes-reason', text: value.reason }),
      ]));
    }
  };

  const choose = (next: SpecificationPreset): void => {
    preset = next;
    chosen = { ...next.values };
    for (const button of list.querySelectorAll<HTMLButtonElement>('button')) {
      button.setAttribute('aria-pressed', String(button.getAttribute('data-recipe') === next.key));
    }
    controls.hidden = false;
    make.hidden = false;
    renderValues();
    check();
  };

  make.addEventListener('click', () => {
    if (preset === null || refusal !== null || making) return;
    const asked = preset;
    making = true;
    make.disabled = true;
    for (const button of list.querySelectorAll('button')) (button as HTMLButtonElement).disabled = true;
    status.textContent = fill('worldRecipes.making', { recipe: asked.label });
    void options.make(asked, { ...chosen }).then(options.open).catch((error: unknown) => {
      making = false;
      for (const button of list.querySelectorAll('button')) (button as HTMLButtonElement).disabled = false;
      status.textContent = fill('worldRecipes.failed', {
        reason: error instanceof Error ? error.message : String(error),
      });
      make.disabled = refusal !== null;
    });
  });

  const loaded = options.specification().then((served) => {
    specification = served;
    status.textContent = '';
    for (const offered of served.presets) {
      const choice = el('button', {
        type: 'button', class: 'world-recipes-choice', 'data-recipe': offered.key, text: offered.label,
        'aria-pressed': 'false',
      });
      choice.addEventListener('click', () => choose(offered));
      list.append(choice);
    }
  }).catch((error: unknown) => {
    status.textContent = fill('worldRecipes.failed', {
      reason: error instanceof Error ? error.message : String(error),
    });
  });

  return {
    root,
    async setValues(presetKey, values) {
      await loaded;
      const next = specification?.presets.find((offered) => offered.key === presetKey);
      if (next === undefined) {
        return { code: 'unknown_world_recipe', key: presetKey, detail: `no world recipe is named ${JSON.stringify(presetKey)}` };
      }
      choose(next);
      chosen = { ...next.values, ...values };
      renderValues();
      check();
      return refusal;
    },
  };
}
