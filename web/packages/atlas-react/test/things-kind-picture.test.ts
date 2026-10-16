// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import * as pc from 'playcanvas';
import type { LookDrawing } from '../src/playcanvas/things/documents.js';
import { ThingFigureMaker } from '../src/playcanvas/things/figure-maker.js';
import { KindPictures, uprightPixels, type PictureFrame } from '../src/playcanvas/things/kind-picture.js';
import { ThingLibrary } from '../src/playcanvas/things/library.js';
import { ThingLayer } from '../src/playcanvas/things/thing-layer.js';
import { servedLibrary, thingsJson, until } from './things-fixtures.js';

/*
 * A kind's picture for build mode's tray, drawn here without a GPU: the frame's read is the one part
 * a test replaces. A kind is made once a size and asks share one drawing; its figure stands alone on
 * a layer only the picture's camera draws, the whole of it in frame; a kind that cannot be made
 * answers null; and everything made for a picture is gone after it, whatever the answer.
 */

const PICTURE = 'data:image/png;base64,UElDVFVSRQ==';

/** What the read saw of its frame: the picture's layer, where each part stands, and the camera's view of the kind's box. */
interface Seen {
  readonly frame: PictureFrame;
  readonly layerId: number;
  readonly worldCameraLayers: readonly number[];
  readonly renderLayers: ReadonlyArray<readonly number[]>;
  readonly lightLayers: ReadonlyArray<readonly number[]>;
  readonly shadows: readonly boolean[];
  readonly corners: ReadonlyArray<readonly [number, number]>;
}

function setup({ answer = PICTURE as string | null, held = false } = {}) {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem, pc.LightComponentSystem];
  app.init(options);
  const world = new pc.Entity('world-camera');
  world.addComponent('camera');
  app.root.addChild(world);
  const served = servedLibrary();
  const library = new ThingLibrary(served.list, (digest) => served.fetch(digest));
  const made: string[] = [];
  const instantiate = (look: LookDrawing) => {
    made.push(look.look);
    const model = new pc.Entity(`model:${look.look}`);
    const part = new pc.Entity(`part:${look.look}`);
    part.addComponent('render', { type: 'box' });
    model.addChild(part);
    return Promise.resolve({ model, tracks: new Map<string, pc.AnimTrack>() });
  };
  const maker = new ThingFigureMaker({ app, library, instantiate });
  const seen: Seen[] = [];
  let release: () => void = () => undefined;
  const gate = held ? new Promise<void>((resolve) => { release = resolve; }) : Promise.resolve();
  const read = async (frame: PictureFrame): Promise<string | null> => {
    const layerId = frame.camera.layers[0]!;
    const stage = app.root.findByName('thing-picture') as pc.Entity;
    const box = thingsJson('kinds/well.v2.json')['body'] as { box_mm: { width: number; depth: number; height: number } };
    const { width, depth, height } = box.box_mm;
    const corners: Array<readonly [number, number]> = [];
    for (const x of [-width / 2000, width / 2000]) {
      for (const y of [0, height / 1000]) {
        for (const z of [-depth / 2000, depth / 2000]) {
          const at = frame.camera.camera.worldToScreen(new pc.Vec3(x, y, z), frame.width, frame.height);
          corners.push([at.x, at.y]);
        }
      }
    }
    seen.push({
      frame,
      layerId,
      worldCameraLayers: [...world.camera!.layers],
      renderLayers: (stage.findComponents('render') as pc.RenderComponent[]).map((render) => [...render.layers]),
      lightLayers: (stage.findComponents('light') as pc.LightComponent[]).map((light) => [...light.layers]),
      shadows: (stage.findComponents('render') as pc.RenderComponent[]).map((render) => render.castShadows),
      corners,
    });
    await gate;
    return answer;
  };
  const invalidate = vi.fn();
  const pictures = new KindPictures({ app, maker, invalidate, read });
  const well = { key: 'well', version: 2, sha256: served.kindRef('well', 2).sha256 };
  return { app, device, served, made, maker, pictures, seen, release: () => release(), invalidate, well };
}

/** What a picture could leave behind: entities, layers, textures and targets. */
function census(app: pc.AppBase) {
  const device = app.graphicsDevice as unknown as { textures: Set<unknown>; targets: Set<unknown> };
  return {
    entities: app.root.find(() => true).length,
    layers: app.scene.layers.layerList.length,
    textures: device.textures.size,
    targets: device.targets.size,
  };
}

