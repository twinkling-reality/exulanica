// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { islandId } from '@exulanica/atlas-core';
import { AtlasBinding } from '../src/playcanvas/atlas-binding.js';
import { CHARACTER_CATALOG } from '../src/playcanvas/character/catalog-data.js';
import { farAppearance } from '../src/playcanvas/character/far.js';
import { inhabitantLookOf, inhabitantRenderable } from '../src/playcanvas/character/inhabitant.js';
import { lookSha256 } from '../src/playcanvas/character/look.js';
import { CHARACTER_RENDERABLE_TAG, type LayeredCharacterRenderable } from '../src/playcanvas/character/renderable.js';
import { SocietyCrowd } from '../src/playcanvas/society/crowd.js';
import type { OwnedSocietyState } from '../src/playcanvas/society/types.js';

/*
 * The people a saved world draws are catalog people: the same person, near or far, as the look
 * their stable id draws. These build a real binding on PlayCanvas's null device, as the app does
 * for a saved world, with nothing but the GPU left out.
 */

const REGION = islandId('region:starter');

async function savedWorld(): Promise<AtlasBinding> {
  const canvas = document.createElement('canvas');
  const overlay = document.createElement('div');
  document.body.append(canvas, overlay);
  return AtlasBinding.create({
    canvas,
    overlayParent: overlay,
    deviceTypes: ['null'],
    scene: { islands: [], edges: [], anchors: [] } as never,
    pointMaps: new Map(),
    authoredRegion: {
      regionId: REGION,
      module: { key: 'region.authored-ground', version: 2 },
      ground: { kind: 'endless', elevationMm: 0 },
      spawn: { xMm: 0, yMm: 0, zMm: 4000, yawMicroradians: 0 },
    },
  } as never);
}

const society = (ids: readonly string[], at: (i: number) => readonly [number, number]): OwnedSocietyState => ({
  profile: 'exulanica-society/v2',
  society_id: 'society',
  branch_id: 'branch',
  tick: 1,
  inhabitants: ids.map((id, i) => ({ id, synthetic: true as const, position_mm: at(i) })),
});

describe('people in a saved world', () => {
  it('draws an inhabitant inside the near distance as the catalog person its id draws', async () => {
    const atlas = await savedWorld();
    const crowd = atlas.authoredSociety!;
    const region = atlas.app.root.findByName(`authored-region:${REGION}`)!;
    const ids = ['person-0', 'person-1', 'person-2'];
    expect(crowd.setSociety(society(ids, (i) => [1000 + i * 1500, 2000]), [0, 4])).toBe(3);
    atlas.update(1 / 60, 1000);
    for (const id of ids) {
      expect(crowd.inhabitantDetail(id)).toBe('near');
      const root = region.findByName(`synthetic:${id}`) as pc.Entity;
      expect(root.tags.has(CHARACTER_RENDERABLE_TAG), id).toBe(true);
      // The drawn person is named by the digest of the look the inhabitant's id draws.
      expect(crowd.inhabitantRepresentation(id)?.representationId).toBe(`look:${lookSha256(inhabitantLookOf(id))}`);
      // With no byte loader registered yet, the person shows the far form of that same look.
      const far = root.findByName('character-far') as pc.Entity;
      expect(far.enabled).toBe(true);
    }
    atlas.destroy();
  });
});

describe('the far form of an inhabitant', () => {
  it('comes from one source whichever drawing shows them, down to the shared palette material', () => {
    const canvas = document.createElement('canvas');
    const device = new pc.NullGraphicsDevice(canvas);
    const app = new pc.AppBase(canvas);
    const options = new pc.AppOptions();
    options.graphicsDevice = device;
    options.componentSystems = [pc.RenderComponentSystem];
    app.init(options);
    const root = new pc.Entity('society', app);
    app.root.addChild(root);
    const crowd = new SocietyCrowd(device, root, { nearLimit: 0 });
    const ids = Array.from({ length: 40 }, (_, i) => `inhabitant-${i}`);
    crowd.set(society(ids, (i) => [i * 2000, 0]), [0, 0]);
    const figures = root.findByName('society-far-figures')!;
    for (const id of ids) {
      const renderable = inhabitantRenderable(device, root, { societyId: 'society', branchId: 'branch', inhabitantId: id }, 'far') as LayeredCharacterRenderable;
      const expected = farAppearance(CHARACTER_CATALOG, inhabitantLookOf(id));
      expect(renderable.farAppearance, id).toEqual(expected);
      expect(crowd.farAppearance(id), id).toEqual(expected);
      const figure = figures.children[ids.indexOf(id)]!.findByName('character-far-body') as pc.Entity;
      const own = renderable.root.findByName('character-far-body') as pc.Entity;
      expect(own.render!.meshInstances[0]!.material).toBe(figure.render!.meshInstances[0]!.material);
      expect(own.getLocalScale().y).toBeCloseTo(figure.getLocalScale().y, 9);
      renderable.destroy();
    }
    crowd.destroy();
    app.destroy();
  });
});
