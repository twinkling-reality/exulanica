/**
 * The surface material catalog a made place's leaves are read by
 * (`assets/catalogs/world-kinds/surface-material.v2.json`): what `ground.sand`, `wall.adobe` or
 * `roof.thatched` is drawn in where the style pack states no surface of its own for it. The file's
 * bytes are bundled, read once and refused by name if they are not the catalog.
 */
import { readSurfaceMaterials, type SurfaceMaterials } from '@exulanica/atlas-core';
import catalogText from '../../../../assets/catalogs/world-kinds/surface-material.v2.json?raw';

export const SURFACE_MATERIALS: SurfaceMaterials = readSurfaceMaterials(catalogText);