describe('a kind\'s picture for build mode\'s tray', () => {
  it('draws a kind once a size, and asks while it is drawn share that drawing', async () => {
    const { pictures, made, seen, release, well } = setup({ held: true });
    const first = pictures.picture(well, { width: 96, height: 96 });
    await until(() => seen.length === 1, 'the picture\'s frame');
    const second = pictures.picture(well, { width: 96, height: 96 });
    release();
    expect(await first).toBe(PICTURE);
    expect(await second).toBe(PICTURE);
    expect(await pictures.picture(well, { width: 96, height: 96 })).toBe(PICTURE);
    expect(made).toEqual(['primitive-well']);
    expect(seen).toHaveLength(1);
    // Another size is another picture.
    expect(await pictures.picture(well, { width: 128, height: 96 })).toBe(PICTURE);
    expect(made).toEqual(['primitive-well', 'primitive-well']);
    expect(seen.map((one) => [one.frame.width, one.frame.height])).toEqual([[96, 96], [128, 96]]);
  });

  it('draws pictures asked for together one at a time', async () => {
    const { pictures, seen, release, well } = setup({ held: true });
    const small = pictures.picture(well, { width: 96, height: 72 });
    const large = pictures.picture(well, { width: 112, height: 84 });
    await until(() => seen.length === 1, 'the first picture\'s frame');
    // The second waits its turn: no camera or target of its own stands while the first is drawn.
    for (let tick = 0; tick < 5; tick += 1) await Promise.resolve();
    expect(seen).toHaveLength(1);
    release();
    expect(await small).toBe(PICTURE);
    expect(await large).toBe(PICTURE);
    expect(seen.map((one) => [one.frame.width, one.frame.height])).toEqual([[96, 72], [112, 84]]);
  });

  it('draws the figure alone on a layer only its camera draws, the whole of it in frame and centred', async () => {
    const { pictures, seen, well } = setup();
    expect(await pictures.picture(well, { width: 160, height: 120 })).toBe(PICTURE);
    const [one] = seen;
    const { frame, layerId } = one!;
    expect([...frame.camera.layers]).toEqual([layerId]);
    expect(frame.camera.renderTarget?.colorBuffer).toBe(frame.texture);
    expect([frame.texture.width, frame.texture.height]).toEqual([160, 120]);
    // The world's camera does not draw the picture's layer, and no part of the figure is on another.
    expect(one!.worldCameraLayers).not.toContain(layerId);
    expect(one!.renderLayers.length).toBeGreaterThan(0);
    for (const layers of one!.renderLayers) expect(layers).toEqual([layerId]);
    expect(one!.lightLayers.length).toBeGreaterThan(0);
    for (const layers of one!.lightLayers) expect(layers).toEqual([layerId]);
    expect(one!.shadows.every((casts) => !casts)).toBe(true);
    // Every corner of the kind's box inside the picture, clear of its edge, and the box centred.
    const xs = one!.corners.map(([x]) => x), ys = one!.corners.map(([, y]) => y);
    for (const x of xs) expect(x > 160 * 0.02 && x < 160 * 0.98).toBe(true);
    for (const y of ys) expect(y > 120 * 0.02 && y < 120 * 0.98).toBe(true);
    expect(Math.abs((Math.min(...xs) + Math.max(...xs)) / 2 - 80)).toBeLessThan(160 * 0.02);
    expect(Math.abs((Math.min(...ys) + Math.max(...ys)) / 2 - 60)).toBeLessThan(120 * 0.02);
    // It fills about seven tenths of the picture on one side or the other (DESIGN, 16 October).
    const fill = Math.max((Math.max(...xs) - Math.min(...xs)) / 160, (Math.max(...ys) - Math.min(...ys)) / 120);
    expect(fill).toBeGreaterThan(0.62);
    expect(fill).toBeLessThan(0.78);
    // Its shadow is the ellipse around its footprint as drawn: under its middle, in the lower part of the picture.
    const contact = frame.contact!;
    expect(contact).not.toBeNull();
    expect(Math.abs(contact.x - 80)).toBeLessThan(160 * 0.15);
    expect(contact.y).toBeGreaterThan(60);
    expect(contact.y).toBeLessThan(Math.max(...ys) + 1);
    expect(contact.rx).toBeGreaterThan(0);
    expect(contact.ry).toBeGreaterThanOrEqual(contact.rx * 0.2 - 1e-9);
  });

  it('answers null for a kind that cannot be made, and draws nothing for it', async () => {
    const { app, pictures, seen, well } = setup();
    const before = census(app);
    expect(await pictures.picture({ ...well, sha256: '0'.repeat(64) }, { width: 96, height: 96 })).toBeNull();
    expect(await pictures.picture({ source: 'workspace', sha256: '1'.repeat(64) }, { width: 96, height: 96 })).toBeNull();
    expect(await pictures.picture(well, { width: 0, height: 96 })).toBeNull();
    expect(seen).toEqual([]);
    expect(census(app)).toEqual(before);
  });

  it('leaves nothing behind after a picture, whatever the answer, and keeps no picture it could not draw', async () => {
    const drawn = setup();
    const before = census(drawn.app);
    expect(await drawn.pictures.picture(drawn.well, { width: 96, height: 96 })).toBe(PICTURE);
    expect(census(drawn.app)).toEqual(before);
    expect(drawn.app.root.findByName('thing-picture')).toBeNull();
    expect(drawn.app.scene.layers.getLayerById(drawn.seen[0]!.layerId)).toBeNull();
    const unread = setup({ answer: null });
    const empty = census(unread.app);
    expect(await unread.pictures.picture(unread.well, { width: 96, height: 96 })).toBeNull();
    expect(census(unread.app)).toEqual(empty);
    // A frame that could not be read is drawn again when asked again.
    expect(await unread.pictures.picture(unread.well, { width: 96, height: 96 })).toBeNull();
    expect(unread.made).toEqual(['primitive-well', 'primitive-well']);
  });

  it('ends a picture still being drawn when the pictures are destroyed', async () => {
    const { app, pictures, seen, release, well } = setup({ held: true });
    const before = census(app);
    const asked = pictures.picture(well, { width: 96, height: 96 });
    await until(() => seen.length === 1, 'the picture\'s frame');
    pictures.destroy();
    expect(seen[0]!.frame.signal.aborted).toBe(true);
    // A read that answers after the end is not a picture.
    release();
    expect(await asked).toBeNull();
    expect(census(app)).toEqual(before);
    expect(await pictures.picture(well, { width: 64, height: 64 })).toBeNull();
    expect(seen).toHaveLength(1);
  });
});

