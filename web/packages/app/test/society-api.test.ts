import { describe, expect, it } from 'vitest';
import { parseSociety } from '../src/society-api.js';

describe('society browser contract', () => {
  it('accepts at least one hundred explicitly synthetic inhabitants', () => {
    const inhabitants = Array.from({ length: 128 }, (_, ordinal) => ({
      id: `synthetic-${ordinal}`,
      synthetic: true,
      position_mm: [ordinal, -ordinal],
    }));
    const snapshot = parseSociety({
      society_id: 'society',
      version_id: 'version',
      place_id: 'place',
      population_size: 128,
      current_tick: 42,
      state_sha256: 'a'.repeat(64),
      state: { tick: 42, inhabitants },
    });
    expect(snapshot.populationSize).toBe(128);
    expect(snapshot.state.inhabitants).toHaveLength(128);
  });

  it('rejects an undersized crowd', () => {
    expect(() => parseSociety({
      society_id: 'society',
      version_id: 'version',
      place_id: 'place',
      population_size: 99,
      current_tick: 0,
      state_sha256: 'a'.repeat(64),
      state: { tick: 0, inhabitants: [] },
    })).toThrow(/Invalid society/);
  });
});
