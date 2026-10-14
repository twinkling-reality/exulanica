import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { CASTER_REACH, ShadowDetail, cascadeMaskFor } from '../src/playcanvas/generated-tile/shadow-detail.js';

/*
 * A small shadow caster is drawn into the near cascades only; anything else, anything that casts no
 * shadow, and a caster whose mask someone else already narrowed are left as they are, and every
 * mask is put back when the environment goes.
 */

const caster = (sizeM: number, castShadow = true, mask: number = pc.SHADOW_CASCADE_ALL) => ({
  castShadow, shadowCascadeMask: mask, aabb: { halfExtents: { x: sizeM / 2, y: sizeM / 4, z: sizeM / 3 } },
});
type Fake = ReturnType<typeof caster>;

function scene(instances: Fake[]) {
  const listeners = new Map<string, (dt: number) => void>();
  const app = {
    scene: { layers: { layerList: [{ shadowCasters: instances }, { shadowCasters: [] as Fake[] }] } },
    on: (name: string, fn: (dt: number) => void) => listeners.set(name, fn),
    off: (name: string) => listeners.delete(name),
  };
  return { app, tick: () => listeners.get('update')?.(1 / 60), listening: () => listeners.has('update') };
}

describe('the cascades a caster is drawn into', () => {
  it('are the nearest one under 0.6 m, the nearest two under 1.5 m, and every cascade otherwise', () => {
    expect(CASTER_REACH.map((rule) => [rule.underM, rule.cascades])).toEqual([[0.6, 1], [1.5, 2]]);
    expect(cascadeMaskFor(0.2)).toBe(1);
    expect(cascadeMaskFor(0.6)).toBe(3);
    expect(cascadeMaskFor(1.49)).toBe(3);
    expect(cascadeMaskFor(1.5)).toBe(pc.SHADOW_CASCADE_ALL);
    expect(cascadeMaskFor(12)).toBe(pc.SHADOW_CASCADE_ALL);
    for (const rule of CASTER_REACH) expect(rule.reason.length).toBeGreaterThan(0);
  });
});

describe('the sweep over a scene', () => {
  it('narrows small casters once, leaves the rest, picks up a caster that arrives later, and puts every mask back', () => {
    const flower = caster(0.3), bench = caster(1.2), tree = caster(6), unlit = caster(0.2, false), narrowed = caster(0.2, true, 2);
    const instances: Fake[] = [flower, bench, tree, unlit, narrowed];
    const { app, tick, listening } = scene(instances);
    const detail = new ShadowDetail(app as unknown as pc.AppBase);
    tick();
    expect([flower, bench, tree, unlit, narrowed].map((one) => one.shadowCascadeMask)).toEqual([1, 3, pc.SHADOW_CASCADE_ALL, pc.SHADOW_CASCADE_ALL, 2]);
    // A figure walks in: its part is given its mask at the next frame's sweep.
    const part = caster(0.25);
    instances.push(part);
    expect(part.shadowCascadeMask).toBe(pc.SHADOW_CASCADE_ALL);
    tick();
    expect(part.shadowCascadeMask).toBe(1);
    // Already seen: a later sweep changes nothing.
    flower.shadowCascadeMask = 4;
    expect(detail.sweep()).toBe(0);
    expect(flower.shadowCascadeMask).toBe(4);
    detail.dispose();
    expect(listening()).toBe(false);
    expect([flower, bench, tree, unlit, narrowed, part].map((one) => one.shadowCascadeMask)).toEqual([
      pc.SHADOW_CASCADE_ALL, pc.SHADOW_CASCADE_ALL, pc.SHADOW_CASCADE_ALL, pc.SHADOW_CASCADE_ALL, 2, pc.SHADOW_CASCADE_ALL,
    ]);
    expect(detail.sweep()).toBe(0);
  });
});

describe('one frame of the sweep', () => {
  it('looks at no more casters than its bound, and resumes where it stopped', () => {
    const instances = Array.from({ length: 5 }, () => caster(0.2));
    const { app } = scene(instances);
    const detail = new ShadowDetail(app as unknown as pc.AppBase);
    expect(detail.sweep(2)).toBe(2);
    expect(instances.map((one) => one.shadowCascadeMask)).toEqual([1, 1, pc.SHADOW_CASCADE_ALL, pc.SHADOW_CASCADE_ALL, pc.SHADOW_CASCADE_ALL]);
    expect(detail.sweep(2)).toBe(2);
    expect(detail.sweep(2)).toBe(1);
    expect(instances.every((one) => one.shadowCascadeMask === 1)).toBe(true);
    detail.dispose();
  });
});
