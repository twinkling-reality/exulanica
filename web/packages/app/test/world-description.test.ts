// @vitest-environment happy-dom
// Describing a town in the person's own words: the page reads the drafting route's document
// strictly, has words for every status and refusal the server names (held here to the Python that
// states them), shows the person's words and the parts no value can say in their own words, and
// hands only a valid proposal's preset and values to the specification panel. The answer's optional
// look offer is read in every state the contract lists and never refuses the draft; the panel says
// an offered look in one line and takes it with the values.
import { readFileSync } from 'node:fs';
import { URL as FileUrl } from 'node:url';
import { describe, expect, it, vi } from 'vitest';
import {
  DRAFT_REFUSALS,
  LOOK_OFFER_STATES,
  SAMPLE_STATUSES,
  parseWorldDraft,
  type LookOffer,
  type OfferedLook,
  type WorldDraft,
} from '../src/world-draft-api.js';
import { say } from '../src/ui/copy.js';
import {
  DESCRIPTION_CHARACTERS,
  specificationWords,
} from '../src/composition/world-description.js';
import {
  REFUSAL_WORDS,
  SAMPLE_WORDS,
  UNIT_WORDS,
  buildWorldDescription,
  draftLines,
  leftOutPhrases,
  lookLine,
  type DraftLook,
  type SpecificationWords,
} from '../src/ui/world-description.js';

const REPOSITORY = new FileUrl('../../../../', import.meta.url);
const python = (path: string): string => readFileSync(new FileUrl(path, REPOSITORY), 'utf8');

const WORDS: SpecificationWords = {
  values: [
    { key: 'city_extent_x_mm', label: 'Length of the town', unit: 'mm',
      minimum: 256000, maximum: 384000, step: 128000, choices: null },
    { key: 'block_length_mm', label: 'Length of a block', unit: 'mm',
      minimum: 90000, maximum: 140000, step: 10000, choices: null },
    { key: 'storey_band_high', label: 'Most storeys', unit: 'count', minimum: 4, maximum: 5, step: 1,
      choices: null },
  ],
  presets: [{ key: 'market_town', label: 'A market town' }],
};

const body = {
  description: 'A market town with taller buildings and a harbour',
  proposal: {
    preset: 'market_town',
    values: { block_length_mm: 140000, city_extent_x_mm: 384000, storey_band_high: 5 },
    set_by_words: ['storey_band_high'],
    fit: 'part',
    valid: true,
    value_refusal: null,
    sample: {
      status: 'sampled', tiles: 3, people: 72, vehicles: 16, vehicles_refused: null,
      streets: [{ key: 'high_street', label: 'High street', count: 1 }],
      premises: [{ key: 'cafe', label: 'Cafe', count: 9 }],
      buildings: 31, refused: null,
    },
  },
  not_supported: ['a harbour'],
  refusal: null,
  specification_version: 1,
  specification_sha256: 'a'.repeat(64),
  prompt_version: 'world-drafting-1',
  prompt_sha256: 'b'.repeat(64),
  model_id: 'nvidia/example',
  model_name: 'Example Model',
  execution: { prompt_version: 'world-drafting-1', rejections: [], calls: [] },
};

function visibleText(root: HTMLElement): string {
  return root.textContent ?? '';
}

/** One call of the look step as the route's `execution` lists it (`ModelCallView`). */
const lookCall = (overrides: Record<string, unknown> = {}) => ({
  role: 'look_chooser', requested_model: 'example/chooser', served_model: 'example/chooser',
  requested_model_name: 'Chooser Model', served_model_name: 'Chooser Model', used_fallback: false,
  attempts: 1, latency_ms: 900, prompt_tokens: 210, completion_tokens: 24, reasoning_tokens: null,
  usd: '0.0001', served_model_unavailable: null, outcome: 'completed', cost_basis: 'known',
  ...overrides,
});

/** A look offer as the route serves it (`LookOfferView`), offered unless overridden. */
const lookOffer = (overrides: Record<string, unknown> = {}) => ({
  state: 'offered', reason: null, pack_id: 'exulanica.toon-town', version: 3,
  manifest_sha256: 'd'.repeat(64), look_words: ['bright cartoon', 'toy box'],
  prompt_version: 'look-choosing-1', prompt_sha256: 'e'.repeat(64),
  execution: { prompt_version: 'look-choosing-1', rejections: [], calls: [lookCall()] },
  ...overrides,
});

