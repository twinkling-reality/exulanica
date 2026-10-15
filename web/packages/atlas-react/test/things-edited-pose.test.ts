// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import type { OwnedSocietyState, SocietyThingSnapshot } from '../src/playcanvas/society/types.js';
import type { LookDrawing } from '../src/playcanvas/things/documents.js';
import { ThingLayer, type PlacedThingRecord } from '../src/playcanvas/things/thing-layer.js';
import { ThingLibrary } from '../src/playcanvas/things/library.js';
import { servedLibrary, until } from './things-fixtures.js';

/*
 * An edit made while a society's minute stands still is drawn at once: a moved object stands where
 * its version now puts it, a thing brought back is drawn, while the minutes drawn still show it as it
 * was before the edit; a minute that took the edit in draws it again. A being stays the crowd's to
 * draw. An editor's see-through copy of a placed thing is drawn apart from it, never picked, throws
 * no shadow, and is drawn as a light copy, coral where the world refused the spot.
 */

function instance(look: LookDrawing) {
  const model = new pc.Entity(`model:${look.look}`);
  const part = new pc.Entity(`part:${look.look}`);
  part.addComponent('render', { type: 'box' });
  model.addChild(part);
  return Promise.resolve({ model, tracks: new Map<string, pc.AnimTrack>() });
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
  const layer = new ThingLayer({ app, camera, library, regionRoot: () => region, ringColour: '#f4ff91', instantiate: instance });
  return { served, layer, region };
}

const step = (layer: ThingLayer) => (layer as unknown as { step(dt: number): void }).step(1 / 60);

function well(served: ReturnType<typeof servedLibrary>, xMm: number, zMm = 1000): PlacedThingRecord {
  return {
    thingId: 'well', kind: served.kindRef('well', 2), regionId: 'r',
    transform: { xMm, yMm: 0, zMm, yawMicroradians: 0, scaleMilli: 1000 }, removed: false,
  };
}

function minute(tick: number, things: readonly SocietyThingSnapshot[]): OwnedSocietyState {
  return { profile: 'exulanica-society/v7', society_id: 's', branch_id: 'b', tick, inhabitants: [], things };
}

const listed = (xMm: number, zMm = 1000): SocietyThingSnapshot =>
  ({ id: 'society-well', placed_id: 'well', position_mm: [xMm, zMm], held_by: null } as unknown as SocietyThingSnapshot);

async function drawnWell() {
  const made = setup();
  await made.layer.setPlaced([well(made.served, 2000)]);
  await until(() => made.layer.figureOf('well') !== null, 'the well\'s figure');
  made.layer.setSociety(minute(5, [listed(2000)]), null);
  step(made.layer);
  return made;
}

const eastOf = (layer: ThingLayer) => layer.figureOf('well')!.root.getLocalPosition().x;

