// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import * as pc from 'playcanvas';
import { SocietyCrowd, type PoseInterval } from '../src/playcanvas/society/crowd.js';
import { CharacterHost } from '../src/playcanvas/character/host.js';
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
  const near = Array.from({ length: 24 }, (_, i) => `p${String(i).padStart(3, '0')}`);
  expect(crowd.drawnIds.slice(0, crowd.counts.near)).toEqual(near);
  const total = () => near.reduce((sum, id) => sum + poses.get(id)!.length, 0);
  const run = (from: number, frames: number) => {
    const posesBefore = new Map(near.map((id) => [id, poses.get(id)!.length]));
    const followsBefore = new Map(near.map((id) => [id, follows.get(id)!]));
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
      poses: new Map(near.map((id) => [id, poses.get(id)!.slice(posesBefore.get(id)!)])),
      follows: new Map(near.map((id) => [id, follows.get(id)! - followsBefore.get(id)!])),
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
    expect(counts.near).toBe(24);
    expect(counts.far).toBe(500 - 24 - people.filter((p) => p.position_mm[0] > 700_000).length);
    expect(counts.drawn).toBe(counts.near + counts.far);
    expect(crowd.nativeFrames(1 / 60, false)).toHaveLength(24);
    crowd.select('p450');
    expect(crowd.detailOf('p450')).toBe('near');
    expect(crowd.counts.near).toBe(24);
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
    // Staggered, so no frame carries more than its share: 4 + 8 / 2 + 12 / 3.
    expect(new Set(window.perFrame)).toEqual(new Set([12]));
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
    const shared = vi.spyOn(CharacterHost, 'residentFor');
    shared.mockReturnValue({ geometryBytes: 0, textureBytes: 0 });

    // Nobody drawn in full: far figures cost geometry and no character textures at all.
    const far = setup(fakeFactory([]), 0);
    far.crowd.set(v4(0, people), [0, 0]);
    expect(far.crowd.residentBytes).toBeGreaterThan(0);
    expect(far.crowd.textureResidentBytes).toBe(0);

    // Four drawn in full by renderables that own their geometry: each one's bytes are added.
    const owning = setup(fakeFactory([]), 4);
    expect(owning.crowd.set(v4(0, people), [0, 0])).toMatchObject({ near: 4, far: 2 });
    expect(owning.crowd.textureResidentBytes).toBe(4 * 1);
    // Whatever the two far figures cost, read while the shared host holds nothing.
    const figures = owning.crowd.residentBytes - 4 * 10;
    expect(figures).toBeGreaterThan(0);

    // The same four drawn from shared containers: they report nothing of their own, so the crowd
    // adds what the shared host holds, once for the whole crowd rather than once for each person.
    shared.mockReturnValue({ geometryBytes: 4096, textureBytes: 2048 });
    const fromHost = setup(sharedContainerFactory(), 4);
    expect(fromHost.crowd.set(v4(0, people), [0, 0])).toMatchObject({ near: 4, far: 2 });
    expect(fromHost.crowd.textureResidentBytes).toBe(2048);

    // Same population and the same split, so the far figures cost the same in both: what is left
    // over is exactly what each kind reports, and neither kind reports the other's bytes.
    expect(fromHost.crowd.residentBytes).toBe(figures + 4096);
    expect(owning.crowd.residentBytes).toBe(figures + 4 * 10 + 4096);

    shared.mockRestore();
    for (const { crowd, app } of [far, owning, fromHost]) { crowd.destroy(); app.destroy(); }
  });

  it('draws far figures with one instanced draw per palette', () => {
    const { crowd, app, root } = setup(undefined, 0);
    const people = Array.from({ length: 64 }, (_, i) => ({
      id: `synthetic-${i}`,
      synthetic: true as const,
      position_mm: [i * 3000, 0] as const,
    }));
    const counts = crowd.set(v4(0, people), [0, 0]);
    expect(counts).toMatchObject({ near: 0, far: 64 });
    const groups = root.findByName('society-far-figures')!.children as pc.Entity[];
    expect(groups.length).toBeGreaterThan(0);
    expect(groups.length).toBeLessThanOrEqual(4);
    const instances = groups.flatMap((g) => g.render!.meshInstances);
    expect(instances.reduce((sum, mi) => sum + mi.instancingCount, 0)).toBe(64);
    expect(crowd.residentBytes).toBeGreaterThan(0);
    crowd.clear();
    expect(crowd.counts).toEqual({ population: 0, outdoors: 0, indoors: 0, near: 0, far: 0, drawn: 0 });
    expect(instances.reduce((sum, mi) => sum + mi.instancingCount, 0)).toBe(0);
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
