// @vitest-environment happy-dom
import { islandId } from '@exulanica/atlas-core';
import { afterEach, describe, expect, it } from 'vitest';
import { buildBinding, FIRST_REGION, PERSONAL_SCENE } from './binding-harness.js';
import { stubTileMount } from './world-kinds.js';

const REGION = islandId('region:generated');
afterEach(() => document.body.replaceChildren());

describe('a generated saved region for authored objects', () => {
  it.each(['tile', 'site'] as const)('keeps %s objects in the environment frame without a society-floor offset', async ground => {
    const options = ground === 'site'
      ? { generatedSite: { ...stubTileMount(), kindLabel: 'Yard', drawing: null as never } }
      : {};
    const { binding } = await buildBinding(ground === 'tile' ? 'generated-tile' : 'personal-regions', {
      ...options, generatedRegionId: REGION,
    });
    const root = binding.regionRoots.get(REGION)!;
    expect(root.parent).toBe(binding.environmentRoot);
    expect(root.getLocalPosition().toArray()).toEqual([0, 0, 0]);
    binding.environmentRoot.setPosition(-100, -8, 200);
    expect(root.getPosition().toArray()).toEqual([-100, -8, 200]);
    binding.destroy();
    expect(root.parent).toBeNull();
    const next = await buildBinding('generated-tile');
    expect(next.binding.regionRoots.has(REGION)).toBe(false);
    next.binding.destroy();
  });

  it('rejects a generated-region label without mounted generated ground or with a colliding memory region', async () => {
    for (const ground of ['personal-regions', 'authored-endless', 'authored-flat', 'owned-district'] as const) {
      await expect(buildBinding(ground, { generatedRegionId: REGION })).rejects.toThrow('requires its own mounted ground');
    }
    await expect(buildBinding('generated-tile', { generatedRegionId: FIRST_REGION, scene: PERSONAL_SCENE }))
      .rejects.toThrow('unambiguous frame');
  });
});
