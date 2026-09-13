import { afterEach, describe, expect, it, vi } from 'vitest';
import { googlePhotorealisticTiles } from '../src/config.js';

describe('application Google tiles configuration', () => {
  afterEach(() => vi.unstubAllEnvs());

  it('is disabled in the ordinary test build without an explicit Vite key and flag', () => {
    vi.stubEnv('VITE_GOOGLE_PHOTOREALISTIC_3D_TILES', '');
    vi.stubEnv('VITE_GOOGLE_MAP_TILES_API_KEY', '');
    const config = googlePhotorealisticTiles();
    expect(config.enabled).toBe(false);
    expect(config.apiKey).toBe('');
  });
});
