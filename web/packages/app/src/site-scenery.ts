/**
 * The site scenery catalog (`assets/catalogs/world-kinds/site-scenery.v1.json`): what stands on the
 * ground beyond a made place, by its base ground's material. The file's bytes are bundled, read once
 * and refused by name if they are not the catalog.
 */
import { readSiteScenery, type SiteSceneryCatalog } from '@exulanica/atlas-core';
import catalogText from '../../../../assets/catalogs/world-kinds/site-scenery.v1.json?raw';

export const SITE_SCENERY: SiteSceneryCatalog = readSiteScenery(catalogText);
