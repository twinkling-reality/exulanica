// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import * as pc from 'playcanvas';
import { SocietyCrowd, type PoseInterval } from '../src/playcanvas/society/crowd.js';
import { CharacterHost } from '../src/playcanvas/character/host.js';
import { NEAR_CHARACTER_BUDGET, NEAR_INHABITANT_BUDGET, PLAYER_NEAR_PLACES } from '../src/playcanvas/character/budget.js';
import { CHARACTER_CATALOG } from '../src/playcanvas/character/catalog-data.js';
import { FAR_REGIONS, farAppearance } from '../src/playcanvas/character/far.js';
import { inhabitantLookOf } from '../src/playcanvas/character/inhabitant.js';
import { abstractInhabitantRenderable } from '../src/playcanvas/society/near-character.js';
import type {
  CrowdPose,
  CrowdRenderable,
  CrowdRenderableFactory,
  OwnedSocietyState,
} from '../src/playcanvas/society/types.js';

function setup(factory?: CrowdRenderableFactory, nearLimit?: number, poseInterval?: PoseInterval) {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  const root = new pc.Entity('society');
  app.root.addChild(root);
  const crowd = new SocietyCrowd(device, root, {
    ...(factory ? { factory } : {}),
    ...(nearLimit !== undefined ? { nearLimit } : {}),
    ...(poseInterval ? { poseInterval } : {}),
  });
  return { crowd, app, root };
}

/** People drawn from shared containers: no bytes of their own, as the seam allows. */
function sharedContainerFactory(): CrowdRenderableFactory {
  return (_device, parent, identity) => {
    const root = new pc.Entity(`shared:${identity.inhabitantId}`);
    parent.addChild(root);
    return {
      root,
      subject: { kind: 'synthetic-inhabitant', ...identity },
      standingHeight: 1.8,
      facing: 0,
      pose: (pose) => root.setLocalPosition(pose.position[0], pose.position[1], pose.position[2]),
      setVisible: (visible) => { root.enabled = visible; },
      destroy: () => root.destroy(),
    };
  };
}

function fakeFactory(log: { identity: unknown; detail: string; poses: CrowdPose[] }[]): CrowdRenderableFactory {
  return (_device, parent, identity, detail) => {
    const entry = { identity, detail, poses: [] as CrowdPose[] };
    log.push(entry);
    const root = new pc.Entity(`fake:${identity.inhabitantId}`);
    parent.addChild(root);
    const renderable: CrowdRenderable = {
      root,
      subject: { kind: 'synthetic-inhabitant', ...identity },
      standingHeight: 1.8,
      facing: 0,
      residentBytes: 10,
      textureResidentBytes: 1,
      pose: (pose) => {
        entry.poses.push(pose);
        root.setLocalPosition(pose.position[0], pose.position[1], pose.position[2]);
      },
      setVisible: (visible) => { root.enabled = visible; },
      destroy: () => root.destroy(),
    };
    return renderable;
  };
}

const v4 = (tick: number, inhabitants: OwnedSocietyState['inhabitants']): OwnedSocietyState => ({
  profile: 'exulanica-society/v4',
  society_id: 'society',
  branch_id: 'branch',
  tick,
  inhabitants,
});