describe('a kind\'s picture through the layer, on a device that reads nothing back', () => {
  function layerSetup() {
    const canvas = document.createElement('canvas');
    const device = new pc.NullGraphicsDevice(canvas);
    const app = new pc.AppBase(canvas);
    const options = new pc.AppOptions();
    options.graphicsDevice = device;
    options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem, pc.LightComponentSystem];
    app.init(options);
    const camera = new pc.Entity('camera');
    app.root.addChild(camera);
    const region = new pc.Entity('region');
    app.root.addChild(region);
    const served = servedLibrary();
    const library = new ThingLibrary(served.list, (digest) => served.fetch(digest));
    const invalidate = vi.fn();
    const instantiate = (look: LookDrawing) => {
      const model = new pc.Entity(`model:${look.look}`);
      const part = new pc.Entity(`part:${look.look}`);
      part.addComponent('render', { type: 'box' });
      model.addChild(part);
      return Promise.resolve({ model, tracks: new Map<string, pc.AnimTrack>() });
    };
    const layer = new ThingLayer({ app, camera, library, regionRoot: () => region, ringColour: '#f4ff91', instantiate, invalidate });
    return { app, layer, served, invalidate };
  }

  it('waits for a frame drawn with its camera, asking for frames until one is, and answers null where nothing reads back', async () => {
    const { app, layer, served, invalidate } = layerSetup();
    const before = census(app);
    const asked = layer.drawKindPicture(served.kindRef('well', 2), { width: 96, height: 96 });
    await until(() => app.root.findByName('thing-picture') !== null, 'the picture\'s stage');
    expect(invalidate).toHaveBeenCalled();
    // A frame the page did not draw: the picture asks for another and waits on.
    const asks = invalidate.mock.calls.length;
    app.fire('frameend');
    expect(invalidate.mock.calls.length).toBe(asks + 1);
    expect(app.root.findByName('thing-picture')).not.toBeNull();
    // A drawn frame: read back, and this device reads nothing, so there is no picture.
    app.fire('postrender');
    app.fire('frameend');
    expect(await asked).toBeNull();
    expect(census(app)).toEqual(before);
  });

  it('answers null for a kind the layer cannot make, and nothing once the layer is gone', async () => {
    const { layer, served } = layerSetup();
    expect(await layer.drawKindPicture({ source: 'workspace', sha256: '2'.repeat(64) }, { width: 96, height: 96 })).toBeNull();
    layer.destroy();
    expect(await layer.drawKindPicture(served.kindRef('well', 2), { width: 96, height: 96 })).toBeNull();
  });
});

describe('a picture read back', () => {
  it('is turned the right way up where the device reads the bottom row first, and its edges keep their colour', () => {
    // Two rows of one pixel: the bottom row read first is red, half covered at its edge.
    const read = new Uint8Array([128, 0, 0, 128, 0, 0, 255, 255]);
    expect([...uprightPixels(read, 1, 2, true)]).toEqual([0, 0, 255, 255, 255, 0, 0, 128]);
    expect([...uprightPixels(read, 1, 2, false)]).toEqual([255, 0, 0, 128, 0, 0, 255, 255]);
  });
});
