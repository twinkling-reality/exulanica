/**
 * The roof form catalog a made place's roofs are shaped by (`assets/catalogs/world-kinds/roof-form.v1.json`):
 * how a pitched or a flat roof of each material is formed. The file's bytes are bundled, read once
 * and refused by name if they are not the catalog.
 */
import { readRoofForms, type RoofForms } from '@exulanica/atlas-core';
import catalogText from '../../../../assets/catalogs/world-kinds/roof-form.v1.json?raw';

export const ROOF_FORMS: RoofForms = readRoofForms(catalogText);