/** Thirty people a metre apart walking north, with renderables that can be carried between poses. */
function cadenceScenario(poseInterval?: PoseInterval) {
  const poses = new Map<string, CrowdPose[]>();
  const follows = new Map<string, number>();
  const factory: CrowdRenderableFactory = (_device, parent, identity) => {
    const id = identity.inhabitantId;
    poses.set(id, poses.get(id) ?? []);
    follows.set(id, follows.get(id) ?? 0);
    const root = new pc.Entity(`fake:${id}`);
    parent.addChild(root);
    return {
      root,
      subject: { kind: 'synthetic-inhabitant', ...identity },
      standingHeight: 1.8,
      facing: 0,
      residentBytes: 10,
      textureResidentBytes: 1,
      pose: (pose) => {
        poses.get(id)!.push(pose);
        root.setLocalPosition(pose.position[0], pose.position[1], pose.position[2]);
      },
      follow: (position) => {
        follows.set(id, follows.get(id)! + 1);
        root.setLocalPosition(position[0], position[1], position[2]);
      },
      setVisible: (visible) => { root.enabled = visible; },
      destroy: () => root.destroy(),
    };
  };
  const { crowd, app } = setup(factory, undefined, poseInterval);
  const people = (tick: number) => Array.from({ length: 30 }, (_, i) => ({
    id: `p${String(i).padStart(3, '0')}`,
    synthetic: true as const,
    position_mm: [i * 1000, tick ? 10_000 : 0] as const,
    motion_path_mm: tick ? [[i * 1000, 0], [i * 1000, 10_000]] as const : [[i * 1000, 0]] as const,
    walk_speed_mm_per_tick: 60_000,
  }));
  crowd.set(v4(0, people(0)), [0, 0], { nowMs: 0, intervalMs: 60_000 });
  crowd.set(v4(1, people(1)), [0, 0], { nowMs: 0, intervalMs: 60_000 });
  const near = Array.from({ length: Math.min(30, NEAR_INHABITANT_BUDGET) }, (_, i) => `p${String(i).padStart(3, '0')}`);
  expect(crowd.drawnIds.slice(0, crowd.counts.near)).toEqual(near);
  const total = () => near.reduce((sum, id) => sum + poses.get(id)!.length, 0);
  const run = (from: number, frames: number) => {
    // Everyone ever drawn in full, so a person who becomes near during a window is counted too.
    const known = () => [...poses.keys()];
    const posesBefore = new Map(known().map((id) => [id, poses.get(id)!.length]));
    const followsBefore = new Map(known().map((id) => [id, follows.get(id)!]));
    const perFrame: number[] = [];
    for (let frame = 1; frame <= frames; frame += 1) {
      const held = total();
      crowd.update(((from + frame) * 1000) / 60);
      perFrame.push(total() - held);
      for (const id of crowd.drawnIds.slice(0, crowd.counts.near)) {
        const at = crowd.positionOf(id)!;
        const root = app.root.findByName(`fake:${id}`)!.getLocalPosition();
        expect([root.x, root.z], id).toEqual([at[0], at[1]]);
      }
    }
    return {
      perFrame,
      poses: new Map(known().map((id) => [id, poses.get(id)!.slice(posesBefore.get(id) ?? 0)])),
      follows: new Map(known().map((id) => [id, follows.get(id)! - (followsBefore.get(id) ?? 0)])),
    };
  };
  return { crowd, app, poses, follows, near, people, run };
}

