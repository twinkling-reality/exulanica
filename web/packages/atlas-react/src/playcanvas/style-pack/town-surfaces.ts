import * as pc from 'playcanvas';
import { resolveLookRole, type LookFamily, type ResolvedStylePack } from '@exulanica/atlas-core';
import type { RenderShading } from '../generated-tile/look.js';
import { applyShading } from '../generated-tile/shading.js';
import { applyUp, swatchMaterial } from './swatch-material.js';

/**
 * A town's surfaces, dressed from a style pack after its tiles are drawn.
 *
 * A town's tiles draw one mesh per texture set (`generated-tile:<set id>`), so a pack dresses a
 * town's surfaces a texture set at a time. `assets/style-packs/town-look-roles.v1.json` names the
 * look role each set takes (`wall.brick_running_bond`, `road.carriageway_asphalt`); the pack
 * resolves it by leaf, then by its family's `default`. A swatch replaces the set's material with
 * the swatch's, in the look's shading model; a texture set keeps the set the tile was baked with;
 * either may colour the set's upward faces with an up swatch. A set the pack does not dress keeps
 * the tile's own material. Nothing about the tile's geometry, its navigation or its records is
 * touched, and `dispose` puts every material back.
 */

/** The look role each texture set a town is drawn with takes. */
export interface TownLookRoles {
  readonly sets: Readonly<Record<string, string>>;
}

export interface TownSurfaceDressing {
  /** What each dressed set took: its look role as resolved, and whether a swatch or its own texture. */
  readonly dressed: readonly { readonly setId: string; readonly role: string; readonly by: 'swatch' | 'texture' }[];
  dispose(): void;
}

const PREFIX = 'generated-tile:';

export function dressTownSurfaces(
  root: pc.Entity,
  pack: ResolvedStylePack,
  roles: TownLookRoles,
  families: ReadonlyMap<string, LookFamily>,
  shading: RenderShading,
): TownSurfaceDressing {
  const made = new Map<string, pc.StandardMaterial>();
  const clones: pc.StandardMaterial[] = [];
  const replaced: { instance: pc.MeshInstance; material: pc.Material }[] = [];
  const dressed = new Map<string, { setId: string; role: string; by: 'swatch' | 'texture' }>();
  for (const render of root.findComponents('render') as pc.RenderComponent[]) {
    const name = render.entity.name;
    if (!name.startsWith(PREFIX)) continue;
    const setId = name.slice(PREFIX.length);
    const role = roles.sets[setId];
    if (role === undefined) continue;
    const dressing = resolveLookRole(pack, { identity: setId, lookRole: role, positionMm: [0, 0, 0], yawQuarterTurns: 0, boxMm: [1, 1, 1] }, families, 'surface');
    if (dressing === null || dressing.kind !== 'surface') continue;
    if (dressing.swatch === null && dressing.up === null) continue;
    for (const instance of render.meshInstances) {
      let material: pc.StandardMaterial;
      if (dressing.swatch !== null) {
        const key = `${dressing.role}`;
        material = made.get(key) ?? swatchMaterial(dressing.swatch, dressing.up, shading, `style-pack:${dressing.role}`);
        made.set(key, material);
      } else {
        material = (instance.material as pc.StandardMaterial).clone();
        material.name = `style-pack:${dressing.role}`;
        applyUp(material, dressing.up!.srgb8);
        applyShading(material, shading);
        clones.push(material);
      }
      replaced.push({ instance, material: instance.material });
      instance.material = material;
    }
    dressed.set(setId, { setId, role: dressing.role, by: dressing.swatch !== null ? 'swatch' : 'texture' });
  }
  let disposed = false;
  return {
    dressed: [...dressed.values()],
    dispose() {
      if (disposed) return;
      disposed = true;
      for (const { instance, material } of replaced) instance.material = material;
      for (const material of [...made.values(), ...clones]) material.destroy();
    },
  };
}
