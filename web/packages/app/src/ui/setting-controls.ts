/**
 * One control for each setting, drawn the same way wherever a setting is offered: Customize's View
 * settings and the Settings overlay both draw the capabilities the server serves
 * (`GET /world/interactions/catalog`) through `drawSetting`, and the device's own display settings
 * from `DEVICE_SETTING_WORDS`. So neither surface restates a range, a choice or a word, and a
 * setting the registry hides is offered by neither.
 */

import {
  PREFERENCE_BINDINGS,
  SETTING_WORDS,
  type InteractionCapability,
  type InteractionValue,
} from '../interaction-settings.js';
import type { AtlasPreferences } from '../preferences.js';
import { el } from './dom.js';

/** How a surface lays out one setting: its label, its control and an optional note. */
export type SettingLayout = (label: string, control: HTMLElement, note?: string) => HTMLElement;

/** What a drawn control reads and writes, on the surface that draws it. */
export interface SettingHost {
  /** The preference a field holds now. */
  value(field: string): InteractionValue;
  /** A value while a range is being dragged. */
  preview(patch: Partial<AtlasPreferences>): void;
  /** A value the person settled on. */
  commit(patch: Partial<AtlasPreferences>): void;
  /** A dragged range was let go of. */
  settle(): void;
}

/** A drawn setting: its element, and how it shows the preference it holds again. */
export interface DrawnSetting {
  readonly element: HTMLElement;
  refresh(): void;
}

function option(value: string, label: string): HTMLOptionElement {
  return el('option', { value, text: label });
}

/**
 * One control for one served capability, wired to its preference; null for a capability this
 * device holds no preference for, or has no words for, which is then not offered.
 */
export function drawSetting(
  capability: InteractionCapability,
  host: SettingHost,
  layout: SettingLayout,
): DrawnSetting | null {
  const binding = PREFERENCE_BINDINGS[capability.key];
  const words = SETTING_WORDS[capability.key];
  if (binding === null || binding === undefined || words === undefined) return null;
  const field = binding.field;
  const valueOf = (): InteractionValue => host.value(field);
  if (capability.kind === 'integer' && capability.minimum !== null && capability.maximum !== null) {
    const scale = binding.scale ?? 1;
    const input = el('input', {
      type: 'range', min: String(capability.minimum / scale), max: String(capability.maximum / scale),
      step: String(words.step ?? 1), 'aria-label': words.label,
    }) as HTMLInputElement;
    const output = el('output', { class: 'option-value' }) as HTMLOutputElement;
    input.addEventListener('input', () => host.preview({ [field]: input.valueAsNumber } as Partial<AtlasPreferences>));
    input.addEventListener('change', () => host.settle());
    return {
      element: layout(words.label, el('span', { class: 'range-control' }, [input, output]), words.note),
      refresh: () => {
        input.value = String(valueOf());
        output.value = words.shown?.(valueOf() as number) ?? String(valueOf());
      },
    };
  }
  if (capability.kind === 'choice') {
    const select = el('select', { 'aria-label': words.label },
      capability.choices.map((choice) => option(choice, words.choices?.[choice] ?? choice))) as HTMLSelectElement;
    select.addEventListener('change', () => host.commit({ [field]: select.value } as Partial<AtlasPreferences>));
    return {
      element: layout(words.label, select, words.note),
      refresh: () => { select.value = String(valueOf()); },
    };
  }
  const toggle = el('input', { type: 'checkbox', 'aria-label': words.label }) as HTMLInputElement;
  toggle.addEventListener('change', () => host.commit({ [field]: toggle.checked } as Partial<AtlasPreferences>));
  return {
    element: layout(words.label, toggle, words.note),
    refresh: () => { toggle.checked = valueOf() === true; },
  };
}

/** A device-only setting's words: its label, its note and each choice's words, keyed by value. */
export interface DeviceSettingWords {
  readonly label: string;
  readonly note: string;
  readonly choices: Readonly<Record<string, string>>;
}

/**
 * The words of the settings this device holds for itself, which no server registry states: light
 * or dark, the reading overrides and the region plan. Keyed by the preference field (`AtlasPreferences`);
 * a choice's value is the preference's own (`preferences.ts`), a toggle's `on` and `off`.
 */
export const DEVICE_SETTING_WORDS = Object.freeze({
  scheme: {
    label: 'Light or dark',
    note: 'For the panels and controls. The world keeps its own light.',
    choices: { light: 'Light', dark: 'Dark', system: 'Follow the system' },
  },
  contrast: {
    label: 'Contrast',
    note: 'Strengthens edges and reading surfaces without changing evidence colors.',
    choices: { standard: 'Standard', high: 'High' },
  },
  transparency: {
    label: 'Transparency',
    note: 'Reduced removes glass and grain beneath reading surfaces.',
    choices: { layered: 'Layered', reduced: 'Reduced' },
  },
  regionMinimap: {
    label: 'Region minimap',
    note: 'A plan of the regions in the corner while traversing. The world is meant to orient you '
      + 'on its own, so this stays off until you want it.',
    choices: { off: 'Off', on: 'Shown' },
  },
} satisfies Readonly<Record<string, DeviceSettingWords>>);

/** A select for one device-only setting, with its choices in their words. */
export function deviceSelect(key: keyof typeof DEVICE_SETTING_WORDS): HTMLSelectElement {
  const words: DeviceSettingWords = DEVICE_SETTING_WORDS[key];
  return el('select', { 'aria-label': words.label },
    Object.entries(words.choices).map(([value, label]) => option(value, label))) as HTMLSelectElement;
}
