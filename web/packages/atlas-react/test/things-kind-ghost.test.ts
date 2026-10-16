// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import * as pc from 'playcanvas';
import type { LookDrawing } from '../src/playcanvas/things/documents.js';
import { ThingLayer, type KindGhost, type PlacedThingRecord } from '../src/playcanvas/things/thing-layer.js';
import { ThingLibrary } from '../src/playcanvas/things/library.js';
import { servedLibrary, until } from './things-fixtures.js';

/*
 * An editor's see-through copy of a thing of a kind not yet placed (a kind picked from build mode's
 * tray): made once for its kind by the layer's own figure maker, posed by each pose without being
 * made again, a light copy that throws no shadow, coral where the world refused the spot, and never
 * picked or listed as drawn. None, or another kind, takes it away, and a make that finishes after it
 * is no longer wanted leaves nothing behind.
 */

/** Each look's container as the engine's reader would make one, counted, and held back for a look asked to wait. */
function containers() {
  const made: string[] = [];
  const held = new Map<string, Array<() => void>>();
  const instantiate = async (look: LookDrawing) => {
    made.push(look.look);
    const waiting = held.get(look.look);
    if (waiting !== undefined) await new Promise<void>((resolve) => waiting.push(resolve));
    const model = new pc.Entity(`model:${look.look}`);
    const part = new pc.Entity(`part:${look.look}`);
    part.addComponent('render', { type: 'box' });
    model.addChild(part);
    return { model, tracks: new Map<string, pc.AnimTrack>() };
  };
  return {
    made,
    instantiate,
    hold: (look: string) => held.set(look, []),
    release(look: string) {
      const waiting = held.get(look) ?? [];
      held.delete(look);
      for (const go of waiting) go();
    },
  };
}

function setup() {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem];
  app.init(options);
  const region = new pc.Entity('region');
  app.root.addChild(region);
  const camera = new pc.Entity('camera');
  app.root.addChild(camera);
  const served = servedLibrary();
  const library = new ThingLibrary(served.list, (digest) => served.fetch(digest));
  const looks = containers();
  const layer = new ThingLayer({
    app, camera, library, regionRoot: (id) => (id === 'r' ? region : null), ringColour: '#f4ff91', instantiate: looks.instantiate,
  });
  const ghost = (kind: string, version: number, xMm: number, more: Partial<KindGhost> = {}): KindGhost => ({
    kind: served.kindRef(kind, version), regionId: 'r', xMm, yMm: 0, zMm: 1000, yawMicroradians: 0, refused: false, ...more,
  });
  return { served, layer, region, looks, ghost };
}

const copies = (region: pc.Entity) => region.children.filter((child) => child.name === 'thing-ghost:kind') as pc.Entity[];
const materialsOf = (root: pc.Entity) => (root.findComponents('render') as pc.RenderComponent[])
  .flatMap((render) => render.meshInstances).map((one) => one.material as pc.StandardMaterial);
const light = (material: pc.StandardMaterial) => [material.emissive.r, material.emissive.g, material.emissive.b].map((v) => Math.round(v * 255));

