/**
 * The land's own surfaces (`assets/catalogs/landform/landform-surface.v1.json`): sand by the sea,
 * planting on banks, rock on steep faces and the far hills' wooded and high bands, laid over a
 * site's ground where it stands on land. The file's bytes are bundled, read once and refused by
 * name if they are not the catalog.
 */
import { readLandSurfaces, type LandSurfaces } from '@exulanica/atlas-core';
import catalogText from '../../../../assets/catalogs/landform/landform-surface.v1.json?raw';

export const LAND_SURFACES: LandSurfaces = readLandSurfaces(catalogText);
