// @vitest-environment happy-dom
// Describing a town in the person's own words: the page reads the drafting route's document
// strictly, has words for every status and refusal the server names (held here to the Python that
// states them), shows the person's words and the parts no value can say in their own words, and
// hands only a valid proposal's preset and values to the specification panel.
import { readFileSync } from 'node:fs';
import { URL as FileUrl } from 'node:url';
import { describe, expect, it, vi } from 'vitest';
import {
  DRAFT_REFUSALS,
  SAMPLE_STATUSES,
  parseWorldDraft,
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
    const prompt = JSON.parse(python('exulanica/selection/world-drafting.v2.json')) as Record<string, unknown>;
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

describe('the Describe it panel', () => {
  async function drafted(answer: WorldDraft) {
    const useValues = vi.fn();
    const panel = buildWorldDescription({
      draft: async () => answer, useValues, words: WORDS, maximumCharacters: 1000,
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

  it('refuses in words and says what a town here is set by, with nothing to use', async () => {
    const refused = parseWorldDraft({
      ...body,
      description: 'A floating city in the clouds',
      proposal: null,
      not_supported: [],
      refusal: { code: 'description_not_supported', detail: 'nothing the description asks for' },
    });
    const { panel } = await drafted(refused);
    const text = visibleText(panel.root);
    expect(text).toContain('Nothing in that is a town this server can make.');
    expect(text).toContain('Length of a block: 90 m to 140 m');
    expect(panel.root.querySelector('.world-description-use')).toBeNull();
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
});