describe('society crowd', () => {
  it('walks each inhabitant at its recorded speed and stops where the recorded path ends', () => {
    const log: Parameters<typeof fakeFactory>[0] = [];
    const { crowd, app } = setup(fakeFactory(log));
    const person = (tick: number, x: number) => ({
      id: 'walker',
      synthetic: true as const,
      position_mm: [x, 0] as const,
      motion_path_mm: tick ? [[0, 0], [x, 0]] as const : [[0, 0]] as const,
      walk_speed_mm_per_tick: 60_000,
    });
    crowd.set(v4(0, [person(0, 0)]), [0, 0], { nowMs: 0, intervalMs: 60_000 });
    crowd.set(v4(1, [person(1, 30_000)]), [0, 0], { nowMs: 0, intervalMs: 60_000 });
    expect(crowd.positionOf('walker')).toEqual([0, 0]);
    crowd.update(10_000);
    expect(crowd.positionOf('walker')![0]).toBeCloseTo(10, 6);
    crowd.update(30_000);
    expect(crowd.positionOf('walker')![0]).toBeCloseTo(30, 6);
    crowd.update(50_000);
    expect(crowd.positionOf('walker')).toEqual([30, 0]);
    expect(log[0]!.poses.at(-1)!.position).toEqual([30, 0, 0]);
    crowd.destroy();
    app.destroy();
  });

  it('counts people indoors without drawing or placing them anywhere else', () => {
    const log: Parameters<typeof fakeFactory>[0] = [];
    const { crowd, app } = setup(fakeFactory(log));
    const counts = crowd.set(v4(0, [
      { id: 'inside', synthetic: true, position_mm: [0, 0], indoors: true },
      { id: 'outside', synthetic: true, position_mm: [1000, 0] },
    ]), [0, 0]);
    expect(counts).toEqual({ population: 2, outdoors: 1, indoors: 1, near: 1, far: 0, drawn: 1 });
    expect(crowd.detailOf('inside')).toBe('indoors');
    expect(crowd.drawnIds).toEqual(['outside']);
    expect(log.map((entry) => entry.identity)).toEqual([
      { societyId: 'society', branchId: 'branch', inhabitantId: 'outside' },
    ]);
    expect(log.every((entry) => entry.detail === 'near')).toBe(true);
    crowd.select('inside');
    expect(crowd.counts.near).toBe(1);
    crowd.destroy();
    app.destroy();
  });

  it('never truncates the population and keeps full detail within the native limit', () => {
    const log: Parameters<typeof fakeFactory>[0] = [];
    const { crowd, app } = setup(fakeFactory(log), 500);
    const people = Array.from({ length: 500 }, (_, i) => ({
      id: `p${String(i).padStart(3, '0')}`,
      synthetic: true as const,
      position_mm: [i * 1000, 0] as const,
    }));
    const counts = crowd.set(v4(0, people), [0, 0]);
    expect(counts.population).toBe(500);
    expect(counts.near).toBe(NEAR_INHABITANT_BUDGET);
    expect(counts.far).toBe(500 - NEAR_INHABITANT_BUDGET - people.filter((p) => p.position_mm[0] > 700_000).length);
    expect(counts.drawn).toBe(counts.near + counts.far);
    expect(crowd.nativeFrames(1 / 60, false)).toHaveLength(NEAR_INHABITANT_BUDGET);
    crowd.select('p450');
    expect(crowd.detailOf('p450')).toBe('near');
    expect(crowd.counts.near).toBe(NEAR_INHABITANT_BUDGET);
    crowd.destroy();
    app.destroy();
  });

  it('shows reduced motion and out-of-sequence snapshots at their recorded end points', () => {
    const { crowd, app } = setup(fakeFactory([]));
    const at = (tick: number, x: number) => v4(tick, [{
      id: 'walker', synthetic: true, position_mm: [x, 0], motion_path_mm: [[0, 0], [x, 0]],
    }]);
    crowd.set(at(0, 0), [0, 0], { nowMs: 0 });
    crowd.set(at(1, 8000), [0, 0], { nowMs: 0 });
    expect(crowd.positionOf('walker')).toEqual([0, 0]);
    crowd.update(Number.MAX_SAFE_INTEGER);
    expect(crowd.positionOf('walker')).toEqual([8, 0]);
    crowd.set(at(5, 20_000), [0, 0], { nowMs: 0 });
    expect(crowd.positionOf('walker')).toEqual([20, 0]);
    crowd.destroy();
    app.destroy();
  });

  it('places every full character every frame and poses the farther ones on fewer frames', () => {
    const scene = cadenceScenario();
    const { crowd, app, poses, near, run } = scene;
    const window = run(0, 60);
    expect(crowd.positionOf('p000')![1]).toBeGreaterThan(0);
    near.forEach((id, rank) => {
      const expected = rank < 4 ? 60 : rank < 12 ? 30 : 20;
      expect(window.poses.get(id)!.length, `${id} at rank ${rank}`).toBe(expected);
      expect(window.follows.get(id), `${id} at rank ${rank}`).toBe(60 - expected);
      // Each pose after the first carries the whole time since the one before it.
      for (const pose of window.poses.get(id)!.slice(1)) expect(pose.deltaSeconds).toBeCloseTo(1 / expected, 9);
    });
    // Staggered: over the window every rank is posed its share, and no frame carries more than
    // one pose above any other.
    const share = near.reduce((sum, _id, rank) => sum + 60 / (rank < 4 ? 1 : rank < 12 ? 2 : 3), 0);
    expect(window.perFrame.reduce((a, b) => a + b, 0)).toBe(share);
    expect(Math.max(...window.perFrame) - Math.min(...window.perFrame)).toBeLessThanOrEqual(1);
    // Ranks follow the observer: p023 is now nearest and p011 is 12 m away, rank 18.
    crowd.refresh([23, 0]);
    const moved = run(60, 60);
    expect(moved.poses.get('p023')!.length).toBe(60);
    expect(moved.poses.get('p011')!.length).toBe(20);
    // A jump is never carried: every full character's next pose starts from scratch.
    const beforeJump = new Map([...poses].map(([id, list]) => [id, list.length]));
    crowd.set(v4(5, scene.people(1)), [0, 0], { nowMs: 0, intervalMs: 60_000 });
    for (const id of crowd.drawnIds.slice(0, crowd.counts.near)) {
      expect(poses.get(id)![beforeJump.get(id) ?? 0]?.discontinuity, id).toBe(true);
    }
    crowd.destroy();
    app.destroy();
  });

  it('carries an abstract character to its new point without solving or skinning a new pose', () => {
    const { crowd, app, root } = setup();
    const identity = { societyId: 'society', branchId: 'branch', inhabitantId: 'walker' };
    const renderable = abstractInhabitantRenderable(app.graphicsDevice, root, identity, 'near');
    renderable.pose({ position: [1, 0, 2], deltaSeconds: 1 / 60, discontinuity: true });
    renderable.pose({ position: [1, 0, 2.02], deltaSeconds: 1 / 60 });
    const mesh = renderable.root.render!.meshInstances[0]!.mesh;
    const skinned: number[] = [];
    expect(mesh.getPositions(skinned)).toBeGreaterThan(100);
    const facing = renderable.facing;
    renderable.follow!([1.5, 0, 3]);
    const carried: number[] = [];
    mesh.getPositions(carried);
    expect(carried).toEqual(skinned);
    expect(renderable.facing).toBe(facing);
    const at = renderable.root.getLocalPosition();
    expect([at.x, at.y, at.z]).toEqual([1.5, 0, 3]);
    // Hidden stays hidden and in place: carrying never shows anyone.
    renderable.setVisible(false);
    renderable.follow!([9, 0, 9]);
    expect(renderable.root.enabled).toBe(false);
    expect(renderable.root.getLocalPosition().x).toBe(1.5);
    renderable.destroy();
    crowd.destroy();
    app.destroy();
  });

  it('poses a selected inhabitant every frame whatever the cadence for its rank', () => {
    const { crowd, app, run } = cadenceScenario(() => 3);
    crowd.select('p020');
    const window = run(0, 60);
    expect(window.poses.get('p020')!.length).toBe(60);
    expect(window.poses.get('p001')!.length).toBe(20);
    crowd.destroy();
    app.destroy();
  });

  it('counts the bytes a renderable owns and the bytes the shared host holds, never one instead of the other', () => {
    const people = Array.from({ length: 6 }, (_, i) => ({
      id: `synthetic-${i}`,
      synthetic: true as const,
      position_mm: [i * 1000, 0] as const,
    }));
    // A 5x1 RGBA palette per distinct far colouring.
    const palettes = (ids: readonly string[]) => new Set(ids.map((id) => {
      const palette = farAppearance(CHARACTER_CATALOG, inhabitantLookOf(id)).palette;
      return FAR_REGIONS.map((region) => palette[region]).join('');
    })).size * FAR_REGIONS.length * 4;
    const shared = vi.spyOn(CharacterHost, 'residentFor');
    shared.mockReturnValue({ geometryBytes: 0, textureBytes: 0 });

    // Nobody drawn in full: far figures cost their shared sculpt and a 5x1 palette each.
    const far = setup(fakeFactory([]), 0);
    far.crowd.set(v4(0, people), [0, 0]);
    expect(far.crowd.residentBytes).toBeGreaterThan(0);
    expect(far.crowd.textureResidentBytes).toBe(palettes(people.map((person) => person.id)));

    // Four drawn in full by renderables that own their geometry: each one's bytes are added.
    const owning = setup(fakeFactory([]), 4);
    expect(owning.crowd.set(v4(0, people), [0, 0])).toMatchObject({ near: 4, far: 2 });
    // Whatever the two far figures cost, read while the shared host holds nothing.
    const figures = owning.crowd.residentBytes - 4 * 10;
    const figureTextures = owning.crowd.textureResidentBytes - 4 * 1;
    expect(figures).toBeGreaterThan(0);
    expect(figureTextures).toBe(palettes(owning.crowd.drawnIds.slice(4)));

    // The same four drawn from shared containers: they report nothing of their own, so the crowd
    // adds what the shared host holds, once for the whole crowd rather than once for each person.
    shared.mockReturnValue({ geometryBytes: 4096, textureBytes: 2048 });
    const fromHost = setup(sharedContainerFactory(), 4);
    expect(fromHost.crowd.set(v4(0, people), [0, 0])).toMatchObject({ near: 4, far: 2 });
    expect(fromHost.crowd.textureResidentBytes).toBe(figureTextures + 2048);

    // Same population and the same split, so the far figures cost the same in both: what is left
    // over is exactly what each kind reports, and neither kind reports the other's bytes.
    expect(fromHost.crowd.residentBytes).toBe(figures + 4096);
    expect(owning.crowd.residentBytes).toBe(figures + 4 * 10 + 4096);

    shared.mockRestore();
    for (const { crowd, app } of [far, owning, fromHost]) { crowd.destroy(); app.destroy(); }
  });

  it('draws everyone beyond the full places in the far form of their own look', () => {
    const { crowd, app, root } = setup(undefined, 0);
    const people = Array.from({ length: 64 }, (_, i) => ({
      id: `synthetic-${i}`,
      synthetic: true as const,
      position_mm: [i * 3000, 0] as const,
    }));
    const counts = crowd.set(v4(0, people), [0, 0]);
    expect(counts).toMatchObject({ near: 0, far: 64 });
    const figures = root.findByName('society-far-figures')!.children as pc.Entity[];
    expect(figures).toHaveLength(64);
    for (const [i, figure] of figures.entries()) {
      const id = `synthetic-${i}`;
      const expected = farAppearance(CHARACTER_CATALOG, inhabitantLookOf(id));
      expect(crowd.farAppearance(id)).toEqual(expected);
      // Each figure is drawn by its own palette material and stands where the person stands.
      const body = figure.findByName('character-far-body') as pc.Entity;
      expect(body.render!.meshInstances[0]!.material.name).toBe(`far-person:${FAR_REGIONS.map((region) => expected.palette[region]).join('')}`);
      expect(figure.getLocalPosition().x).toBeCloseTo(i * 3, 6);
    }
    expect(crowd.residentBytes).toBeGreaterThan(0);
    crowd.clear();
    expect(crowd.counts).toEqual({ population: 0, outdoors: 0, indoors: 0, near: 0, far: 0, drawn: 0 });
    expect(root.findByName('society-far-figures')!.children).toHaveLength(0);
    crowd.destroy();
    app.destroy();
  });

  it('keeps the player a place in the budget and gives the inhabitants the rest', () => {
    expect(NEAR_INHABITANT_BUDGET + PLAYER_NEAR_PLACES).toBe(NEAR_CHARACTER_BUDGET);
    const { crowd, app } = setup(fakeFactory([]), NEAR_CHARACTER_BUDGET + 10);
    const people = Array.from({ length: NEAR_CHARACTER_BUDGET + 10 }, (_, i) => ({
      id: `p${String(i).padStart(3, '0')}`,
      synthetic: true as const,
      position_mm: [i * 500, 0] as const,
    }));
    expect(crowd.set(v4(0, people), [0, 0]).near).toBe(NEAR_INHABITANT_BUDGET);
    crowd.destroy();
    app.destroy();
  });

  it('hands a person the activity their state names once they have walked there, never one read from motion', () => {
    const log: Parameters<typeof fakeFactory>[0] = [];
    const { crowd, app } = setup(fakeFactory(log));
    const person = (id: string, tick: number, action?: { kind: string; status: 'active' | 'completed' | 'blocked' }) => ({
      id,
      synthetic: true as const,
      position_mm: [tick ? 6000 : 0, 0] as const,
      motion_path_mm: tick ? [[0, 0], [6000, 0]] as const : [[0, 0]] as const,
      walk_speed_mm_per_tick: 60_000,
      ...(action ? { action: { ...action, reason: 'test' } } : {}),
    });
    crowd.set(v4(0, [person('rests', 0), person('walks', 0), person('done', 0)]), [0, 0], { nowMs: 0, intervalMs: 60_000 });
    crowd.set(v4(1, [
      person('rests', 1, { kind: 'rest', status: 'active' }),
      person('walks', 1),
      person('done', 1, { kind: 'rest', status: 'completed' }),
    ]), [0, 0], { nowMs: 0, intervalMs: 60_000 });
    const last = (id: string) => (log.find((entry) => (entry.identity as { inhabitantId: string }).inhabitantId === id)!.poses.at(-1) as { activity?: string | null });
    // On the way there the state already says "rest"; the person is drawn walking until they arrive.
    crowd.update(3_000);
    expect(crowd.positionOf('rests')![0]).toBeCloseTo(3, 6);
    expect(last('rests').activity).toBeNull();
    expect(crowd.activityOf('rests')).toBeNull();
    crowd.update(7_000);
    expect(crowd.positionOf('rests')).toEqual([6, 0]);
    expect(last('rests').activity).toBe('rest');
    expect(crowd.activityOf('rests')).toBe('rest');
    // Arriving and standing still is not resting unless the state says so, and a finished rest is over.
    expect(crowd.positionOf('walks')).toEqual([6, 0]);
    expect(last('walks').activity).toBeNull();
    expect(last('done').activity).toBeNull();
    crowd.destroy();
    app.destroy();
  });
});