describe('an edit made while the minute stands still is drawn at once', () => {
  it('stands a moved object where its version now puts it, until a later minute lists it there', async () => {
    const { served, layer } = await drawnWell();
    expect(eastOf(layer)).toBeCloseTo(2, 6);
    await layer.setPlaced([well(served, 6000)]);
    step(layer);
    expect(eastOf(layer)).toBeCloseTo(6, 6);
    // The same minute read again changes nothing.
    layer.setSociety(minute(5, [listed(2000)]), null);
    step(layer);
    expect(eastOf(layer)).toBeCloseTo(6, 6);
    // The next minute lists it at its new place: the society draws it again, there.
    layer.setSociety(minute(6, [listed(6000)]), null);
    step(layer);
    expect(eastOf(layer)).toBeCloseTo(6, 6);
    layer.setSociety(minute(7, [listed(5000)]), null);
    step(layer);
    expect(eastOf(layer)).toBeCloseTo(5, 6);
  });

  it('keeps it there while minutes still list it at its old spot, however many pass', async () => {
    const { served, layer } = await drawnWell();
    await layer.setPlaced([well(served, 6000)]);
    for (const tick of [6, 7, 8, 30]) {
      layer.setSociety(minute(tick, [listed(2000)]), null);
      step(layer);
      expect(eastOf(layer)).toBeCloseTo(6, 6);
    }
    // A minute that put it anywhere else took the edit in: the society draws it again, there.
    layer.setSociety(minute(31, [listed(4000)]), null);
    step(layer);
    expect(eastOf(layer)).toBeCloseTo(4, 6);
  });

  it('keeps the newest of two moves made within one minute until a minute takes the newest in', async () => {
    const { served, layer } = await drawnWell();
    await layer.setPlaced([well(served, 6000)]);
    await layer.setPlaced([well(served, 8000)]);
    step(layer);
    expect(eastOf(layer)).toBeCloseTo(8, 6);
    // A minute that took only the first move in lists the middle spot: the drawing stays.
    layer.setSociety(minute(6, [listed(6000)]), null);
    step(layer);
    expect(eastOf(layer)).toBeCloseTo(8, 6);
    layer.setSociety(minute(7, [listed(8000)]), null);
    layer.setSociety(minute(8, [listed(7000)]), null);
    step(layer);
    expect(eastOf(layer)).toBeCloseTo(7, 6);
  });

  it('keeps a newly placed thing moved before any minute listed it, past a minute at its first spot', async () => {
    const { served, layer } = await drawnWell();
    const bench: PlacedThingRecord = { ...well(served, 0, 5000), thingId: 'bench', kind: served.kindRef('bench', 1) };
    await layer.setPlaced([well(served, 2000), bench]);
    await until(() => layer.figureOf('bench') !== null, 'the bench\'s figure');
    await layer.setPlaced([well(served, 2000), { ...bench, transform: { ...bench.transform, xMm: 3000 } }]);
    const benchEast = () => layer.figureOf('bench')!.root.getLocalPosition().x;
    layer.setSociety(minute(6, [listed(2000), { ...listed(0, 5000), id: 'society-bench', placed_id: 'bench' } as SocietyThingSnapshot]), null);
    step(layer);
    expect(benchEast()).toBeCloseTo(3, 6);
    expect(layer.figureOf('bench')!.root.enabled).toBe(true);
  });

  it('keeps an edit made before any minute was read when the first minute predates it', async () => {
    const { served, layer } = setup();
    await layer.setPlaced([well(served, 2000)]);
    await until(() => layer.figureOf('well') !== null, 'the well\'s figure');
    await layer.setPlaced([well(served, 6000)]);
    layer.setSociety(minute(5, [listed(2000)]), null);
    step(layer);
    expect(eastOf(layer)).toBeCloseTo(6, 6);
    layer.setSociety(minute(6, [listed(6000)]), null);
    layer.setSociety(minute(7, [listed(5000)]), null);
    step(layer);
    expect(eastOf(layer)).toBeCloseTo(5, 6);
  });

  it('draws a thing brought back that the standing minute does not list', async () => {
    const { served, layer } = await drawnWell();
    layer.setSociety(minute(6, []), null);
    step(layer);
    expect(layer.figureOf('well')!.root.enabled).toBe(false);
    await layer.setPlaced([]);
    await layer.setPlaced([well(served, 2000)]);
    await until(() => layer.figureOf('well') !== null, 'the well brought back');
    step(layer);
    expect(layer.figureOf('well')!.root.enabled).toBe(true);
  });

  it('leaves a thing the version first stood, and the society does not list, hidden', async () => {
    const { served, layer } = setup();
    layer.setSociety(minute(3, []), null);
    await layer.setPlaced([well(served, 2000)]);
    await until(() => layer.figureOf('well') !== null, 'the well\'s figure');
    step(layer);
    expect(layer.figureOf('well')!.root.enabled).toBe(false);
  });
});

describe('a fresh page, where the society read states the edit its minute took in', () => {
  const stated = (tick: number, things: readonly SocietyThingSnapshot[], edit: number): OwnedSocietyState =>
    ({ ...minute(tick, things), authored_edit_seq: edit });

  it('draws a thing whose newest edit the minute has not taken in as its version says, until it has', async () => {
    const { served, layer } = setup();
    await layer.setPlaced([{ ...well(served, 6000), editSeq: 5 }]);
    await until(() => layer.figureOf('well') !== null, 'the well\'s figure');
    layer.setSociety(stated(9, [listed(2000)], 4), null);
    step(layer);
    expect(eastOf(layer)).toBeCloseTo(6, 6);
    layer.setSociety(stated(10, [listed(6000)], 5), null);
    layer.setSociety(stated(11, [listed(5000)], 5), null);
    step(layer);
    expect(eastOf(layer)).toBeCloseTo(5, 6);
  });

  it('draws a thing as the society has it where the minute took its newest edit in', async () => {
    const { served, layer } = setup();
    await layer.setPlaced([{ ...well(served, 6000), editSeq: 4 }]);
    await until(() => layer.figureOf('well') !== null, 'the well\'s figure');
    layer.setSociety(stated(9, [listed(2000)], 4), null);
    step(layer);
    expect(eastOf(layer)).toBeCloseTo(2, 6);
  });

  it('draws a thing placed after the minute even though the minute does not list it', async () => {
    const { served, layer } = setup();
    await layer.setPlaced([{ ...well(served, 6000), editSeq: 7 }]);
    await until(() => layer.figureOf('well') !== null, 'the well\'s figure');
    layer.setSociety(stated(9, [], 6), null);
    step(layer);
    expect(layer.figureOf('well')!.root.enabled).toBe(true);
    expect(eastOf(layer)).toBeCloseTo(6, 6);
  });
});