/** A state's offer as the route serves it: only an offered look names a pack and words. */
const lookOfferIn = (state: string) => (state === 'offered' ? lookOffer() : lookOffer({
  state, reason: state === 'unavailable' ? 'timed_out' : null, pack_id: null, version: null,
  manifest_sha256: null, look_words: [],
}));

/** The states the contract's table lists for a look offer (section 10.1), in its order. */
function contractLookStates(): string[] {
  const contract = python('docs/style-pack-contract.md');
  const table = contract.slice(contract.indexOf('| `state` | Meaning |', contract.indexOf('### 10.1 ')));
  return [...table.slice(0, table.indexOf('\n\n')).matchAll(/^\| `(\w+)` \|/gm)]
    .map((row) => row[1]!).filter((state) => state !== 'state');
}

/** A committed pack's title, as its own manifest states it. */
const packTitle = (packId: string): string => (
  JSON.parse(python(`assets/style-packs/packs/${packId}/manifest.json`)) as { title: string }).title;

describe('the drafting route document', () => {
  it('names the statuses and refusals the server names', () => {
    const statuses = /SampleStatus = Literal\[([^\]]+)\]/.exec(
      python('exulanica/world/specification_samples.py'),
    )![1]!.match(/"(\w+)"/g)!.map((quoted) => quoted.slice(1, -1));
    expect([...SAMPLE_STATUSES].sort()).toEqual(statuses.sort());
    const refusals = [...python('exulanica/selection/world_drafting.py').matchAll(
      /^ {4}[A-Z_]+ = "(\w+)"$/gm,
    )].map((match) => match[1]);
    expect(refusals).toEqual(expect.arrayContaining([...DRAFT_REFUSALS]));
  });

  it('reads a proposal and refuses one whose verdict and sample disagree', () => {
    const draft = parseWorldDraft(body);
    expect(draft.proposal?.values['storey_band_high']).toBe(5);
    expect(draft.notSupported).toEqual(['a harbour']);
    const broken = structuredClone(body);
    broken.proposal.valid = false;
    expect(() => parseWorldDraft(broken)).toThrow(TypeError);
  });

  it('holds the page to the description ceiling the server reads', () => {
    const prompt = JSON.parse(python('exulanica/selection/world-drafting.v6.json')) as Record<string, unknown>;
    expect(DESCRIPTION_CHARACTERS).toBe(prompt['description_characters_maximum']);
  });

  it('words every adjustable value of the served specification, a choice by its words', () => {
    const words = specificationWords({
      values: [
        { key: 'block_length_mm', label: 'Distance between cross streets', kind: 'integer', unit: 'mm',
          adjustable: true, minimum: 90000, maximum: 140000, step: 10000 },
        { key: 'block_depth_mm', label: 'Depth of a block', kind: 'integer', unit: 'mm',
          adjustable: false, minimum: 56000, maximum: 56000, step: 1000 },
        { key: 'driving_side', label: 'Side', kind: 'choice', unit: 'key',
          adjustable: false, minimum: null, maximum: null, step: null },
        { key: 'cross_street_hierarchy', label: 'The other cross streets', kind: 'choice', unit: 'key',
          adjustable: true, minimum: null, maximum: null, step: null,
          choices: ['local_street', 'narrow_street'], choiceLabels: ['Local street', 'Narrow street'] },
      ],
      presets: [{ key: 'small_town', label: 'A small town' }],
    });
    expect(words.values.map((value) => value.key)).toEqual(['block_length_mm', 'cross_street_hierarchy']);
    expect(words.values[1]!.choices).toEqual([
      { key: 'local_street', label: 'Local street' },
      { key: 'narrow_street', label: 'Narrow street' },
    ]);
    expect(words.presets).toEqual([{ key: 'small_town', label: 'A small town' }]);
  });

  it('has words for every status, refusal and unit it names', () => {
    for (const status of SAMPLE_STATUSES) expect(say(SAMPLE_WORDS[status])).not.toBe(SAMPLE_WORDS[status]);
    for (const code of DRAFT_REFUSALS) expect(say(REFUSAL_WORDS[code])).not.toBe(REFUSAL_WORDS[code]);
    expect(UNIT_WORDS['mm']!(128000)).toBe('128 m');
    expect(UNIT_WORDS['permille']!(750)).toBe('750 of 1,000');
  });
});