describe('facing', () => {
  it('turns a person the way their recorded travel went in both forms, and keeps turning once they stop', () => {
    const east = (tick: number) => ({
      id: 'east', synthetic: true as const,
      position_mm: [tick ? 800 : 0, 0] as const,
      motion_path_mm: tick ? [[0, 0], [800, 0]] as const : [[0, 0]] as const,
    });
    // Heading +X is a quarter turn clockwise seen from above: -90 degrees about +Y, -Z forward.
    const expected = -90;
    for (const nearLimit of [1, 0]) {
      // The catalog person, as the crowd draws by default; with no loader it shows its far form.
      const { crowd, app, root } = setup(undefined, nearLimit);
      crowd.set(v4(0, [east(0)]), [0, 0], { nowMs: 0, intervalMs: 1 });
      crowd.set(v4(1, [east(1)]), [0, 0], { nowMs: 0, intervalMs: 1 });
      // The whole step is walked in one frame, then the person stands there.
      for (let frame = 0; frame < 120; frame += 1) crowd.update(16 * (frame + 1));
      expect(crowd.positionOf('east')).toEqual([0.8, 0]);
      const drawn = nearLimit
        ? root.findByName('synthetic:east')!
        : root.findByName('society-far-figures')!.children[0]!;
      expect(drawn.getLocalEulerAngles().y, `near limit ${nearLimit}`).toBeCloseTo(expected, 3);
      crowd.destroy();
      app.destroy();
    }
  });
});

