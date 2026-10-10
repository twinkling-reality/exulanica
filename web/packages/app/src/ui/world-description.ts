/**
 * "Describe it": a town asked for in the person's own words, drafted into values they confirm.
 *
 * The person types what they want; the server's specification drafter proposes a preset and
 * values (`POST /worlds/specification/drafts`), judges them by the specification's own
 * validation and samples one town of them. This panel shows the words back, the proposal in plain
 * words, the sample's people, vehicles, streets and premises, and the parts of the words no value
 * can say, each in the person's own words. "Use these values" hands the preset and values to the
 * specification panel (its `setValues` hook), where the person can change any value and make the
 * town; nothing is made here. A description that asks for nothing a town can be is refused in
 * words, with what a town here is set by, read from the served specification.
 *
 * A draft that can be used may offer the look its words ask for (`WorldDraft.lookOffer`). The panel
 * says it in one line under the person's words: the look by its title, the open model that chose
 * it, and the words of theirs that chose it. "Use these values" takes that look with the values
 * (`DraftLook.take`, handed every taken draft's offer so the look can follow the draft), and the
 * Look row beside the controls then shows it. A look the person chose themselves stays: the line
 * says so and offers the other with one press. A look step that did not answer is one calm line;
 * an offer of none is no line.
 *
 * Every word is in `copy.ts`; the tables below map each status and unit the server names to a key
 * there, and `world-description.test.ts` holds them to the server's own lists.
 */

import { problemSentence } from './words/problems.js';
import type {
  DraftRefusalCode,
  LookOffer,
  OfferedLook,
  SampleStatus,
  TownSample,
  WorldDraft,
} from '../world-draft-api.js';
import { fill, say } from './copy.js';
import { el, replace } from './dom.js';

/** A value a person may set, as the served specification states it, for its words. */
export interface SpecificationValueWords {
  readonly key: string;
  readonly label: string;
  readonly unit: string;
  readonly minimum: number;
  readonly maximum: number;
  readonly step: number;
  /** A choice's keys, each with its words; null for a number. */
  readonly choices: readonly { readonly key: string; readonly label: string }[] | null;
}

/** What the panel words a draft with, read from the served specification. */
export interface SpecificationWords {
  readonly values: readonly SpecificationValueWords[];
  readonly presets: readonly { readonly key: string; readonly label: string }[];
}

/** The words for each sample status the server names. */
export const SAMPLE_WORDS: Readonly<Record<SampleStatus, string>> = Object.freeze({
  sampled: 'worldDescription.sample.sampled',
  refused: 'worldDescription.sample.refused',
  overran: 'worldDescription.sample.overran',
  busy: 'worldDescription.sample.busy',
  unavailable: 'worldDescription.sample.unavailable',
});

/** The words for each reason a description gave no proposal. */
export const REFUSAL_WORDS: Readonly<Record<DraftRefusalCode, string>> = Object.freeze({
  description_not_supported: 'worldDescription.refused',
  not_drafted: 'worldDescription.notDrafted',
});

/** How a value of each unit the specification states is written; a unit with no entry is
 * written as the served specification spells it. */
export const UNIT_WORDS: Readonly<Record<string, (value: number) => string>> = Object.freeze({
  mm: (value: number) => fill('worldDescription.unit.mm', { metres: String(value / 1000) }),
  count: (value: number) => fill('worldDescription.unit.count', { count: String(value) }),
  permille: (value: number) => fill('worldDescription.unit.permille', { thousandths: String(value) }),
});

export function valueWords(value: number | string, unit: string): string {
  const words = UNIT_WORDS[unit];
  return words === undefined || typeof value === 'string' ? `${value} ${unit}`.trim() : words(value);
}

/** A value in words: a choice by its label, a number by its unit. */
function worded(value: SpecificationValueWords, chosen: number | string): string {
  if (typeof chosen === 'string') {
    return value.choices?.find((choice) => choice.key === chosen)?.label ?? chosen;
  }
  return valueWords(chosen, value.unit);
}

function listed(kinds: TownSample['streets']): string {
  return kinds.map((kind) => fill('worldDescription.sample.counted', {
    label: kind.label, count: String(kind.count),
  })).join(', ');
}

