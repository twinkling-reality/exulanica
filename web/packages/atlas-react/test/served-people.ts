/**
 * TEST FIXTURE: the committed people catalog served to a test application, as the host would serve
 * its first publication of it. Production code never imports the compiled catalog; it is handed
 * catalogs through `CharacterCatalogs`, and so are these tests.
 */
import type * as pc from 'playcanvas';
import { CHARACTER_CATALOG } from '../src/playcanvas/character/catalog-data.js';
import { canonicalSha256 } from '../src/playcanvas/character/digest.js';
import { DESIGNED_LOOKS } from '../src/playcanvas/character/looks-data.js';
import { CharacterCatalogs, LAYERED_PROFILE, type ServedLayeredCatalog } from '../src/playcanvas/character/served.js';

export const SERVED_PEOPLE: ServedLayeredCatalog = {
  kind: 'layered-people',
  catalogSha256: canonicalSha256({ profile: LAYERED_PROFILE, catalog: CHARACTER_CATALOG, looks: DESIGNED_LOOKS }),
  catalogId: CHARACTER_CATALOG.catalogId,
  revision: CHARACTER_CATALOG.revision,
  state: 'current',
  catalog: CHARACTER_CATALOG,
  looks: DESIGNED_LOOKS,
};

/** Serve the committed people catalog to `app`, as an application is served its host's. */
export function serveFixturePeople(app: pc.AppBase): ServedLayeredCatalog {
  CharacterCatalogs.forApp(app).add(SERVED_PEOPLE);
  return SERVED_PEOPLE;
}
