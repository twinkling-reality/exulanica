import { describe, expect, it } from 'vitest';
import {
  googleTilesConfig,
  googleTilesConfigured,
} from '../src/playcanvas/google-tiles-config.js';

describe('Google tiles configuration', () => {
  it('requires both the explicit feature flag and a key', () => {
    expect(googleTilesConfigured(googleTilesConfig({}))).toBe(false);
    expect(googleTilesConfigured(googleTilesConfig({
      VITE_GOOGLE_PHOTOREALISTIC_3D_TILES: 'true',
    }))).toBe(false);
    expect(googleTilesConfigured(googleTilesConfig({
      VITE_GOOGLE_MAP_TILES_API_KEY: 'key-only',
    }))).toBe(false);
    expect(googleTilesConfigured(googleTilesConfig({
      VITE_GOOGLE_PHOTOREALISTIC_3D_TILES: 'true',
      VITE_GOOGLE_MAP_TILES_API_KEY: ' explicit-key ',
    }))).toBe(true);
  });

  it('does not enable approximate truthy flag values', () => {
    expect(googleTilesConfig({
      VITE_GOOGLE_PHOTOREALISTIC_3D_TILES: '1',
      VITE_GOOGLE_MAP_TILES_API_KEY: 'key',
    }).enabled).toBe(false);
  });
});