/** The sample's sentences: its numbers when there is a town, else why there is none. */
export function sampleLines(sample: TownSample): readonly string[] {
  if (sample.status !== 'sampled') {
    return [fill(SAMPLE_WORDS[sample.status], { code: sample.refused ?? '' })];
  }
  const vehicles = sample.vehicles !== null
    ? fill('worldDescription.sample.vehicles', { count: String(sample.vehicles) })
    : fill('worldDescription.sample.noVehicles', { code: sample.vehiclesRefused ?? '' });
  return [
    fill(SAMPLE_WORDS.sampled, {
      tiles: String(sample.tiles ?? 0),
      people: String(sample.people ?? 0),
      buildings: String(sample.buildings ?? 0),
      vehicles,
    }),
    fill('worldDescription.sample.streets', { list: listed(sample.streets) }),
    fill('worldDescription.sample.premises', { list: listed(sample.premises) }),
    say('worldDescription.sample.differs'),
  ];
}

/** The sentences a draft is shown in, from the words the person typed to the sample. */
export function draftLines(draft: WorldDraft, words: SpecificationWords): readonly string[] {
  const lines = [fill('worldDescription.yourWords', { words: draft.description })];
  const byKey = new Map(words.values.map((value) => [value.key, value]));
  if (draft.proposal === null) {
    const code = draft.refusal?.code ?? 'not_drafted';
    lines.push(say(REFUSAL_WORDS[code]));
    return lines;
  }
  const proposal = draft.proposal;
  const preset = words.presets.find((one) => one.key === proposal.preset)?.label ?? proposal.preset;
  lines.push(fill('worldDescription.proposed', {
    model: draft.modelName ?? say('worldDescription.unknownModel'), preset,
  }));
  // In the specification's own order, then any key it did not word.
  const ordered = [
    ...words.values.map((value) => value.key).filter((key) => key in proposal.values),
    ...Object.keys(proposal.values).filter((key) => !byKey.has(key)),
  ];
  for (const key of ordered) {
    const number = proposal.values[key]!;
    const value = byKey.get(key);
    lines.push(fill(proposal.setByWords.includes(key)
      ? 'worldDescription.valueFromWords' : 'worldDescription.value', {
      label: value?.label ?? key,
      value: value === undefined ? String(number) : worded(value, number),
    }));
  }
  const refused = proposal.valueRefusal;
  if (refused !== null) {
    const value = refused.key === null ? undefined : byKey.get(refused.key);
    const other = refused.withKey === null ? undefined : byKey.get(refused.withKey);
    const unit = value?.unit ?? '';
    lines.push(fill(refused.withKey === null
      ? 'worldDescription.valueRefused' : 'worldDescription.valuesDisagree', {
      label: value?.label ?? refused.key ?? '',
      value: refused.value === null ? '' : valueWords(refused.value, unit),
      other: other?.label ?? refused.withKey ?? '',
      otherValue: refused.withValue === null ? '' : valueWords(refused.withValue, other?.unit ?? ''),
      minimum: refused.minimum === null ? '' : valueWords(refused.minimum, unit),
      maximum: refused.maximum === null ? '' : valueWords(refused.maximum, unit),
      step: refused.step === null ? '' : valueWords(refused.step, unit),
    }));
  }
  if (proposal.sample !== null) lines.push(...sampleLines(proposal.sample));
  return lines;
}

/**
 * The parts of the words a proposed town's left-out line still names: those the drafter could not
 * place, less any that a step the page shows chose something from (`taken`, the words an offered
 * look was chosen from), so the page never says of the same words both that they chose the look
 * and that they are not in the town. A left-out phrase is dropped when it lies within one of those
 * or holds one, letters compared without case and spaces as one.
 */
export function leftOutPhrases(notSupported: readonly string[], taken: readonly string[]): readonly string[] {
  const fold = (words: string): string => words.toLowerCase().replace(/\s+/g, ' ').trim();
  const chosen = taken.map(fold).filter((words) => words !== '');
  return notSupported.filter((phrase) => {
    const words = fold(phrase);
    return !chosen.some((other) => other.includes(words) || words.includes(other));
  });
}

