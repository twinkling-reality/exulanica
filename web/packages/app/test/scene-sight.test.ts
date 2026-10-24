// What stands in a camera's way (tools/previews/world-workspace/scene-sight.ts sceneHit): a ray asks the picker for a
// mesh only where its segment, out to the nearest surface met so far, passes through the mesh's world box as it is now.
// The meshes here are stand-ins whose surface is their box, so a ray's answer can be worked out by asking every one.
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../atlas-react/src/playcanvas/index.ts', () => ({ StaticMeshPicker: class { pick() { return null; } } }));

type Vec = readonly [number, number, number];
type Mesh = { aabb: { center: { x: number; y: number; z: number }; halfExtents: { x: number; y: number; z: number } } };

/** What these tests use of the preview module, which sits outside this package. */
interface SceneSight {
  sceneHit(app: unknown, picker: { pick(instance: Mesh, origin: Vec, direction: Vec, maximum: number): number | null }): (origin: Vec, direction: Vec, most?: number) => number;
}
// A joined path: the test runner still finds the file, and the type checker leaves the preview module out of the program.
const sight = async (): Promise<SceneSight> => import('../../../../tools/previews/world-workspace/' + 'scene-sight.ts') as never;

const mesh = (x: number, y: number, z: number, hx: number, hy: number, hz: number): Mesh => ({ aabb: { center: { x, y, z }, halfExtents: { x: hx, y: hy, z: hz } } });

/** Where a ray first meets a box, as a picker of a mesh whose surface is its box would answer, out to `maximum`. */
function entry(one: Mesh, origin: Vec, direction: Vec, maximum: number): number | null {
  const { center: c, halfExtents: h } = one.aabb;
  let near = 0, far = maximum;
  for (const [o, d, m, r] of [[origin[0], direction[0], c.x, h.x], [origin[1], direction[1], c.y, h.y], [origin[2], direction[2], c.z, h.z]] as const) {
    if (d === 0) { if (o < m - r || o > m + r) return null; continue; }
    const a = (m - r - o) / d, b = (m + r - o) / d;
    near = Math.max(near, Math.min(a, b));
    far = Math.min(far, Math.max(a, b));
    if (near > far) return null;
  }
  return near;
}

/** A town's worth of stand-in meshes: a row of houses, a low wall, a post, and the ground under them. */
function town(): Mesh[] {
  const meshes: Mesh[] = [mesh(0, -0.05, 0, 60, 0.05, 60), mesh(3, 0.5, -2, 4, 0.5, 0.15), mesh(-1, 1.5, 1, 0.1, 1.5, 0.1)];
  for (let house = 0; house < 40; house += 1) meshes.push(mesh(-40 + house * 2.2, 4, -9, 1, 4, 3));
  return meshes;
}

const appOf = (meshes: Mesh[]) => ({ scene: { layers: { layerList: [{ name: 'World', meshInstances: meshes }, { name: 'UI', meshInstances: [mesh(0, 1, 0, 100, 100, 100)] }] } } });

describe('what stands in a camera\'s way', () => {
  it('answers every ray as asking every mesh does, asking the picker only for the boxes its segment meets', async () => {
    const { sceneHit } = await sight();
    const meshes = town();
    const asked: Mesh[] = [];
    const hit = sceneHit(appOf(meshes), { pick: (one, origin, direction, maximum) => { asked.push(one); return entry(one, origin, direction, maximum); } });
    let rays = 0;
    for (const origin of [[0, 1.6, 6], [5, 1.6, 2], [-8, 3, 0], [0, 0.3, -1]] as const) {
      for (let turn = 0; turn < 24; turn += 1) {
        for (const rise of [-0.3, 0, 0.2]) {
          const yaw = (turn * Math.PI) / 12, length = Math.hypot(1, rise);
          const direction = [Math.sin(yaw) / length, rise / length, -Math.cos(yaw) / length] as const;
          for (const most of [Infinity, 4, 12]) {
            const every = Math.min(...meshes.map((one) => entry(one, origin, direction, most) ?? Infinity));
            expect(hit(origin, direction, most), `${origin} ${turn} ${rise} ${most}`).toBe(every);
            rays += 1;
          }
        }
      }
    }
    // Most meshes are passed by the box test: far fewer asks than a mesh a ray.
    expect(asked.length).toBeLessThan((rays * meshes.length) / 5);
    // What only the user interface draws is never what stands in the way.
    expect(asked.every((one) => meshes.includes(one))).toBe(true);
  });

  it('meets a mesh where it stands now: one moved or placed after the hit was made is met where it is drawn', async () => {
    const { sceneHit } = await sight();
    const meshes = town();
    const moved = mesh(0, 1, -30, 0.5, 1, 0.5);
    meshes.push(moved);
    const hit = sceneHit(appOf(meshes), { pick: entry });
    const origin = [0, 1.6, 5] as const, ahead = [0, 0, -1] as const;
    // Over the low wall to the houses' row 11 m ahead: the one moved stands out of the way, beyond it.
    expect(hit(origin, ahead)).toBeCloseTo(11, 9);
    moved.aabb.center = { x: 0, y: 1, z: 2 };
    expect(hit(origin, ahead)).toBeCloseTo(2.5, 9);
    moved.aabb.center = { x: 20, y: 1, z: 2 };
    expect(hit(origin, ahead)).toBeCloseTo(11, 9);
  });
});
