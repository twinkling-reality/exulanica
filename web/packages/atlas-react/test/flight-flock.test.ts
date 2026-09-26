// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { FlightFlock } from '../src/playcanvas/flight/flock.js';
import type { FlightKindLook, FlightSamples, FlightWindow } from '../src/playcanvas/flight/types.js';
import { AuthoredRegionSociety } from '../src/playcanvas/society/authored-society.js';

const STATES = ['perching', 'taking_off', 'flying', 'landing'] as const;
const PERCHING = 0;
const FLYING = 2;
const LOOK: FlightKindLook = { key: 'small_bird', wingHingeMm: [30, 6, 66], maxBankMrad: 785, flapCycleMs: 120 };

function setup() {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  const root = new pc.Entity('region');
  app.root.addChild(root);
  return { app, device, root };
}

/** Parts with no geometry: the flock only places them. */
const parts = {
  body: () => new pc.Entity('body'),
  wing: () => new pc.Entity('wing'),
};

interface Step {
  readonly p: readonly [number, number, number];
  readonly v?: readonly [number, number, number];
  readonly turn?: number;
  readonly state?: number;
  readonly flap?: number;
}

function flyer(id: string, steps: readonly Step[]): FlightSamples {
  return {
    flyerId: id,
    kind: 'small_bird',
    positionMm: steps.flatMap((s) => [...s.p]),
    velocityMmS: steps.flatMap((s) => [...(s.v ?? [0, 0, 0])]),
    turnMmS2: steps.map((s) => s.turn ?? 0),
    state: steps.map((s) => s.state ?? FLYING),
    flap: steps.map((s) => s.flap ?? 0),
  };
}

function window(fromStep: number, flyers: readonly FlightSamples[], digest = 'a'.repeat(64)): FlightWindow {
  return {
    inputSha256: digest,
    groundMm: 0,
    stepMs: 100,
    fromStep,
    steps: flyers[0] ? flyers[0].state.length : 0,
    states: STATES,
    flyers,
  };
}

function position(entity: pc.Entity): number[] {
  const at = entity.getLocalPosition();
  return [at.x, at.y, at.z].map((value) => Math.round(value * 1000));
}

describe('FlightFlock', () => {
  it('draws each flyer between its served steps, along the segment between them', () => {
    const { root } = setup();
    const flock = new FlightFlock(root, () => 1_050);
    flock.setKind(LOOK, parts);
    flock.setWindow(window(0, [flyer('bird', [{ p: [0, 6_500, 0] }, { p: [500, 6_500, -1_000] }])]), 1_000);
    flock.update(1_050);
    const [bird] = flock.root.children as pc.Entity[];
    expect(position(bird!)).toEqual([250, 6_500, -500]);
    expect(flock.animating).toBe(true);
  });

  it('faces its served velocity, banks into a served turn and pitches up a served climb', () => {
    const { root } = setup();
    const flock = new FlightFlock(root);
    flock.setKind(LOOK, parts);
    // Heading north (-z), climbing, turning left.
    const step = { p: [0, 6_500, 0] as const, v: [0, 1_000, -5_000] as const, turn: 3_000 };
    flock.setWindow(window(0, [flyer('bird', [step, step])]), 0);
    flock.update(0);
    const [bird] = flock.root.children as pc.Entity[];
    const forward = bird!.forward.clone();
    const right = bird!.right.clone();
    // The body's -z (its forward) points north and a little up; its right wing is lifted.
    expect(forward.z).toBeLessThan(-0.9);
    expect(forward.y).toBeGreaterThan(0.1);
    expect(right.y).toBeGreaterThan(0.1);
    // Turning right banks the other way.
    flock.setWindow(window(0, [flyer('bird', [{ ...step, turn: -3_000 }, { ...step, turn: -3_000 }])], 'b'.repeat(64)), 0);
    flock.update(0);
    const [again] = flock.root.children as pc.Entity[];
    expect(again!.right.y).toBeLessThan(-0.1);
  });

  it('folds its wings while it perches and beats them while a step says it flaps', () => {
    const { root } = setup();
    const flock = new FlightFlock(root);
    flock.setKind(LOOK, parts);
    const perched = { p: [0, 5_650, 0] as const, state: PERCHING };
    const flapping = { p: [0, 6_500, 0] as const, v: [0, 0, -3_000] as const, flap: 1 };
    flock.setWindow(window(0, [flyer('bird', [perched, perched, flapping, flapping, flapping])]), 0);
    flock.update(0);
    const [bird] = flock.root.children as pc.Entity[];
    const [, right] = bird!.children as pc.Entity[];
    // Folded: the right wing's span points back along the body (+z), not out to the side.
    const folded = right!.right.clone();
    expect(folded.z).toBeGreaterThan(0.9);
    flock.update(230);
    const beating = [right!.right.y];
    flock.update(260);
    beating.push(right!.right.y);
    expect(beating[0]).not.toBeCloseTo(beating[1]!, 3);
  });

  it('holds the last served step when the clock passes it, and counts it', () => {
    const { root } = setup();
    const flock = new FlightFlock(root);
    flock.setKind(LOOK, parts);
    flock.setWindow(window(0, [flyer('bird', [{ p: [0, 6_500, 0] }, { p: [100, 6_500, 0] }])]), 0);
    flock.update(5_000);
    const [bird] = flock.root.children as pc.Entity[];
    expect(position(bird!)).toEqual([100, 6_500, 0]);
    expect(flock.starved).toBe(1);
    expect(flock.nextStep).toBe(2);
  });

  it('draws a kind only once its parts are set, and starts again for a changed world', () => {
    const { root } = setup();
    const flock = new FlightFlock(root);
    flock.setWindow(window(0, [flyer('bird', [{ p: [0, 6_500, 0] }, { p: [0, 6_500, 0] }])]), 0);
    flock.update(0);
    expect(flock.drawnFlyerIds).toEqual([]);
    flock.setKind(LOOK, parts);
    flock.update(10);
    expect(flock.drawnFlyerIds).toEqual(['bird']);
    flock.setWindow(window(600, [flyer('other', [{ p: [0, 6_500, 0] }])], 'c'.repeat(64)), 20);
    expect(flock.stepAt(20)).toBe(600);
    flock.update(20);
    expect(flock.drawnFlyerIds).toEqual(['other']);
  });
});

