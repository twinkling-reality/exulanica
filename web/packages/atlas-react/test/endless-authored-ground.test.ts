import { describe, expect, it } from 'vitest';
import {
  DEFAULT_EYE_HEIGHT_AU,
  INITIAL_RENDER_ORIGIN,
  RECOVERY_MARGIN_AU,
  atlasVec3,
  buildNavigationWorld,
  buildNeighborhoodIndex,
  makeScene,
  renderOriginForNeighborhood,
  resolveGroundMovement,
  type AtlasVec3,
  type NavigationWorld,
} from '@exulanica/atlas-core';
import {
  AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M,
  authoredGroundSurface,
  endlessAuthoredNavigation,
} from '../src/playcanvas/world-kind.js';

/**
 * A ground that states it has no extent, and the distance this renderer can honestly carry a
 * person across one.
 *
 * The descriptor says there is no edge. That is a fact about the world. How far a person can
 * actually walk is a fact about the pipeline drawing it, and these tests measure it rather than
 * repeating a number from the source: the float32 step is read out of the bits, and the walk is
 * run through the real movement resolver one frame at a time.
 */

const RADIUS = AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M;
const ENDLESS = { kind: 'endless', elevationMm: 0 } as const;
const BOUNDED = { kind: 'flat', halfWidthMm: 12_000, halfDepthMm: 12_000, elevationMm: 0 } as const;

/** The gap between one 32-bit float and the next at `value`: what a drawn position rounds to. */
function float32Step(value: number): number {
  const floats = new Float32Array(2);
  const bits = new Uint32Array(floats.buffer);
  floats[0] = value;
  floats[1] = value;
  bits[1] = bits[1]! + 1;
  return floats[1]! - floats[0]!;
}

function endlessWorld(): NavigationWorld {
  return endlessAuthoredNavigation(
    buildNavigationWorld(makeScene([], 1, 1), authoredGroundSurface(ENDLESS)),
  );
}

describe('the float32 limit the supported radius is taken from', () => {
  it('still resolves one millimetre at the supported radius and stops resolving it past there', () => {
    expect(float32Step(RADIUS)).toBeLessThan(0.001);
    expect(float32Step(RADIUS * 2)).toBeGreaterThan(0.001);
  });

  it('measures the step the drawn position rounds to across the walk', () => {
    const steps = [1, 256, 2048, RADIUS / 2, RADIUS].map(float32Step);
    expect(steps.every((step) => step < 0.001)).toBe(true);
    // Monotonic by exponent: the last stretch of the walk is the coarsest part of it.
    expect(steps[steps.length - 1]).toBeGreaterThan(steps[0]!);
  });

  it('never rebases the render origin in a world whose scene holds no regions', () => {
    /*
     * This is why the float32 step above is measured from the world origin rather than from a
     * moving one. The origin only follows the active neighborhood, neighborhoods are built from
     * scene regions, and a starter world has none, so the whole walk is drawn at its true
     * distance.
     */
    const scene = makeScene([], 1, 1);
    const neighborhoods = buildNeighborhoodIndex(scene);
    expect(neighborhoods.neighborhoods).toHaveLength(0);
    let origin = INITIAL_RENDER_ORIGIN;
    for (const active of [null, null, null]) {
      origin = renderOriginForNeighborhood(scene, neighborhoods, active, origin);
    }
    expect(origin).toBe(INITIAL_RENDER_ORIGIN);
    expect(origin.origin).toEqual(atlasVec3(0, 0, 0));
  });
});

describe('the walking surface an authored ground states', () => {
  it('answers everywhere out to the supported radius', () => {
    const surface = authoredGroundSurface(ENDLESS);
    for (const distance of [0, 24, 90, 138, 1_000, RADIUS - 1, RADIUS]) {
      expect(surface.sample(distance, 0), `at ${distance} m`).toEqual({
        height: 0,
        normal: { x: 0, y: 1, z: 0 },
      });
      expect(surface.sample(0, -distance), `at -${distance} m`).not.toBeNull();
    }
  });

  it('answers on a circle, not a square, so no direction runs further than another', () => {
    const surface = authoredGroundSurface(ENDLESS);
    const diagonal = RADIUS / Math.SQRT2;
    expect(surface.sample(diagonal, diagonal)).not.toBeNull();
    expect(surface.sample(diagonal + 1, diagonal + 1)).toBeNull();
    expect(surface.sample(RADIUS + 1, 0)).toBeNull();
  });

  it('carries the stated elevation rather than assuming zero', () => {
    expect(authoredGroundSurface({ kind: 'endless', elevationMm: 1_250 }).sample(500, 500))
      .toEqual({ height: 1.25, normal: { x: 0, y: 1, z: 0 } });
  });

  it('leaves a ground that really has edges exactly where its edges are', () => {
    const surface = authoredGroundSurface(BOUNDED);
    expect(surface.sample(12, 12)).not.toBeNull();
    expect(surface.sample(12.001, 0)).toBeNull();
    expect(surface.sample(0, 12.001)).toBeNull();
    // The corner of the declared rectangle is inside it, which a circular rule would refuse.
    expect(surface.sample(11.9, 11.9)).not.toBeNull();
  });
});

