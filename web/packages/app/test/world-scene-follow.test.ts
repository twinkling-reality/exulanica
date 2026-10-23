// @vitest-environment happy-dom
// The follow view's frame for a talking scene (tools/previews/world-workspace/scene-follow.ts, F8): while the
// scene shows, a pose that frames its speaker (and the listener) from a side no bystander stands in front of,
// asked again when the line's people change or the pair walks out of the middle (F8b, eased to, at most every
// 2 s); none without a scene. The world is a stand-in society with nothing drawn in the way.
import { beforeAll, describe, expect, it } from 'vitest';

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

/**
 * Something the scene draws, as the sight test meets it: an upright box `width` metres square and `height` tall
 * standing at render-space (x, z), its twelve triangles in a static mesh instance at the world's own frame.
 */
function standing(x: number, z: number, width: number, height = 3): object {
  const h = width / 2;
  const min = [x - h, 0, z - h], max = [x + h, height, z + h];
  const corners = [0, 1, 2, 3, 4, 5, 6, 7].map((c) => [c & 1 ? max[0]! : min[0]!, c & 2 ? max[1]! : min[1]!, c & 4 ? max[2]! : min[2]!]);
  const faces = [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]];
  const node = { enabled: true, parent: null, getWorldTransform: () => ({ data: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1] }) };
  const mesh = {
    primitive: [{ type: 4, base: 0, count: 36, indexed: true }],
    getPositions: (out: number[]) => out.push(...corners.flat()),
    getIndices: (out: number[]) => out.push(...faces.flatMap(([a, b, c, d]) => [a!, b!, c!, a!, c!, d!])),
  };
  // The box's slab test, as the engine's bounds answer a ray.
  const intersectsRay = ({ origin, direction }: { origin: Json; direction: Json }) => {
    let near = -Infinity, far = Infinity;
    for (const [axis, low, high] of [['x', min[0]!, max[0]!], ['y', min[1]!, max[1]!], ['z', min[2]!, max[2]!]] as const) {
      const o = origin[axis] as number, d = direction[axis] as number;
      if (Math.abs(d) < 1e-12) { if (o < low || o > high) return false; continue; }
      const [a, b] = [(low - o) / d, (high - o) / d].sort((p, q) => p - q);
      near = Math.max(near, a!); far = Math.min(far, b!);
    }
    return near <= far && far >= 0;
  };
  return { mesh, node, visible: true, aabb: { intersectsRay } };
}

/**
 * Teo and Ines facing each other 1.2 m apart, and a camera that stands where the view put it last (as
 * framePair does) and projects as a 60 degree lens: `project` gives a point's screen x and depth, `look` moves
 * the camera to a pose.
 */
function walkingWorld() {
  type Pose = { x: number; z: number; heading?: number };
  const people: { teo: Pose; ines: Pose } & Record<string, Pose> = {
    teo: { x: 0, z: 0, heading: Math.PI / 2 }, ines: { x: 1.2, z: 0, heading: -Math.PI / 2 },
  };
  const { binding } = world(people);
  let eye = { x: 0, y: 1.6, z: 10, yaw: 0, pitch: 0 };
  const half = Math.atan(Math.tan(Math.PI / 6) * innerWidth / innerHeight);
  const project = (p: { x: number; z: number }) => {
    const d = { x: p.x - eye.x, z: p.z - eye.z };
    const depth = -d.x * Math.sin(eye.yaw) - d.z * Math.cos(eye.yaw), across = d.x * Math.cos(eye.yaw) - d.z * Math.sin(eye.yaw);
    return { x: innerWidth / 2 + (across / depth) * (innerWidth / 2) / Math.tan(half), y: innerHeight / 2, z: depth };
  };
  Object.assign(binding.camera, { getPosition: () => eye, camera: { fov: 60, worldToScreen: project } });
  binding.controls.state = eye;
  const look = (pose: Json) => { eye = { ...pose } as typeof eye; binding.controls.state = eye; };
  return { people, binding, project, look };
}

