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
 *
 * Under the recipes, the kinds of place the server lists besides the town (`GET /worlds/kinds`:
 * those it ships and the workspace's own) are cards too, with no picture box where none is served.
 * Choosing one shows its words, what it holds and any values it offers, and "Create this world"
 * makes a world of it (`POST /worlds/kinds/{kind}/worlds`). The last card, "A new kind of place",
 * is there only where the server offers this person drafting one (`drafting`), or a draft of theirs
 * runs; it shows one field (`./kind-draft.ts`), and a kind drafted ready is listed and chosen.
 */

import { problemSentence } from './words/problems.js';
import { worldBudgetWords } from './words/world-budgets.js';
import type { SavedWorldEntry } from '../world-entry-api.js';
import {
  effectiveRange,
  refusalOf,
  type SpecificationPreset,
  type SpecificationRefusal,
  type SpecificationValue,
  type WorldSpecification,
} from '../world-specification.js';
import { recipePicture } from './recipe-pictures.js';
import { TOWN_KIND, type KindDraft, type KindLibrary, type WorldKind } from '../world-kinds-api.js';
import { buildKindDraft, type KindDraftPanel } from './kind-draft.js';
import './create-world.css';
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
  /**
   * Put focus in the panel: Describe it's field once it is there, else the first recipe, else the
   * panel itself, so Escape and the panel's keys work from the moment it opens and Describe it can
   * take focus when it arrives. A hidden or disabled control is never chosen: focus would fall back
   * to the page.
   */
  focus(): void;
  /** Where the look a new town is made in is shown, above Create this town (empty until filled). */
  readonly lookSlot: HTMLElement;
  /** Say where the values shown came from, such as a saved world's own; null says nothing. */
  showOrigin(words: string | null): void;
}

