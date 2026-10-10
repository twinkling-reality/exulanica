import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  effectiveRange,
  parseWorldSpecification,
  rangeWords,
  refusalOf,
} from '../src/world-specification.js';
import { servedSpecification } from './world-specification-document.js';

/**
 * The served specification document, read strictly, and the page's statement of the refusal the
 * server's gate gives values the ranges do not admit: the same codes, and the same words
 * (`exulanica/world/world_recipes.py`, `SpecificationValue.refused` and `SpecificationSchema.check`).
 */

describe('the served specification', () => {
  it('is read strictly: its values, presets, bounds and refusals', () => {
    const read = parseWorldSpecification(servedSpecification());
    expect(read.grammar).toEqual({ grammarId: 'city', grammarVersion: 4 });
    expect(read.values.filter((value) => value.adjustable).map((value) => value.key)).toEqual(['city_extent_x_mm', 'block_length_mm']);
    expect(read.values.find((value) => value.key === 'block_depth_mm')?.value).toBe(56000);
    expect(read.presets.map((preset) => [preset.key, preset.tiles])).toEqual([['small_town', 2], ['market_town', 3]]);
    expect(read.mostPeople).toBe(128);
    expect(read.generatedWorldsPerWorkspace).toBe(3);
    expect(() => parseWorldSpecification({ ...servedSpecification(), profile: 'another/v1' })).toThrow(TypeError);
    expect(() => parseWorldSpecification({ ...servedSpecification(), presets: undefined })).toThrow(TypeError);
  });

  it('reads a ground that states no maximum of people, and the least maximum where grounds state some', () => {
    const withPeople = (people: unknown[]) => ({ ...servedSpecification(), bounds: { ...(servedSpecification() as { bounds: object }).bounds, people } });
    const ground = (most: unknown) => ({ ground: 'generated_town', composer: 'city-grammar-town', most, minute_share_milli: 100 });
    // A town is peopled by its own homes: the server states no maximum, as null.
    expect(parseWorldSpecification(withPeople([ground(null)])).mostPeople).toBeNull();
    expect(parseWorldSpecification(withPeople([ground(null), ground(64), ground(128)])).mostPeople).toBe(64);
    // Anything else there is not a bound.
    for (const most of ['128', 12.5, undefined, {}]) {
      expect(() => parseWorldSpecification(withPeople([ground(most)])), String(most)).toThrow('invalid people bound');
    }
  });

  it('reads the specification the server serves today, whole', () => {
    // Relative to web/, where the suite runs. Written by tests/test_world_specification_served_snapshot.py
    // from the server's own document, and held to it there: what the creation screen is given.
    const served = JSON.parse(readFileSync('../tests/snapshots/world-specification.served.json', 'utf8')) as { presets: unknown[]; values: unknown[] };
    const read = parseWorldSpecification(served);
    expect(read.presets.length).toBe(served.presets.length);
    expect(read.values.length).toBe(served.values.length);
    expect(read.presets.length).toBeGreaterThan(0);
  });

  it('states the refusal the gate gives, by its code and in its words, before anything is sent', () => {
    const read = parseWorldSpecification(servedSpecification());
    expect(refusalOf(read, { block_length_mm: 130000, city_extent_x_mm: 384000 })).toBeNull();
    const cases: [Record<string, unknown>, string, string][] = [
      [{ block_length_mm: 150000 }, 'specification_value_out_of_range',
        'block_length_mm (distance between cross streets) is 150000; this schema admits 90000 to 140000 mm in steps of 10000'],
      [{ block_length_mm: 95000 }, 'specification_value_out_of_range', 'in steps of 10000'],
      [{ block_length_mm: '90000' }, 'specification_value_out_of_range', 'is "90000";'],
      [{ block_length_mm: 90000.5 }, 'specification_value_out_of_range', 'is 90000.5;'],
      [{ block_depth_mm: 52000 }, 'specification_value_unknown',
        'block_depth_mm: this schema fixes it at 56000: Measured: 56 m, so traffic compiles.'],
      [{ driving_side: 'left' }, 'specification_value_unknown', 'fixes it at "right"'],
      [{ grammar_id: 'city' }, 'specification_value_unknown', 'grammar_id: this schema states no value with that key'],
      [{ lamp_spacing_mm: 20000 }, 'specification_value_unknown', 'lamp_spacing_mm: this schema states no value with that key'],
    ];
    for (const [values, code, words] of cases) {
      const refusal = refusalOf(read, values);
      expect(refusal?.code, JSON.stringify(values)).toBe(code);
      expect(refusal?.key).toBe(Object.keys(values)[0]);
      expect(refusal?.detail).toContain(words);
    }
    // Keys are checked in the gate's order, so the first refusal is the gate's first.
    expect(refusalOf(read, { lamp_spacing_mm: 1, block_length_mm: 1 })?.key).toBe('block_length_mm');
  });

  it('refuses two values the document does not admit together, naming both, and narrows the range', () => {
    const read = parseWorldSpecification(servedSpecification());
    const length = read.values.find((value) => value.key === 'block_length_mm')!;
    expect(refusalOf(read, { city_extent_x_mm: 384000, block_length_mm: 130000 })).toBeNull();
    expect(refusalOf(read, { city_extent_x_mm: 256000, block_length_mm: 90000 })).toBeNull();
    const refused = refusalOf(read, { city_extent_x_mm: 384000, block_length_mm: 90000 });
    expect(refused).toEqual({
      code: 'specification_values_disagree',
      key: 'block_length_mm',
      detail: 'block_length_mm (distance between cross streets) is 90000 and city_extent_x_mm (length of the town, '
        + 'west to east) is 384000; with that value this schema admits 130000 to 140000 mm in steps of 10000: '
        + 'Measured: three tiles need long blocks.',
    });
    // A value's own range is checked before any pair.
    expect(refusalOf(read, { city_extent_x_mm: 384000, block_length_mm: 95000 })?.code).toBe('specification_value_out_of_range');
    // Two tiles take cross streets at most 120 m apart: the other span of the same value.
    expect(refusalOf(read, { city_extent_x_mm: 256000, block_length_mm: 130000 })?.detail).toContain(
      'with that value this schema admits 90000 to 120000 mm in steps of 10000: Measured: two tiles need short blocks.');
    expect(effectiveRange(length, { city_extent_x_mm: 384000 })).toEqual({ minimum: 130000, maximum: 140000, step: 10000 });
    expect(effectiveRange(length, { city_extent_x_mm: 256000 })).toEqual({ minimum: 90000, maximum: 120000, step: 10000 });
    expect(effectiveRange(length, {})).toEqual({ minimum: 90000, maximum: 140000, step: 10000 });
  });

  it('says a range as the gate says it', () => {
    const read = parseWorldSpecification(servedSpecification());
    const words = Object.fromEntries(read.values.map((value) => [value.key, rangeWords(value)]));
    expect(words['block_length_mm']).toBe('90000 to 140000 mm in steps of 10000');
    expect(words['block_depth_mm']).toBe('56000 mm, fixed');
    expect(words['driving_side']).toBe('one of right');
  });
});
