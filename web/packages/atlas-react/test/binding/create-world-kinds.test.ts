// @vitest-environment happy-dom
/**
 * What `AtlasBinding.create` builds for each kind of world, pinned as data.
 *
 * Each row is one option combination the app can pass. The pin holds the camera, fog, lights,
 * exposure, the installed end chunk, navigation radii and surface, the start pose, the controls'
 * configuration, the render roots and the scene graph with every mesh instance's shadow and
 * culling flags. The pins live beside this file under `pins/`; a change that moves any of them
 * shows as a diff there, which is the point: a refactor that should move nothing must leave them
 * alone, and a fix that should move something says exactly what it moved.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { makeScene } from '@exulanica/atlas-core';
import { AtlasBinding } from '../../src/playcanvas/atlas-binding.js';
import {
  DISTRICT_DOCUMENT,
  WORLD_KINDS,
  buildBinding,
  describeBuiltWorld,
  sceneGraph,
  stubTileMount,
  worldOptions,
} from './binding-harness.js';

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

describe('what the binding builds for each kind of world', () => {
  for (const kind of WORLD_KINDS) {
    it(`builds ${kind} as pinned`, async () => {
      const { binding } = await buildBinding(kind);
      try {
        const described = `${JSON.stringify(describeBuiltWorld(binding), null, 1)}\n`;
        const graph = `${sceneGraph(binding.app.root).join('\n')}\n`;
        await expect(described).toMatchFileSnapshot(`pins/create-${kind}.json`);
        await expect(graph).toMatchFileSnapshot(`pins/create-${kind}.scene.txt`);
      } finally {
        binding.destroy();
      }
    });
  }

  it('builds the same world twice from the same options', async () => {
    // The control for every pin above: a pin that could differ between two identical builds
    // would fail for reasons that have nothing to do with a change.
    for (const kind of WORLD_KINDS) {
      const first = await buildBinding(kind);
      const second = await buildBinding(kind);
      try {
        expect(describeBuiltWorld(second.binding)).toEqual(describeBuiltWorld(first.binding));
        expect(sceneGraph(second.binding.app.root)).toEqual(sceneGraph(first.binding.app.root));
      } finally {
        first.binding.destroy();
        second.binding.destroy();
      }
    }
  });

  it('refuses a generated tile beside an owned district, and an authored region over either', async () => {
    const base = {
      canvas: document.createElement('canvas'),
      overlayParent: document.createElement('div'),
      deviceTypes: ['null'],
      scene: makeScene([], 1, 1),
      pointMaps: new Map(),
    };
    const district = { ownedDistrict: { document: DISTRICT_DOCUMENT as never, residentBytes: 100 } };
    await expect(AtlasBinding.create({ ...base, ...district, generatedTile: stubTileMount() }))
      .rejects.toThrow('A generated tile replaces the owned district; pass one or the other');
    await expect(AtlasBinding.create({ ...base, ...district, ...worldOptions('authored-endless') }))
      .rejects.toThrow('An authored starter region cannot replace geographic ground');
    await expect(AtlasBinding.create({
      ...base, generatedTile: stubTileMount(), ...worldOptions('authored-flat'),
    })).rejects.toThrow('An authored starter region cannot replace geographic ground');
  });
});
