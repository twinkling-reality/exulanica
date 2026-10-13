import { atlasVec3, isNavigationPositionClear, type NavigationWorld } from '@exulanica/atlas-core';

/** The authorized saved region and the exact ground the current generated renderer walks. */
export interface GeneratedObjectGround {
  readonly worldId: string;
  readonly versionId: string;
  readonly regionId: string;
  readonly navigation: NavigationWorld;
}

/** Region-local millimetres from a generated world's metre sampler, including its declared keep-outs. */
export function generatedObjectHeight(ground: GeneratedObjectGround, xMm: number, zMm: number): number | null {
  if (!Number.isFinite(xMm) || !Number.isFinite(zMm)) return null;
  const x = xMm / 1000, z = zMm / 1000;
  const sampled = ground.navigation.surface.sample(x, z);
  if (sampled === null || !Number.isFinite(sampled.height)
      || !isNavigationPositionClear(ground.navigation, atlasVec3(x, sampled.height, z), 0)) return null;
  return Math.round(sampled.height * 1000);
}
