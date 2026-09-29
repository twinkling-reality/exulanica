// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import { buildBinding, stubTileMount } from './binding-harness.js';

/**
 * A generated tile that moves something of its own, such as its city's traffic, keeps frames
 * coming while it says so, and leaves a settled world still when it stops.
 */
describe('a generated tile that is animating', () => {
  it('asks for every frame while it animates, and for none once it stops', async () => {
    let animating = false;
    const stub = stubTileMount();
    const mount = {
      ...stub,
      attach: (host: Parameters<typeof stub.attach>[0]) => {
        const attachment = stub.attach(host);
        return { ...attachment, get animating() { return animating; } };
      },
    };
    const { binding } = await buildBinding('generated-tile', { generatedTile: mount });
    try {
      binding.markRendered(1000);
      expect(binding.wantsFrame(1001)).toBe(false);
      animating = true;
      expect(binding.wantsFrame(1001)).toBe(true);
      animating = false;
      expect(binding.wantsFrame(1001)).toBe(false);
    } finally {
      binding.destroy();
    }
  });
});
