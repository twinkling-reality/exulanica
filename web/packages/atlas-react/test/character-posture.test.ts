// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import * as pc from 'playcanvas';
import { CHARACTER_CATALOG } from '../src/playcanvas/character/catalog-data.js';
import { activityPosture } from '../src/playcanvas/character/catalog.js';
import { CharacterHost } from '../src/playcanvas/character/host.js';
import { inhabitantRenderable } from '../src/playcanvas/character/inhabitant.js';
import type { LayeredCharacterRenderable } from '../src/playcanvas/character/renderable.js';

/*
 * A person is drawn in the posture the catalog declares for the activity the simulation states,
 * in both forms, and stands for any activity the catalog draws no posture for.
 */

function application() {
  const canvas = document.createElement('canvas');
  canvas.id = `posture-${Math.random().toString(36).slice(2)}`;
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

function farHeight(renderable: LayeredCharacterRenderable): number {
  const body = renderable.root.findByName('character-far-body') as pc.Entity;
  return body.render!.meshInstances[0]!.mesh.aabb.getMax().y;
}

afterEach(() => vi.unstubAllGlobals());

describe('postures', () => {
  it('are declared for society activities and resolve through the catalog, standing otherwise', () => {
    expect(activityPosture(family, 'rest')).toBe('seated');
    expect(activityPosture(family, 'visit')).toBeNull();
    expect(activityPosture(family, null)).toBeNull();
    expect(activityPosture(family, undefined)).toBeNull();
  });

  it('seat the far form for a stated rest and stand it again when the rest ends', () => {
    const { app, device, parent } = application();
    const person = inhabitantRenderable(device, parent, identity('sitter'), 'far') as LayeredCharacterRenderable;
    person.pose({ position: [0, 0, 0], deltaSeconds: 1 / 60, discontinuity: true });
    const standing = farHeight(person);
    person.pose({ position: [0, 0, 0], deltaSeconds: 1 / 60, activity: 'rest' });
    expect(person.drawnPosture).toBe('seated');
    // Seated on the ground the figure is not much over half its standing height.
    expect(farHeight(person)).toBeLessThan(standing * 0.65);
    person.pose({ position: [0, 0, 0], deltaSeconds: 1 / 60, activity: 'visit' });
    expect(person.drawnPosture).toBeNull();
    expect(farHeight(person)).toBeCloseTo(standing, 6);
    person.destroy();
    app.destroy();
  });

  it('play the seated clip on a full person assembled from the committed containers', async () => {
    // The null device uploads nothing, so an image only needs a size.
    vi.stubGlobal('createImageBitmap', async () => ({ width: 4, height: 4, close: () => undefined }));
    const { app, device, parent } = application();
    CharacterHost.forApp(app, CHARACTER_CATALOG).setLoader(async (asset) => {
      // Tests run from web/; a happy-dom module URL is not a file path.
      const bytes = readFileSync(resolve('../assets/characters', asset.file));
      return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    });
    const person = inhabitantRenderable(device, parent, identity('sitter'), 'near') as LayeredCharacterRenderable;
    for (let i = 0; i < 200 && person.status === 'pending'; i += 1) await new Promise((resolve) => setTimeout(resolve, 10));
    expect(person.status).toBe('ready');
    const anim = () => (person.root.findComponents('anim') as pc.AnimComponent[])[0]!;
    person.pose({ position: [0, 0, 0], deltaSeconds: 1 / 60, discontinuity: true, activity: 'rest' });
    app.update(1 / 60);
    expect(anim().baseLayer!.activeState).toBe('Posture:seated');
    person.pose({ position: [0, 0, 0], deltaSeconds: 1 / 60 });
    for (let frame = 0; frame < 60; frame += 1) app.update(1 / 60);
    expect(anim().baseLayer!.activeState).toBe('Locomotion');
    person.destroy();
    app.destroy();
  });
});