describe('an editor\'s see-through copy of a kind not yet placed', () => {
  it('is made once for its kind and posed by each pose, apart from anything placed', async () => {
    const { layer, region, looks, ghost } = setup();
    // Two asks while it is made share the one figure, which stands where it was asked for last.
    const [first, second] = await Promise.all([
      layer.setKindGhost(ghost('well', 2, 9000, { yawMicroradians: 1_570_796 })),
      layer.setKindGhost(ghost('well', 2, 8000, { yawMicroradians: 1_570_796 })),
    ]);
    expect([first, second]).toEqual([true, true]);
    const [copy] = copies(region);
    expect(copies(region)).toHaveLength(1);
    expect(copy!.getLocalPosition().x).toBeCloseTo(8, 6);
    expect(copy!.getLocalPosition().z).toBeCloseTo(1, 6);
    expect(copy!.getLocalEulerAngles().y).toBeCloseTo(90, 3);
    expect(await layer.setKindGhost(ghost('well', 2, 4000))).toBe(true);
    expect(copies(region)).toEqual([copy]);
    expect(copy!.getLocalPosition().x).toBeCloseTo(4, 6);
    expect(copy!.getLocalEulerAngles().y).toBeCloseTo(0, 3);
    expect(looks.made).toEqual(['primitive-well']);
    // It is not a thing: never listed as drawn, and a ray down onto its spot meets nothing.
    expect(layer.drawn).toEqual([]);
    expect(layer.pick([4, 5, 1], [0, -1, 0])).toBeNull();
  });

  it('is a light copy that throws no shadow, coral where the world refused the spot, and tinted again in place', async () => {
    const { layer, region, looks, ghost, served } = setup();
    const placed: PlacedThingRecord = {
      thingId: 'well', kind: served.kindRef('well', 2), regionId: 'r',
      transform: { xMm: 0, yMm: 0, zMm: 0, yawMicroradians: 0, scaleMilli: 1000 }, removed: false,
    };
    await layer.setPlaced([placed]);
    await until(() => layer.figureOf('well') !== null, 'the placed well');
    await layer.setKindGhost(ghost('well', 2, 9000));
    const [copy] = copies(region);
    for (const render of copy!.findComponents('render') as pc.RenderComponent[]) expect(render.castShadows).toBe(false);
    const drawn = materialsOf(copy!);
    expect(drawn.length).toBeGreaterThan(0);
    for (const material of drawn) {
      expect(material.useLighting).toBe(false);
      expect(material.diffuseMap).toBeNull();
      expect(light(material)).toEqual([255, 255, 255]);
      expect(material.opacity).toBeCloseTo(0.3, 6);
    }
    // A light copy of its own: the placed thing of the same kind keeps its surface.
    const own = materialsOf(layer.figureOf('well')!.root);
    for (const material of own) expect(material.opacity).toBe(1);
    expect(drawn.some((material) => own.includes(material))).toBe(false);
    expect(await layer.setKindGhost(ghost('well', 2, 9000, { refused: true }))).toBe(true);
    for (const material of materialsOf(copy!)) {
      expect(light(material)).toEqual([0xff, 0x8f, 0x7e]);
      expect(material.opacity).toBeCloseTo(0.4, 6);
    }
    await layer.setKindGhost(ghost('well', 2, 9000));
    for (const material of materialsOf(copy!)) expect(light(material)).toEqual([255, 255, 255]);
    expect(copies(region)).toEqual([copy]);
    // The placed well's container and the copy's: tinting again made nothing again.
    expect(looks.made).toEqual(['primitive-well', 'primitive-well']);
  });

  it('goes with null, and gives way to a copy of another kind', async () => {
    const { layer, region, ghost } = setup();
    await layer.setKindGhost(ghost('well', 2, 9000));
    expect(await layer.setKindGhost(null)).toBe(false);
    expect(copies(region)).toEqual([]);
    await layer.setKindGhost(ghost('well', 2, 9000));
    expect(await layer.setKindGhost(ghost('bench', 1, 3000))).toBe(true);
    expect(copies(region)).toHaveLength(1);
    expect(copies(region)[0]!.findByName('model:bench')).not.toBeNull();
    expect(region.findByName('model:primitive-well')).toBeNull();
    // A region this world does not draw has no copy, and takes the one drawn away.
    expect(await layer.setKindGhost({ ...ghost('bench', 1, 3000), regionId: 'elsewhere' })).toBe(false);
    expect(copies(region)).toEqual([]);
  });

  it('leaves nothing behind when its make finishes after it is no longer wanted', async () => {
    const { layer, region, looks, ghost } = setup();
    const before = region.children.length;
    looks.hold('primitive-well');
    const late = layer.setKindGhost(ghost('well', 2, 9000));
    await until(() => looks.made.length === 1, 'the well\'s container');
    expect(await layer.setKindGhost(null)).toBe(false);
    looks.release('primitive-well');
    expect(await late).toBe(false);
    expect(region.children.length).toBe(before);
    expect(region.findByName('model:primitive-well')).toBeNull();
    // Overtaken by another kind: only the newer kind's copy stands.
    looks.hold('primitive-well');
    const overtaken = layer.setKindGhost(ghost('well', 2, 9000));
    await until(() => looks.made.length === 2, 'the well\'s second container');
    expect(await layer.setKindGhost(ghost('bench', 1, 3000))).toBe(true);
    looks.release('primitive-well');
    expect(await overtaken).toBe(false);
    expect(copies(region)).toHaveLength(1);
    expect(region.findByName('model:primitive-well')).toBeNull();
    expect(region.findByName('model:bench')).not.toBeNull();
  });

  it('has no copy of a kind this page cannot draw, and does not make it again until another kind is asked for', async () => {
    const { layer, region, ghost } = setup();
    const make = vi.spyOn(layer.maker, 'make');
    const missing: KindGhost = { ...ghost('well', 2, 9000), kind: { kind: 'well', version: 2, sha256: '0'.repeat(64) } };
    expect(await layer.setKindGhost(missing)).toBe(false);
    expect(await layer.setKindGhost({ ...missing, xMm: 8000 })).toBe(false);
    expect(make).toHaveBeenCalledTimes(1);
    expect(copies(region)).toEqual([]);
    expect(await layer.setKindGhost(ghost('well', 2, 9000))).toBe(true);
    expect(await layer.setKindGhost(missing)).toBe(false);
    expect(make).toHaveBeenCalledTimes(3);
  });

  it('makes a kind its maker drew nothing for only once, until another kind is asked for', async () => {
    const { layer, region, ghost } = setup();
    // The maker draws nothing for it (a kind the library does not serve yet): no copy, and not made again on each move.
    const make = vi.spyOn(layer.maker, 'make').mockResolvedValue(null);
    expect(await layer.setKindGhost(ghost('well', 2, 9000))).toBe(false);
    expect(await layer.setKindGhost(ghost('well', 2, 8000))).toBe(false);
    expect(make).toHaveBeenCalledTimes(1);
    expect(copies(region)).toEqual([]);
    expect(await layer.setKindGhost(ghost('bench', 2, 9000))).toBe(false);
    expect(make).toHaveBeenCalledTimes(2);
  });

  it('is taken away with the layer', async () => {
    const { layer, region, ghost } = setup();
    await layer.setKindGhost(ghost('well', 2, 9000));
    layer.destroy();
    expect(copies(region)).toEqual([]);
    expect(await layer.setKindGhost(ghost('well', 2, 9000))).toBe(false);
    expect(copies(region)).toEqual([]);
  });
});
