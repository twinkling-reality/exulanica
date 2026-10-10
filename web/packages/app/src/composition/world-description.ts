/**
 * "Describe it" inside the Make a world panel: a person's words drafted into the panel's values.
 *
 * The panel that lists the presets and a control for every value (`../ui/world-recipes.ts`) offers
 * one hook, `setValues`, which loads a preset and values into its controls and checks them as a
 * person's own edit is checked. This attaches the description panel (`../ui/world-description.ts`)
 * above the presets and hands it that hook: a drafted proposal the person chooses to use becomes
 * the controls' values, where they can change any of them and make the town. The words the
 * description panel shows a value in come from the same served specification the controls read.
 * Given the town's look (`./town-look.ts`), the description panel also says the look a draft's
 * words ask for and takes it with the values.
 */

import type { TransportOptions } from '@exulanica/graph-client';
import {
  buildWorldDescription,
  type DraftLook,
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

/** The panel the description is attached to, by the hooks it offers. */
export interface SpecificationPanel {
  readonly root: HTMLElement;
  /** Put focus in the panel; called again once Describe it is in place, if focus was waiting. */
  focus?(): void;
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
  /** The town's look, where the panel shows one: a draft's offered look is said and taken by it. */
  readonly look?: DraftLook;
}): void {
  const client = new WorldDraftClient(options.credentials);
  void options.specification().then((specification) => {
    const description = buildWorldDescription({
      draft: (words) => client.draft(words),
      useValues: (preset, values) => { void panel.setValues(preset, values); },
      words: specificationWords(specification),
      maximumCharacters: DESCRIPTION_CHARACTERS,
      ...(options.look === undefined ? {} : { look: options.look }),
    });
    // Above the recipes and the line that introduces them: describing the town is the main way in.
    const presets = panel.root.querySelector('.world-recipes-list-label')
      ?? panel.root.querySelector('.world-recipes-list');
    if (presets?.parentElement) presets.parentElement.insertBefore(description.root, presets);
    else panel.root.append(description.root);
    // Focus held on the panel itself was waiting for this field, the main way in.
    if (document.activeElement === panel.root) panel.focus?.();
  });
}
