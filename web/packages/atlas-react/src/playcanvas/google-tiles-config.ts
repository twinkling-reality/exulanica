import { NYC_REFERENCE_FRAME } from './nyc-reference-frame.js';

export interface GoogleTilesConfig {
  readonly enabled: boolean;
  readonly apiKey: string;
  readonly longitude: number;
  readonly latitude: number;
  readonly altitude: number;
}

export interface GoogleTilesEnvironment {
  readonly VITE_GOOGLE_PHOTOREALISTIC_3D_TILES?: string;
  readonly VITE_GOOGLE_MAP_TILES_API_KEY?: string;
}

export const GOOGLE_REFERENCE_ORIGIN = NYC_REFERENCE_FRAME;

/** Fail closed. A key alone never turns the provider on. */
export function googleTilesConfig(environment: GoogleTilesEnvironment): GoogleTilesConfig {
  const key = environment.VITE_GOOGLE_MAP_TILES_API_KEY?.trim() ?? '';
  return Object.freeze({
    enabled: environment.VITE_GOOGLE_PHOTOREALISTIC_3D_TILES === 'true' && key.length > 0,
    apiKey: key,
    ...GOOGLE_REFERENCE_ORIGIN,
  });
}

export function googleTilesConfigured(config: GoogleTilesConfig): boolean {
  return config.enabled && config.apiKey.trim().length > 0;
}
