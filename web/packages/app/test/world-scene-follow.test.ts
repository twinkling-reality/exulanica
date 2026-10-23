// @vitest-environment happy-dom
// The follow view's frame for a talking scene (tools/previews/world-workspace/scene-follow.ts, F8): while the
// scene shows, a pose that frames its speaker (and the listener) from a side no bystander stands in front of,
// asked again only when the line's people change; none without a scene. The world is a stand-in society with
// nothing drawn in the way.
import { describe, expect, it } from 'vitest';

type Json = Record<string, any>;
// Joined paths: the test runner still finds the files, and the type checker leaves the preview modules out.
const follow = async (): Promise<any> => import('../../../../tools/previews/world-workspace/' + 'scene-follow.ts');
const framing = async (): Promise<any> => import('../../../../tools/previews/world-workspace/' + 'moment-framing.mjs');

/** A society standing people at render-space points (x, z), 1.7 m tall, facing as given (radians, -Z forward at 0). */
function world(people: Record<string, { x: number; z: number; heading?: number }>) {
  const asked: string[] = [];
  const society = {
    visibleInhabitantIds: Object.keys(people),
    groundOf(id: string, out: Json) { asked.push(id); const one = people[id]; if (!one) return false; out.set(one.x, 0, one.z); return true; },
    heightOf: () => 1.7,
    headingOf: (id: string) => people[id]?.heading ?? 0,
  };
  const binding = {
    authoredSociety: society,
    app: { scene: { layers: { layerList: [] } } },
    camera: { camera: { fov: 60 }, getPosition: () => ({ x: 0, y: 1.6, z: 10 }) },
    controls: { state: { x: 0, y: 1.6, z: 10, yaw: 0, pitch: 0 } },
  };
  return { binding, asked };
}

const scene = (speaker: string, to: string | null) => ({ showing: true, now: { speaker, to } });

describe('the follow view in a talking scene', () => {
  it('frames the speaker and the one spoken to while the scene shows, and holds no frame without one', async () => {
    const { createSceneFollow } = await follow();
    const { binding } = world({ teo: { x: 0, z: 0, heading: Math.PI / 2 }, ines: { x: 1.2, z: 0, heading: -Math.PI / 2 } });
    const view = createSceneFollow(binding);
    expect(view.pose(0)).toBeNull();
    view.saw(scene('teo', 'ines'));
    const pose = view.pose(10);
    expect(pose).not.toBeNull();
    // Looking at the pair from a few metres off, both within the frame's width.
    const toPair = { x: 0.6 - pose.x, z: 0 - pose.z };
    const distance = Math.hypot(toPair.x, toPair.z);
    expect(distance).toBeGreaterThan(1.5);
    expect(distance).toBeLessThan(20);
    const looking = { x: -Math.sin(pose.yaw), z: -Math.cos(pose.yaw) };
    expect((looking.x * toPair.x + looking.z * toPair.z) / distance).toBeGreaterThan(0.8);
    view.saw({ showing: false, now: null });
    expect(view.pose(20)).toBeNull();
  });

  it('is asked again only when the line\'s people change, not every frame', async () => {
    const { createSceneFollow } = await follow();
    const { binding, asked } = world({ teo: { x: 0, z: 0 }, ines: { x: 1, z: 0 }, lia: { x: -1, z: 0.5 } });
    const view = createSceneFollow(binding);
    view.saw(scene('teo', 'ines'));
    const first = view.pose(0);
    const reads = asked.length;
    expect(view.pose(16)).toBe(first);
    expect(asked.length).toBe(reads);
    view.saw(scene('lia', 'teo'));
    expect(view.pose(32)).not.toBe(first);
    expect(asked.length).toBeGreaterThan(reads);
  });

  it('never frames from a side a bystander stands in front of, nearer and larger than the speaker', async () => {
    const { createSceneFollow } = await follow();
    const { standsInBand, MOMENT_FRAMING } = await framing();
    // Teo speaks to the south (toward +z); Bo stands 2 m south of him, where a camera square on would look through him.
    const { binding } = world({ teo: { x: 0, z: 0, heading: Math.PI }, bo: { x: 0, z: 2 } });
    const view = createSceneFollow(binding);
    view.saw(scene('teo', null));
    const pose = view.pose(0);
    expect(pose).not.toBeNull();
    const live = { ...MOMENT_FRAMING, fov_deg: 60, size_px: [innerWidth, innerHeight] };
    const teo = { x: 0, y: 0, z: 0, height: 1.7, heading: Math.PI };
    expect(standsInBand(pose, { x: 0, y: 0, z: 2, height: 1.7 }, live, teo)).toBe(true);
  });

  it('frames the one spoken to with the speaker where both fit', async () => {
    const { createSceneFollow } = await follow();
    const { lensOf, MOMENT_FRAMING } = await framing();
    // Teo and Ines face each other 3 m apart; framed alone from in front, Teo would stand with Ines behind the camera.
    const { binding } = world({ teo: { x: 0, z: 0, heading: -Math.PI / 2 }, ines: { x: 3, z: 0, heading: Math.PI / 2 } });
    const view = createSceneFollow(binding);
    view.saw(scene('teo', 'ines'));
    const pose = view.pose(0);
    const half = lensOf({ ...MOMENT_FRAMING, fov_deg: 60, size_px: [innerWidth, innerHeight] }).horizontal;
    const looking = { x: -Math.sin(pose.yaw), z: -Math.cos(pose.yaw) };
    for (const one of [{ x: 0, z: 0 }, { x: 3, z: 0 }]) {
      const to = { x: one.x - pose.x, z: one.z - pose.z }, length = Math.hypot(to.x, to.z);
      expect(Math.acos((looking.x * to.x + looking.z * to.z) / length)).toBeLessThan(half);
    }
  });

  it('holds no frame for a speaker the crowd does not draw', async () => {
    const { createSceneFollow } = await follow();
    const { binding } = world({ ines: { x: 0, z: 0 } });
    const view = createSceneFollow(binding);
    view.saw(scene('nobody', 'ines'));
    expect(view.pose(0)).toBeNull();
  });
});