/**
 * The look a town not made yet will be made in, as this panel needs it: the Look row's side of a
 * draft's offered look (`../composition/town-look.ts`).
 */
export interface DraftLook {
  /**
   * What the page can say of an offered look: its title as the host lists it, and `kept`, the
   * title of another look the person chose themselves, which stays (null when they chose none, or
   * chose this one). Null where the host's list does not hold the offered pack, or is not read
   * yet: a look the page cannot name is not shown or taken.
   */
  offered(offer: OfferedLook): { readonly title: string; readonly kept: string | null } | null;
  /**
   * A draft was taken with its values: `offer` is its look offer as the answer carried it, null
   * for none carried. The look follows the draft unless the person chose the look themselves, so
   * an offered look becomes the town's, and a draft whose words ask for no look returns a look
   * that came with an earlier draft to the host's default. True when the offered look is the
   * town's after it; false where the person's own look stays, the page cannot name the offered
   * one, or the draft offers none.
   */
  take(offer: LookOffer | null): boolean;
  /**
   * Take the offered look in place of the one the person chose themselves: their own press, so
   * the look is theirs from then on.
   */
  takeInstead(offer: OfferedLook): boolean;
  /** Run `changed` whenever the town's look changes or the host's looks arrive. */
  watch(changed: () => void): void;
}

/** A draft's look line: its words, and the words of the one press that takes the look instead. */
export interface LookLine {
  readonly line: string;
  readonly instead: string | null;
}

/**
 * The line a usable draft says its look offer in, or null for no line: an offer of none, no offer,
 * or an offered look the page cannot name (`known` null).
 */
export function lookLine(
  offer: LookOffer | null,
  known: { readonly title: string; readonly kept: string | null } | null,
): LookLine | null {
  if (offer === null || offer.state === 'none') return null;
  if (offer.state === 'unavailable') return { line: say('worldDescription.look.unavailable'), instead: null };
  if (known === null) return null;
  const words = {
    model: offer.modelName ?? say('worldDescription.look.unknownModel'),
    title: known.title,
    phrases: offer.lookWords.map((phrase) => fill('worldDescription.quoted', { phrase })).join(', '),
  };
  if (known.kept === null) return { line: fill('worldDescription.look.offered', words), instead: null };
  return {
    line: fill('worldDescription.look.kept', { ...words, chosen: known.kept }),
    instead: fill('worldDescription.look.instead', { title: known.title }),
  };
}

export interface WorldDescriptionPanel {
  readonly root: HTMLElement;
}

