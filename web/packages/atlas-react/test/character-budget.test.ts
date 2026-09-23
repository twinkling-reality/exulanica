import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { NEAR_CHARACTER_BUDGET, NEAR_INHABITANT_BUDGET, PLAYER_NEAR_PLACES } from '../src/playcanvas/character/budget.js';

/** Half of a 60 Hz frame for people, leaving the rest for the city, the society and slower machines. */
const WORK_BUDGET_MS = 8.3;
/** Presented frames still at 60 Hz: the 95th percentile interval of a 60 Hz display, as measured. */
const PRESENTED_P95_MS = 16.8;
/** The machine-wide timing gate: CPU idle percent before a configuration, and while it was measured. */
const IDLE_BEFORE = 70;
const IDLE_DURING = 50;
/** Accepted repeats a count needs before it can decide the budget. */
const REPEATS = 2;
const EVIDENCE = new URL('./character-evidence/', import.meta.url);
const LOG = new URL('frame-budget-production-2026-09-23.log.txt', EVIDENCE);

interface Environment {
  readonly canvas: readonly number[];
  readonly engine: { readonly playcanvasBuildDirectories: readonly string[]; readonly mode: string };
  readonly cameraMode: string;
}

interface Configuration {
  readonly nearBudget: number;
  readonly crowd: number;
  readonly verdict: string;
  readonly counts: { readonly near: number; readonly far: number; readonly pending: number; readonly unavailable: number };
  readonly visible: { readonly near: number; readonly far: number };
  readonly preIdle: readonly number[];
  readonly idleDuring: { readonly mean: number };
  readonly frameP95Ms: number;
  readonly workP95Ms: number;
}

const lines = readFileSync(LOG, 'utf8').split('\n').filter((line) => line.startsWith('{')).map((line) => JSON.parse(line) as Record<string, unknown>);
const fits = (run: Configuration) => run.workP95Ms <= WORK_BUDGET_MS && run.frameP95Ms <= PRESENTED_P95_MS;

describe('the near character budget', () => {
  it('was measured by the harness retained beside it, on a production build, with the player drawn in full', () => {
    const harness = lines.find((line) => line['harness'])!['harness'] as Record<string, { retained: string; sha256: string }>;
    expect(Object.keys(harness).length).toBeGreaterThan(0);
    for (const { retained, sha256 } of Object.values(harness)) {
      expect(createHash('sha256').update(readFileSync(new URL(retained, EVIDENCE))).digest('hex'), retained).toBe(sha256);
    }
    const environments = lines.flatMap((line) => (line['environment'] ? [line['environment'] as Environment] : []));
    expect(environments.length).toBeGreaterThanOrEqual(REPEATS);
    for (const environment of environments) {
      expect(environment.canvas).toEqual([1440, 900]);
      // The release engine, as a production build bundles it; a development server serves `playcanvas.dbg`.
      expect(environment.engine).toEqual({ playcanvasBuildDirectories: ['playcanvas'], mode: 'production' });
      // Third person: the player's own body is one of the people drawn in full.
      expect(environment.cameraMode).toBe('third-person');
    }
  });

  it('is the largest count every accepted repeat of which fits half a 60 Hz frame, and the next count does not', () => {
    const accepted = lines.filter((line) => line['verdict'] === 'accepted') as unknown as Configuration[];
    for (const run of accepted) {
      expect(run.preIdle.at(-1)!, `idle before ${run.nearBudget}`).toBeGreaterThanOrEqual(IDLE_BEFORE);
      expect(run.idleDuring.mean, `idle during ${run.nearBudget}`).toBeGreaterThanOrEqual(IDLE_DURING);
      expect(run.counts).toEqual({ near: run.nearBudget, far: run.crowd - run.nearBudget, pending: 0, unavailable: 0 });
      // Everyone measured was on screen, in the form the budget gave them.
      expect(run.visible).toEqual({ near: run.nearBudget, far: run.crowd - run.nearBudget });
    }
    const byCount = new Map<number, Configuration[]>();
    for (const run of accepted) byCount.set(run.nearBudget, [...(byCount.get(run.nearBudget) ?? []), run]);
    const decided = [...byCount].filter(([, runs]) => runs.length >= REPEATS).sort(([a], [b]) => a - b);
    const within = decided.filter(([, runs]) => runs.every(fits)).map(([count]) => count);
    // The crowd's full people, measured beside the player's own body.
    expect(NEAR_INHABITANT_BUDGET).toBe(Math.max(...within));
    expect(NEAR_CHARACTER_BUDGET).toBe(NEAR_INHABITANT_BUDGET + PLAYER_NEAR_PLACES);
    // Every smaller decided count fits too, so the answer is not a lucky repeat.
    for (const [count, runs] of decided) if (count < NEAR_INHABITANT_BUDGET) expect(runs.every(fits), `${count}`).toBe(true);
    // The next decided count above does not fit, so the budget is not an unmeasured guess.
    const above = decided.find(([count]) => count > NEAR_INHABITANT_BUDGET);
    expect(above).toBeDefined();
    expect(above![1].some((run) => !fits(run))).toBe(true);
  });
});