/** Whether a person can reach a control: not inside anything hidden, not disabled. */
const usable = (control: HTMLElement): boolean => control.closest('[hidden]') === null
  && !(control as HTMLButtonElement).disabled;

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
  /** The kinds of place besides the town, and drafting a new one; absent offers neither. */
  readonly kinds?: {
    readonly library: () => Promise<KindLibrary>;
    readonly drafts: () => Promise<readonly KindDraft[]>;
    readonly startDraft: (description: string) => Promise<KindDraft>;
    readonly draft: (draftId: string) => Promise<KindDraft>;
    readonly make: (
      kind: WorldKind,
      preset: string,
      values: Readonly<Record<string, number | string>>,
    ) => Promise<SavedWorldEntry>;
    /** The longest description the server reads. */
    readonly maximumCharacters: number;
    /** Ask again after `ms`; returns a cancel. Tests pass their own. */
    readonly schedule?: (run: () => void, ms: number) => () => void;
  };
}): WorldRecipesPanel {
  const status = el('p', { class: 'world-recipes-status', role: 'status', 'aria-live': 'polite',
    text: say('worldRecipes.loading') });
  const list = el('div', { class: 'world-recipes-list' });
  const kindList = el('div', { class: 'world-recipes-list world-kinds-list' });
  const kindsBlock = el('div', { class: 'world-kinds', hidden: true }, [
    el('p', { class: 'world-recipes-list-label', text: say('worldKinds.heading') }),
    kindList,
  ]);
  // A kind's words and values, or the field that drafts a new one, in place of the town's values.
  const kindSide = el('div', { class: 'world-kinds-side', hidden: true });
  const controls = el('div', { class: 'world-recipes-values', hidden: true });
  const make = el('button', { type: 'button', class: 'world-recipes-make', text: say('worldRecipes.make'), hidden: true });
  const close = el('button', { type: 'button', class: 'world-recipes-close', text: say('worldRecipes.close') });
  close.addEventListener('click', () => options.onClose());
  // Keys: Escape goes back; Command or Control with Enter creates the town once its values are
  // admitted, which works from a field because it is a modified press.
  const keys = (event: KeyboardEvent): void => {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      options.onClose();
      return;
    }
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && !make.hidden && !make.disabled) {
      event.preventDefault();
      make.click();
    }
  };
  const origin = el('p', { class: 'world-recipes-origin', role: 'status', hidden: true });
  const lookSlot = el('div', { class: 'world-recipes-look' });
  const root = el('section', {
    class: 'world-recipes', role: 'dialog', 'aria-label': say('worldRecipes.heading'),
    'data-ui-stage': 'dark', tabindex: '-1',
  }, [
    el('div', { class: 'world-recipes-main' }, [
      el('h2', { text: say('worldRecipes.heading') }),
      origin,
      el('p', { class: 'world-recipes-introduction', text: say('worldRecipes.introduction') }),
      el('p', { class: 'world-recipes-list-label', text: say('worldRecipes.recipes') }),
      list,
      kindsBlock,
    ]),
    el('div', { class: 'world-recipes-side' }, [
      kindSide,
      controls,
      lookSlot,
      status,
      el('div', { class: 'world-recipes-actions' }, [make, close]),
    ]),
  ]);

  root.addEventListener('keydown', keys);

  let specification: WorldSpecification | null = null;
  let preset: SpecificationPreset | null = null;
  // The values the controls hold: the preset's, with every change a person or `setValues` made.
  let chosen: Record<string, number | string> = {};
  let refusal: WorldRecipesRefusal | null = null;
  let making = false;
  // What the right column holds: a town recipe's values, a kind of place, or the draft field.
  let mode: 'town' | 'kind' | 'new' | null = null;
  let kind: WorldKind | null = null;
  let kindPreset: string | null = null;
  let kindValues: Record<string, number | string> = {};

  const check = (): void => {
    // A kind's controls offer only values inside its ranges; the server holds them again.
    refusal = specification === null || mode !== 'town' ? null : refusalOf(specification, chosen);
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
    // Shares (thousandths) set the mix of buildings and shops; they sit together behind one
    // disclosure so the town's shape reads first.
    const more = el('details', { class: 'world-recipes-more' }, [
      el('summary', { text: say('worldRecipes.more') }),
    ]);
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
      (value.unit === 'permille' ? more : controls).append(el('div', { class: 'world-recipes-parameter' }, [
        el('label', { class: 'world-recipes-value' }, [
          el('span', { text: value.label }), input, output,
        ]),
        el('details', { class: 'world-recipes-reason' }, [
          el('summary', { text: 'Why this range?' }),
          el('p', { text: value.reason }),
        ]),
      ]));
    }
    if (more.childElementCount > 1) controls.append(more);
  };

  /** Mark one card of either list pressed, every other one not. */
  const press = (chosenCard: Element | null): void => {
    for (const button of [...list.querySelectorAll('button'), ...kindList.querySelectorAll('button')]) {
      button.setAttribute('aria-pressed', String(button === chosenCard));
    }
  };

  /** The right column for a town recipe, a kind of place, or the draft field. */
  const showMode = (next: 'town' | 'kind' | 'new'): void => {
    mode = next;
    controls.hidden = next !== 'town';
    lookSlot.hidden = next !== 'town';
    kindSide.hidden = next === 'town';
    make.hidden = next === 'new';
    make.textContent = say(next === 'town' ? 'worldRecipes.make' : 'worldKinds.make');
  };

  const choose = (next: SpecificationPreset): void => {
    preset = next;
    chosen = { ...next.values };
    press(list.querySelector(`[data-recipe="${CSS.escape(next.key)}"]`));
    showMode('town');
    renderValues();
    check();
  };

  /** A kind's words, what it holds, and a control for each value it offers. */
  const renderKind = (shown: WorldKind, modelName: string | null): void => {
    const holds = [...new Set(shown.parts.map((part) => part.label))];
    const values = el('div', { class: 'world-recipes-values' });
    if (shown.presets.length > 1) {
      const select = el('select', { 'aria-label': say('worldKinds.preset'), 'data-kind-preset': '' },
        shown.presets.map((offered) => el('option', { value: offered.key, text: offered.label, selected: offered.key === kindPreset })));
      select.addEventListener('change', () => {
        const next = shown.presets.find((offered) => offered.key === select.value);
        if (next === undefined) return;
        kindPreset = next.key;
        kindValues = { ...next.values };
        renderKind(shown, modelName);
      });
      values.append(el('div', { class: 'world-recipes-parameter' }, [
        el('label', { class: 'world-recipes-value' }, [el('span', { text: say('worldKinds.preset') }), select]),
      ]));
    }
    for (const parameter of shown.parameters) {
      const current = kindValues[parameter.key] ?? '';
      const output = el('output', { text: String(current) });
      const input = parameter.choices !== null
        ? el('select', { 'aria-label': parameter.label, 'data-parameter': parameter.key },
          parameter.choices.map((choice) => el('option', { value: choice, text: choice, selected: choice === current })))
        : el('input', {
          type: 'range', min: String(parameter.minimum ?? 0), max: String(parameter.maximum ?? 0),
          step: String(parameter.step ?? 1), value: String(current), 'aria-label': parameter.label,
          'data-parameter': parameter.key,
        });
      input.addEventListener('input', () => {
        const next = parameter.choices !== null ? input.value : Number(input.value);
        kindValues = { ...kindValues, [parameter.key]: next };
        output.textContent = String(next);
      });
      values.append(el('div', { class: 'world-recipes-parameter' }, [
        el('label', { class: 'world-recipes-value' }, [el('span', { text: parameter.label }), input, output]),
        el('details', { class: 'world-recipes-reason' }, [
          el('summary', { text: 'Why this range?' }),
          el('p', { text: parameter.reason }),
        ]),
      ]));
    }
    kindSide.replaceChildren(
      el('p', { class: 'world-kinds-words', text: fill('worldKinds.ready', { label: shown.label, summary: shown.summary }) }),
      ...(modelName === null ? [] : [el('p', { class: 'world-kinds-by', text: fill('worldKinds.draftedBy', { model: modelName }) })]),
      ...(holds.length === 0 ? [] : [el('p', { class: 'world-kinds-holds', text: fill('worldKinds.holds', { parts: holds.join(', ') }) })]),
      values,
    );
  };

  const chooseKind = (next: WorldKind, modelName: string | null = null): void => {
    kind = next;
    kindPreset = next.presets[0]?.key ?? null;
    kindValues = { ...(next.presets[0]?.values ?? {}) };
    press(kindList.querySelector(`[data-kind="${CSS.escape(next.kind)}"]`));
    showMode('kind');
    renderKind(next, modelName);
    make.disabled = making || kindPreset === null;
    status.textContent = '';
  };

  const cards = (): HTMLButtonElement[] => [...list.querySelectorAll('button'), ...kindList.querySelectorAll('button')];

  make.addEventListener('click', () => {
    if (making) return;
    let made: Promise<SavedWorldEntry>;
    let label: string;
    if (mode === 'kind' && kind !== null && kindPreset !== null && options.kinds !== undefined) {
      label = kind.label;
      made = options.kinds.make(kind, kindPreset, { ...kindValues });
    } else if (mode === 'town' && preset !== null && refusal === null) {
      label = preset.label;
      made = options.make(preset, { ...chosen });
    } else {
      return;
    }
    making = true;
    make.disabled = true;
    for (const button of cards()) button.disabled = true;
    status.textContent = fill('worldRecipes.making', { recipe: label });
    void made.then(options.open).catch((error: unknown) => {
      making = false;
      for (const button of cards()) button.disabled = false;
      status.textContent = fill('worldRecipes.failed', {
        // The count policy's two budgets are said in the person's terms: which one refused, and
        // for the day's, when another town can be made by their own clock.
        reason: problemSentence(error, worldBudgetWords(error)),
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
      // A frame of a town made from this recipe, where one ships with the page; the label stays
      // the button's only text.
      const picture = recipePicture(offered.key);
      if (picture !== null) choice.style.setProperty('--recipe-picture', `url("${picture}")`);
      choice.addEventListener('click', () => choose(offered));
      list.append(choice);
    }
  }).catch((error: unknown) => {
    status.textContent = fill('worldRecipes.failed', {
      reason: problemSentence(error),
    });
  });

  // The kinds of place: read beside the recipes; a server without them leaves only the recipes.
  const kinds = options.kinds;
  if (kinds !== undefined) {
    let drafting: KindLibrary['drafting'] = null;
    let newCard: HTMLButtonElement | null = null;
    let draftPanel: KindDraftPanel | null = null;
    const kindCard = (offered: WorldKind): HTMLButtonElement => {
      const card = el('button', {
        type: 'button', class: 'world-recipes-choice world-kinds-choice', 'data-kind': offered.kind, 'aria-pressed': 'false',
      }, [
        el('span', { class: 'world-kinds-choice-label', text: offered.label }),
        el('span', { class: 'world-kinds-choice-detail', text: offered.summary }),
      ]);
      card.addEventListener('click', () => chooseKind(offered));
      return card;
    };
    const listKind = (offered: WorldKind): void => {
      const card = kindCard(offered);
      const earlier = kindList.querySelector(`[data-kind="${CSS.escape(offered.kind)}"]`);
      if (earlier !== null) earlier.replaceWith(card);
      else if (newCard !== null) kindList.insertBefore(card, newCard);
      else kindList.append(card);
      kindsBlock.hidden = false;
    };
    const panel = (): KindDraftPanel => {
      draftPanel ??= buildKindDraft({
        start: kinds.startDraft,
        read: kinds.draft,
        refusals: () => drafting?.refusals ?? [],
        maximumCharacters: kinds.maximumCharacters,
        onReady: (ready, modelName) => {
          listKind(ready);
          // Chosen only where the person is still looking at the draft; focus follows only from it.
          if (mode !== 'new') return;
          const focused = kindSide.contains(document.activeElement);
          chooseKind(ready, modelName);
          if (focused) make.focus({ preventScroll: true });
        },
        onRunning: (running) => {
          newCard?.querySelector('.world-kinds-choice-detail')
            ?.replaceChildren(say(running ? 'worldKinds.drafting.card' : 'worldKinds.new.detail'));
        },
        onLeave: () => newCard?.focus({ preventScroll: true }),
        ...(kinds.schedule === undefined ? {} : { schedule: kinds.schedule }),
      });
      return draftPanel;
    };
    const offerNew = (): void => {
      if (newCard !== null) return;
      newCard = el('button', {
        type: 'button', class: 'world-recipes-choice world-kinds-choice world-kinds-choice-new', 'data-kind-new': '', 'aria-pressed': 'false',
      }, [
        el('span', { class: 'world-kinds-choice-label', text: say('worldKinds.new') }),
        el('span', { class: 'world-kinds-choice-detail', text: say('worldKinds.new.detail') }),
      ]);
      newCard.addEventListener('click', () => {
        press(newCard);
        showMode('new');
        status.textContent = '';
        kindSide.replaceChildren(panel().root);
        panel().focus();
      });
      kindList.append(newCard);
      kindsBlock.hidden = false;
    };
    void kinds.library().then(async (library) => {
      drafting = library.drafting;
      for (const offered of library.kinds) if (offered.kind !== TOWN_KIND) listKind(offered);
      // A draft of this person's still running is found, not started again; it is followed here.
      const running = drafting === null ? undefined
        : (await kinds.drafts().catch(() => [])).find((held) => held.state === 'drafting');
      if (drafting?.offered === true || running !== undefined) offerNew();
      if (running !== undefined) panel().follow(running);
    }, () => undefined);
  }

  return {
    root,
    lookSlot,
    focus() {
      const describe = root.querySelector<HTMLElement>('.world-description-input');
      const target = describe !== null && usable(describe) ? describe
        : [...list.querySelectorAll<HTMLElement>('button')].find(usable) ?? root;
      target.focus({ preventScroll: true });
    },
    showOrigin(words) {
      origin.textContent = words ?? '';
      origin.hidden = words === null;
    },
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
