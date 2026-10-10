import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { DECIDER_MARKS, deciderMarkRule } from '../src/decider-marks.js';

/*
 * The decider marks catalog through the page's reader. Each expected value is read here from the
 * file's own entry, by its key, and carried into the rule's unit by hand.
 */
const text = readFileSync(new URL('../../../../assets/catalogs/thing-presentation/decider-marks.v1.json', import.meta.url), 'utf8');
interface Entry { key: string; value: number; unit: string; class: string; reason: string }
const document = JSON.parse(text) as { profile: string; entries: Entry[] };
const entries = new Map(document.entries.map((entry) => [entry.key, entry]));

describe('the decider marks catalog', () => {
  it('states every value once, with a class and a reason, and none as a count of beings', () => {
    expect(new Set(document.entries.map((entry) => entry.key)).size).toBe(document.entries.length);
    for (const entry of document.entries) {
      expect(['chosen_default', 'chosen_budget', 'measured_cost']).toContain(entry.class);
      expect(entry.reason.length).toBeGreaterThan(60);
      expect(entry.value).toBeGreaterThan(0);
    }
    // What is drawn is bounded by letters, by a being's size on the screen and by a share of the
    // view: the only count is of lines of speech open at once, a budget of reading.
    expect(document.entries.filter((entry) => entry.unit === 'count').map((entry) => entry.key)).toEqual(['lines_at_once']);
    expect(entries.get('screen_share_milli')!.class).toBe('chosen_budget');
  });

  it('is read into the rule the overlay is drawn by, each value in the rule\'s unit', () => {
    const rule = deciderMarkRule(text);
    expect(rule.nameLeastPx).toBe(entries.get('name_least_px')!.value);
    expect(rule.beingLeastPx).toBe(entries.get('being_least_px')!.value);
    expect(rule.screenShare).toBeCloseTo(entries.get('screen_share_milli')!.value / 1000, 12);
    expect(rule.linesAtOnce).toBe(entries.get('lines_at_once')!.value);
    expect([rule.lineBaseMs, rule.linePerCharacterMs, rule.lineMostMs]).toEqual(
      ['line_base_ms', 'line_per_character_ms', 'line_most_ms'].map((key) => entries.get(key)!.value));
    expect(DECIDER_MARKS).toEqual(rule);
    // The floor a person asked for: a name is never under 14 px.
    expect(rule.nameLeastPx).toBeGreaterThanOrEqual(14);
  });

  it('refuses a file of another profile, one missing a value, one with no class, and a share above the whole view', () => {
    expect(() => deciderMarkRule(JSON.stringify({ ...document, profile: 'exulanica.decider-marks/v2' }))).toThrow('not the decider marks catalog');
    expect(() => deciderMarkRule(JSON.stringify({ ...document, entries: document.entries.filter((entry) => entry.key !== 'name_least_px') })))
      .toThrow('name_least_px');
    const unclassed = document.entries.map((entry) => (entry.key === 'being_least_px' ? { ...entry, class: 'leftover' } : entry));
    expect(() => deciderMarkRule(JSON.stringify({ ...document, entries: unclassed }))).toThrow('being_least_px');
    const whole = document.entries.map((entry) => (entry.key === 'screen_share_milli' ? { ...entry, value: 1001 } : entry));
    expect(() => deciderMarkRule(JSON.stringify({ ...document, entries: whole }))).toThrow('cannot be held');
    const shorter = document.entries.map((entry) => (entry.key === 'line_most_ms' ? { ...entry, value: 1000 } : entry));
    expect(() => deciderMarkRule(JSON.stringify({ ...document, entries: shorter }))).toThrow('cannot be held');
  });
});