describe('the look a draft offers', () => {
  it('names the states the contract and the server name', () => {
    const contract = contractLookStates();
    expect(contract).toEqual(['offered', 'none', 'unavailable']);
    expect([...LOOK_OFFER_STATES]).toEqual(contract);
    const served = /class LookOfferView[\s\S]*?state: Literal\[([^\]]+)\]/.exec(
      python('exulanica/api/routes/world_drafts.py'),
    )![1]!.match(/"(\w+)"/g)!.map((quoted) => quoted.slice(1, -1));
    expect(served.sort()).toEqual([...contract].sort());
  });

  it('is read in every state the contract lists, and is none where the answer carries none', () => {
    for (const state of contractLookStates()) {
      expect(parseWorldDraft({ ...body, look_offer: lookOfferIn(state) }).lookOffer?.state).toBe(state);
    }
    expect(parseWorldDraft({ ...body, look_offer: lookOffer() }).lookOffer).toEqual({
      state: 'offered', packId: 'exulanica.toon-town', version: 3, manifestSha256: 'd'.repeat(64),
      lookWords: ['bright cartoon', 'toy box'], modelName: 'Chooser Model',
    });
    // Absent from an answer written before the offer, and null for a refused draft.
    expect(parseWorldDraft(body).lookOffer).toBeNull();
    expect(parseWorldDraft({ ...body, look_offer: null }).lookOffer).toBeNull();
  });

  it('never refuses the draft it came with: an unknown state or field is passed over', () => {
    const unreadable: unknown[] = [
      lookOffer({ state: 'suggested' }),
      lookOffer({ manifest_sha256: null }),
      lookOffer({ manifest_sha256: 'not-a-digest' }),
      lookOffer({ version: '3' }),
      lookOffer({ pack_id: null }),
      lookOffer({ look_words: [] }),
      lookOffer({ look_words: 'bright cartoon' }),
      'offered',
      ['offered'],
      7,
    ];
    for (const offer of unreadable) {
      const draft = parseWorldDraft({ ...body, look_offer: offer });
      expect(draft.lookOffer).toBeNull();
      expect(draft.proposal?.values).toEqual(body.proposal.values);
    }
    // A field a later server adds is passed over, in any state; so is an execution it cannot read.
    const grown = parseWorldDraft({ ...body, look_offer: lookOffer({ preview: 'later', execution: 'later' }) });
    expect(grown.lookOffer).toMatchObject({ state: 'offered', packId: 'exulanica.toon-town', modelName: null });
    expect(parseWorldDraft({ ...body, look_offer: { state: 'none', more: 1 } }).lookOffer).toEqual({ state: 'none' });
  });

  it('names the model whose call answered: the last completed one, as served', () => {
    const named = (calls: unknown[]) => {
      const offer = parseWorldDraft({ ...body, look_offer: lookOffer({
        execution: { prompt_version: 'look-choosing-1', rejections: [], calls },
      }) }).lookOffer;
      return offer?.state === 'offered' ? offer.modelName : undefined;
    };
    // A first answer refused and repaired by a fallback: the repair chose the look.
    expect(named([
      lookCall({ served_model_name: 'First Model' }),
      lookCall({ served_model_name: 'Second Model', used_fallback: true }),
      lookCall({ served_model_name: null, served_model: null, outcome: 'timed_out' }),
    ])).toBe('Second Model');
    // A response that named no model is called by the one that was asked.
    expect(named([lookCall({ served_model_name: null, served_model: null })])).toBe('Chooser Model');
    expect(named([lookCall({ outcome: 'failed' })])).toBeNull();
    expect(named([])).toBeNull();
  });

  it('is said in one line: the look, the model that chose it and the words that chose it', () => {
    const toon = packTitle('exulanica.toon-town');
    const cozy = packTitle('exulanica.cozy-town');
    const offered = parseWorldDraft({ ...body, look_offer: lookOffer() }).lookOffer;
    expect(lookLine(offered, { title: toon, kept: null })).toEqual({
      line: `Chooser Model chose the look ${toon} from your words “bright cartoon”, “toy box”.`,
      instead: null,
    });
    // A look the person chose themselves stays, and the other is one press away.
    expect(lookLine(offered, { title: toon, kept: cozy })).toEqual({
      line: `Chooser Model chose the look ${toon} from your words “bright cartoon”, “toy box”. `
        + `You chose ${cozy} yourself, so it stays.`,
      instead: `Use ${toon} instead`,
    });
    const unnamed = parseWorldDraft({ ...body, look_offer: lookOffer({ execution: null }) }).lookOffer;
    expect(lookLine(unnamed, { title: toon, kept: null })?.line).toBe(
      `An open model chose the look ${toon} from your words “bright cartoon”, “toy box”.`);
    // A look the page cannot name is not said.
    expect(lookLine(offered, null)).toBeNull();
  });

  it('is one calm line when the step did not answer, and no line when it offers none', () => {
    const lineOf = (state: string) => lookLine(
      parseWorldDraft({ ...body, look_offer: lookOfferIn(state) }).lookOffer, null);
    expect(lineOf('unavailable')).toEqual({
      line: 'No look was chosen from your words this time. The town will be drawn in the look shown.',
      instead: null,
    });
    expect(lineOf('none')).toBeNull();
    expect(lookLine(null, null)).toBeNull();
  });
});

