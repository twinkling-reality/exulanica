// The page parses the documents the server serves for a comparison of models: the golden in
// tests/snapshots/society-comparison-documents.json is what the server served in the backend's
// own test (tests/test_society_comparison_postgres.py holds every served document to its keys).
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  parseComparison,
  parseComparisons,
  parseRunReplay,
  SocietyComparisonClient,
} from '../src/society-comparison-api.js';

const REPOSITORY = new URL('../../../../', import.meta.url);
const golden = JSON.parse(
  readFileSync(new URL('tests/snapshots/society-comparison-documents.json', REPOSITORY), 'utf8'),
) as { readonly listing: unknown; readonly result: Record<string, unknown>; readonly run: Record<string, unknown> };

describe('the documents of a comparison of models', () => {
  it('reads the listing, the result and a replayed run exactly as the server served them', () => {
    const [listing] = parseComparisons(golden.listing);
    expect(listing!.arms.map((arm) => arm.role)).toEqual(['candidate', 'candidate', 'one', 'zero']);
    expect(listing!.runsCompleted).toBe(listing!.runsExpected);

    const result = parseComparison(golden.result);
    expect(result.verdict).toEqual({ code: 'not_judged', higher: null, reason: 'development_seeds' });
    expect(result.summaries['routine']!.meanScore).toBe('1.0000');
    expect(result.summaries['wait']!.meanScore).toBe('0.0000');
    expect(result.seeds.length).toBeGreaterThan(1);

    const run = parseRunReplay(golden.run);
    expect(run.arm).toBe('model_a');
    expect(run.minutes[0]!.tick).toBe(0);
    expect(run.activities.map((activity) => activity.kind)).toContain('rest');
    expect(run.people.length).toBe(run.minutes[0]!.people.length);
  });

  it('keeps a score as the server wrote it, below zero or above one, never clipped', () => {
    const result = structuredClone(golden.result) as Record<string, unknown>;
    const summaries = result['summaries'] as Record<string, Record<string, unknown>>;
    summaries['model_a']!['mean_score'] = '-0.2500';
    summaries['model_b']!['mean_score'] = '1.2500';
    const read = parseComparison(result);
    expect(read.summaries['model_a']!.meanScore).toBe('-0.2500');
    expect(read.summaries['model_b']!.meanScore).toBe('1.2500');
  });

  it('refuses a run the server did not verify by replaying it, and a verdict it does not know', () => {
    expect(() => parseRunReplay({ ...golden.run, replay_verified: false })).toThrow();
    expect(() => parseComparison({ ...golden.result, verdict: { code: 'better', higher: null, reason: null } }))
      .toThrow();
    // A registered pair must name the comparison's own arms.
    expect(() => parseComparison({ ...golden.result, primary: ['model_a', 'model_z'] })).toThrow();
    // A model the server did not name is refused: the page never makes up a name for one.
    const unnamed = structuredClone(golden.result) as { arms: { decider: Record<string, unknown> }[] };
    delete unnamed.arms.find((arm) => arm.decider['kind'] === 'model')!.decider['name'];
    expect(() => parseComparison(unnamed)).toThrow();
  });

  it('sends nothing without an open world, and reads each document by its own path', async () => {
    const asked: string[] = [];
    const fetch = (async (input: RequestInfo | URL) => {
      asked.push(String(input));
      const url = String(input);
      const body = url.includes('/runs/') ? golden.run : url.endsWith('/comparisons?world_id=world%3Aauthored%3Ax')
        ? golden.listing : golden.result;
      return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
    }) as typeof globalThis.fetch;
    const closed = new SocietyComparisonClient({ baseUrl: 'http://api.test', token: 'test-token', fetch, worldId: null });
    await expect(closed.list('v')).rejects.toThrow();
    expect(asked).toEqual([]);
    const open = new SocietyComparisonClient({ baseUrl: 'http://api.test', token: 'test-token', fetch, worldId: 'world:authored:x' });
    await open.list('v');
    await open.read('v', 'c');
    await open.run('v', 'c', 'r');
    expect(asked.map((url) => new URL(url).pathname)).toEqual([
      '/world/versions/v/society/comparisons',
      '/world/versions/v/society/comparisons/c',
      '/world/versions/v/society/comparisons/c/runs/r',
    ]);
  });
});
