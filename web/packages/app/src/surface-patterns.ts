/**
 * The surface pattern catalog a made place's surfaces are patterned by
 * (`assets/catalogs/world-kinds/surface-pattern.v1.json`): the courses, boards, strokes, seams,
 * ripples or grain each material is drawn with. The file's bytes are bundled, read once and refused
 * by name if they are not the catalog.
 */
import { readSurfacePatterns, type SurfacePatterns } from '@exulanica/atlas-core';
import catalogText from '../../../../assets/catalogs/world-kinds/surface-pattern.v1.json?raw';

export const SURFACE_PATTERNS: SurfacePatterns = readSurfacePatterns(catalogText);
