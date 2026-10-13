// @vitest-environment happy-dom
import { expect, it, vi } from 'vitest';
import type * as pc from 'playcanvas';
import { buildBinding, stubTileMount } from './binding-harness.js';
it('selects immutable source metadata in the displayed frame and withdraws revoked picks', async () => {
  let current = true;
  const surface = { instanceId: 'west-gateway', assetKey: 'reviewed.gateway', contentSha256: 'a'.repeat(64),
    nodeIndex: 4, meshIndex: 2, primitiveIndex: 1, meshInstance: {} as pc.MeshInstance };
  const pickSource = vi.fn(() => ({ surface, distance: 7 }));
  const stub = stubTileMount();
  const { binding } = await buildBinding('generated-tile', { generatedTile: { ...stub,
    attach: host => ({ ...stub.attach(host), pickSource, sourceCurrent: () => current }),
  } });
  try {
    // Install the nonzero source/display offset used by floating-origin worlds.
    (binding as unknown as { renderOriginState: unknown }).renderOriginState = {
      origin: { x: 400, y: 0, z: -200 }, neighborhoodId: null, revision: 1,
    };
    binding.environmentRoot.setPosition(-400, 0, 200);
    binding.camera.setPosition(3, 1.5, 7);
    const ray = binding.interactionRay();
    expect(ray.origin).toEqual([403, 1.5, -193]);
    const hit = binding.pickSourceSurface(ray.origin, [0, 0, -2]);
    const camera = binding.camera.getPosition();
    expect(pickSource).toHaveBeenLastCalledWith([camera.x, camera.y, camera.z], [0, 0, -1]);
    expect(hit).toEqual({ kind: 'terrain-dressing', instanceId: surface.instanceId,
      assetKey: surface.assetKey, contentSha256: surface.contentSha256,
      nodeIndex: 4, meshIndex: 2, primitiveIndex: 1, distance: 7 });
    expect(Object.isFrozen(hit)).toBe(true);
    expect(hit).not.toHaveProperty('meshInstance');
    expect(binding.pickSourceSurface(ray.origin, [0, 0, 0])).toBeNull();
    current = false;
    expect(binding.sourceSurfaceCurrent()).toBe(false);
    expect(binding.pickSourceSurface(ray.origin, ray.direction)).toBeNull();
    expect(pickSource).toHaveBeenCalledTimes(1);
  } finally { binding.destroy(); }
  expect(binding.pickSourceSurface([0, 0, 0], [0, 0, -1])).toBeNull();
});
