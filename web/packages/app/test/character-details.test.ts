import { describe, expect, it } from 'vitest';
import { characterDisplayDetails } from '../src/ui/character-details.js';
describe('actual character representation details', () => {
  it('identifies imported bytes and the native rig instead of the retained abstract fallback', () => {
    const details = characterDisplayDetails({ subject: { kind: 'player', playerId: 'local-viewer' }, status: 'ready', error: null,
      rigId: 'artist-rig/v2', asset: { assetKey: 'look-v2', mediaType: 'model/gltf-binary', contentSha256: 'a'.repeat(64), byteSize: 42 },
      gait: 'idle', speed: 0, mutableBytes: 0 }, 'abstract-1');
    expect(details.flat()).toContain('artist-rig/v2');
    expect(details.flat()).toContain('a'.repeat(64));
    expect(details.flat()).not.toContain('abstract-1');
  });
  it('keeps the abstract version for unavailable imported content', () => {
    expect(characterDisplayDetails(null, 'abstract-1').flat()).toContain('abstract-1');
  });
});
