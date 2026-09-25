// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import * as pc from 'playcanvas';
import { CHARACTER_CATALOG } from '../src/playcanvas/character/catalog-data.js';
import { activityPosture, seatPosture } from '../src/playcanvas/character/catalog.js';
import { CharacterHost } from '../src/playcanvas/character/host.js';
import { inhabitantRenderable } from '../src/playcanvas/character/inhabitant.js';
import type { LayeredCharacterRenderable } from '../src/playcanvas/character/renderable.js';

/*
 * A person drawn at a seat takes the family's seat posture for the activity, and a full person's
 * feet are planted on the ground below the seat rather than carried up with the body. At no seat,
 * the same activity keeps the posture it always had.
 */

function application() {
  const canvas = document.createElement('canvas');
  canvas.id = `seated-${Math.random().toString(36).slice(2)}`;
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem, pc.AnimComponentSystem];
  options.resourceHandlers = [pc.ContainerHandler, pc.AnimClipHandler, pc.AnimStateGraphHandler];
  app.init(options);
  const parent = new pc.Entity('people', app);
  app.root.addChild(parent);
  return { app, device, parent };
}

const identity = (inhabitantId: string) => ({ societyId: 'society', branchId: 'branch', inhabitantId });
const family = CHARACTER_CATALOG.families[0]!;

afterEach(() => vi.unstubAllGlobals());

