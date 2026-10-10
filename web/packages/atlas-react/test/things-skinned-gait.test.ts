// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { CLIP_SPEED_LIMIT, SkinnedFigure } from '../src/playcanvas/things/skinned.js';
import { thingsJson } from './things-fixtures.js';
import { KNIGHT_CLIP_SECONDS, KNIGHT_LOOK, KNIGHT_PLAN, KNIGHT_RIG, KNIGHT_RUN, KNIGHT_STRIDE, KNIGHT_WALK, knightContainer } from './things-knight-rig.js';

/*
 * A rigged look that plays its own clips steps as fast as the ground goes by, and stands when it is
 * going nowhere. The look is the shipped armoured knight's document; its clips last as long as the
 * clips of its own container do, read from the container's bytes (`./things-knight-rig.ts`); the
 * expected cadences are arithmetic on those and on the ground speeds the look declares. The engine
 * plays the clips: what is measured is how far through its cycle the engine's own state has gone.
 */

const app = (() => {
  const canvas = document.createElement('canvas');
  const made = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = new pc.NullGraphicsDevice(canvas);
  options.componentSystems = [pc.RenderComponentSystem, pc.AnimComponentSystem];
  made.init(options);
  return made;
})();

const LOOK = KNIGHT_LOOK;
const WALK = KNIGHT_WALK;
const RUN = KNIGHT_RUN;
const CLIP_SECONDS = KNIGHT_CLIP_SECONDS;
const STRIDE = KNIGHT_STRIDE;

/** A figure of the look, drawn `heightMm` tall, on the stand-in rig. */
function knight(heightMm = LOOK.heightMm!): { figure: SkinnedFigure; anim: pc.AnimComponent } {
  const region = new pc.Entity('region');
  app.root.addChild(region);
  const { model, tracks } = knightContainer();
  const figure = new SkinnedFigure(region, model, tracks, KNIGHT_PLAN, KNIGHT_RIG, 'knight', LOOK.heightMm!, heightMm);
  return { figure, anim: figure.root.findComponent('anim') as pc.AnimComponent };
}

const FRAME = 1 / 60;

/**
 * Walk a figure straight ahead at `speed` (metres a second on the ground it is drawn on) for
 * `seconds`, the engine playing its clips each frame; returns the cycles its clips played a second
 * over the last half, once the speed it reads from the ground has settled.
 */
function cyclesPerSecond(figure: SkinnedFigure, anim: pc.AnimComponent, speed: number, seconds: number, from = 0): number {
  const frames = Math.round(seconds / FRAME);
  let before = 0;
  for (let frame = 1; frame <= frames; frame += 1) {
    figure.pose({ position: [0, 0, -(from + speed * frame * FRAME)], facing: 0, deltaSeconds: FRAME });
    app.systems.fire('animationUpdate', FRAME);
    if (frame === Math.floor(frames / 2)) before = anim.baseLayer!.activeStateProgress;
  }
  return (anim.baseLayer!.activeStateProgress - before) / ((frames - Math.floor(frames / 2)) * FRAME);
}

/** How much of the blend the walk clip is, between standing and the walk: the engine's 1D blend is linear in its parameter. */
const walkShare = (anim: pc.AnimComponent): number => Math.min(1, anim.getFloat('speed') / WALK);