describe('the field an endless authored ground admits', () => {
  it('replaces the empty-scene floor that was the second wall behind the sampler', () => {
    const bare = buildNavigationWorld(makeScene([], 1, 1), authoredGroundSurface(ENDLESS));
    expect(bare.fieldRadius).toBe(90);
    expect(bare.recoveryRadius).toBe(138);

    const world = endlessAuthoredNavigation(bare);
    expect(world.recoveryRadius).toBe(RADIUS - RECOVERY_MARGIN_AU);
    expect(world.fieldRadius).toBe(RADIUS - RECOVERY_MARGIN_AU * 2);
    expect(world.surface).toBe(bare.surface);
  });

  it('keeps every reachable point inside the surface the ground answers for', () => {
    const world = endlessWorld();
    // Movement compresses anything past `fieldRadius` and returns anything past `recoveryRadius`,
    // so the furthest point it can ever sample is the compressed edge of that band.
    const furthest = world.fieldRadius
      + (world.recoveryRadius - world.fieldRadius) * 0.22;
    expect(furthest).toBeLessThan(world.recoveryRadius);
    expect(world.recoveryRadius).toBeLessThan(RADIUS);
    expect(world.surface.sample(furthest, 0)).not.toBeNull();
    expect(world.surface.sample(world.recoveryRadius, 0)).not.toBeNull();
  });
});

describe('walking out of the old starter world', () => {
  const STRIDE = 1.4 / 60;

  function walk(world: NavigationWorld, metres: number): {
    readonly reached: number;
    readonly recoveredAt: number | null;
    readonly reason: string | null;
  } {
    let position: AtlasVec3 = atlasVec3(0, DEFAULT_EYE_HEIGHT_AU, 0);
    let lastSafe = position;
    for (let travelled = 0; travelled < metres; travelled += STRIDE) {
      const resolution = resolveGroundMovement(world, {
        current: position,
        desired: atlasVec3(position.x + STRIDE, position.y, position.z),
        lastSafe,
      });
      if (resolution.recovered) {
        return { reached: position.x, recoveredAt: travelled, reason: resolution.recoveryReason };
      }
      position = resolution.position;
      lastSafe = resolution.lastSafe;
    }
    return { reached: position.x, recoveredAt: null, reason: null };
  }

  it('bounces at 24 metres on the ground module version 1 still states', () => {
    const bounded = buildNavigationWorld(makeScene([], 1, 1), authoredGroundSurface(BOUNDED));
    const result = walk(bounded, 60);
    expect(result.recoveredAt).not.toBeNull();
    expect(result.reason).toBe('no-surface');
    expect(result.reached).toBeGreaterThan(11.9);
    expect(result.reached).toBeLessThan(12.1);
  });

  it('walks the whole supported radius on an endless ground without being returned', () => {
    const world = endlessWorld();
    const result = walk(world, world.fieldRadius - 1);
    expect(result.recoveredAt).toBeNull();
    expect(result.reason).toBeNull();
    expect(result.reached).toBeGreaterThan(world.fieldRadius - 2);
    // The distance actually walked, not a constant restated: 8 kilometres, on the world's own
    // resolver, one 23 millimetre frame at a time.
    expect(result.reached).toBeGreaterThan(8_000);
  });

  it('resists through the last stretch and then returns, naming the field rather than the ground', () => {
    const world = endlessWorld();
    const far = atlasVec3(world.fieldRadius - 1, DEFAULT_EYE_HEIGHT_AU, 0);
    const resisted = resolveGroundMovement(world, {
      current: far,
      desired: atlasVec3(world.fieldRadius + 20, far.y, 0),
      lastSafe: far,
    });
    expect(resisted.recovered).toBe(false);
    expect(resisted.position.x).toBeGreaterThan(world.fieldRadius);
    expect(resisted.position.x).toBeLessThan(world.fieldRadius + 20);

    const past = resolveGroundMovement(world, {
      current: far,
      desired: atlasVec3(world.recoveryRadius + 1, far.y, 0),
      lastSafe: far,
    });
    expect(past.recovered).toBe(true);
    // Not `no-surface`: on a ground that states it has no edge, running out of ground is the
    // wrong account of what happened, and it is the sentence the operator was shown.
    expect(past.recoveryReason).toBe('outside-field');
    expect(past.position).toEqual(far);
  });
});