describe('the Describe it panel', () => {
  async function drafted(answer: WorldDraft, look?: DraftLook) {
    const useValues = vi.fn();
    const panel = buildWorldDescription({
      draft: async () => answer, useValues, words: WORDS, maximumCharacters: 1000,
      ...(look === undefined ? {} : { look }),
    });
    document.body.append(panel.root);
    panel.root.querySelector('textarea')!.value = answer.description;
    panel.root.querySelector<HTMLButtonElement>('.world-description-draft')!.click();
    await vi.waitFor(() => expect(panel.root.querySelector('.world-description-result p')).not.toBeNull());
    return { panel, useValues };
  }

  it('shows the words, the proposal in plain words and the sample, and hands on the values', async () => {
    const { panel, useValues } = await drafted(parseWorldDraft(body));
    const text = visibleText(panel.root);
    expect(text).toContain('A market town with taller buildings and a harbour');
    expect(text).toContain('Example Model drafted these values, starting from A market town');
    expect(text).toContain('Length of the town: 384 m');
    expect(text).toContain('Most storeys: 5, from your words');
    expect(text).toContain('3 tiles, 72 people, 31 buildings and 16 vehicles');
    expect(text).toContain('Streets: High street 1');
    expect(text).toContain('“a harbour”');
    expect(text).not.toMatch(/worldDescription\./);
    const lines = [...panel.root.querySelectorAll('.world-description-result p')].map((p) => p.textContent);
    expect(lines.indexOf('Length of the town: 384 m')).toBeLessThan(
      lines.indexOf('Length of a block: 140 m'));
    panel.root.querySelector<HTMLButtonElement>('.world-description-use')!.click();
    expect(useValues).toHaveBeenCalledWith('market_town', body.proposal.values);
    expect(text).not.toContain(say('worldDescription.used'));
    expect(visibleText(panel.root)).toContain(say('worldDescription.used'));
  });

  it('answers words that ask for no town in one sentence with one thing to try, and nothing to use', async () => {
    const refused = parseWorldDraft({
      ...body,
      description: 'A red bicycle',
      proposal: null,
      // Whatever the answer lists, a description that asks for no town is told so and nothing more.
      not_supported: ['A red bicycle'],
      refusal: { code: 'description_not_supported', detail: 'the description asks for no town' },
    });
    const { panel } = await drafted(refused);
    const lines = [...panel.root.querySelectorAll('.world-description-result p')].map((p) => p.textContent);
    // The person's words, then the one sentence: no list of the values a town is set by.
    expect(lines).toEqual([
      'You asked for: \u201cA red bicycle\u201d',
      'This makes towns, and that does not ask for one: try something like \u201ca quiet town with low buildings\u201d.',
    ]);
    expect(panel.root.querySelector('.world-description-not-supported')).toBeNull();
    expect(panel.root.querySelector('.world-description-use')).toBeNull();
  });

  it('says in one sentence, with one thing to try, when the drafter gave no usable answer', async () => {
    // Whatever the words were: code cannot know they ask for no town, so the page does not say so.
    const none = parseWorldDraft({
      ...body, description: 'asdfghjkl', proposal: null, not_supported: [],
      refusal: { code: 'not_drafted', detail: 'the model could not fill the form' },
    });
    const { panel } = await drafted(none);
    const lines = [...panel.root.querySelectorAll('.world-description-result p')].map((p) => p.textContent);
    expect(lines).toEqual([
      'You asked for: \u201casdfghjkl\u201d',
      'No town was drafted from that: say a little more about the town you want, or start from a recipe below.',
    ]);
    expect(panel.root.querySelector('.world-description-use')).toBeNull();
  });

  it('proposes a town whose words no value can say, and says what is not in it yet in one line under them', async () => {
    // As the route answers a description that asks for a town and names nothing on the form: the
    // preset's own values, none set by the words, and each part of the words left out.
    const seaside = parseWorldDraft({
      ...body,
      description: 'A sleepy seaside town at dawn, mist off the water',
      proposal: { ...body.proposal, set_by_words: [], fit: 'part' },
      not_supported: ['seaside', 'at dawn', 'mist off the water'],
    });
    const { panel } = await drafted(seaside);
    const lines = [...panel.root.querySelectorAll('.world-description-result p')].map((p) => p.textContent);
    expect(lines[0]).toBe('You asked for: \u201cA sleepy seaside town at dawn, mist off the water\u201d');
    // Said first and plainly: the words changed nothing of this town yet.
    expect(lines[1]).toBe('A market town as it usually is: nothing you typed changes it yet.');
    expect(lines[2]).toBe('Not in this town yet: \u201cseaside\u201d, \u201cat dawn\u201d, \u201cmist off the water\u201d');
    expect(lines.filter((line) => line?.startsWith('Not in this town'))).toHaveLength(1);
    // The town is proposed and can be used: it is the recipe's own.
    expect(lines.some((line) => line?.includes('drafted these values, starting from'))).toBe(true);
    expect(lines.some((line) => line?.includes('from your words'))).toBe(false);
    expect(panel.root.querySelector('.world-description-use')).not.toBeNull();
  });

  it('says which value the server refuses and the range it broke, and offers nothing to use', () => {
    const lines = draftLines(parseWorldDraft({
      ...body,
      proposal: {
        ...body.proposal,
        valid: false,
        sample: null,
        value_refusal: {
          code: 'specification_values_disagree', detail: 'three tiles need long blocks',
          key: 'block_length_mm', value: 90000, minimum: 130000, maximum: 140000, step: 10000,
        },
      },
    }), WORDS);
    expect(lines.join('\n')).toContain(
      'The server refuses Length of a block at 90 m with these values: it takes 130 m to 140 m, '
      + 'in steps of 10 m.',
    );
  });

  it('says which two values disagree and the range one narrows the other to', () => {
    const lines = draftLines(parseWorldDraft({
      ...body,
      proposal: {
        ...body.proposal,
        valid: false,
        sample: null,
        value_refusal: {
          code: 'specification_values_disagree', detail: 'three tiles need long blocks',
          key: 'block_length_mm', value: 100000, minimum: 130000, maximum: 140000, step: 10000,
          choices: [], with_key: 'city_extent_x_mm', with_value: 384000,
        },
      },
    }), WORDS);
    expect(lines.join('\n')).toContain(
      'The server refuses Length of a block at 100 m while Length of the town is 384 m: with that '
      + 'it takes 130 m to 140 m, in steps of 10 m.',
    );
  });

  /** The Look row's side, as the panel is handed it: what it was asked, and what it answers. */
  function rowSide(known: { title: string; kept: string | null } | null, takes = true) {
    const taken: (LookOffer | null)[] = [];
    const instead: OfferedLook[] = [];
    const look: DraftLook = {
      offered: () => known,
      take: (offer) => { taken.push(offer); return takes; },
      takeInstead: (offer) => { instead.push(offer); return true; },
      watch: () => undefined,
    };
    return { look, taken, instead };
  }
  const lookText = (root: HTMLElement): string | null => (
    root.querySelector('.world-description-look p')?.textContent ?? null);

  it('says the offered look right under the person\'s words and takes it with the values', async () => {
    const toon = packTitle('exulanica.toon-town');
    const side = rowSide({ title: toon, kept: null });
    const { panel, useValues } = await drafted(parseWorldDraft({ ...body, look_offer: lookOffer() }), side.look);
    expect(lookText(panel.root)).toBe(
      `Chooser Model chose the look ${toon} from your words “bright cartoon”, “toy box”.`);
    const result = [...panel.root.querySelector('.world-description-result')!.children];
    expect(result[0]!.textContent).toContain('You asked for:');
    expect(result[1]!.className).toBe('world-description-look');
    expect(panel.root.querySelector('.world-description-look-instead')).toBeNull();
    expect(side.taken).toEqual([]);
    panel.root.querySelector<HTMLButtonElement>('.world-description-use')!.click();
    expect(useValues).toHaveBeenCalledWith('market_town', body.proposal.values);
    expect(side.taken).toEqual([{
      state: 'offered', packId: 'exulanica.toon-town', version: 3, manifestSha256: 'd'.repeat(64),
      lookWords: ['bright cartoon', 'toy box'], modelName: 'Chooser Model',
    }]);
    expect(panel.root.querySelector('.world-description-status')!.textContent).toBe(
      `These values are in the controls below, and the look is ${toon}. Change any of them, then make the town.`);
  });

  it('never says of the same words both that they chose the look and that they are not in the town', async () => {
    // As the real roles answered "A bright cartoon town like a toy box, with lofts, cafes and
    // restaurants": the drafter left three phrases out and the look step chose from the same words.
    const leftOut = ['bright', 'cartoon', 'toy box'];
    const chosenFrom = ['bright', 'cartoon town', 'like a toy box'];
    expect(leftOutPhrases(leftOut, chosenFrom)).toEqual([]);
    // Without case and with spaces as one; a phrase that holds a chosen one goes too.
    expect(leftOutPhrases(['Toy  Box', 'a harbour', 'bright cartoon colours'], ['toy box', 'cartoon'])).toEqual(['a harbour']);
    expect(leftOutPhrases(['a harbour'], [])).toEqual(['a harbour']);

    const side = rowSide({ title: packTitle('exulanica.toon-town'), kept: null });
    const said = (root: HTMLElement) => root.querySelector('.world-description-not-supported')?.textContent ?? null;
    const usual = (root: HTMLElement) => root.querySelector('.world-description-usual')?.textContent ?? null;
    const all = await drafted(parseWorldDraft({
      ...body, not_supported: leftOut, look_offer: lookOffer({ look_words: chosenFrom }),
    }), side.look);
    expect(lookText(all.panel.root)).toContain('chose the look');
    expect(said(all.panel.root)).toBeNull();
    // A value came from the words in this draft, so the town is not said to be the usual one.
    expect(usual(all.panel.root)).toBeNull();
    // No value from the words, but a look chosen from them and shown: not the usual town either.
    const looked = await drafted(parseWorldDraft({
      ...body, proposal: { ...body.proposal, set_by_words: [] }, not_supported: leftOut, look_offer: lookOffer({ look_words: chosenFrom }),
    }), side.look);
    expect(usual(looked.panel.root)).toBeNull();
    // No value and a look the page cannot name: the words reached nothing, and the page says so.
    const reached = await drafted(parseWorldDraft({
      ...body, proposal: { ...body.proposal, set_by_words: [] }, not_supported: leftOut, look_offer: lookOffer({ look_words: chosenFrom }),
    }), rowSide(null).look);
    expect(usual(reached.panel.root)).toBe('A market town as it usually is: nothing you typed changes it yet.');
    // What the look did not take is still said, once, right after the look's line.
    const some = await drafted(parseWorldDraft({
      ...body, not_supported: [...leftOut, 'a harbour'], look_offer: lookOffer({ look_words: chosenFrom }),
    }), side.look);
    expect(said(some.panel.root)).toBe('Not in this town yet: \u201ca harbour\u201d');
    const order = [...some.panel.root.querySelector('.world-description-result')!.children].map((node) => node.className);
    expect(order.slice(1, 3)).toEqual(['world-description-look', 'world-description-left-out']);
    // A look the page cannot name is not shown, so its words stay in the line.
    const unnamed = await drafted(parseWorldDraft({
      ...body, not_supported: leftOut, look_offer: lookOffer({ look_words: chosenFrom }),
    }), rowSide(null).look);
    expect(said(unnamed.panel.root)).toBe('Not in this town yet: \u201cbright\u201d, \u201ccartoon\u201d, \u201ctoy box\u201d');
  });

  it('keeps a look the person chose themselves, and takes the other only on its own press', async () => {
    const toon = packTitle('exulanica.toon-town');
    const finished = packTitle('exulanica.finished-town');
    const side = rowSide({ title: toon, kept: finished }, false);
    const { panel } = await drafted(parseWorldDraft({ ...body, look_offer: lookOffer() }), side.look);
    expect(lookText(panel.root)).toBe(
      `Chooser Model chose the look ${toon} from your words “bright cartoon”, “toy box”. `
      + `You chose ${finished} yourself, so it stays.`);
    const instead = panel.root.querySelector<HTMLButtonElement>('.world-description-look-instead')!;
    expect(instead.textContent).toBe(`Use ${toon} instead`);
    panel.root.querySelector<HTMLButtonElement>('.world-description-use')!.click();
    // The row refused the take, so the values alone are said to be in the controls.
    expect(panel.root.querySelector('.world-description-status')!.textContent).toBe(say('worldDescription.used'));
    expect(side.instead).toEqual([]);
    instead.click();
    expect(side.instead.map((offer) => offer.packId)).toEqual(['exulanica.toon-town']);
    expect(panel.root.querySelector('.world-description-status')!.textContent).toBe(`The look is now ${toon}.`);
  });

  it('says one calm line when no look was chosen and nothing when none is offered, and tells the row which draft was taken', async () => {
    const use = (root: HTMLElement): void => root.querySelector<HTMLButtonElement>('.world-description-use')!.click();
    const statusOf = (root: HTMLElement) => root.querySelector('.world-description-status')!.textContent;
    for (const [state, line] of [
      ['unavailable', 'No look was chosen from your words this time. The town will be drawn in the look shown.'],
      ['none', null],
    ] as const) {
      const side = rowSide(null, false);
      const { panel } = await drafted(parseWorldDraft({ ...body, look_offer: lookOfferIn(state) }), side.look);
      expect(lookText(panel.root)).toBe(line);
      // Never an error: the draft is there to use, and nothing on the panel is an alert.
      expect(panel.root.querySelector('[role="alert"]')).toBeNull();
      // Nothing reaches the row when the draft arrives; the press hands it this draft's offer as
      // it is, so the look can follow the draft that was taken.
      expect(side.taken).toEqual([]);
      use(panel.root);
      expect(side.taken).toEqual([{ state }]);
      expect(statusOf(panel.root)).toBe(say('worldDescription.used'));
      panel.root.remove();
    }
    // An answer with no offer hands the row none, and says nothing of a look.
    const side = rowSide({ title: 'Toon town', kept: null }, false);
    const absent = await drafted(parseWorldDraft(body), side.look);
    expect(lookText(absent.panel.root)).toBeNull();
    use(absent.panel.root);
    expect(side.taken).toEqual([null]);
    expect(statusOf(absent.panel.root)).toBe(say('worldDescription.used'));
    // A panel handed no Look row says nothing of a look.
    expect(lookText((await drafted(parseWorldDraft({ ...body, look_offer: lookOffer() }))).panel.root)).toBeNull();
  });

  it('says no look for a draft that cannot be used', async () => {
    const side = rowSide({ title: 'Toon town', kept: null });
    const { panel } = await drafted(parseWorldDraft({
      ...body,
      look_offer: lookOffer(),
      proposal: {
        ...body.proposal, valid: false, sample: null,
        value_refusal: {
          code: 'specification_values_disagree', detail: 'three tiles need long blocks',
          key: 'block_length_mm', value: 90000, minimum: 130000, maximum: 140000, step: 10000,
        },
      },
    }), side.look);
    expect(panel.root.querySelector('.world-description-use')).toBeNull();
    expect(lookText(panel.root)).toBeNull();
  });
});
