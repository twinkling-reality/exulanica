import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { NEAR_CHARACTER_BUDGET } from '../src/playcanvas/character/budget.js';

/** Half of a 60 Hz frame for people, leaving the rest for the city, the society and slower machines. */
const WORK_BUDGET_MS = 8.3;
const LOG = new URL('./character-evidence/frame-budget-2026-09-17.log.txt', import.meta.url);

interface Configuration {
  readonly nearBudget: number;
  readonly crowd: number;
  readonly counts: { readonly near: number; readonly far: number; readonly pending: number; readonly unavailable: number };
  readonly visible: { readonly near: number; readonly far: number };
  readonly loadBefore: string;
  readonly frameP95Ms: number;
  readonly workP95Ms: number;
}

describe('the near character budget', () => {
  it('is the largest measured count whose frame work stays within half a 60 Hz frame on a quiet machine', () => {
    const lines = readFileSync(LOG, 'utf8').split('\n').filter((line) => line.startsWith('{'));
    const { environment } = JSON.parse(lines[0]!) as { environment: { canvas: number[] } };
    expect(environment.canvas).toEqual([1440, 900]);
    const runs = lines.slice(1).map((line) => JSON.parse(line) as Configuration);
    expect(runs.map((run) => run.nearBudget)).toEqual([0, 12, 24, 36, 48, 64]);
    for (const run of runs) {
      expect(Number(run.loadBefore.split(' ')[0]), `load before ${run.nearBudget}`).toBeLessThanOrEqual(8);
      expect(run.counts).toEqual({ near: run.nearBudget, far: run.crowd - run.nearBudget, pending: 0, unavailable: 0 });
      // Everyone measured was on screen, in the form the budget gave them.
      expect(run.visible).toEqual({ near: run.nearBudget, far: run.crowd - run.nearBudget });
    }
    const within = runs.filter((run) => run.workP95Ms <= WORK_BUDGET_MS && run.frameP95Ms <= 16.8);
    expect(NEAR_CHARACTER_BUDGET).toBe(Math.max(...within.map((run) => run.nearBudget)));
  });
});