describe('the follow view in a talking scene', () => {
  // The preview modules load once, under their own bound, so no test's bound pays for the first import.
  beforeAll(async () => { await follow(); await framing(); }, 30_000);

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
    // Between askings only the speaker's ground is read (to carry the frame as they walk, F8b), nobody else's.
    expect(asked.slice(reads).every((id) => id === 'teo')).toBe(true);
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

  it('carries the frame with a speaker who walks on, keeping them where they stood in it', async () => {
    const { createSceneFollow } = await follow();
    const { people, binding, project, look } = walkingWorld();
    const view = createSceneFollow(binding);
    view.saw(scene('teo', 'ines'));
    const first = view.pose(0);
    look(first);
    const before = project(people.teo);
    for (const one of [people.teo, people.ines]) { one.x += 3; one.z -= 1; }
    const carried = view.pose(100);
    expect(carried.x - first.x).toBeCloseTo(3, 6);
    expect(carried.z - first.z).toBeCloseTo(-1, 6);
    expect(carried.yaw).toBe(first.yaw);
    look(carried);
    expect(project(people.teo).x).toBeCloseTo(before.x, 3);
  });

  it('asks again, eased and at most every 2 s, once a listener framed with the speaker drifts out of the middle', async () => {
    const { createSceneFollow, SCENE_FOLLOW } = await follow();
    const { people, binding, project, look } = walkingWorld();
    const view = createSceneFollow(binding);
    view.saw(scene('teo', 'ines'));
    const first = view.pose(0);
    look(first);
    // The listener stands in the middle at the first check; then the speaker walks on and Ines stays behind.
    expect(view.pose(SCENE_FOLLOW.checkMs)).toBe(first);
    const listenerSeen = project(people.ines);
    expect(listenerSeen.x).toBeGreaterThan(innerWidth * 0.1);
    expect(listenerSeen.x).toBeLessThan(innerWidth * 0.9);
    // To the camera's left, across the view, so far that Ines (carried with Teo's frame) stands nine tenths of
    // the way from the middle to the right edge: still in the frame, out of its middle.
    const metres = (innerWidth * 0.95 - listenerSeen.x) / ((innerWidth / 2) / Math.tan(Math.atan(Math.tan(Math.PI / 6) * innerWidth / innerHeight))) * listenerSeen.z;
    const left = { x: -metres * Math.cos(first.yaw), z: metres * Math.sin(first.yaw) };
    people.teo.x += left.x; people.teo.z += left.z;
    // Drifted at once, but not asked again until 2 s after the frame: the frame is only carried.
    for (const at of [2 * SCENE_FOLLOW.checkMs, SCENE_FOLLOW.reaskLeastMs - SCENE_FOLLOW.checkMs]) {
      const carried = view.pose(at);
      expect(carried.x - first.x).toBeCloseTo(left.x, 6);
      expect(carried.z - first.z).toBeCloseTo(left.z, 6);
      expect(carried.yaw).toBe(first.yaw);
      look(carried);
      const out = project(people.ines);
      expect(out.z).toBeGreaterThan(0);
      expect(out.x).toBeGreaterThan(innerWidth * 0.9);
      expect(out.x).toBeLessThan(innerWidth);
    }
    const held = view.pose(SCENE_FOLLOW.reaskLeastMs - SCENE_FOLLOW.checkMs);
    const started = SCENE_FOLLOW.reaskLeastMs;
    const eased = view.pose(started);
    // Asked again, and eased from the frame held: at first still where the camera stands.
    expect(Math.hypot(eased.x - held.x, eased.z - held.z)).toBeLessThan(0.01);
    const midway = view.pose(started + SCENE_FOLLOW.easeMs / 2);
    const settled = view.pose(started + SCENE_FOLLOW.easeMs);
    const moved = Math.hypot(settled.x - held.x, settled.z - held.z) + Math.abs(Math.sin(settled.yaw - held.yaw));
    expect(moved).toBeGreaterThan(0.05);
    const part = Math.hypot(midway.x - held.x, midway.z - held.z) / Math.max(1e-9, Math.hypot(settled.x - held.x, settled.z - held.z));
    if (Math.hypot(settled.x - held.x, settled.z - held.z) > 0.05) {
      expect(part).toBeGreaterThan(0.2);
      expect(part).toBeLessThan(0.8);
    }
    // Settled, the frame holds as it is.
    expect(view.pose(started + SCENE_FOLLOW.easeMs + 16)).toBe(view.pose(started + SCENE_FOLLOW.easeMs + 32));
    look(settled);
    const speaker = project(people.teo);
    expect(speaker.x).toBeGreaterThan(innerWidth * 0.1);
    expect(speaker.x).toBeLessThan(innerWidth * 0.9);
  });

  it('asks again, eased, once a passer-by has stood in front of the speaker for two checks, to a side clear of them', async () => {
    const { createSceneFollow, SCENE_FOLLOW } = await follow();
    const { standsInBand, MOMENT_FRAMING } = await framing();
    const { people, binding, look } = walkingWorld();
    // Teo and Ines face each other along a north-south line, so either side shows both in profile.
    people.teo = { x: 0, z: 0, heading: 0 };
    people.ines = { x: 0, z: -1.2, heading: Math.PI };
    const view = createSceneFollow(binding);
    view.saw(scene('teo', 'ines'));
    const first = view.pose(0);
    look(first);
    // Bo stops a third of the way from the camera to Teo: nearer and larger than him, in front of him.
    people.bo = { x: first.x + (people.teo.x - first.x) / 3, z: first.z + (people.teo.z - first.z) / 3 };
    binding.authoredSociety.visibleInhabitantIds = Object.keys(people);
    const live = { ...MOMENT_FRAMING, fov_deg: 60, size_px: [innerWidth, innerHeight] };
    const teo = () => ({ x: people.teo.x, y: 0, z: people.teo.z, height: 1.7 });
    const bo = () => ({ x: people.bo!.x, y: 0, z: people.bo!.z, height: 1.7 });
    expect(standsInBand(first, bo(), live, teo())).toBe(false);
    // Two checks in a row in front, but no new frame within 2 s of the first.
    for (let at = SCENE_FOLLOW.checkMs; at < SCENE_FOLLOW.reaskLeastMs; at += SCENE_FOLLOW.checkMs) expect(view.pose(at)).toBe(first);
    const started = SCENE_FOLLOW.reaskLeastMs;
    const eased = view.pose(started);
    expect(Math.hypot(eased.x - first.x, eased.z - first.z)).toBeLessThan(0.01);
    const settled = view.pose(started + SCENE_FOLLOW.easeMs);
    look(settled);
    expect(standsInBand(settled, bo(), live, teo())).toBe(true);
    expect(SCENE_FOLLOW.crowdedChecks).toBe(2);
  });

  it('never moves the camera for someone near it at the frame\'s edge who covers neither of the line\'s people', async () => {
    const { createSceneFollow, SCENE_FOLLOW } = await follow();
    const { standsInBand, lensOf, MOMENT_FRAMING } = await framing();
    const { people, binding, look } = walkingWorld();
    people.teo = { x: 0, z: 0, heading: 0 };
    people.ines = { x: 0, z: -1.2, heading: Math.PI };
    const view = createSceneFollow(binding);
    view.saw(scene('teo', 'ines'));
    const first = view.pose(0);
    look(first);
    // Bo stands 1.5 m ahead of the camera, nine tenths of the way from the middle to the right edge: nearer and
    // larger than Teo, but over nobody.
    const live = { ...MOMENT_FRAMING, fov_deg: 60, size_px: [innerWidth, innerHeight] };
    const ahead = { x: -Math.sin(first.yaw), z: -Math.cos(first.yaw) }, right = { x: Math.cos(first.yaw), z: -Math.sin(first.yaw) };
    const aside = 0.9 * 1.5 * Math.tan(lensOf(live).horizontal);
    people.bo = { x: first.x + ahead.x * 1.5 + right.x * aside, z: first.z + ahead.z * 1.5 + right.z * aside };
    binding.authoredSociety.visibleInhabitantIds = Object.keys(people);
    expect(standsInBand(first, { x: people.bo.x, y: 0, z: people.bo.z, height: 1.7 }, live, { x: 0, y: 0, z: 0, height: 1.7 })).toBe(false);
    for (let at = SCENE_FOLLOW.checkMs; at <= 3 * SCENE_FOLLOW.reaskLeastMs; at += SCENE_FOLLOW.checkMs) expect(view.pose(at)).toBe(first);
  });

  it('counts a passer-by just beside the speaker, within a tenth of the frame\'s width of them', async () => {
    const { createSceneFollow, SCENE_FOLLOW } = await follow();
    const { lensOf, MOMENT_FRAMING } = await framing();
    const { people, binding, look } = walkingWorld();
    people.teo = { x: 0, z: 0, heading: 0 };
    people.ines = { x: 0, z: -1.2, heading: Math.PI };
    const view = createSceneFollow(binding);
    view.saw(scene('teo', 'ines'));
    const first = view.pose(0);
    look(first);
    // Across the frame, -1 to 1 edge to edge: Teo's box, and Bo 1.5 m ahead of the camera with his box a twentieth
    // of the width clear of Teo's on the side away from Ines.
    const tan = Math.tan(lensOf({ ...MOMENT_FRAMING, fov_deg: 60, size_px: [innerWidth, innerHeight] }).horizontal);
    const ahead = { x: -Math.sin(first.yaw), z: -Math.cos(first.yaw) }, right = { x: Math.cos(first.yaw), z: -Math.sin(first.yaw) };
    const across = (p: { x: number; z: number }) => {
      const v = { x: p.x - first.x, z: p.z - first.z };
      const depth = v.x * ahead.x + v.z * ahead.z;
      return { at: (v.x * right.x + v.z * right.z) / (depth * tan), half: SCENE_FOLLOW.bodyWidthMetres / 2 / (depth * tan) };
    };
    const teo = across(people.teo), ines = across(people.ines);
    const side = teo.at >= ines.at ? 1 : -1;
    const boHalf = SCENE_FOLLOW.bodyWidthMetres / 2 / (1.5 * tan);
    const boAt = teo.at + side * (teo.half + boHalf + 0.1);
    people.bo = { x: first.x + ahead.x * 1.5 + right.x * boAt * 1.5 * tan, z: first.z + ahead.z * 1.5 + right.z * boAt * 1.5 * tan };
    binding.authoredSociety.visibleInhabitantIds = Object.keys(people);
    for (let at = SCENE_FOLLOW.checkMs; at < SCENE_FOLLOW.reaskLeastMs; at += SCENE_FOLLOW.checkMs) expect(view.pose(at)).toBe(first);
    expect(view.pose(SCENE_FOLLOW.reaskLeastMs)).not.toBe(first);
  });

  it('asks again once the one spoken to stands over the speaker\'s head, to a frame where they no longer do', async () => {
    const { createSceneFollow, SCENE_FOLLOW } = await follow();
    const { standsInBand, MOMENT_FRAMING } = await framing();
    const { people, binding, look } = walkingWorld();
    people.teo = { x: 0, z: 0, heading: 0 };
    people.ines = { x: 0, z: -1.2, heading: Math.PI };
    const view = createSceneFollow(binding);
    view.saw(scene('teo', 'ines'));
    const first = view.pose(0);
    look(first);
    // Ines, still the one Teo speaks to, steps round to a third of the way from the camera to him: nearer and larger
    // than him, straight over his head.
    people.ines = { x: first.x + (people.teo.x - first.x) / 3, z: first.z + (people.teo.z - first.z) / 3, heading: first.yaw };
    const live = { ...MOMENT_FRAMING, fov_deg: 60, size_px: [innerWidth, innerHeight] };
    const teo = { x: people.teo.x, y: 0, z: people.teo.z, height: 1.7 };
    const ines = { x: people.ines.x, y: 0, z: people.ines.z, height: 1.7 };
    expect(standsInBand(first, ines, live, teo)).toBe(false);
    for (let at = SCENE_FOLLOW.checkMs; at < SCENE_FOLLOW.reaskLeastMs; at += SCENE_FOLLOW.checkMs) expect(view.pose(at)).toBe(first);
    expect(view.pose(SCENE_FOLLOW.reaskLeastMs)).not.toBe(first);
    const settled = view.pose(SCENE_FOLLOW.reaskLeastMs + SCENE_FOLLOW.easeMs);
    look(settled);
    // From the new side Ines is farther than Teo, or her body clears his across the frame.
    const ahead = { x: -Math.sin(settled.yaw), z: -Math.cos(settled.yaw) }, right = { x: Math.cos(settled.yaw), z: -Math.sin(settled.yaw) };
    const seen = (p: { x: number; z: number }) => {
      const v = { x: p.x - settled.x, z: p.z - settled.z };
      const depth = v.x * ahead.x + v.z * ahead.z;
      return { depth, at: (v.x * right.x + v.z * right.z) / depth, half: SCENE_FOLLOW.bodyWidthMetres / 2 / depth };
    };
    const him = seen(teo), her = seen(ines);
    expect(her.depth > him.depth || Math.abs(her.at - him.at) > her.half + him.half).toBe(true);
    expect(settled).not.toEqual(first);
  });

  it('never frames from a side where a post stands across the speaker\'s widened box, between the rays to their points', async () => {
    const { createSceneFollow } = await follow();
    const { lensOf, MOMENT_FRAMING } = await framing();
    const tan = Math.tan(lensOf({ ...MOMENT_FRAMING, fov_deg: 60, size_px: [innerWidth, innerHeight] }).horizontal);
    for (const margin of [false, true]) {
      const { people, binding, look } = walkingWorld();
      people.teo = { x: 0, z: 0, heading: 0 };
      people.ines = { x: 0, z: -1.2, heading: Math.PI };
      const first = createSceneFollow(binding);
      first.saw(scene('teo', 'ines'));
      const was = first.pose(0);
      // A post 8 cm across a third of the way from that camera to Teo: its near edge 2 cm beside the line to him
      // (across his body, clear of the rays to his feet, waist and head); or, on the side away from Ines, in the
      // margin his box is widened by, half a tenth of the frame's width out from his body.
      const way = { x: (people.teo.x - was.x) / 3, z: (people.teo.z - was.z) / 3 }, length = Math.hypot(way.x, way.z);
      const right = { x: -way.z / length, z: way.x / length };
      const away = (people.ines.x - people.teo.x) * right.x + (people.ines.z - people.teo.z) * right.z > 0 ? -1 : 1;
      const by = margin ? away * (0.25 + 0.1 * 3 * length * tan) / 3 : 0.06;
      const post = { x: was.x + way.x + right.x * by, z: was.z + way.z + right.z * by };
      expect(clearOf(was, post, people.teo)).toBe(false);
      binding.app.scene.layers.layerList = [{ name: 'World', meshInstances: [standing(post.x, post.z, 0.08)] }] as never;
      const view = createSceneFollow(binding);
      view.saw(scene('teo', 'ines'));
      const now = view.pose(0);
      look(now);
      expect(Math.hypot(now.x - was.x, now.z - was.z)).toBeGreaterThan(0.5);
      // From the side chosen the post stands clear of Teo's box widened by a tenth of the frame, or beyond him.
      expect(clearOf(now, post, people.teo)).toBe(true);
    }
  });

  it('asks again once a frame carried with the pair has slid behind a post for two checks', async () => {
    const { createSceneFollow, SCENE_FOLLOW } = await follow();
    const { people, binding, look } = walkingWorld();
    people.teo = { x: 0, z: 0, heading: 0 };
    people.ines = { x: 0, z: -1.2, heading: Math.PI };
    const probe = createSceneFollow(binding);
    probe.saw(scene('teo', 'ines'));
    const was = probe.pose(0);
    // The pair will walk 3 m on, square to the line from that camera to Teo; the post stands where that line will
    // be once the frame is carried with them, a third of the way, 6 cm beside it.
    const line = { x: people.teo.x - was.x, z: people.teo.z - was.z }, length = Math.hypot(line.x, line.z);
    const walk = { x: (-line.z / length) * 3, z: (line.x / length) * 3 };
    const post = { x: was.x + walk.x + line.x / 3 - (line.z / length) * 0.06, z: was.z + walk.z + line.z / 3 + (line.x / length) * 0.06 };
    binding.app.scene.layers.layerList = [{ name: 'World', meshInstances: [standing(post.x, post.z, 0.08)] }] as never;
    const view = createSceneFollow(binding);
    view.saw(scene('teo', 'ines'));
    const first = view.pose(0);
    expect(first).toEqual(was);
    look(first);
    people.teo = { ...people.teo, x: people.teo.x + walk.x, z: people.teo.z + walk.z };
    people.ines = { ...people.ines, x: people.ines.x + walk.x, z: people.ines.z + walk.z };
    // Carried with Teo: the same view of the pair, now with the post across him, held two checks and 2 s at least.
    const carried = view.pose(SCENE_FOLLOW.checkMs);
    expect(carried.x).toBeCloseTo(first.x + walk.x, 9);
    look(carried);
    expect(clearOf(carried, post, people.teo)).toBe(false);
    for (let at = 2 * SCENE_FOLLOW.checkMs; at < SCENE_FOLLOW.reaskLeastMs; at += SCENE_FOLLOW.checkMs) expect(view.pose(at)).toEqual(carried);
    // Asked again at 2 s, eased to from the frame held.
    expect(view.pose(SCENE_FOLLOW.reaskLeastMs)).toEqual(carried);
    const settled = view.pose(SCENE_FOLLOW.reaskLeastMs + SCENE_FOLLOW.easeMs);
    expect(Math.hypot(settled.x - carried.x, settled.z - carried.z)).toBeGreaterThan(0.5);
    expect(clearOf(settled, post, people.teo)).toBe(true);
  });

  it('asks again for something within half the speaker\'s distance over more than a tenth of the frame, not for less', async () => {
    const { createSceneFollow, SCENE_FOLLOW } = await follow();
    const { lensOf, MOMENT_FRAMING } = await framing();
    const tan = Math.tan(lensOf({ ...MOMENT_FRAMING, fov_deg: 60, size_px: [innerWidth, innerHeight] }).horizontal);
    // Wide and within half his distance; thin; wide but beyond half his distance (and inward, still clear of both).
    for (const [width, share, moves] of [[0.8, 0, true], [0.08, 0, false], [0.8, 0.65, false]] as const) {
      const { people, binding, look } = walkingWorld();
      people.teo = { x: 0, z: 0, heading: 0 };
      people.ines = { x: 0, z: -1.2, heading: Math.PI };
      const probe = createSceneFollow(binding);
      probe.saw(scene('teo', 'ines'));
      const was = probe.pose(0);
      // Teo walks 2 m on, square to the line from the camera; where the carried camera will stand, something stands
      // 1 m ahead of it at the frame's right edge (clear of both their boxes), within half Teo's distance.
      const line = { x: people.teo.x - was.x, z: people.teo.z - was.z }, length = Math.hypot(line.x, line.z);
      const walk = { x: (-line.z / length) * 2, z: (line.x / length) * 2 };
      const ahead = { x: -Math.sin(was.yaw), z: -Math.cos(was.yaw) }, right = { x: Math.cos(was.yaw), z: -Math.sin(was.yaw) };
      // On the line of the foreground test's outermost column of rays (16 across), so the thin one meets one column.
      const off = share === 0 ? 1 : share * length, out = (share === 0 ? 15 / 16 : 0.6) * off * tan;
      const at = { x: was.x + walk.x + ahead.x * off + right.x * out, z: was.z + walk.z + ahead.z * off + right.z * out };
      // Its nearest corner within half his distance, or beyond it.
      expect(Math.hypot(off, out) - width / Math.SQRT2 < length * SCENE_FOLLOW.nearShare).toBe(share === 0);
      // Drawn once the frame is asked, as a building's part comes in sight.
      const thing = standing(at.x, at.z, width) as { visible: boolean };
      thing.visible = false;
      binding.app.scene.layers.layerList = [{ name: 'World', meshInstances: [thing] }] as never;
      const view = createSceneFollow(binding);
      view.saw(scene('teo', 'ines'));
      const first = view.pose(0);
      expect(first).toEqual(was);
      look(first);
      thing.visible = true;
      people.teo = { ...people.teo, x: people.teo.x + walk.x, z: people.teo.z + walk.z };
      people.ines = { ...people.ines, x: people.ines.x + walk.x, z: people.ines.z + walk.z };
      const carried = view.pose(SCENE_FOLLOW.checkMs);
      look(carried);
      for (let at = 2 * SCENE_FOLLOW.checkMs; at < SCENE_FOLLOW.reaskLeastMs; at += SCENE_FOLLOW.checkMs) expect(view.pose(at)).toEqual(carried);
      if (moves) {
        view.pose(SCENE_FOLLOW.reaskLeastMs);
        const settled = view.pose(SCENE_FOLLOW.reaskLeastMs + SCENE_FOLLOW.easeMs);
        expect(Math.hypot(settled.x - carried.x, settled.z - carried.z)).toBeGreaterThan(0.5);
      } else for (let at = SCENE_FOLLOW.reaskLeastMs; at <= 3 * SCENE_FOLLOW.reaskLeastMs; at += SCENE_FOLLOW.checkMs) expect(view.pose(at)).toEqual(carried);
    }
  });

  it('asks again for a post across the one spoken to, and never for one the carried frame passes within a check', async () => {
    const { createSceneFollow, SCENE_FOLLOW } = await follow();
    for (const brief of [false, true]) {
      const { people, binding, look } = walkingWorld();
      people.teo = { x: 0, z: 0, heading: 0 };
      people.ines = { x: 0, z: -1.2, heading: Math.PI };
      const probe = createSceneFollow(binding);
      probe.saw(scene('teo', 'ines'));
      const was = probe.pose(0);
      // A post a third of the way from the camera to Ines, 6 cm beside the line to her: across her, clear of Teo.
      const line = { x: people.ines.x - was.x, z: people.ines.z - was.z }, length = Math.hypot(line.x, line.z);
      const post = { x: was.x + line.x / 3 - (line.z / length) * 0.06, z: was.z + line.z / 3 + (line.x / length) * 0.06 };
      expect(clearOf(was, post, people.teo)).toBe(true);
      expect(clearOf(was, post, people.ines)).toBe(false);
      const thing = standing(post.x, post.z, 0.08) as { visible: boolean };
      thing.visible = false;
      binding.app.scene.layers.layerList = [{ name: 'World', meshInstances: [thing] }] as never;
      const view = createSceneFollow(binding);
      view.saw(scene('teo', 'ines'));
      const first = view.pose(0);
      expect(first).toEqual(was);
      look(first);
      for (let at = SCENE_FOLLOW.checkMs; at < SCENE_FOLLOW.reaskLeastMs; at += SCENE_FOLLOW.checkMs) expect(view.pose(at)).toEqual(first);
      // Drawn from 2 s on; where brief, only at that one check.
      thing.visible = true;
      expect(view.pose(SCENE_FOLLOW.reaskLeastMs)).toEqual(first);
      if (brief) thing.visible = false;
      view.pose(SCENE_FOLLOW.reaskLeastMs + SCENE_FOLLOW.checkMs);
      const settled = view.pose(SCENE_FOLLOW.reaskLeastMs + SCENE_FOLLOW.checkMs + SCENE_FOLLOW.easeMs);
      if (brief) expect(settled).toEqual(first);
      else expect(clearOf(settled, post, people.ines)).toBe(true);
    }
  });

  it('never moves the camera for a passer-by who crosses in front within a check', async () => {
    const { createSceneFollow, SCENE_FOLLOW } = await follow();
    const { people, binding, look } = walkingWorld();
    const view = createSceneFollow(binding);
    view.saw(scene('teo', 'ines'));
    const first = view.pose(0);
    look(first);
    // Lia stands well beyond the pair, in the frame and smaller than Teo: in the band, never a reason to move.
    people.lia = { x: people.teo.x + (people.teo.x - first.x) * 1.5, z: people.teo.z + (people.teo.z - first.z) * 1.5 };
    binding.authoredSociety.visibleInhabitantIds = Object.keys(people);
    // Checks pass with nobody in front; then, at the first check a new frame could be asked, Bo is in front of
    // Teo, and by the next he has walked on out of the frame.
    for (let at = SCENE_FOLLOW.checkMs; at < SCENE_FOLLOW.reaskLeastMs; at += SCENE_FOLLOW.checkMs) expect(view.pose(at)).toBe(first);
    people.bo = { x: first.x + (people.teo.x - first.x) / 3, z: first.z + (people.teo.z - first.z) / 3 };
    binding.authoredSociety.visibleInhabitantIds = Object.keys(people);
    expect(view.pose(SCENE_FOLLOW.reaskLeastMs)).toBe(first);
    people.bo = { x: first.x - 40, z: first.z + 40 };
    for (let at = SCENE_FOLLOW.reaskLeastMs + SCENE_FOLLOW.checkMs; at <= 3 * SCENE_FOLLOW.reaskLeastMs; at += SCENE_FOLLOW.checkMs) expect(view.pose(at)).toBe(first);
  });

  it('holds no frame for a speaker the crowd does not draw', async () => {
    const { createSceneFollow } = await follow();
    const { binding } = world({ ines: { x: 0, z: 0 } });
    const view = createSceneFollow(binding);
    view.saw(scene('nobody', 'ines'));
    expect(view.pose(0)).toBeNull();
  });
});

/**
 * Whether a post (its centre, render space) stands clear of someone's box from a pose: beyond them, or across the
 * frame farther from them than half a body and a tenth of the frame's width at their distance, and its own half.
 */
function clearOf(pose: { x: number; z: number; yaw: number }, post: { x: number; z: number }, one: { x: number; z: number }): boolean {
  const ahead = { x: -Math.sin(pose.yaw), z: -Math.cos(pose.yaw) }, right = { x: Math.cos(pose.yaw), z: -Math.sin(pose.yaw) };
  const seen = (p: { x: number; z: number }) => {
    const v = { x: p.x - pose.x, z: p.z - pose.z };
    const depth = v.x * ahead.x + v.z * ahead.z;
    return { depth, at: (v.x * right.x + v.z * right.z) / depth };
  };
  const him = seen(one), it = seen(post);
  const tan = Math.tan(Math.atan(Math.tan(Math.PI / 6) * innerWidth / innerHeight));
  if (it.depth <= 0 || it.depth > him.depth) return true;
  return Math.abs(it.at - him.at) > 0.25 / him.depth + 0.2 * tan + 0.04 / it.depth;
}
