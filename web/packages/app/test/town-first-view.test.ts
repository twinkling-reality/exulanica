import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { TOWN_FIRST_VIEW, firstViewRule } from '../src/town-first-view.js';

/*
 * The town first-view catalogs, every version, through the page's one reader. Each expected value is
 * read here from the file's own entry, by its key, and carried into the rule's unit by hand.
 */
const file = (version: number): string =>
  readFileSync(new URL(`../../../../assets/catalogs/arrival/town-first-view.v${version}.json`, import.meta.url), 'utf8');
interface Entry { key: string; value: number; unit: string; class: string; reason: string }
const entries = (version: number): Map<string, Entry> =>
  new Map((JSON.parse(file(version)) as { entries: Entry[] }).entries.map((entry) => [entry.key, entry]));
const DEGREE = Math.PI / 180;

describe('the town first-view catalog', () => {
  it('states every value of every version once, as a chosen default with its reason', () => {
    for (const version of [1, 2, 3]) {
      const stated = (JSON.parse(file(version)) as { entries: Entry[] }).entries;
      expect(new Set(stated.map((entry) => entry.key)).size).toBe(stated.length);
      for (const entry of stated) {
        expect(entry.class).toBe('chosen_default');
        expect(entry.reason.length).toBeGreaterThan(40);
        expect(Number.isFinite(entry.value) && entry.value >= 0).toBe(true);
      }
    }
  });

  it('reads version 1 as it always was: by openness, with a face distance and no judging by life', () => {
    const v1 = entries(1);
    const rule = firstViewRule(file(1));
    expect(rule.life).toBeUndefined();
    expect(rule.faceMm).toBe(v1.get('face_mm')!.value);
    expect(rule.slant).toBeCloseTo(v1.get('slant_degrees')!.value * DEGREE, 12);
    expect(rule.fanHalf).toBeCloseTo(v1.get('fan_half_degrees')!.value * DEGREE, 12);
    expect(rule.sightLines).toBe(v1.get('sight_lines')!.value);
    expect(rule.reachMm).toBe(v1.get('reach_mm')!.value);
    expect([rule.backStepMm, rule.backMaximumMm, rule.alongStepMm, rule.alongMaximumMm]).toEqual(
      ['back_step_mm', 'back_maximum_mm', 'along_step_mm', 'along_maximum_mm'].map((key) => v1.get(key)!.value));
    expect(rule.tie).toBeCloseTo(v1.get('tie_milli')!.value / 1000, 12);
  });

  it('reads version 2 with how life is judged, each value in the rule\'s unit', () => {
    const v2 = entries(2);
    const rule = firstViewRule(file(2));
    expect(rule.faceMm).toBe(0);
    expect(rule.slant).toBeCloseTo(v2.get('slant_degrees')!.value * DEGREE, 12);
    expect(rule.life).toBeDefined();
    const life = rule.life!;
    expect(life.nearMm).toBe(v2.get('life_near_mm')!.value);
    expect(life.farMm).toBe(v2.get('life_far_mm')!.value);
    expect(life.seatWeight).toBeCloseTo(v2.get('seat_weight_milli')!.value / 1000, 12);
    expect(life.tie).toBeCloseTo(v2.get('life_tie_milli')!.value / 1000, 12);
    expect(life.sightMarginMm).toBe(v2.get('sight_margin_mm')!.value);
    expect(life.centreHalf).toBeCloseTo(v2.get('centre_half_degrees')!.value * DEGREE, 12);
    expect(life.centreFloorMm).toBe(v2.get('centre_floor_mm')!.value);
    expect([life.seatTopMinimumMm, life.seatTopMaximumMm, life.seatSpanMinimumMm]).toEqual(
      ['seat_top_minimum_mm', 'seat_top_maximum_mm', 'seat_span_minimum_mm'].map((key) => v2.get(key)!.value));
    // Version 2 states no least distance: a seat counts however near, as it did.
    expect(life.leastMm).toBe(0);
    expect(v2.has('life_least_mm')).toBe(false);
  });

  it('reads version 3 as version 2 with a least distance, and it is the one the page opens a town by', () => {
    const v3 = entries(3);
    const rule = firstViewRule(file(3));
    expect(rule.life!.leastMm).toBe(v3.get('life_least_mm')!.value);
    expect(rule.life!.leastMm).toBeGreaterThan(0);
    // Every other value is version 2's own, unchanged.
    const before = entries(2);
    expect([...v3.keys()].filter((key) => key !== 'life_least_mm')).toEqual([...before.keys()]);
    for (const [key, entry] of before) expect([key, v3.get(key)!.value, v3.get(key)!.unit]).toEqual([key, entry.value, entry.unit]);
    expect(firstViewRule(file(2))).toEqual({ ...rule, life: { ...rule.life!, leastMm: 0 } });
    expect(TOWN_FIRST_VIEW).toEqual(rule);
  });

  it('refuses a file of another profile, a version 2 missing a value, and distances that cannot hold together', () => {
    const v2 = JSON.parse(file(2)) as { profile: string; entries: Entry[] };
    expect(() => firstViewRule(JSON.stringify({ ...v2, profile: 'exulanica.town-first-view/v4' }))).toThrow('not a town first-view catalog');
    expect(() => firstViewRule(JSON.stringify({ ...v2, entries: v2.entries.filter((entry) => entry.key !== 'centre_floor_mm') })))
      .toThrow('centre_floor_mm');
    const swapped = v2.entries.map((entry) => (entry.key === 'life_far_mm' ? { ...entry, value: 20_000 } : entry));
    expect(() => firstViewRule(JSON.stringify({ ...v2, entries: swapped }))).toThrow('cannot be held together');
    // A version 3 with no least distance, or one at or beyond the near distance, is refused too.
    const v3 = JSON.parse(file(3)) as { profile: string; entries: Entry[] };
    expect(() => firstViewRule(JSON.stringify({ ...v3, entries: v3.entries.filter((entry) => entry.key !== 'life_least_mm') })))
      .toThrow('life_least_mm');
    const far = v3.entries.map((entry) => (entry.key === 'life_least_mm' ? { ...entry, value: 25_000 } : entry));
    expect(() => firstViewRule(JSON.stringify({ ...v3, entries: far }))).toThrow('cannot be held together');
    // A version 1 file is not asked for version 2's values, nor a version 2 file for a face distance.
    expect(() => firstViewRule(file(1))).not.toThrow();
    expect(entries(2).has('face_mm')).toBe(false);
  });
});