describe('recorded paths', () => {
  it('are walked wherever the snapshot records them, whatever profile names it', () => {
    const { crowd, app } = setup(fakeFactory([]));
    const at = (tick: number, x: number, withPath: boolean) => ({
      profile: 'exulanica-society/v3', society_id: 'society', branch_id: 'branch', tick,
      inhabitants: [{
        id: 'walker', synthetic: true as const, position_mm: [x, 0] as const,
        ...(withPath ? { motion_path_mm: [[0, 0], [x, 0]] as const } : {}),
      }],
    }) as unknown as OwnedSocietyState;
    crowd.set(at(0, 0, true), [0, 0], { nowMs: 0, intervalMs: 1000 });
    crowd.set(at(1, 8000, true), [0, 0], { nowMs: 0, intervalMs: 1000 });
    crowd.update(500);
    const midway = crowd.positionOf('walker')![0];
    expect(midway).toBeGreaterThan(0);
    expect(midway).toBeLessThan(8);
    // A snapshot that records no path shows each person at their recorded point at once.
    crowd.set(at(2, 16_000, false), [0, 0], { nowMs: 0, intervalMs: 1000 });
    expect(crowd.positionOf('walker')).toEqual([16, 0]);
    crowd.destroy();
    app.destroy();
  });
});

