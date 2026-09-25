/**
 * What the crowd needs to draw people at the objects they use, from what the page already reads.
 *
 * Each kind's use comes from the registry list (`GET /world/assets`, `ReviewedAsset.use`), each
 * object's kind and transform from the version being drawn, and which object each society target
 * belongs to from the places the society's current state consumed (`SocietySnapshot.places`).
 * Nothing here decides where anybody is; the crowd reads a person's place from their own state.
 */
import type { SeatingLayout, SeatingObject } from '@exulanica/atlas-react/playcanvas';
import type { SocietyPlaces } from '../society-api.js';
import type { AlternateVersion, ReviewedAsset } from '../world-objects-api.js';

/** The layout for one drawn version and one consumed input, or null when either is not read. */
export function seatingLayout(
  assets: readonly ReviewedAsset[],
  version: AlternateVersion | null,
  places: SocietyPlaces | null,
): SeatingLayout | null {
  if (version === null || places === null) return null;
  const uses = new Map(
    assets.flatMap((asset) => (asset.use ? [[asset.assetKey, asset.use] as const] : [])),
  );
  const objects: SeatingObject[] = version.objects
    .filter((object) => !object.removed)
    .map((object) => ({
      objectId: object.objectId,
      assetKey: object.asset.assetKey,
      xMm: object.transform.xMm,
      yMm: object.transform.yMm,
      zMm: object.transform.zMm,
      yawMicroradians: object.transform.yawMicroradians,
      scaleMilli: object.transform.scaleMilli,
    }));
  const targets = new Map(places.targets.map((target) => [target.targetId, target.objectId] as const));
  return { uses, objects, targets };
}