describe('FlightFlock across windows, under reduced motion and at rest', () => {
  it('draws the move that joins two windows along its segment, as any other', () => {
    const { root } = setup();
    const flock = new FlightFlock(root);
    flock.setKind(LOOK, parts);
    flock.setWindow(window(0, [flyer('bird', [{ p: [0, 6_500, 0] }, { p: [100, 6_500, 0] }])]), 0);
    flock.setWindow(window(2, [flyer('bird', [{ p: [300, 6_500, 0] }, { p: [400, 6_500, 0] }])]), 0);
    flock.update(150);
    const [bird] = flock.root.children as pc.Entity[];
    expect(position(bird!)).toEqual([200, 6_500, 0]);
  });

  it('lets windows the clock has passed go as new ones arrive, and stands flyers still under reduced motion', () => {
    const { root } = setup();
    const flock = new FlightFlock(root);
    flock.setKind(LOOK, parts);
    const steps = (x: number) => [{ p: [x, 6_500, 0] as const }, { p: [x + 10, 6_500, 0] as const }];
    for (let index = 0; index < 5; index += 1) {
      // Reduced motion never ticks the clock; each window arrives as the clock reaches it.
      flock.setWindow(window(2 * index, [flyer('bird', steps(1_000 * index))]), 200 * index);
      flock.update(Number.MAX_SAFE_INTEGER);
    }
    expect(flock.heldWindows).toBeLessThanOrEqual(2);
    const [bird] = flock.root.children as pc.Entity[];
    // The latest window arrived when the clock was at step 8: its first sample, wings still.
    expect(position(bird!)).toEqual([4_000, 6_500, 0]);
    expect(flock.animating).toBe(false);
  });

  it('draws the flyers of a flight started again after a clear, under reduced motion', () => {
    const { root } = setup();
    const flock = new FlightFlock(root);
    flock.setKind(LOOK, parts);
    flock.setWindow(window(0, [flyer('bird', [{ p: [0, 6_500, 0] }, { p: [0, 6_500, 0] }])]), 0);
    flock.update(Number.MAX_SAFE_INTEGER);
    expect(flock.drawnFlyerIds).toEqual(['bird']);
    flock.clear();
    expect(flock.drawnFlyerIds).toEqual([]);
    flock.setWindow(window(0, [flyer('other', [{ p: [0, 6_500, 0] }, { p: [0, 6_500, 0] }])], 'd'.repeat(64)), 50);
    flock.update(Number.MAX_SAFE_INTEGER);
    expect(flock.drawnFlyerIds).toEqual(['other']);
  });

  it('asks for frames only while a flyer is off its perch at the clock', () => {
    const { root } = setup();
    let clock = 0;
    const flock = new FlightFlock(root, () => clock);
    flock.setKind(LOOK, parts);
    const perched = { p: [0, 5_650, 0] as const, state: PERCHING };
    const leaving = { p: [0, 5_700, 0] as const, state: 1 };
    flock.setWindow(window(0, [flyer('bird', [perched, perched, perched, leaving])]), 0);
    flock.update(0);
    expect(flock.animating).toBe(false);
    clock = 150;
    expect(flock.animating).toBe(false);
    // At step 2 the next step is a take-off: frames are wanted before it is drawn.
    clock = 250;
    expect(flock.animating).toBe(true);
    // Past the last served step the flock holds still.
    clock = 10_000;
    expect(flock.animating).toBe(false);
  });
});

describe('AuthoredRegionSociety flight', () => {
  it('makes its flock with the first window, animates while flyers are drawn, and destroys it', () => {
    const { device, root } = setup();
    const society = new AuthoredRegionSociety(device, root);
    const names = () => society.root.children.map((child) => child.name);
    expect(names()).not.toContain('flight-flock');
    expect(society.flightNextStep).toBeNull();
    society.setFlight(window(0, [flyer('bird', [{ p: [0, 6_500, 0] }, { p: [0, 6_500, 0] }])]), 0);
    expect(names()).toContain('flight-flock');
    expect(society.flightNextStep).toBe(2);
    society.tickSociety(0);
    expect(society.drawnFlyerIds).toEqual([]);
    expect(society.societyAnimating).toBe(false);
    society.destroy();
    expect(society.root.parent).toBeNull();
  });
});
