import { describe, expect, it } from 'vitest';
import { googlePhotorealisticTiles } from '../src/config.js';

describe('application Google tiles configuration', () => {
  it('is disabled in the ordinary test build without an explicit Vite key and flag', () => {
    const config = googlePhotorealisticTiles();
    expect(config.enabled).toBe(false);
    expect(config.apiKey).toBe('');
  });
});
