/**
 * The surface finish a made place's grounds, paths and water are drawn with over their pack's
 * colours, and the cell its still slots are merged in
 * (`assets/catalogs/world-kinds/surface-finish.v2.json`). The file's bytes are bundled, read once
 * and refused by name if they are not the catalog. Presentation only.
 */
import { readSurfaceFinish, type SurfaceFinish } from '@exulanica/atlas-react/style-pack';
import catalogText from '../../../../assets/catalogs/world-kinds/surface-finish.v2.json?raw';

export const SURFACE_FINISH: SurfaceFinish = readSurfaceFinish(JSON.parse(catalogText));
