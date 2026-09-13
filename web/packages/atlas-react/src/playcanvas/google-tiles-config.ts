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

export const GOOGLE_REFERENCE_ORIGIN = Object.freeze({
  longitude: -73.9885,
  latitude: 40.722,
  altitude: 0,
});

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
