import { describe, expect, it } from 'vitest';
import {
  atlasVec3,
  buildNeighborhoodIndex,
  islandId,
  localVec3,
  makeIsland,
  makeScene,
  placement,
  planResidency,
  residencyDemandsForView,
  type ResidencyAsset,
  type ResidencyDemand,
} from '../src/index.js';

/**
 * The pressure controller's level 3 caps every demanded region at its stub. Measured 2026-09-06
 * and recorded in docs/evaluation/2026-09-06-phase-10-atlas.json: the trained bowl stopped being
 * drawn about thirteen seconds after arrival, because the region the visitor was standing in was
 * capped along with everything else. A ceiling on what may be LOADED is not a reason to release
 * what is already under the visitor's feet, so the occupied region is exempt and every other
 * region keeps staging down.
 */

// The real trained-region cost from atlas-binding.ts: flat at every drawn stage, and above the
// level-3 budget of 96 * 0.22 = 21.12, so the stage ceiling is not the only thing that stubs it.
const trained = (id: string): ResidencyAsset => ({
  islandId: islandId(id),
  cost: { stub: 0, proxy: 24, coarse: 24, full: 24 },
});
const cheap = (id: string): ResidencyAsset => ({
  islandId: islandId(id),
  cost: { stub: 0, proxy: 2, coarse: 5, full: 10 },
});
const demand = (
  id: string,
  desired: ResidencyDemand['desired'],
  priority: number,
  extra: Partial<ResidencyDemand> = {},
): ResidencyDemand => ({ islandId: islandId(id), desired, priority, ...extra });

const LEVEL_3_BUDGET = 96 * 0.22;

describe('the region the visitor occupies', () => {
  it('stays drawn when the pressure ceiling is stub, while other regions stage down', () => {
    const plan = planResidency(
      [trained('here'), cheap('next'), cheap('far')],
      [
        demand('here', 'full', 203, { occupied: true }),
        demand('next', 'coarse', 201),
        demand('far', 'proxy', 50),
      ],
      { maxCost: LEVEL_3_BUDGET, maxStage: 'stub' },
    );
    expect(plan.allocated.get(islandId('here'))).not.toBe('stub');
    expect(plan.allocated.get(islandId('next'))).toBe('stub');
    expect(plan.allocated.get(islandId('far'))).toBe('stub');
  });

  it('clears the scaled budget too, since a trained region costs more than level 3 allows', () => {
    const plan = planResidency(
      [trained('here')],
      [demand('here', 'full', 203, { occupied: true })],
      { maxCost: LEVEL_3_BUDGET, maxStage: 'stub' },
    );
    // 24 does not fit 21.12 at any drawn stage, so the descent finds nothing and the floor applies.
    expect(plan.allocated.get(islandId('here'))).toBe('proxy');
    expect(plan.reservedCost).toBe(24);
  });

  it('takes the best stage the budget affords rather than always dropping to the floor', () => {
    const plan = planResidency(
      [cheap('here')],
      [demand('here', 'full', 203, { occupied: true })],
      { maxCost: 6, maxStage: 'stub' },
    );
    expect(plan.allocated.get(islandId('here'))).toBe('coarse');
  });

  it('does not draw a region the tier itself puts at stub', () => {
    const plan = planResidency(
      [cheap('here')],
      [demand('here', 'stub', 200, { occupied: true })],
      { maxCost: 96 },
    );
    expect(plan.allocated.get(islandId('here'))).toBe('stub');
  });

  it('keeps the exemption when the occupied region is also the navigation pin', () => {
    const plan = planResidency(
      [trained('here')],
      [
        demand('here', 'full', 203, { occupied: true }),
        demand('here', 'proxy', 10_000, { pin: true }),
      ],
      { maxCost: LEVEL_3_BUDGET, maxStage: 'stub' },
    );
    expect(plan.allocated.get(islandId('here'))).not.toBe('stub');
  });
});

const island = (id: string, x: number, ordinal: number) => makeIsland({
  islandId: islandId(id),
  creationOrdinal: ordinal,
  createdAt: ordinal,
  placement: placement(atlasVec3(x, 0, 0), 0, 1),
  rung: 4,
  scaleIsMetric: false,
  footprintRadiusLocal: 3,
  viewpointLocal: localVec3(0, 1.6, 0),
  anchors: [],
  layoutEntities: new Set(['shared' as never]),
});

describe('residencyDemandsForView', () => {
  const index = buildNeighborhoodIndex(
    makeScene([island('r0', 0, 0), island('r1', 100, 1)], 1, 1),
    { capacity: 2 },
  );
  const active = index.neighborhoodOf.get(islandId('r0'))!;

  it('marks the occupied region and leaves its neighbours unmarked', () => {
    const demands = residencyDemandsForView(index, {
      map: false,
      activeNeighborhood: active,
      tier: { tier: new Map([[islandId('r0'), 3], [islandId('r1'), 2]]) },
      target: null,
      occupied: islandId('r0'),
    });
    expect(demands.find((value) => value.islandId === islandId('r0'))?.occupied).toBe(true);
    expect(demands.find((value) => value.islandId === islandId('r1'))?.occupied).toBeUndefined();
  });

  it('demands the occupied region even when it is outside the active neighborhood', () => {
    const demands = residencyDemandsForView(index, {
      map: false,
      activeNeighborhood: null,
      tier: { tier: new Map([[islandId('r0'), 3]]) },
      target: null,
      occupied: islandId('r0'),
    });
    const occupied = demands.find((value) => value.islandId === islandId('r0'));
    expect(occupied?.occupied).toBe(true);
    expect(occupied?.desired).toBe('full');
  });

  it('marks nothing while the visitor is between regions', () => {
    const demands = residencyDemandsForView(index, {
      map: false,
      activeNeighborhood: active,
      tier: { tier: new Map([[islandId('r0'), 3]]) },
      target: null,
      occupied: null,
    });
    expect(demands.some((value) => value.occupied === true)).toBe(false);
  });
});

describe('an occupied region the index does not know', () => {
  const index = buildNeighborhoodIndex(
    makeScene([island('r0', 0, 0), island('r1', 100, 1)], 1, 1),
    { capacity: 2 },
  );
  const active = index.neighborhoodOf.get(islandId('r0'))!;

  it('is ignored rather than demanded, because planResidency has no catalog asset for it', () => {
    const demands = residencyDemandsForView(index, {
      map: false,
      activeNeighborhood: active,
      tier: { tier: new Map([[islandId('r0'), 3]]) },
      target: null,
      occupied: islandId('not-in-this-scene'),
    });
    expect(demands.some((value) => value.islandId === islandId('not-in-this-scene'))).toBe(false);
    expect(() => planResidency(
      [cheap('r0'), cheap('r1')],
      demands,
      { maxCost: 96, maxStage: 'stub' },
    )).not.toThrow();
  });
});
