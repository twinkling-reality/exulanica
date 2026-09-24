/**
 * The binding may shrink and may not grow, and its public surface changes only on purpose.
 *
 * The line budget is a ratchet: the file may not exceed it, and once the file is more than
 * `SLACK` lines under it the budget must come down to meet it, so lines taken out cannot quietly
 * come back. `atlas-binding.ts` regrew around one lifecycle after every earlier split; the
 * budget is what stops that recurring. Lower `ATLAS_BINDING_LINE_BUDGET` in the same change that
 * moves code out.
 *
 * The playcanvas barrel is the binding package's public surface. Its exported names are listed
 * here, so adding or removing one is a visible change.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import * as barrel from '../../src/playcanvas/index.js';

/** Lines in atlas-binding.ts, measured on the file this budget was last lowered with. */
const ATLAS_BINDING_LINE_BUDGET = 3321;
/** How far under budget the file may drift before the budget must be lowered to follow it. */
const SLACK = 40;

const BINDING = new URL('../../src/playcanvas/atlas-binding.ts', import.meta.url);

describe('the binding line budget', () => {
  it('holds atlas-binding.ts at or under its budget, and the budget within reach of the file', () => {
    const lines = readFileSync(BINDING, 'utf8').split('\n').length - 1;
    expect(lines).toBeGreaterThan(0);
    expect(lines, 'atlas-binding.ts grew past its budget: move code out instead').toBeLessThanOrEqual(ATLAS_BINDING_LINE_BUDGET);
    expect(ATLAS_BINDING_LINE_BUDGET - lines, 'the file shrank: lower the budget to meet it')
      .toBeLessThanOrEqual(SLACK);
  });
});

describe('the playcanvas barrel', () => {
  it('exports exactly the pinned names', async () => {
    const names = Object.keys(barrel).sort();
    await expect(`${names.join('\n')}\n`).toMatchFileSnapshot('pins/barrel-exports.txt');
  });
});
