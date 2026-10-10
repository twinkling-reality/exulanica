import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { CONVERSATION_DISTANCE_METRES } from '../src/society-presentation.js';

/*
 * The page reads how far apart talkers are drawn from the catalog, never from a figure of its own:
 * the value here is read from the file again, by hand, and every entry states its reason.
 */
const CATALOG = JSON.parse(readFileSync(
  new URL('../../../../assets/catalogs/society-presentation/society-presentation.v1.json', import.meta.url), 'utf8',
)) as { profile: string; entries: { key: string; value: number; unit: string; class: string; reason: string }[] };

describe('the society presentation catalog', () => {
  it('states the conversation distance the page hands the crowd, in millimetres, with its reason', () => {
    const entry = CATALOG.entries.find((one) => one.key === 'conversation_distance_mm')!;
    expect(entry.unit).toBe('millimetre');
    expect(CONVERSATION_DISTANCE_METRES).toBe(entry.value / 1000);
    // A person is about half a metre deep: nearer than that and two bodies meet; a room's width is no talk.
    expect(CONVERSATION_DISTANCE_METRES).toBeGreaterThan(0.5);
    expect(CONVERSATION_DISTANCE_METRES).toBeLessThan(2);
  });

  it('gives every value a class and a reason', () => {
    expect(CATALOG.profile).toBe('exulanica.society-presentation/v1');
    for (const entry of CATALOG.entries) {
      expect(entry.class).toBe('chosen_default');
      expect(entry.reason.length).toBeGreaterThan(80);
    }
  });
});
