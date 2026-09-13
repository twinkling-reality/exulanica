import { afterEach, describe, expect, it, vi } from 'vitest';
import { googlePhotorealisticTiles, nycOpenDataAdmissionId } from '../src/config.js';

describe('application Google tiles configuration', () => {
  afterEach(() => vi.unstubAllEnvs());

  it('is disabled in the ordinary test build without an explicit Vite key and flag', () => {
    vi.stubEnv('VITE_GOOGLE_PHOTOREALISTIC_3D_TILES', '');
    vi.stubEnv('VITE_GOOGLE_MAP_TILES_API_KEY', '');
    const config = googlePhotorealisticTiles();
    expect(config.enabled).toBe(false);
    expect(config.apiKey).toBe('');
  });

  it('configures NYC semantic admission independently of Google availability', () => {
    const admission = '12345678-1234-4123-8123-123456789abc';
    expect(nycOpenDataAdmissionId({
      VITE_NYC_OPEN_DATA_ADMISSION_ID: admission,
      VITE_GOOGLE_PHOTOREALISTIC_3D_TILES: 'false',
    })).toBe(admission);
    expect(nycOpenDataAdmissionId({ VITE_GOOGLE_MAP_TILES_API_KEY: 'key-only' })).toBeNull();
  });
});
