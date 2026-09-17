/**
 * Export the tile runtime bench's test street as exact integer geometry, for structure capture.
 *
 * Run from web/ (whose tsx this uses):
 *
 *   ./node_modules/.bin/tsx ../ml/appearance/capture/export-bench.ts > bench-geometry.json
 *
 * It imports lane 16's pure `test-street.ts` and never edits it. The bench's poses, eye height,
 * camera and default sets live in `bench.ts`, which imports PlayCanvas and cannot run in Node, so
 * the lines below are copied from it verbatim, and `tests/test_bench_capture.py` fails if any of
 * them stops appearing in `bench.ts` exactly as written here.
 *
 * Every length is written in integer micrometres and every normal component in millionths, so the
 * output holds no fraction.
 */

import {
  CORNICE, DOOR, KERB_FACE_Z, KERB_HEIGHT_M, WALL_Z,
  testStreet,
} from '../../../web/packages/atlas-react/test/generated-tile-bench/test-street.js';

// Copied verbatim from bench.ts (checked by tests/test_bench_capture.py).
const EYE_M = 1.62;
const eye = KERB_HEIGHT_M + EYE_M;
const sets = {
      wall: 'cc0.brick-running-bond',
      plinth: 'cc0.limestone-ashlar',
      door: 'cc0.storefront-metal',
      cornice: 'cc0.cast-concrete',
      footway: 'cc0.footway-paving',
      kerb: 'cc0.kerb-stone',
      carriageway: 'cc0.carriageway-asphalt',
};
type Pose = { readonly position: readonly [number, number, number]; readonly target: readonly [number, number, number] };
function eyeLevel(name: 'wall' | 'kerb' | 'door' | 'cornice' | 'street' | 'footway'): Pose {
    switch (name) {
      case 'wall': return { position: [-2.4, eye, 0.4], target: [0.6, 2.6, WALL_Z] };
      case 'kerb': return { position: [-2.0, EYE_M, -4.0], target: [0.4, 0.07, KERB_FACE_Z] };
      case 'door': return { position: [-0.6, eye, 0.8], target: [(DOOR.x0 + DOOR.x1) / 2, 1.2, WALL_Z + DOOR.depth] };
      case 'cornice': return { position: [-2.4, eye, 0.6], target: [0.6, CORNICE.y0, WALL_Z] };
      case 'street': return { position: [-14, eye, 1.0], target: [6, 2.2, 1.6] };
      case 'footway': return { position: [-1.5, eye, 0.6], target: [2.5, 0.15, 1.8] };
    }
}
// End of the verbatim copy.

const um = (metres: number): number => Math.round(metres * 1_000_000);
const millionths = (unit: number): number => Math.round(unit * 1_000_000);
const names = ['wall', 'kerb', 'door', 'cornice', 'street', 'footway'] as const;

const surfaces = testStreet(sets).map((surface) => ({
  indices: [...surface.indices],
  name: surface.name,
  normals_millionths: surface.normals.map(millionths),
  positions_um: surface.positions.map(um),
  surface_mm: surface.surfaceMm.map((value) => Math.round(value)),
  texture_set: surface.setId,
}));
const poses = Object.fromEntries(names.map((name) => {
  const pose = eyeLevel(name);
  return [name, { position_um: pose.position.map(um), target_um: pose.target.map(um) }];
}));

process.stdout.write(JSON.stringify({
  camera: { far_um: um(1200), height: 900, near_um: um(0.08), vertical_fov_degrees: 70, width: 1440 },
  eye_um: um(eye),
  poses,
  profile: 'exulanica.appearance-bench-geometry/v1',
  surfaces,
}));
