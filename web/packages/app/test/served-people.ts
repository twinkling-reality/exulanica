/**
 * TEST SUPPORT: the committed people catalog, read from the repository files the host publishes,
 * through the same validators a served publication passes. The app imports no compiled catalog.
 */
import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import {
  canonicalJson,
  readServedCatalog,
  sha256Hex,
  type ServedLayeredCatalog,
} from '@exulanica/atlas-react/playcanvas';

// Relative to web/, where the suite runs, as character-sources.test.ts reads the same files.
const root = resolve('../assets/characters');
const bundle = {
  profile: 'exulanica.character-catalog-bundle/v1',
  catalog: JSON.parse(readFileSync(join(root, 'catalog.json'), 'utf8')) as { catalogId: string; revision: number },
  looks: JSON.parse(readFileSync(join(root, 'looks.json'), 'utf8')) as unknown,
};
const bytes = new TextEncoder().encode(canonicalJson(bundle));
const served = readServedCatalog(
  {
    catalog_sha256: sha256Hex(bytes),
    catalog_id: bundle.catalog.catalogId,
    revision: bundle.catalog.revision,
    profile: 'exulanica.character-catalog-bundle/v1',
    kind: 'layered-people',
    state: 'current',
  },
  bytes,
);
if (served.kind !== 'layered-people') throw new Error('the committed people catalog is not layered');

export const SERVED_PEOPLE: ServedLayeredCatalog = served;
export const CHARACTER_CATALOG = SERVED_PEOPLE.catalog;
export const DESIGNED_LOOKS = SERVED_PEOPLE.looks;
