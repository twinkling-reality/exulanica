import { drawDeclaredFloors } from '@exulanica/atlas-react/playcanvas';
import type { MountedAtlas } from '../atlas.js';
import type { DeclaredFloor } from '../world-entry-api.js';

/**
 * A mounted Atlas with the floor a world made from photographs declares drawn under every region,
 * and taken away with it: disposing the returned Atlas destroys the floors' texture and materials
 * before the binding they were drawn under, so a remount leaves nothing of the last one behind.
 * A world that declares no floor gets back the Atlas it gave.
 */
export function withDeclaredFloors(
  mounted: MountedAtlas,
  floor: DeclaredFloor | null,
  draw: typeof drawDeclaredFloors = drawDeclaredFloors,
): MountedAtlas {
  if (floor === null) return mounted;
  const floors = draw(mounted.binding, floor);
  return {
    ...mounted,
    dispose: () => {
      floors.destroy();
      mounted.dispose();
    },
  };
}
