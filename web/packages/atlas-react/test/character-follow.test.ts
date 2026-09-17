// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { inhabitantRenderable } from '../src/playcanvas/character/inhabitant.js';
import type { InhabitantIdentity } from '../src/playcanvas/character/inhabitant.js';

let canvases = 0;

function world() {
  const canvas = document.createElement('canvas');
  canvas.id = `character-follow-${canvases++}`;
  document.body.appendChild(canvas);
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  const parent = new pc.Entity('crowd', app);
  app.root.addChild(parent);
  return { app, device, parent };
}

const identity = (id: string): InhabitantIdentity => ({ societyId: 'society', branchId: 'main', inhabitantId: id });

describe('carrying a person between poses', () => {
  it('is the same person, posed once at the end, as one posed on every frame of the gap', () => {
    const { app, device, parent } = world();
    const carried = inhabitantRenderable(device, parent, identity('carried'), 'far');
    const posed = inhabitantRenderable(device, parent, identity('posed'), 'far');
    // The same walk for both: three steps north, then a turn east. One is carried between poses and
    // handed the time that passed; the other is posed at each step.
    const path: readonly (readonly [number, number, number])[] = [[0, 0, 0], [0, 0, -0.4], [0, 0, -0.8], [0.6, 0, -1.0]];
    for (const person of [carried, posed]) person.pose({ position: path[0]!, deltaSeconds: 1 / 60, discontinuity: true });
    carried.follow(path[1]!);
    carried.follow(path[2]!);
    carried.pose({ position: path[3]!, deltaSeconds: 3 / 60 });
    for (const step of path.slice(1)) posed.pose({ position: step, deltaSeconds: 1 / 60 });

    expect(carried.root.getLocalPosition().z).toBeCloseTo(-1.0, 6);
    // Carrying is not a pose: the gait and heading of the carried person come from the one pose it
    // was given, over the whole gap, so it faces where it travelled, not where it last hopped.
    expect(carried.facing).not.toBeCloseTo(posed.facing, 3);
    expect(Math.abs(carried.facing)).toBeGreaterThan(Math.abs(posed.facing));

    // The pose that follows a carry reads the travel of the whole gap: the same person posed once
    // over the same time and distance ends up identical.
    const once = inhabitantRenderable(device, parent, identity('once'), 'far');
    once.pose({ position: path[0]!, deltaSeconds: 1 / 60, discontinuity: true });
    once.pose({ position: path[3]!, deltaSeconds: 3 / 60 });
    expect(carried.facing).toBeCloseTo(once.facing, 6);

    for (const person of [carried, posed, once]) person.destroy();
    app.destroy();
  });

  it('refuses a position that is not a place, and ignores a carry after destruction', () => {
    const { app, device, parent } = world();
    const person = inhabitantRenderable(device, parent, identity('one'), 'far');
    person.pose({ position: [0, 0, 0], deltaSeconds: 1 / 60, discontinuity: true });
    expect(() => person.follow([Number.NaN, 0, 0])).toThrow(/finite/);
    expect(() => person.follow([0, Number.POSITIVE_INFINITY, 0])).toThrow(/finite/);
    person.destroy();
    expect(() => person.follow([1, 0, 1])).not.toThrow();
    app.destroy();
  });
});