describe('a resting person beyond the full places', () => {
  it('is drawn in the far form of the posture their state names, once they have arrived', () => {
    const { crowd, app, root } = setup(fakeFactory([]), 0);
    const person = (tick: number) => ({
      id: 'resting', synthetic: true as const,
      position_mm: [tick ? 6000 : 0, 0] as const,
      motion_path_mm: tick ? [[0, 0], [6000, 0]] as const : [[0, 0]] as const,
      walk_speed_mm_per_tick: 60_000,
      ...(tick ? { action: { kind: 'rest', status: 'active' as const, reason: 'arrived_at_access_node' } } : {}),
    });
    crowd.set(v4(0, [person(0)]), [0, 0], { nowMs: 0, intervalMs: 60_000 });
    crowd.set(v4(1, [person(1)]), [0, 0], { nowMs: 0, intervalMs: 60_000 });
    const height = () => ((root.findByName('society-far-figures')!.children[0] as pc.Entity)
      .findByName('character-far-body') as pc.Entity).render!.meshInstances[0]!.mesh.aabb.getMax().y;
    crowd.update(3_000);
    const walking = height();
    crowd.update(7_000);
    expect(crowd.activityOf('resting')).toBe('rest');
    expect(height()).toBeLessThan(walking * 0.65);
    crowd.destroy();
    app.destroy();
  });
});

describe('a place that states heights', () => {
  it('refuses a walker standing on a stated surface, because this crowd draws the ground plane', () => {
    const { crowd, app } = setup();
    const plan = { id: 'p0', synthetic: true as const, position_mm: [1000, 2000] as const };
    expect(crowd.set(v4(0, [plan]), [0, 0])).toMatchObject({ population: 1, drawn: 1 });
    expect(() => crowd.set(v4(1, [{ ...plan, support_z_mm: 146 }]), [0, 0])).toThrow(
      /stands on a surface at 146 mm/,
    );
    // A height of zero is a stated height too: the ground plane is where the walker happens to be,
    // not a reason to accept a number this renderer does not read.
    expect(() => crowd.set(v4(2, [{ ...plan, support_z_mm: 0 }]), [0, 0])).toThrow(
      /draws every walker on the ground plane/,
    );
    // Absent is not zero: a place that states no height draws exactly as it did.
    expect(crowd.set(v4(3, [plan]), [0, 0])).toMatchObject({ population: 1, drawn: 1 });
    crowd.destroy();
    app.destroy();
  });
});
