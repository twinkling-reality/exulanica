/**
 * The site interior catalog (`assets/catalogs/world-kinds/site-interior.v1.json`): the ceiling and the
 * light an indoor made place is drawn with. The file's bytes are bundled, read once and refused by name
 * if they are not the catalog.
 */
import { readSiteInterior, type SiteInteriorCatalog } from '@exulanica/atlas-core';
import catalogText from '../../../../assets/catalogs/world-kinds/site-interior.v1.json?raw';

export const SITE_INTERIOR: SiteInteriorCatalog = readSiteInterior(catalogText);