describe('a rigged look that plays its own clips', () => {
  it('reads its figures from the shipped look and its container', () => {
    // The knight's walk and run, and the lengths of its clips: what every figure below is derived from.
    expect([WALK, RUN]).toEqual([0.504, 2.377]);
    expect(CLIP_SECONDS.get('idle')).toBeCloseTo(1.0667, 4);
    expect(CLIP_SECONDS.get('walk')).toBeCloseTo(1.0667, 4);
    expect(CLIP_SECONDS.get('run')).toBeCloseTo(0.8, 4);
    expect(STRIDE).toBeCloseTo(0.5376, 4);
  });

  it('steps at the cadence of the ground across its walking range, the whole walk and nothing of standing', () => {
    for (const share of [0.5, 0.6, 0.75, 0.9, 1]) {
      const { figure, anim } = knight();
      const speed = WALK * share;
      const cadence = cyclesPerSecond(figure, anim, speed, 8);
      // One cycle of the walk covers its stride: the ground speed over the stride is the cadence.
      expect(cadence, `at ${speed.toFixed(3)} m/s`).toBeCloseTo(speed / STRIDE, 6);
      expect(walkShare(anim), `at ${speed.toFixed(3)} m/s`).toBeCloseTo(1, 9);
      expect(figure.misses.size).toBe(0);
      figure.destroy();
    }
  });

  it('shortens its step below half its walking pace, a planted foot still as fast as the ground', () => {
    for (const speed of [0.03, 0.06, 0.12, 0.2, 0.25]) {
      const { figure, anim } = knight();
      const cadence = cyclesPerSecond(figure, anim, speed, 8);
      // Never slower than half the walk's own cadence: slower, the step is shortened instead.
      expect(cadence, `at ${speed} m/s`).toBeCloseTo(0.5 / CLIP_SECONDS.get('walk')!, 6);
      // A blend's step is the walk's stride by the walk's share of it; step by cadence is the foot's speed.
      expect(cadence * STRIDE * walkShare(anim), `at ${speed} m/s`).toBeCloseTo(speed, 6);
      figure.destroy();
    }
  });

  it('stands when it goes nowhere, however it is turned, and below the standing threshold', () => {
    const { figure, anim } = knight();
    // A walk, then a stop where it is: the speed it reads eases to nothing and it stands.
    cyclesPerSecond(figure, anim, WALK, 3);
    const at = WALK * 3;
    const standing = cyclesPerSecond(figure, anim, 0, 3, at);
    expect(anim.getFloat('speed')).toBe(0);
    // Standing is the idle clip alone at its own cadence: no stride at all.
    expect(standing).toBeCloseTo(1 / CLIP_SECONDS.get('idle')!, 6);
    // Turned on the spot, a quarter turn a frame and then slowly, it still stands.
    for (let frame = 0; frame < 120; frame += 1) {
      figure.pose({ position: [0, 0, -at], facing: frame < 4 ? (frame * Math.PI) / 2 : frame * 0.01, deltaSeconds: FRAME });
      app.systems.fire('animationUpdate', FRAME);
      expect(anim.getFloat('speed'), `frame ${frame}`).toBe(0);
      expect(anim.speed).toBe(1);
    }
    // Drifting slower than the standing threshold (0.02 m/s) is standing too: 0.015 m/s for five seconds.
    cyclesPerSecond(figure, anim, 0.015, 5, at);
    expect(anim.getFloat('speed')).toBe(0);
    // And just over the threshold it steps.
    cyclesPerSecond(figure, anim, 0.03, 5, at + 0.075);
    expect(anim.getFloat('speed')).toBeGreaterThan(0);
    figure.destroy();
  });

  it('blends walk into run at the clips\' own cadence, and past the run plays faster, at most twice', () => {
    const between = knight();
    cyclesPerSecond(between.figure, between.anim, 1.2, 6);
    expect(between.anim.getFloat('speed')).toBeCloseTo(1.2, 6);
    expect(between.anim.speed).toBe(1);
    between.figure.destroy();
    const past = knight();
    cyclesPerSecond(past.figure, past.anim, RUN * 1.5, 6);
    expect(past.anim.getFloat('speed')).toBeCloseTo(RUN, 9);
    expect(past.anim.speed).toBeCloseTo(1.5, 6);
    expect(past.figure.misses.size).toBe(0);
    past.figure.destroy();
    const sliding = knight();
    cyclesPerSecond(sliding.figure, sliding.anim, RUN * 3, 6);
    expect(sliding.anim.speed).toBe(CLIP_SPEED_LIMIT);
    expect([...sliding.figure.misses]).toEqual(['feet_slide']);
    sliding.figure.destroy();
  });

  it('states its look\'s walking speed at the size it is drawn, and steps to it at that size', () => {
    const natural = knight();
    expect(natural.figure.walkSpeed).toBeCloseTo(WALK, 12);
    natural.figure.destroy();
    // Drawn 1,900 mm tall, the top of its kind's range, every length of it is 19/18 as long: so is its stride.
    const kind = thingsJson('kinds/knight.v2.json')['body'] as { height_mm: { to: number } };
    const scale = kind.height_mm.to / LOOK.heightMm!;
    expect(scale).toBeCloseTo(19 / 18, 12);
    const tall = knight(kind.height_mm.to);
    expect(tall.figure.walkSpeed).toBeCloseTo(WALK * scale, 12);
    const cadence = cyclesPerSecond(tall.figure, tall.anim, WALK * scale * 0.8, 8);
    expect(cadence).toBeCloseTo((WALK * scale * 0.8) / (STRIDE * scale), 6);
    tall.figure.destroy();
  });
});
