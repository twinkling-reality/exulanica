// @vitest-environment happy-dom
import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { islandId } from '@exulanica/atlas-core';
import { AtlasBinding } from '../src/playcanvas/atlas-binding.js';
import type { OwnedSocietyState } from '../src/playcanvas/society/types.js';

/*
 * A saved world's inhabitants are drawn by the same crowd the owned district draws, hung from the
 * authored region's root. These build real bindings on PlayCanvas's null device: everything but
 * the GPU runs as it does in the app.
 */

const REGION = islandId('region:starter');

async function binding(world: 'district' | 'saved'): Promise<AtlasBinding> {
  const canvas = document.createElement('canvas');
  const overlay = document.createElement('div');
  document.body.append(canvas, overlay);
  return AtlasBinding.create({
    canvas,
    overlayParent: overlay,
    deviceTypes: ['null'],
    scene: { islands: [], edges: [], anchors: [] } as never,
    pointMaps: new Map(),
    ...(world === 'district'
      ? {
          ownedDistrict: {
            document: {
              profile: 'exulanica.owned-district/v1', district_id: 'test', name: 'Test', seed: 1,
              bounds_cm: [-1000, -1000, 1000, 1000],
              materials: [{ name: 'stone', base: '#778899', roughness_milli: 800, metalness_milli: 0 }],
              buildings: [], sidewalks: [], source_records: [],
            } as never,
            residentBytes: 100,
          },
        }
      : {
          authoredRegion: {
            regionId: REGION,
            module: { key: 'region.authored-ground', version: 2 },
            ground: { kind: 'endless', elevationMm: 0 },
            spawn: { xMm: 0, yMm: 0, zMm: 4000, yawMicroradians: 0 },
          },
        }),
  } as never);
}

/** Every native frame the binding sends, as the inhabitant identities in each call. */
function recordNativeFrames(atlas: AtlasBinding): string[][] {
  const calls: string[][] = [];
  (atlas as unknown as { nativeCharacters: unknown }).nativeCharacters = {
    syncFrames: (all: readonly { subject: { inhabitantId?: string } }[]) => {
      calls.push(all.map((frame) => frame.subject.inhabitantId ?? '?'));
    },
    destroy: () => undefined,
  };
  return calls;
}

const society = (count: number, at: (i: number) => readonly [number, number]): OwnedSocietyState => ({
  profile: 'exulanica-society/v2',
  society_id: 'society',
  branch_id: 'branch',
  tick: 1,
  inhabitants: Array.from({ length: count }, (_, i) => ({
    id: `person-${i}`,
    synthetic: true as const,
    position_mm: at(i),
    motion_path_mm: [[at(i)[0], 0], at(i)] as const,
  })),
});

const fmt = (v: pc.Vec3) => [v.x, v.y, v.z].map((n) => n.toFixed(6)).join(',');
function tree(node: pc.GraphNode, depth = 0): string[] {
  const e = node as pc.Entity;
  const components = e.c ? Object.keys(e.c).sort().join(',') : '';
  const render = e.render ? `mi=${e.render.meshInstances.length}` : '';
  const lines = [`${'  '.repeat(depth)}${node.name}|${e.enabled}|${fmt(node.getLocalPosition())}|`
    + `${fmt(node.getLocalEulerAngles())}|${fmt(node.getLocalScale())}|${components}|${render}`];
  for (const child of node.children) lines.push(...tree(child, depth + 1));
  return lines;
}

describe('a saved world draws its inhabitants over its authored region', () => {
  it('builds exactly what an owned-district world built before it existed', async () => {
    const atlas = await binding('district');
    const frames = recordNativeFrames(atlas);
    atlas.ownedDistrict!.setSociety(society(6, (i) => [i * 1500, 2000]), [0, 0]);
    for (let i = 0; i < 5; i += 1) atlas.update(1 / 60, 1000 + i * 16);
    const text = [
      ...tree(atlas.app.root),
      `frames:${frames.map((call) => call.join(',')).join('/')}`,
      `district:${atlas.ownedDistrict !== null}`,
    ].join('\n');
    // The whole scene graph after a society and five frames, recorded on 7e6144ea before the
    // authored-region crowd was added, and again when inhabitants became catalog people (drawn
    // as their far form while their containers load; this test registers no loader). A district
    // builds no authored crowd and sends the native character runtime exactly the frames it did.
    expect(createHash('sha256').update(text).digest('hex'))
      .toBe('aa14da25824f0aee39cd386af173a1a85fb7d68317c96c6d5a2b57b0bbad53ae');
    expect(atlas.authoredSociety).toBeNull();
  });

  it('draws each inhabitant at its stated point in the region the objects are placed in', async () => {
    const atlas = await binding('saved');
    const crowd = atlas.authoredSociety!;
    const region = atlas.app.root.findByName(`authored-region:${REGION}`)!;
    expect(crowd.root.parent).toBe(region);
    expect(atlas.ownedDistrict).toBeNull();
    const drawn = crowd.setSociety(society(3, (i) => [3000 + i * 1000, 5000]), [0, 4]);
    expect(drawn).toBe(3);
    atlas.update(1 / 60, 2000);
    const figure = region.findByName('synthetic:person-0')!;
    expect(fmt(figure.getPosition())).toBe(fmt(new pc.Vec3(3, 0, 5)));
    // Looking along the ground from the spawn toward the first person selects that person.
    expect(crowd.pickInhabitant([3, 1, 0], [0, 0, 1])).toBe('person-0');
    expect(crowd.pickInhabitant([3, 1, 0], [0, 0, -1])).toBeNull();
    crowd.clearSociety();
    expect(crowd.visibleInhabitantIds).toEqual([]);
  });

  it('hands every full character it draws to the native character runtime each frame', async () => {
    const atlas = await binding('saved');
    const frames = recordNativeFrames(atlas);
    atlas.authoredSociety!.setSociety(society(5, (i) => [i * 2000, 0]), [0, 0]);
    for (let i = 0; i < 3; i += 1) atlas.update(1 / 60, 3000 + i * 16);
    const near = atlas.authoredSociety!.visibleInhabitantIds
      .filter((id) => atlas.authoredSociety!.inhabitantDetail(id) === 'near');
    expect(near.length).toBe(5);
    expect(frames.length).toBe(3);
    // A resident missing from a call is released by NativeCharacterRuntime.syncFrames.
    for (const call of frames) expect([...call].sort()).toEqual([...near].sort());
  });

  it('is released with the binding', async () => {
    const atlas = await binding('saved');
    const crowd = atlas.authoredSociety!;
    crowd.setSociety(society(2, (i) => [i * 1000, 0]), [0, 0]);
    atlas.destroy();
    expect(atlas.authoredSociety).toBeNull();
    expect(crowd.root.parent).toBeNull();
  });
});
