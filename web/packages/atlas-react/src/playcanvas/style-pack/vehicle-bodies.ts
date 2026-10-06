import * as pc from 'playcanvas';
import { resolveLookRole, type LookFamily, type ResolvedStylePack } from '@exulanica/atlas-core';
import type { RenderShading } from '../generated-tile/look.js';
import type { VehicleBodies } from '../traffic/traffic-layer.js';
import type { VehicleSamples } from '../traffic/types.js';
import type { PackPieces } from './pieces.js';
import { swatchMaterial } from './swatch-material.js';

/**
 * A world's traffic drawn in a style pack's vehicles.
 *
 * A vehicle's body is the pack's piece for `vehicle.<body family>` (`vehicle.hatchback`,
 * `vehicle.rigid_city_bus`), chosen among its variants by the vehicle's id, so every page draws a
 * vehicle the same, and fitted into the record's own width, length and height by the family's fit.
 * The piece's `vehicle_body` swatch takes the vehicle's colour as the pack draws it: the swatch
 * `vehicle_<colour>` (`vehicle_red`, `vehicle_silver`) when the pack states one, else its own. A body
 * family the pack does not dress, or a piece not loaded, keeps the traffic layer's boxes.
 *
 * The pieces' meshes are the library's; every body shares them, and a material per swatch.
 */

/** The swatch a vehicle piece paints its body with, which a vehicle's own colour replaces. */
export const VEHICLE_BODY_SWATCH = 'vehicle_body';

export interface PackVehicleBodies extends VehicleBodies {
  dispose(): void;
}

export function packVehicleBodies(
  pack: ResolvedStylePack,
  families: ReadonlyMap<string, LookFamily>,
  pieces: PackPieces,
  shading: RenderShading,
): PackVehicleBodies {
  const materials = new Map<string, pc.StandardMaterial>();
  const materialOf = (key: string): pc.StandardMaterial => {
    let material = materials.get(key);
    if (material === undefined) {
      material = swatchMaterial(pack.swatches.get(key)!, null, shading, `style-pack:swatch:${key}`);
      materials.set(key, material);
    }
    return material;
  };
  return {
    body(row: VehicleSamples): pc.Entity | null {
      if (!/^[a-z][a-z0-9_]{0,47}$/.test(row.bodyFamily)) return null;
      const { length, width, height } = row.dimensionsMm;
      const dressing = resolveLookRole(
        pack,
        { identity: row.vehicleId, lookRole: `vehicle.${row.bodyFamily}`, positionMm: [0, 0, 0], yawQuarterTurns: 0, boxMm: [width, length, height] },
        families,
        'module',
      );
      if (dressing?.kind !== 'module') return null;
      const module = pack.modules[dressing.role];
      const piece = module === undefined ? undefined : pieces.get(module, dressing.file);
      if (piece === undefined) return null;
      const colour = `vehicle_${row.colour}`;
      const entity = new pc.Entity(`style-pack:${dressing.role}`);
      entity.addComponent('render', {
        meshInstances: piece.groups.map((group) => new pc.MeshInstance(
          group.mesh,
          materialOf(group.swatch === VEHICLE_BODY_SWATCH && pack.swatches.has(colour) ? colour : group.swatch),
        )),
        castShadows: true,
        receiveShadows: true,
      });
      // A piece's front is +Z; a vehicle at yaw 0 faces -Z.
      entity.setLocalEulerAngles(0, 180, 0);
      entity.setLocalScale(dressing.scale[0], dressing.scale[1], dressing.scale[2]);
      return entity;
    },
    dispose() {
      for (const material of materials.values()) material.destroy();
      materials.clear();
    },
  };
}
