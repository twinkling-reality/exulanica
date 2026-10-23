// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import * as pc from 'playcanvas';
import type { LookDrawing } from '../src/playcanvas/things/documents.js';
import { ThingFigureMaker } from '../src/playcanvas/things/figure-maker.js';
import { KindPictures, drawnPoints, headOf, uprightPixels, type PictureFrame } from '../src/playcanvas/things/kind-picture.js';
import type { ThingFigure } from '../src/playcanvas/things/figures.js';
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
  /** The camera's view of the corners of every part the stage draws. */
  readonly drawnCorners: ReadonlyArray<readonly [number, number]>;
  /** The camera's view of the corners of each named part (`part:<name>`) the figure draws. */
  readonly parts: ReadonlyMap<string, ReadonlyArray<readonly [number, number]>>;
}

/** A blocky body's joints standing (the things contract's figures, glTF metres), and the boxes drawn on some of them. */
const BLOCKY: Record<string, [number, number, number]> = {
  hips: [0, 0.9, 0], spine: [0, 1, 0], chest: [0, 1.15, 0], neck: [0, 1.4, 0], head: [0, 1.45, 0],
  leftUpperLeg: [0.09, 0.86, 0], leftLowerLeg: [0.09, 0.46, 0], leftFoot: [0.09, 0.08, 0],
  rightUpperLeg: [-0.09, 0.86, 0], rightLowerLeg: [-0.09, 0.46, 0], rightFoot: [-0.09, 0.08, 0],
  leftUpperArm: [0.2, 1.35, 0], leftLowerArm: [0.46, 1.35, 0], leftHand: [0.7, 1.35, 0],
  rightUpperArm: [-0.2, 1.35, 0], rightLowerArm: [-0.46, 1.35, 0], rightHand: [-0.7, 1.35, 0],
};
const BLOCKY_BOXES: Record<string, [number, number, number]> = { head: [0.3, 0.3, 0.3], neck: [0.12, 0.06, 0.12], chest: [0.5, 0.4, 0.25], hips: [0.4, 0.8, 0.25] };

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
    if (look.lookKind === 'rigid_on_bones') {
      for (const [bone, at] of Object.entries(BLOCKY)) {
        const node = new pc.Entity(`bone:${bone}`);
        node.setLocalPosition(...at);
        const size = BLOCKY_BOXES[bone];
        if (size !== undefined) {
          const part = new pc.Entity(`part:${bone}`);
          part.addComponent('render', { type: 'box' });
          part.setLocalScale(...size);
          part.setLocalPosition(0, bone === 'hips' || bone === 'neck' ? -size[1] / 2 : size[1] / 2, 0);
          node.addChild(part);
        }
        model.addChild(node);
      }
      return Promise.resolve({ model, tracks: new Map<string, pc.AnimTrack>() });
    }
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
    const drawnCorners = drawnPoints(stage).map((point) => {
      const at = frame.camera.camera.worldToScreen(point, frame.width, frame.height);
      return [at.x, at.y] as const;
    });
    const parts = new Map<string, Array<readonly [number, number]>>();
    for (const render of stage.findComponents('render') as pc.RenderComponent[]) {
      if (!render.entity.name.startsWith('part:')) continue;
      parts.set(render.entity.name.slice('part:'.length), drawnPoints(render.entity).map((point) => {
        const at = frame.camera.camera.worldToScreen(point, frame.width, frame.height);
        return [at.x, at.y] as const;
      }));
    }
    seen.push({
      parts,
      drawnCorners,
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

  it('draws a kind in a look it is given, its first look without one, each its own picture', async () => {
    const { pictures, made, served } = setup();
    const sword = { key: 'sword', version: 3, sha256: served.kindRef('sword', 3).sha256 };
    const second = (thingsJson('kinds/sword.v3.json')['looks'] as { look: string; version: number; sha256: string }[])[1]!;
    const look = { key: second.look, version: second.version, sha256: second.sha256 };
    expect(await pictures.picture(sword, { width: 96, height: 96 })).toBe(PICTURE);
    expect(await pictures.picture(sword, { width: 96, height: 96 }, { look })).toBe(PICTURE);
    expect(await pictures.picture(sword, { width: 96, height: 96 }, { look })).toBe(PICTURE);
    expect(made).toEqual(['kaykit-sword', 'primitive-sword']);
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

  it('makes the figures of pictures waiting their turn while an earlier one is taken, the pictures still one at a time', async () => {
    const { app, pictures, seen, made, release, well } = setup({ held: true });
    const asked = [96, 112, 128, 144].map((width) => pictures.picture(well, { width, height: 72 }));
    await until(() => seen.length === 1, 'the first picture\'s frame');
    // Every later figure is made while the first picture is held: one making after another would have made none.
    await until(() => made.length === 4, 'the later figures made ahead');
    for (let tick = 0; tick < 5; tick += 1) await Promise.resolve();
    expect(seen).toHaveLength(1);
    // Made away from the scene: only the picture being taken stands in it.
    expect(app.root.find((node) => node.name === 'thing-picture')).toHaveLength(1);
    release();
    expect(await Promise.all(asked)).toEqual([PICTURE, PICTURE, PICTURE, PICTURE]);
    expect(seen.map((one) => one.frame.width)).toEqual([96, 112, 128, 144]);
  });

  it('puts away the figures made ahead with the pictures, leaving nothing behind', async () => {
    const { app, pictures, seen, made, release, well } = setup({ held: true });
    const before = census(app);
    const asked = [96, 112, 128].map((width) => pictures.picture(well, { width, height: 72 }));
    await until(() => seen.length === 1 && made.length === 3, 'a picture held and two figures made ahead');
    pictures.destroy();
    release();
    expect(await Promise.all(asked)).toEqual([null, null, null]);
    expect(seen).toHaveLength(1);
    expect(census(app)).toEqual(before);
    expect(app.root.findByName('thing-picture')).toBeNull();
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

  it('framed round, fills the circle inscribed in the picture with all it draws, centred, a picture of its own', async () => {
    const { pictures, seen, made, well } = setup();
    expect(await pictures.picture(well, { width: 156, height: 156 }, { round: true })).toBe(PICTURE);
    const [one] = seen;
    // Every corner of every part it draws inside the circle, the farthest nearly on it, all of it centred; no shadow.
    expect(one!.drawnCorners).toHaveLength(8);
    const radii = one!.drawnCorners.map(([x, y]) => Math.hypot(x - 78, y - 78) / 78);
    for (const radius of radii) expect(radius).toBeLessThan(0.97);
    expect(Math.max(...radii)).toBeGreaterThan(0.92);
    const xs = one!.drawnCorners.map(([x]) => x), ys = one!.drawnCorners.map(([, y]) => y);
    expect(Math.abs((Math.min(...xs) + Math.max(...xs)) / 2 - 78)).toBeLessThan(156 * 0.02);
    expect(Math.abs((Math.min(...ys) + Math.max(...ys)) / 2 - 78)).toBeLessThan(156 * 0.02);
    expect(one!.frame.contact).toBeNull();
    // The same kind framed whole is another picture.
    expect(await pictures.picture(well, { width: 156, height: 156 })).toBe(PICTURE);
    expect(made).toEqual(['primitive-well', 'primitive-well']);
  });

  it('framed round, an upright body with a head by its head, as large in the circle as a person\'s, the body out of it', async () => {
    const { pictures, seen, served } = setup();
    const knight = { key: 'knight', version: 1, sha256: served.kindRef('knight', 1).sha256 };
    expect(await pictures.picture(knight, { width: 156, height: 156 }, { round: true })).toBe(PICTURE);
    const parts = seen[0]!.parts;
    // The head's box in the picture, nine tenths of it tall (the head drawn within it measures about three
    // quarters, as a person's portrait shows one) and its middle about halfway down; the legs run out below it.
    expect([...parts.keys()].sort()).toEqual(['chest', 'head', 'hips', 'neck']);
    const head = parts.get('head')!.map(([, y]) => y);
    for (const [x, y] of parts.get('head')!) expect(x >= 0 && x <= 156 && y >= 0 && y <= 156).toBe(true);
    expect((Math.max(...head) - Math.min(...head)) / 156).toBeGreaterThan(0.85);
    expect((Math.max(...head) - Math.min(...head)) / 156).toBeLessThan(0.95);
    expect(Math.abs((Math.max(...head) + Math.min(...head)) / 2 - 78)).toBeLessThan(156 * 0.1);
    expect(Math.min(...parts.get('hips')!.map(([, y]) => y))).toBeGreaterThan(156);
    // Seen nearer its face than a whole figure is: about 15 degrees round from its front, not 35.
    const eye = seen[0]!.frame.camera.entity.getPosition(), at = seen[0]!.frame.camera.entity.forward;
    expect(Math.abs((Math.atan2(-at.x, -at.z) * 180) / Math.PI)).toBeLessThan(25);
    expect(eye.z).toBeGreaterThan(0);
  });

  it('frames a portrait by the head its skeleton names, past the neck, only for an upright body with a head', () => {
    const root = new pc.Entity('figure');
    const nodes = new Map<string, pc.Entity>();
    for (const bone of ['chest', 'neck', 'head', 'hips']) {
      const node = new pc.Entity(`bone:${bone}`);
      nodes.set(bone, node);
      (bone === 'head' ? nodes.get('neck')! : root).addChild(node);
    }
    const limb = (role: string, bones: string[]) => ({ role, from: 'chest', bones });
    const figure = (lying: boolean, limbs: ReturnType<typeof limb>[] | null) =>
      ({ root, ...(limbs === null ? {} : { skeleton: { lying, limbs } }) }) as unknown as ThingFigure;
    const person = [limb('arm', ['leftUpperArm']), limb('head', ['neck', 'head']), limb('leg', ['leftUpperLeg'])];
    expect(headOf(figure(false, person))).toBe(nodes.get('head'));
    // A body along the ground, a body with no head, a head whose joint is not drawn, a figure with no skeleton: framed whole.
    expect(headOf(figure(true, person))).toBeNull();
    expect(headOf(figure(false, [limb('arm', ['leftUpperArm'])]))).toBeNull();
    expect(headOf(figure(false, [limb('head', ['skull'])]))).toBeNull();
    expect(headOf(figure(false, null))).toBeNull();
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
