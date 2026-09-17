/**
 * The one entry point the society display uses to draw an inhabitant.
 *
 * The look is drawn from the committed catalog, keyed only by the inhabitant's stable id and the
 * street population domain: branch, position, tick, role and draw order never change it, and it
 * never touches simulation state or decides what an interaction targets.
 */
import type * as pc from 'playcanvas';
import type { CharacterSubject } from '@exulanica/atlas-core';
import { CHARACTER_CATALOG } from './catalog-data.js';
import { CharacterHost } from './host.js';
import { drawLook, type CharacterDetail, type CharacterLook } from './look.js';
import { LayeredCharacterRenderable, type CharacterRenderable } from './renderable.js';

export const INHABITANT_DRAW_DOMAIN = 'street-population/v1';

export interface InhabitantIdentity {
  readonly societyId: string;
  readonly branchId: string;
  /** The inhabitant's stable uuid5. With the draw domain it alone selects the look. */
  readonly inhabitantId: string;
}

/** The look an inhabitant is drawn with, without any renderer. */
export function inhabitantLook(identity: InhabitantIdentity): CharacterLook {
  return drawLook(CHARACTER_CATALOG, INHABITANT_DRAW_DOMAIN, identity.inhabitantId);
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
  const host = CharacterHost.forDevice(device, CHARACTER_CATALOG);
  const subject: CharacterSubject = {
    kind: 'synthetic-inhabitant',
    societyId: identity.societyId,
    branchId: identity.branchId,
    inhabitantId: identity.inhabitantId,
  };
  return new LayeredCharacterRenderable(host, parent, subject, inhabitantLook(identity), detail);
}
