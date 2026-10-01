/**
 * The one entry point the society display uses to draw an inhabitant.
 *
 * The look is drawn from the people catalog the host serves this application
 * (`CharacterCatalogs.people`), keyed only by the inhabitant's stable id and the street population
 * domain: branch, position, tick, role and draw order never change it, and it never touches
 * simulation state or decides what an interaction targets. Nothing is drawn from a catalog compiled
 * into the bundle; until the host has served one, asking for an inhabitant is refused by name, and
 * the society display waits for one (`society/crowd.ts`).
 */
import type * as pc from 'playcanvas';
import type { CharacterSubject } from '@exulanica/atlas-core';
import type { CharacterCatalog } from './catalog.js';
import { CharacterHost } from './host.js';
import { drawLook, type CharacterDetail, type CharacterLook } from './look.js';
import { LayeredCharacterRenderable, type CharacterRenderable } from './renderable.js';
import { CharacterCatalogs, INHABITANT_DRAW_DOMAIN } from './served.js';

export { INHABITANT_DRAW_DOMAIN };

export interface InhabitantIdentity {
  readonly societyId: string;
  readonly branchId: string;
  /** The inhabitant's stable uuid5. With the draw domain it alone selects the look. */
  readonly inhabitantId: string;
}

/** No people catalog has been served to this application yet, so no inhabitant can be drawn. */
export class PeopleCatalogNotServed extends Error {
  constructor() {
    super('No people catalog is served here yet');
    this.name = 'PeopleCatalogNotServed';
  }
}

/** The look an inhabitant is drawn with in `catalog`, without any renderer. */
export function inhabitantLook(catalog: CharacterCatalog, identity: InhabitantIdentity): CharacterLook {
  return inhabitantLookOf(catalog, identity.inhabitantId);
}

/** The same look from the stable id alone, which is all the draw reads. */
export function inhabitantLookOf(catalog: CharacterCatalog, inhabitantId: string): CharacterLook {
  return drawLook(catalog, INHABITANT_DRAW_DOMAIN, inhabitantId);
}

/** The catalog this application's inhabitants are drawn from, or a refusal naming its absence. */
export function inhabitantCatalog(app: pc.AppBase): CharacterCatalog {
  const served = CharacterCatalogs.forApp(app).people;
  if (served === null) throw new PeopleCatalogNotServed();
  return served.catalog;
}

/**
 * A renderable for one inhabitant at a detail level. The caller parents nothing: the returned
 * root is already a child of `parent`, and `pose` positions it in `parent`'s space.
 */
export function inhabitantRenderable(
  device: pc.GraphicsDevice,
  parent: pc.Entity,
  identity: InhabitantIdentity,
  detail: CharacterDetail,
): CharacterRenderable {
  const host = CharacterHost.forDevice(device);
  const catalog = inhabitantCatalog(host.app);
  const subject: CharacterSubject = {
    kind: 'synthetic-inhabitant',
    societyId: identity.societyId,
    branchId: identity.branchId,
    inhabitantId: identity.inhabitantId,
  };
  return new LayeredCharacterRenderable(host, parent, subject, inhabitantLook(catalog, identity), detail, catalog);
}