describe('a person at a seat', () => {
  it('takes the seat posture the family declares, and the ground posture at no seat', () => {
    expect(seatPosture(family, 'rest')).toBe('perched');
    expect(activityPosture(family, 'rest', true)).toBe('perched');
    expect(activityPosture(family, 'rest', false)).toBe('seated');
    // An activity with no seat posture keeps its own, seat or not.
    expect(activityPosture(family, 'visit', true)).toBeNull();
  });

  it('sits a full person on the seat with the feet planted on the ground', async () => {
    vi.stubGlobal('createImageBitmap', async () => ({ width: 4, height: 4, close: () => undefined }));
    const { app, device, parent } = application();
    CharacterHost.forApp(app, CHARACTER_CATALOG).setLoader(async (asset) => {
      const bytes = readFileSync(resolve('../assets/characters', asset.file));
      return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    });
    const person = inhabitantRenderable(device, parent, identity('sitter'), 'near') as LayeredCharacterRenderable;
    for (let i = 0; i < 200 && person.status === 'pending'; i += 1) await new Promise((done) => setTimeout(done, 10));
    expect(person.status).toBe('ready');
    const anim = () => (person.root.findComponents('anim') as pc.AnimComponent[])[0]!;
    const ankles = () => ['Left', 'Right'].map((side) => person.root.findByName(`mixamorig:${side}Foot`)!.getPosition().y);
    // A seat lifts the root 0.12 m; the feet go back to the ground at 0.
    const lift = 0.12;
    const posed = (groundY?: number) => person.pose({
      position: [0, lift, 0], deltaSeconds: 1 / 60, discontinuity: true, activity: 'rest', seated: true,
      ...(groundY === undefined ? {} : { groundY }),
    });
    posed();
    app.update(1 / 60);
    expect(anim().baseLayer!.activeState).toBe('Posture:perched');
    expect(person.drawnPosture).toBe('perched');
    // Positive control: with no ground stated, the clip carries the ankles up with the root.
    posed();
    const carried = ankles();
    posed(0);
    const planted = ankles();
    for (let i = 0; i < 2; i += 1) expect(carried[i]! - planted[i]!).toBeCloseTo(lift, 3);
    person.destroy();
    app.destroy();
  });

  it('snaps into the seat posture under reduced motion and plants the feet while rising', async () => {
    vi.stubGlobal('createImageBitmap', async () => ({ width: 4, height: 4, close: () => undefined }));
    const { app, device, parent } = application();
    CharacterHost.forApp(app, CHARACTER_CATALOG).setLoader(async (asset) => {
      const bytes = readFileSync(resolve('../assets/characters', asset.file));
      return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    });
    const person = inhabitantRenderable(device, parent, identity('sitter'), 'near') as LayeredCharacterRenderable;
    for (let i = 0; i < 200 && person.status === 'pending'; i += 1) await new Promise((done) => setTimeout(done, 10));
    const anim = () => (person.root.findComponents('anim') as pc.AnimComponent[])[0]!;
    person.pose({ position: [0, 0, 0], deltaSeconds: 1 / 60, discontinuity: true });
    app.update(1 / 60);
    person.pose({ position: [0, 0.12, 0], deltaSeconds: 1 / 60, activity: 'rest', seated: true, groundY: 0, reducedMotion: true });
    app.update(1 / 60);
    expect(anim().baseLayer!.activeState).toBe('Posture:perched');
    expect(anim().baseLayer!.transitioning).toBe(false);
    // Rising: the seat posture is left while the root is still above the ground, and the feet are
    // planted on it all the same.
    const ankles = () => ['Left', 'Right'].map((side) => person.root.findByName(`mixamorig:${side}Foot`)!.getPosition().y);
    person.pose({ position: [0, 0.12, 0], deltaSeconds: 1 / 60 });
    const carried = ankles();
    person.pose({ position: [0, 0.12, 0], deltaSeconds: 1 / 60, groundY: 0 });
    const planted = ankles();
    for (let i = 0; i < 2; i += 1) expect(carried[i]! - planted[i]!).toBeCloseTo(0.12, 3);
    person.destroy();
    app.destroy();
  });

  it('goes from sitting on the ground to sitting on a seat when a seat is found for them', async () => {
    vi.stubGlobal('createImageBitmap', async () => ({ width: 4, height: 4, close: () => undefined }));
    const { app, device, parent } = application();
    CharacterHost.forApp(app, CHARACTER_CATALOG).setLoader(async (asset) => {
      const bytes = readFileSync(resolve('../assets/characters', asset.file));
      return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    });
    const person = inhabitantRenderable(device, parent, identity('sitter'), 'near') as LayeredCharacterRenderable;
    for (let i = 0; i < 200 && person.status === 'pending'; i += 1) await new Promise((done) => setTimeout(done, 10));
    const anim = () => (person.root.findComponents('anim') as pc.AnimComponent[])[0]!;
    person.pose({ position: [0, 0, 0], deltaSeconds: 1 / 60, discontinuity: true, activity: 'rest' });
    app.update(1 / 60);
    expect(anim().baseLayer!.activeState).toBe('Posture:seated');
    person.pose({ position: [0, 0, 0], deltaSeconds: 1 / 60, activity: 'rest', seated: true });
    for (let frame = 0; frame < 60; frame += 1) app.update(1 / 60);
    expect(anim().baseLayer!.activeState).toBe('Posture:perched');
    expect(anim().baseLayer!.transitioning).toBe(false);
    person.destroy();
    app.destroy();
  });

  it('asks for a missing container once, but asks again after a failure that may pass or a new loader', async () => {
    const { app } = application();
    let asked = 0;
    const host = CharacterHost.forApp(app, CHARACTER_CATALOG);
    const base = family.bases[0]!.asset;
    const acquire = () => host.acquire(base, new AbortController().signal, true);
    const failing = (status: number) => async () => {
      asked += 1;
      throw Object.assign(new Error(`HTTP ${status}`), { status });
    };
    // Not there: asked once, however many people need it.
    host.setLoader(failing(404));
    for (let i = 0; i < 3; i += 1) await expect(acquire()).rejects.toThrow('HTTP 404');
    expect(asked).toBe(1);
    // A new loader asks afresh.
    asked = 0;
    host.setLoader(failing(503));
    // A server error, a network failure or an expiring token may pass: every request asks again.
    for (let i = 0; i < 3; i += 1) await expect(acquire()).rejects.toThrow('HTTP 503');
    expect(asked).toBe(3);
    asked = 0;
    host.setLoader(async () => { asked += 1; throw new TypeError('Failed to fetch'); });
    for (let i = 0; i < 2; i += 1) await expect(acquire()).rejects.toThrow('Failed to fetch');
    expect(asked).toBe(2);
    // Bytes that are not the catalog's stay refused.
    asked = 0;
    host.setLoader(async () => { asked += 1; return new ArrayBuffer(3); });
    for (let i = 0; i < 2; i += 1) await expect(acquire()).rejects.toThrow('wrong length');
    expect(asked).toBe(1);
    app.destroy();
  });
});
