// @vitest-environment happy-dom
/**
 * Placed objects are drawn when the ground under them is.
 *
 * Residency governs the regions of a scene: each has an entry in the plan, at least `stub`, and
 * an object in a stubbed region is not drawn. An authored starter region is not one of them: its
 * ground is always drawn, so its objects are drawn whenever the Map is closed. Before this was
 * pinned, any residency replan (leaving the Map, or a change of representation pressure) hid
 * every object in a starter world until the page was reloaded.
 */
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type * as pc from 'playcanvas';
import type { IslandId } from '@exulanica/atlas-core';
import type { AtlasBinding } from '../../src/playcanvas/atlas-binding.js';
import { STARTER_REGION, buildBinding } from './binding-harness.js';
import { FIRST_REGION, SECOND_REGION } from './world-kinds.js';

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

async function place(binding: AtlasBinding, objectId: string, islandId: IslandId): Promise<pc.Entity> {
  // Relative to web/, where the suite runs.
  const bytes = readFileSync('packages/graph-client/test/fixtures/cc0.marker-cube.glb');
  await binding.objects.place({
    objectId,
    islandId,
    asset: {
      assetKey: 'cc0.marker-cube', mediaType: 'model/gltf-binary',
      contentSha256: createHash('sha256').update(bytes).digest('hex'), byteSize: bytes.byteLength,
    },
    transform: { xMm: 0, yMm: 0, zMm: 500, yawMicroradians: 0, scaleMilli: 1000 },
    behaviour: null,
  }, bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer);
  return binding.app.root.findByName(`authored-object:${objectId}`) as pc.Entity;
}

describe('placed objects and residency', () => {
  it('draws a starter world\'s objects again when the Map closes', async () => {
    const { binding } = await buildBinding('authored-endless');
    try {
      binding.update(1 / 60, 10_000);
      const cube = await place(binding, 'starter-cube', STARTER_REGION);
      binding.update(1 / 60, 10_016);
      expect(cube.enabled).toBe(true);
      binding.setMapMode(true);
      binding.update(1 / 60, 10_032);
      expect(cube.enabled).toBe(false);
      binding.setMapMode(false);
      binding.update(1 / 60, 10_048);
      expect(cube.enabled).toBe(true);
    } finally {
      binding.destroy();
    }
  });

  it('draws a scene region\'s objects exactly when residency gives the region a drawn stage', async () => {
    // A budget of 2 units affords one region: the one the person stands in, which is exempt.
    const { binding } = await buildBinding('personal-regions', { residencyBudget: 2 });
    try {
      binding.update(1 / 60, 10_000);
      const first = await place(binding, 'first-cube', FIRST_REGION);
      const second = await place(binding, 'second-cube', SECOND_REGION);
      // Residency replans on the frames that see the Map open and close.
      binding.setMapMode(true);
      binding.update(1 / 60, 10_016);
      binding.setMapMode(false);
      binding.update(1 / 60, 10_032);
      const allocated = (binding as unknown as { residencyAllocated: ReadonlyMap<IslandId, string> }).residencyAllocated;
      // The control: both regions are governed, one drawn and one stubbed.
      expect([allocated.get(FIRST_REGION), allocated.get(SECOND_REGION)].filter((stage) => stage === 'stub'))
        .toEqual(['stub']);
      expect(first.enabled).toBe(allocated.get(FIRST_REGION) !== 'stub');
      expect(second.enabled).toBe(allocated.get(SECOND_REGION) !== 'stub');
    } finally {
      binding.destroy();
    }
  });
});