export function buildWorldDescription(options: {
  readonly draft: (description: string) => Promise<WorldDraft>;
  /** The specification panel's hook: its values become these, for the person to change. */
  readonly useValues: (preset: string, values: Readonly<Record<string, number | string>>) => void;
  readonly words: SpecificationWords;
  /** The longest description the server reads. */
  readonly maximumCharacters: number;
  /** The town's look, shown and taken with a draft that offers one; absent, no look is said. */
  readonly look?: DraftLook;
}): WorldDescriptionPanel {
  const input = el('textarea', {
    class: 'world-description-input', rows: 3, maxlength: options.maximumCharacters,
    'aria-label': say('worldDescription.label'), placeholder: say('worldDescription.placeholder'),
  });
  const ask = el('button', { type: 'button', class: 'world-description-draft',
    text: say('worldDescription.draft') });
  const status = el('p', { class: 'world-description-status', role: 'status', 'aria-live': 'polite' });
  const result = el('div', { class: 'world-description-result' });
  const root = el('section', { class: 'world-description', 'aria-label': say('worldDescription.heading') }, [
    el('h3', { text: say('worldDescription.heading') }),
    el('p', { text: say('worldDescription.introduction') }),
    input,
    ask,
    status,
    result,
  ]);
  // The look of the draft shown: said only for a draft that can be used, and said again whenever
  // the town's look changes, so the line is true of the Look row beside it.
  const look = options.look;
  const lookBox = el('div', { class: 'world-description-look' });
  let offer: LookOffer | null = null;
  const offeredLook = (): OfferedLook | null => (offer !== null && offer.state === 'offered' ? offer : null);
  const sayLook = (): void => {
    if (look === undefined) return;
    const offered = offeredLook();
    const known = offered === null ? null : look.offered(offered);
    const said = lookLine(offer, known);
    // An offered look is said in full ink among the muted values; a step that did not answer is not.
    lookBox.dataset['look'] = said === null || offer === null ? '' : offer.state;
    const children: Node[] = said === null ? [] : [el('p', { text: said.line })];
    if (said !== null && said.instead !== null && offered !== null && known !== null) {
      const instead = el('button', { type: 'button', class: 'world-description-look-instead',
        text: said.instead });
      instead.addEventListener('click', () => {
        if (look.takeInstead(offered)) {
          status.textContent = fill('worldDescription.look.taken', { title: known.title });
        }
      });
      children.push(instead);
    }
    replace(lookBox, children);
    sayLeftOut(known === null || offered === null ? null : offered.lookWords);
  };
  // What the words did not reach, for a town that is proposed: first, where they set no value and
  // chose no look shown above, that the town is its recipe's usual one; then, in one plain line,
  // what of the words is not in the town yet, never the words the shown look was chosen from.
  const leftOutBox = el('div', { class: 'world-description-left-out' });
  let leftOut: readonly string[] | null = null;
  let usual: string | null = null;
  const sayLeftOut = (taken: readonly string[] | null): void => {
    const phrases = leftOut === null ? [] : leftOutPhrases(leftOut, taken ?? []);
    replace(leftOutBox, [
      ...(usual === null || taken !== null ? [] : [
        el('p', { class: 'world-description-usual', text: fill('worldDescription.usual', { preset: usual }) }),
      ]),
      ...(phrases.length === 0 ? [] : [el('p', { class: 'world-description-not-supported', text: fill(
        'worldDescription.notSupported',
        { phrases: phrases.map((phrase) => fill('worldDescription.quoted', { phrase })).join(', ') },
      ) })]),
    ]);
  };
  look?.watch(sayLook);
  const show = (draft: WorldDraft): void => {
    const lines = draftLines(draft, options.words).map((line) => el('p', { text: line }));
    offer = draft.proposal !== null && draft.proposal.valid ? draft.lookOffer : null;
    // A description that asks for no town is answered in its one sentence, with no such line.
    leftOut = draft.proposal === null ? null : draft.notSupported;
    // The recipe's own town, by the name the specification gives the preset, where no value came
    // from the words.
    const from = draft.proposal;
    usual = from === null || from.setByWords.length > 0 ? null
      : options.words.presets.find((one) => one.key === from.preset)?.label ?? from.preset;
    if (look === undefined) sayLeftOut(null);
    else sayLook();
    // The look comes right under the person's words, then what is not in the town yet, both
    // before the long list of values.
    const children: Node[] = [...lines.slice(0, 1), lookBox, leftOutBox, ...lines.slice(1)];
    const proposal = draft.proposal;
    if (proposal !== null && proposal.valid) {
      const use = el('button', { type: 'button', class: 'world-description-use',
        text: say('worldDescription.use') });
      use.addEventListener('click', () => {
        options.useValues(proposal.preset, proposal.values);
        // The look follows the draft taken: the row is handed this draft's offer, whatever it
        // says, and answers whether the offered look is the town's.
        const offered = offeredLook();
        const known = offered === null || look === undefined ? null : look.offered(offered);
        status.textContent = look?.take(offer) === true && known !== null
          ? fill('worldDescription.usedWithLook', { title: known.title })
          : say('worldDescription.used');
      });
      children.push(use);
    }
    replace(result, children);
  };
  ask.addEventListener('click', () => {
    const description = input.value.trim();
    if (description === '') {
      status.textContent = say('worldDescription.empty');
      return;
    }
    ask.disabled = true;
    status.textContent = say('worldDescription.drafting');
    void options.draft(description).then((draft) => {
      status.textContent = '';
      show(draft);
    }).catch((error: unknown) => {
      status.textContent = fill('worldDescription.failed', {
        reason: problemSentence(error),
      });
    }).finally(() => {
      ask.disabled = false;
    });
  });
  return { root };
}
