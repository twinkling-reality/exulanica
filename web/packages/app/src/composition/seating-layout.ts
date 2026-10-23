/**
 * What the crowd needs to draw people at the objects they use, from what the page already reads.
 *
 * Each kind's use comes from the registry list (`GET /world/assets`, `ReviewedAsset.use`), each
 * object's kind and transform from the version being drawn, and which object each society target
 * belongs to from the places the society's current state consumed (`SocietySnapshot.places`), and a
 * generated town's street furniture from the town's own tile records (`town-furniture.ts`), and each
 * placed thing whose kind states places from its kind and pose as the thing layer draws it
 * (`ThingLayer.seating`).
 * Nothing here decides where anybody is; the crowd reads a person's place from their own state.
 */
import type { FixtureSeat, KindUse, SeatingLayout, SeatingObject, StreetFurniture } from '@exulanica/atlas-react/playcanvas';
import type { SocietyPlaces } from '../society-api.js';
import type { AlternateVersion, ReviewedAsset } from '../world-objects-api.js';

/**
 * The layout for one drawn version and one consumed input, or null when either is not read. A
 * generated town's own street furniture, read from its tiles, rides with it: a town seats people on
 * furniture no object of the version is. A placed thing is an object of the layout by its own id, the
 * id the society's target for it names, with its kind's use: a person resting at a placed bench sits
 * on its seat.
 */
export function seatingLayout(
  assets: readonly ReviewedAsset[],
  version: AlternateVersion | null,
  places: SocietyPlaces | null,
  streetFurniture: readonly StreetFurniture[] = [],
  fixtureSeats: readonly FixtureSeat[] = [],
  placedThings: readonly { readonly object: SeatingObject; readonly use: KindUse }[] = [],
): SeatingLayout | null {
  if (version === null || places === null) return null;
  const uses = new Map<string, KindUse>([
    ...assets.flatMap((asset) => (asset.use ? [[asset.assetKey, asset.use] as const] : [])),
    ...placedThings.map((thing) => [thing.object.assetKey, thing.use] as const),
  ]);
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
  objects.push(...placedThings.map((thing) => thing.object));
  const targets = new Map(places.targets.map((target) => [target.targetId, target.objectId] as const));
  return { uses, objects, targets, ...(streetFurniture.length === 0 ? {} : { streetFurniture }), ...(fixtureSeats.length === 0 ? {} : { fixtureSeats }) };
}
