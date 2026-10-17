/**
 * The street furniture form catalog a town's furniture is drawn by
 * (`assets/catalogs/world-kinds/street-furniture-form.v1.json`): a bench as slats on frames, a bin as a
 * turned body under a lid, a cycle stand as a bent hoop, a sign post as a pole carrying a framed plate,
 * each inside the parts its record states. The file's bytes are bundled, read once and refused by name
 * if they are not the catalog.
 */
import { readStreetFurnitureForms, type FurnitureForms } from '@exulanica/atlas-core';
import catalogText from '../../../../assets/catalogs/world-kinds/street-furniture-form.v1.json?raw';

export const STREET_FURNITURE_FORMS: FurnitureForms = readStreetFurnitureForms(catalogText);
