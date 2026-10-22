/**
 * The surface material catalog a made place's leaves are read by
 * (`assets/catalogs/world-kinds/surface-material.v3.json`): what `ground.sand`, `wall.adobe` or
 * `roof.thatched` is drawn in where the style pack states no surface of its own for it, and which
 * the eye sees through (`wall.glass`). The file's bytes are bundled, read once and refused by name if
 * they are not the catalog.
 */
import { materialOfLeaf, readSurfaceMaterials, splitLookRole, type SurfaceMaterials } from '@exulanica/atlas-core';
import catalogText from '../../../../assets/catalogs/world-kinds/surface-material.v3.json?raw';

export const SURFACE_MATERIALS: SurfaceMaterials = readSurfaceMaterials(catalogText);

/** Whether the eye sees through what a look role's leaf names (`SurfaceMaterial.seeThrough`): false for a leaf that names no material. */
export function seenThrough(lookRole: string): boolean {
  const { family, leaf } = splitLookRole(lookRole, 'lookRole');
  return leaf !== 'default' && materialOfLeaf(SURFACE_MATERIALS, family, leaf)?.seeThrough === true;
}
