import { describe, expect, it } from 'vitest';
import {
  RepresentationPressureController,
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
  type TierState,
} from '@exulanica/atlas-core';
import {
  TRAINED_REGION_RESIDENCY_COST,
  residencyFrameInputs,
} from '../src/playcanvas/atlas-binding.js';

/**
 * The binding half of the same defect. The occupied region is already computed as
 * `classifySpatialPhase(...).islandId` twenty-five lines above the plan call; it just never
 * reached the residency inputs, and it was absent from the replan signature, so a region crossing
 * inside one neighborhood could not revisit a plan that had stubbed the region under the visitor.
 */

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

const index = buildNeighborhoodIndex(
  makeScene([island('here', 0, 0), island('next', 100, 1)], 1, 1),
  { capacity: 2 },
);
const neighborhood = index.neighborhoodOf.get(islandId('here'))!;
const tier: TierState = {
  tier: new Map([[islandId('here'), 3], [islandId('next'), 3]] as const),
};

const catalog: ResidencyAsset[] = [
  { islandId: islandId('here'), cost: TRAINED_REGION_RESIDENCY_COST },
  { islandId: islandId('next'), cost: TRAINED_REGION_RESIDENCY_COST },
];

/** Drive the controller to level 3 the way a slow machine does: overloaded 60-frame windows. */
function pressuredToLevel3(): RepresentationPressureController {
  const controller = new RepresentationPressureController();
  for (let frame = 0; frame < 60 * 6; frame += 1) controller.record({ frameTimeMs: 30 });
  return controller;
}

/** The one predicate in applyResidencyPresentation that decides whether a splat is drawn. */
const drawn = (stage: string | undefined): boolean => stage !== 'stub';

describe('residencyFrameInputs', () => {
  it('carries the occupied region into the view', () => {
    const { view } = residencyFrameInputs({
      map: false,
      activeNeighborhood: neighborhood,
      tier,
      target: null,
      occupied: islandId('here'),
    });
    expect(view.occupied).toBe(islandId('here'));
  });

  it('replans on a region crossing inside one neighborhood at unchanged tiers', () => {
    const base = {
      map: false,
      activeNeighborhood: neighborhood,
      tier,
      target: null,
    };
    const before = residencyFrameInputs({ ...base, occupied: islandId('here') });
    const after = residencyFrameInputs({ ...base, occupied: islandId('next') });
    expect(before.signature).not.toBe(after.signature);
  });

  it('does not replan when nothing spatial changed', () => {
    const input = {
      map: false,
      activeNeighborhood: neighborhood,
      tier,
      target: null,
      occupied: islandId('here'),
    };
    expect(residencyFrameInputs(input).signature).toBe(residencyFrameInputs(input).signature);
  });
});

describe('a trained scene under representation pressure', () => {
  it('keeps drawing the region the visitor stands in at pressure level 3', () => {
    const pressure = pressuredToLevel3();
    expect(pressure.state.level).toBe(3);
    expect(pressure.state.maxStage).toBe('stub');

    const { view } = residencyFrameInputs({
      map: false,
      activeNeighborhood: neighborhood,
      tier,
      target: null,
      occupied: islandId('here'),
    });
    const plan = planResidency(catalog, residencyDemandsForView(index, view), {
      maxCost: 96 * pressure.state.budgetScale,
      maxStage: pressure.state.maxStage,
    });

    expect(drawn(plan.allocated.get(islandId('here')))).toBe(true);
    // The saving still comes from everywhere else.
    expect(drawn(plan.allocated.get(islandId('next')))).toBe(false);
  });

  it('still stubs every region once the visitor is between them', () => {
    const pressure = pressuredToLevel3();
    const { view } = residencyFrameInputs({
      map: false,
      activeNeighborhood: neighborhood,
      tier,
      target: null,
      occupied: null,
    });
    const plan = planResidency(catalog, residencyDemandsForView(index, view), {
      maxCost: 96 * pressure.state.budgetScale,
      maxStage: pressure.state.maxStage,
    });
    expect(drawn(plan.allocated.get(islandId('here')))).toBe(false);
    expect(drawn(plan.allocated.get(islandId('next')))).toBe(false);
  });
});
