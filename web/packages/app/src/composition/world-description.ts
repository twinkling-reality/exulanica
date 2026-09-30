/**
 * "Describe it" inside the Make a world panel: a person's words drafted into the panel's values.
 *
 * The panel that lists the presets and a control for every value (`../ui/world-recipes.ts`) offers
 * one hook, `setValues`, which loads a preset and values into its controls and checks them as a
 * person's own edit is checked. This attaches the description panel (`../ui/world-description.ts`)
 * above the presets and hands it that hook: a drafted proposal the person chooses to use becomes
 * the controls' values, where they can change any of them and make the town. The words the
 * description panel shows a value in come from the same served specification the controls read.
 */

import type { TransportOptions } from '@exulanica/graph-client';
import {
  buildWorldDescription,
  type SpecificationValueWords,
  type SpecificationWords,
} from '../ui/world-description.js';
import { WorldDraftClient } from '../world-draft-api.js';

/**
 * The longest description the server reads: the ceiling `exulanica/selection/world-drafting.v2.json`
 * states, which `world-description.test.ts` holds this to.
 */
export const DESCRIPTION_CHARACTERS = 1000;

/** What this reads of the served specification (`GET /worlds/specification`). */
export interface ServedSpecification {
  readonly values: readonly {
    readonly key: string;
    readonly label: string;
    readonly kind: string;
    readonly unit: string;
    readonly adjustable: boolean;
    readonly minimum: number | null;
    readonly maximum: number | null;
    readonly step: number | null;
    /** A choice's keys, and each in words where the server states them. */
    readonly choices?: readonly string[] | null;
    readonly choiceLabels?: readonly string[] | null;
  }[];
  readonly presets: readonly { readonly key: string; readonly label: string }[];
}

/** The panel the description is attached to, by the one hook it offers. */
export interface SpecificationPanel {
  readonly root: HTMLElement;
  setValues(
    presetKey: string,
    values: Readonly<Record<string, number | string>>,
  ): Promise<unknown>;
}

/** The words the description panel shows values in: every adjustable value the served
 * specification states, a number with its range and a choice with its words, and every preset's
 * label. */
export function specificationWords(specification: ServedSpecification): SpecificationWords {
  return {
    values: specification.values.flatMap((value): SpecificationValueWords[] => {
      if (!value.adjustable) return [];
      if (value.kind === 'choice' && value.choices) {
        return [{ key: value.key, label: value.label, unit: value.unit, minimum: 0, maximum: 0, step: 0,
          choices: value.choices.map((choice, index) => ({
            key: choice, label: value.choiceLabels?.[index] ?? choice,
          })) }];
      }
      return value.minimum !== null && value.maximum !== null && value.step !== null
        ? [{ key: value.key, label: value.label, unit: value.unit,
          minimum: value.minimum, maximum: value.maximum, step: value.step, choices: null }]
        : [];
    }),
    presets: specification.presets.map((preset) => ({ key: preset.key, label: preset.label })),
  };
}

export function attachWorldDescription(panel: SpecificationPanel, options: {
  readonly credentials: TransportOptions;
  readonly specification: () => Promise<ServedSpecification>;
}): void {
  const client = new WorldDraftClient(options.credentials);
  void options.specification().then((specification) => {
    const description = buildWorldDescription({
      draft: (words) => client.draft(words),
      useValues: (preset, values) => { void panel.setValues(preset, values); },
      words: specificationWords(specification),
      maximumCharacters: DESCRIPTION_CHARACTERS,
    });
    const presets = panel.root.querySelector('.world-recipes-list');
    panel.root.insertBefore(description.root, presets);
  });
}
