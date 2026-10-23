import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { FIRST_VIEW_DEFAULTS, TOWN_FIRST_VIEW, firstViewRule } from '../src/town-first-view.js';

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
    for (const version of [1, 2, 3, 4, 5]) {
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

  it('reads version 3 as version 2 with a least distance', () => {
    const v3 = entries(3);
    const rule = firstViewRule(file(3));
    expect(rule.life!.leastMm).toBe(v3.get('life_least_mm')!.value);
    expect(rule.life!.leastMm).toBeGreaterThan(0);
    // Every other value is version 2's own, unchanged.
    const before = entries(2);
    expect([...v3.keys()].filter((key) => key !== 'life_least_mm')).toEqual([...before.keys()]);
    for (const [key, entry] of before) expect([key, v3.get(key)!.value, v3.get(key)!.unit]).toEqual([key, entry.value, entry.unit]);
    expect(firstViewRule(file(2))).toEqual({ ...rule, life: { ...rule.life!, leastMm: 0 } });
  });

  it('reads version 4 as version 3 with the figures of the view of placed things', () => {
    const v4 = entries(4);
    const rule = firstViewRule(file(4));
    expect(rule.offLineBonus).toBeCloseTo(v4.get('off_line_bonus_milli')!.value / 1000, 12);
    expect(rule.placed).toEqual({
      stepMm: v4.get('placed_step_mm')!.value,
      stepsAlong: v4.get('placed_steps_along')!.value,
      stepsBack: v4.get('placed_steps_back')!.value,
      outReachMm: v4.get('placed_out_reach_mm')!.value,
      parkedClearanceMm: v4.get('parked_clearance_mm')!.value,
      parkedFartherMm: v4.get('parked_farther_mm')!.value,
    });
    // Every value version 3 states is version 3's own, unchanged.
    const before = entries(3);
    expect([...v4.keys()].slice(0, before.size)).toEqual([...before.keys()]);
    for (const [key, entry] of before) expect([key, v4.get(key)!.value, v4.get(key)!.unit]).toEqual([key, entry.value, entry.unit]);
    expect(rule.seafront).toBeUndefined();
    // Versions 1 to 3 are read with the figures as the page chose by them before version 4 stated them,
    // which are version 4's own: a town opens as it did.
    for (const version of [1, 2, 3]) {
      const older = firstViewRule(file(version));
      expect(older.offLineBonus).toBe(FIRST_VIEW_DEFAULTS.offLineBonus);
      expect(older.placed).toEqual(FIRST_VIEW_DEFAULTS.placed);
    }
    expect(firstViewRule(file(3))).toEqual(rule);
    // And a version 4 that states other figures is read by them.
    const other = (JSON.parse(file(4)) as { entries: Entry[] }).entries.map((entry) => (
      entry.key === 'placed_step_mm' ? { ...entry, value: 2_000 } : entry.key === 'off_line_bonus_milli' ? { ...entry, value: 0 } : entry));
    const read = firstViewRule(JSON.stringify({ ...JSON.parse(file(4)), entries: other }));
    expect([read.placed!.stepMm, read.offLineBonus]).toEqual([2_000, 0]);
  });

  it('reads version 5 as version 4 with a seafront view, and the page opens a town by it', () => {
    const v5 = entries(5);
    const rule = firstViewRule(file(5));
    expect(rule.seafront!.facingMost).toBeCloseTo(v5.get('seafront_facing_most_degrees')!.value * DEGREE, 12);
    expect(rule.seafront!.slant).toBeCloseTo(v5.get('seafront_slant_degrees')!.value * DEGREE, 12);
    expect(rule.seafront!.slant).toBeGreaterThan(rule.slant);
    // Its middle third, tested as dead ahead is: the third of a 102 degree frame reaches 22.4 degrees.
    expect(rule.middleThirdHalf).toBeCloseTo(v5.get('middle_third_half_degrees')!.value * DEGREE, 12);
    expect(rule.middleThirdHalf).toBeGreaterThanOrEqual(Math.atan(Math.tan(51 * DEGREE) / 3));
    expect(rule.middleThirdHalf).toBeGreaterThan(rule.life!.centreHalf);
    expect(rule.seafront!.frontStep).toBeCloseTo(v5.get('seafront_front_step_degrees')!.value * DEGREE, 12);
    expect(rule.seafront!.frontsLeast).toBe(v5.get('seafront_fronts_least')!.value);
    expect(rule.seafront!.frontLinesLeast).toBe(v5.get('seafront_front_lines_least')!.value);
    // Fronts are counted across the frame's half field, wider than the fan life is judged over.
    expect(rule.seafront!.frontHalf).toBeCloseTo(v5.get('seafront_front_half_degrees')!.value * DEGREE, 12);
    expect(rule.seafront!.frontHalf).toBeGreaterThan(rule.fanHalf);
    expect(rule.seafront!.alongMaximumMm).toBe(v5.get('seafront_along_maximum_mm')!.value);
    expect(rule.seafront!.alongMaximumMm).toBeGreaterThan(rule.alongMaximumMm);
    // It stands only where its open water fills a band of the frame's height across a share of its width.
    expect(rule.seafront!.water).toEqual({
      band: v5.get('seafront_water_band_thousandths')!.value / 1000,
      share: v5.get('seafront_water_share_thousandths')!.value / 1000,
      halfHeight: v5.get('seafront_water_half_height_degrees')!.value * DEGREE,
      stepMm: v5.get('seafront_water_step_mm')!.value,
    });
    // Every value version 4 states is version 4's own, unchanged.
    const before = entries(4);
    expect([...v5.keys()].slice(0, before.size)).toEqual([...before.keys()]);
    for (const [key, entry] of before) expect([key, v5.get(key)!.value, v5.get(key)!.unit]).toEqual([key, entry.value, entry.unit]);
    const { seafront: _seafront, middleThirdHalf: _third, ...versionFour } = rule;
    expect(firstViewRule(file(4))).toEqual(versionFour);
    expect(TOWN_FIRST_VIEW).toEqual(rule);
    // A version 5 that does not state its seafront slant is refused.
    const v5file = JSON.parse(file(5)) as { profile: string; entries: Entry[] };
    expect(() => firstViewRule(JSON.stringify({ ...v5file, entries: v5file.entries.filter((entry) => entry.key !== 'seafront_slant_degrees') })))
      .toThrow('seafront_slant_degrees');
    expect(() => firstViewRule(JSON.stringify({ ...v5file, entries: v5file.entries.map((entry) => (
      entry.key === 'middle_third_half_degrees' ? { ...entry, value: 90 } : entry)) }))).toThrow('cannot be held together');
    expect(() => firstViewRule(JSON.stringify({ ...v5file, entries: v5file.entries.map((entry) => (
      entry.key === 'seafront_front_step_degrees' ? { ...entry, value: 0 } : entry)) }))).toThrow('cannot be held together');
    expect(() => firstViewRule(JSON.stringify({ ...v5file, entries: v5file.entries.map((entry) => (
      entry.key === 'seafront_fronts_least' ? { ...entry, value: 2.5 } : entry)) }))).toThrow('cannot be held together');
    // Nor one without its water's figures, or with a band, a share or a field that cannot be measured by.
    expect(() => firstViewRule(JSON.stringify({ ...v5file, entries: v5file.entries.filter((entry) => entry.key !== 'seafront_water_share_thousandths') })))
      .toThrow('seafront_water_share_thousandths');
    for (const [key, value] of [
      ['seafront_water_band_thousandths', 0], ['seafront_water_band_thousandths', 1_000], ['seafront_water_share_thousandths', 0],
      ['seafront_water_share_thousandths', 1_001], ['seafront_water_half_height_degrees', 90], ['seafront_water_step_mm', 0],
    ] as const) {
      expect(() => firstViewRule(JSON.stringify({ ...v5file, entries: v5file.entries.map((entry) => (
        entry.key === key ? { ...entry, value } : entry)) }))).toThrow('cannot be held together');
    }
  });

  it('refuses a file of another profile, a version 2 missing a value, and distances that cannot hold together', () => {
    const v2 = JSON.parse(file(2)) as { profile: string; entries: Entry[] };
    expect(() => firstViewRule(JSON.stringify({ ...v2, profile: 'exulanica.town-first-view/v6' }))).toThrow('not a town first-view catalog');
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
    // A version 4 missing a figure of the view of placed things, or with a step of nothing or a part
    // of one, is refused.
    const v4 = JSON.parse(file(4)) as { profile: string; entries: Entry[] };
    expect(() => firstViewRule(JSON.stringify({ ...v4, entries: v4.entries.filter((entry) => entry.key !== 'placed_out_reach_mm') })))
      .toThrow('placed_out_reach_mm');
    const nothing = v4.entries.map((entry) => (entry.key === 'placed_step_mm' ? { ...entry, value: 0 } : entry));
    expect(() => firstViewRule(JSON.stringify({ ...v4, entries: nothing }))).toThrow('a step of nothing');
    const part = v4.entries.map((entry) => (entry.key === 'placed_steps_along' ? { ...entry, value: 2.5 } : entry));
    expect(() => firstViewRule(JSON.stringify({ ...v4, entries: part }))).toThrow('a part of a step');
    // A version 1 file is not asked for version 2's values, nor a version 2 file for a face distance.
    expect(() => firstViewRule(file(1))).not.toThrow();
    expect(entries(2).has('face_mm')).toBe(false);
  });
});