describe('an editor\'s see-through copy of a placed thing', () => {
  it('stands apart from the thing, is never picked, and goes when asked', async () => {
    const { layer, region } = await drawnWell();
    const shadows = () => (layer.figureOf('well')!.root.findComponents('render') as pc.RenderComponent[]).map((render) => render.castShadows);
    layer.setPicked({ placedId: 'well', thingId: null, subjectId: null });
    const shadowsBefore = shadows();
    expect(shadowsBefore).toContain(true);
    layer.setGhost({ placedId: 'well', xMm: 9000, yMm: 0, zMm: 1000, yawMicroradians: 1_570_796, refused: false });
    const ghost = region.findByName('thing-ghost:well') as pc.Entity;
    expect(ghost).not.toBeNull();
    // The picked thing keeps its ring; its copy has none.
    expect(ghost.findByName('thing-pick-ring')).toBeNull();
    expect(layer.figureOf('well')!.root.findByName('thing-pick-ring')).not.toBeNull();
    expect(ghost.getLocalPosition().x).toBeCloseTo(9, 6);
    expect(ghost.getLocalEulerAngles().y).toBeCloseTo(90, 3);
    expect(eastOf(layer)).toBeCloseTo(2, 6);
    const drawn = (ghost.findComponents('render') as pc.RenderComponent[]).flatMap((render) => render.meshInstances);
    const original = (layer.figureOf('well')!.root.findComponents('render') as pc.RenderComponent[]).flatMap((render) => render.meshInstances);
    expect(drawn.length).toBeGreaterThan(0);
    for (const one of drawn) {
      expect((one.material as pc.StandardMaterial).opacity).toBeCloseTo(0.3, 6);
      expect(original.some((other) => other.material === one.material)).toBe(false);
    }
    for (const one of original) expect((one.material as pc.StandardMaterial).opacity).toBe(1);
    // It throws no shadow of its own; the thing's own shadows are as they were.
    for (const render of ghost.findComponents('render') as pc.RenderComponent[]) expect(render.castShadows).toBe(false);
    expect(shadows()).toEqual(shadowsBefore);
    // A ray down onto the copy's spot meets nothing: the copy is not a thing.
    expect(layer.pick([9, 5, 1], [0, -1, 0])).toBeNull();
    layer.setGhost(null);
    expect(region.findByName('thing-ghost:well')).toBeNull();
  });

  it('is a light copy, drawn unlit, and coral where the world refused the spot', async () => {
    const { layer, region } = await drawnWell();
    const materials = () => ((region.findByName('thing-ghost:well') as pc.Entity).findComponents('render') as pc.RenderComponent[])
      .flatMap((render) => render.meshInstances).map((one) => one.material as pc.StandardMaterial);
    const light = (material: pc.StandardMaterial) => [material.emissive.r, material.emissive.g, material.emissive.b].map((v) => Math.round(v * 255));
    layer.setGhost({ placedId: 'well', xMm: 9000, yMm: 0, zMm: 1000, yawMicroradians: 0, refused: false });
    for (const material of materials()) {
      expect(material.useLighting).toBe(false);
      expect(material.diffuseMap).toBeNull();
      expect(light(material)).toEqual([255, 255, 255]);
      expect(material.opacity).toBeCloseTo(0.3, 6);
    }
    layer.setGhost({ placedId: 'well', xMm: 9000, yMm: 0, zMm: 1000, yawMicroradians: 0, refused: true });
    for (const material of materials()) {
      expect(light(material)).toEqual([0xff, 0x8f, 0x7e]);
      expect(material.opacity).toBeCloseTo(0.4, 6);
    }
    expect(region.findByName('thing-ghost:well')).not.toBeNull();
  });
});
