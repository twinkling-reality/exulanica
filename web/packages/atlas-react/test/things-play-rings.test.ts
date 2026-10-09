// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { ThingLibrary } from '../src/playcanvas/things/library.js';
import { ThingLayer, type DrawnSociety } from '../src/playcanvas/things/thing-layer.js';
import { servedLibrary } from './things-fixtures.js';

/*
 * Play this one's rings: one at the feet of the being the viewer plays, following its drawn walk, and
 * one where its next walk goes, a point of the society's own frame (the state's position_mm). The
 * places expected come from the fake society's stated points and the region's stated move, and the
 * radii and colour from what lanes UI and DRAW agreed (0.45 m, 0.35 m, --color-world-mark-person), and the
 * dark edge the operator chose for them (B of package 18's A/B: the person ink, a band 8 percent of the
 * radius wider either side, just under the yellow).
 */

const PERSON = '#f4ff91';
const INK = '#1b2430';

function setup() {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem];
  app.init(options);
  const region = new pc.Entity('region');
  region.setLocalPosition(10, 0, 5);
  app.root.addChild(region);
  const crowdRoot = new pc.Entity('society');
  region.addChild(crowdRoot);
  const camera = new pc.Entity('camera');
  app.root.addChild(camera);
  const feet = new pc.Vec3(1, 0, 2);
  let drawn = true;
  let society: DrawnSociety | null = {
    root: crowdRoot,
    groundOf: (id, out) => {
      if (id !== 'knight-1' || !drawn) return false;
      out.copy(feet);
      return true;
    },
  };
  const served = servedLibrary();
  const layer = new ThingLayer({
    app, camera, library: new ThingLibrary(served.list, (digest) => served.fetch(digest)), regionRoot: () => region,
    ringColour: '#123456', personColour: PERSON, personEdge: INK, society: () => society,
  });
  return {
    app, layer, feet,
    hide: (hidden: boolean) => { drawn = !hidden; },
    drop: () => { society = null; },
  };
}

/** The ring standing under a holder of this name, if one is shown. */
function ring(app: pc.AppBase, holder: string) {
  const found = app.root.findByName(holder) as pc.Entity | null;
  const entity = found?.children.find((child) => child.name === 'thing-pick-ring') as pc.Entity | undefined;
  if (entity === undefined || !entity.enabled) return null;
  const material = (entity.render!.meshInstances[0]!.material as pc.StandardMaterial);
  return { at: entity.getPosition().toArray(), radius: entity.getLocalScale().x, glow: material.emissiveIntensity, colour: material.emissive.toString(false) };
}

const step = (layer: ThingLayer) => (layer as unknown as { step(dt: number): void }).step(1 / 60);

describe('the rings of Play this one', () => {
  it('rings the played being at its feet, follows its walk, and goes when it is not drawn or given back', () => {
    const { app, layer, feet, hide } = setup();
    expect(ring(app, 'thing-played-at')).toBeNull();
    layer.setPlayed('knight-1');
    const first = ring(app, 'thing-played-at')!;
    expect(first.at.map((v) => Number(v.toFixed(6)))).toEqual([1, 0.012, 2]);
    expect(first.radius).toBe(0.45);
    expect(first.colour).toBe(PERSON);
    feet.set(3, 0, -4);
    step(layer);
    expect(ring(app, 'thing-played-at')!.at.map((v) => Number(v.toFixed(6)))).toEqual([3, 0.012, -4]);
    hide(true);
    step(layer);
    expect(ring(app, 'thing-played-at')).toBeNull();
    hide(false);
    step(layer);
    expect(ring(app, 'thing-played-at')).not.toBeNull();
    layer.setPlayed(null);
    expect(ring(app, 'thing-played-at')).toBeNull();
  });

  it('rings where the next walk goes, a point of the society\'s frame, and takes it away', () => {
    const { app, layer, drop } = setup();
    layer.setDestination({ xMm: 2500, zMm: -1500 });
    const shown = ring(app, 'thing-destination-at')!;
    // The society's point (2.5, 0, -1.5) m, moved with the region by (10, 0, 5).
    expect(shown.at.map((v) => Number(v.toFixed(6)))).toEqual([12.5, 0.012, 3.5]);
    expect(shown.radius).toBe(0.35);
    expect(shown.colour).toBe(PERSON);
    layer.setDestination(null);
    expect(ring(app, 'thing-destination-at')).toBeNull();
    // With no society drawn there is nowhere to ring.
    drop();
    layer.setDestination({ xMm: 0, zMm: 0 });
    expect(ring(app, 'thing-destination-at')).toBeNull();
  });

  it('keeps both rings steady: they never pulse', () => {
    const { app, layer } = setup();
    layer.setPlayed('knight-1');
    layer.setDestination({ xMm: 0, zMm: 0 });
    for (let i = 0; i < 30; i += 1) step(layer);
    expect(ring(app, 'thing-played-at')!.glow).toBe(1);
    expect(ring(app, 'thing-destination-at')!.glow).toBe(1);
  });

  it('stands both rings on a dark edge in the person ink, wider than the yellow either side and just under it', () => {
    const { app, layer } = setup();
    layer.setPlayed('knight-1');
    layer.setDestination({ xMm: 0, zMm: 0 });
    for (const holder of ['thing-played-at', 'thing-destination-at']) {
      const yellow = (app.root.findByName(holder) as pc.Entity).children.find((child) => child.name === 'thing-pick-ring') as pc.Entity;
      const edge = yellow.children.find((child) => child.name === 'thing-pick-ring-edge') as pc.Entity;
      expect(edge.enabled).toBe(true);
      expect((edge.render!.meshInstances[0]!.material as pc.StandardMaterial).emissive.toString(false)).toBe(INK);
      // In the ring's own frame, where its radius is 1: the yellow reaches 1, the edge 8 percent beyond it.
      const outer = (entity: pc.Entity) => entity.render!.meshInstances[0]!.mesh.aabb.halfExtents.x;
      expect(outer(yellow)).toBeCloseTo(1, 6);
      expect(outer(edge)).toBeCloseTo(1.08, 6);
      expect(edge.getLocalPosition().y).toBeLessThan(0);
    }
  });
});
