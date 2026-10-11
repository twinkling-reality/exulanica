/**
 * The ground border catalog (`assets/catalogs/world-kinds/ground-border.v1.json`): how the edge of each
 * ground of a made place is broken where it meets another. The file's bytes are bundled, read once and
 * refused by name if they are not the catalog.
 */
import { readGroundBorders, type GroundBorders } from '@exulanica/atlas-core';
import catalogText from '../../../../assets/catalogs/world-kinds/ground-border.v1.json?raw';

export const GROUND_BORDERS: GroundBorders = readGroundBorders(catalogText);
