// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { postureSeatMetres } from '../src/playcanvas/character/far.js';
import { AuthoredRegionSociety, LAND_RAY_REACH_M, visitorRayOnRootGround, visitorRayOnRootLand } from '../src/playcanvas/society/authored-society.js';
import { SocietyCrowd, type CrowdGround } from '../src/playcanvas/society/crowd.js';
import { hostGeneratedSociety } from '../src/playcanvas/society/region-society.js';
import type { SeatingLayout } from '../src/playcanvas/society/seating.js';
import type { CrowdPose, CrowdRenderableFactory, OwnedSocietyState, SocietyInhabitantSnapshot } from '../src/playcanvas/society/types.js';
import type { LookDrawing } from '../src/playcanvas/things/documents.js';
import { ThingLibrary } from '../src/playcanvas/things/library.js';
import { ThingLayer, type DrawnSociety } from '../src/playcanvas/things/thing-layer.js';
import { serveFixturePeople } from './served-people.js';
import { servedLibrary } from './things-fixtures.js';

/*
 * People of a site on land stand on the land: each walker is drawn at the land's height under the
 * point they are drawn at on that frame, so a walk over a crest goes over it; their feet are dropped
 * to the land only when they are lifted above it, onto a seat, which they are lowered onto from the
 * land; and a person standing still is posed no more often than on level ground. With no ground
 * the crowd draws exactly what it drew before, and so does a ground that is 0 everywhere.
 */

/** A ridge along the society's south axis: 7 m at east 0, falling 0.2 m a metre either way to 5 m at 10 m. */
const RIDGE: CrowdGround = (east) => 7 - Math.min(10, Math.abs(east)) * 0.2;

interface Seen { readonly poses: CrowdPose[]; readonly follows: number[][] }

function setup(ground?: CrowdGround, poseInterval?: (rank: number) => number) {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  serveFixturePeople(app);
  const root = new pc.Entity('society');
  app.root.addChild(root);
  const seen = new Map<string, Seen>();
  const factory: CrowdRenderableFactory = (_device, parent, identity) => {
    const entity = new pc.Entity(identity.inhabitantId);
    parent.addChild(entity);
    const record: Seen = { poses: [], follows: [] };
    seen.set(identity.inhabitantId, record);
    return {
      root: entity, subject: { kind: 'synthetic-inhabitant', ...identity }, standingHeight: 1.7, facing: 0, drawsSeats: true,
      pose: (pose) => { record.poses.push(pose); entity.setLocalPosition(...(pose.position as [number, number, number])); },
      follow: (position) => { record.follows.push([...position]); },
      setVisible: (visible) => { entity.enabled = visible; },
      destroy: () => entity.destroy(),
    };
  };
  const crowd = new SocietyCrowd(device, root, {
    factory, ...(ground === undefined ? {} : { ground }), ...(poseInterval === undefined ? {} : { poseInterval }),
  });
  return { crowd, seen, root };
}

const state = (inhabitants: SocietyInhabitantSnapshot[], tick = 1): OwnedSocietyState => ({
  profile: 'exulanica-society/v2', society_id: 'society', branch_id: 'branch', tick, movement_budget_mm_per_tick: 60_000, inhabitants,
});
const walker = (id: string, path: readonly (readonly [number, number])[]): SocietyInhabitantSnapshot => ({
  id, synthetic: true, position_mm: path.at(-1)!, motion_path_mm: path,
});

function run(crowd: SocietyCrowd, seconds: number, from = 0): number {
  let now = from;
  for (let frame = 0; frame < Math.round(seconds * 60); frame += 1) crowd.update((now += 1000 / 60));
  return now;
}

/** A walk over the ridge, east to west, and one standing person beside it. */
function walkOver(ground?: CrowdGround, poseInterval?: (rank: number) => number) {
  const made = setup(ground, poseInterval);
  // First seen where they stand; the next minute's walk is walked.
  made.crowd.set(state([walker('crossing', [[-10_000, 2_000]]), walker('standing', [[3_000, -1_000]])], 0), [0, 0], { nowMs: 0, intervalMs: 8_000 });
  made.crowd.set(state([walker('crossing', [[-10_000, 2_000], [10_000, 2_000]]), walker('standing', [[3_000, -1_000]])], 1), [0, 0], { nowMs: 0, intervalMs: 8_000 });
  run(made.crowd, 12);
  return made;
}

describe('people on land', () => {
  it('stand on the land under the point they are drawn at, every frame, over the crest', () => {
    const { seen, crowd } = walkOver(RIDGE);
    const poses = seen.get('crossing')!.poses;
    expect(poses.length).toBeGreaterThan(100);
    for (const pose of poses) {
      expect(pose.position[1]).toBe(RIDGE(pose.position[0], pose.position[2]));
      // On their feet on the land: nothing to drop the feet to.
      expect('groundY' in pose).toBe(false);
    }
    // Over the crest, not through it: between the ends' 5 m the walk reaches 7 m.
    expect(Math.max(...poses.map((pose) => pose.position[1]))).toBeGreaterThan(6.8);
    expect(poses.at(-1)!.position[0]).toBeCloseTo(10, 6);
    crowd.destroy();
  });

  it('are posed no more often standing on land than on level ground', () => {
    const everyThird = () => 3;
    const onLand = walkOver(RIDGE, everyThird).seen.get('standing')!;
    const level = walkOver(undefined, everyThird).seen.get('standing')!;
    // A person standing still is posed on one frame in three and followed on the others, on land
    // as on level ground; posing everyone above 0 on every frame would pose them all 720 times.
    expect(onLand.poses.length).toBe(level.poses.length);
    expect(onLand.poses.length).toBeLessThan(300);
    expect(onLand.follows.length).toBe(level.follows.length);
    for (const pose of onLand.poses) expect(pose.position[1]).toBe(RIDGE(3, -1));
  });

  it('lower from the land onto a seat at its height, their feet on the land under them', () => {
    const ground: CrowdGround = () => 5;
    const { crowd, seen } = setup(ground);
    const layout: SeatingLayout = {
      uses: new Map(), objects: [], targets: new Map([['fixture-rest', 'bench-a']]),
      fixtureSeats: [{ objectId: 'bench-a', heightHintM: 5.225, maximumHeightM: 5.46, facing: Math.PI / 2,
        triangles: [1, 5.45, -3, 3, 5.45, -3, 1, 5.45, -1, 3, 5.45, -3, 3, 5.45, -1, 1, 5.45, -1],
        normals: Array.from({ length: 6 }, () => [0, 1, 0]).flat() }],
    };
    crowd.set(state([{
      ...walker('resting', [[1800, -2400]]),
      action: { kind: 'rest', status: 'active', target_id: 'fixture-rest', remaining_ticks: 2, reason: 'test' },
    }]), [0, 0], { nowMs: 0, intervalMs: 1000 }, layout);
    run(crowd, 3);
    const poses = seen.get('resting')!.poses;
    const seated = poses.at(-1)!;
    expect(seated.position[1] + postureSeatMetres(crowd.farAppearance('resting'), 'perched')).toBeCloseTo(5.45, 9);
    expect(seated).toMatchObject({ seated: true, groundY: 5 });
    // On their way to it they stand on the land, never under it or at the datum.
    const first = poses.findIndex((pose) => pose.seated === true);
    expect(first).toBeGreaterThan(0);
    expect(poses.slice(0, first).every((pose) => pose.position[1] === 5 && !('groundY' in pose))).toBe(true);
    // Lowering runs from the land to the seat: no pose of it is below the land.
    expect(poses.every((pose) => pose.position[1] >= 5 - 1e-9 || pose.seated === true)).toBe(true);
    crowd.destroy();
  });
});

describe('two people talking on a slope', () => {
  it('each stand on the land under where they are drawn, stepped apart for the conversation', () => {
    const { crowd, seen } = setup(RIDGE);
    const talk = (id: string, partner: string): SocietyInhabitantSnapshot => ({
      ...walker(id, [[3_000, 0]]),
      action: { kind: 'talk', status: 'active', target_id: null, remaining_ticks: 3, reason: 'talking' },
      goal: { kind: 'talk', target_id: null, reason: 'stopped_to_talk', partner_id: partner },
    });
    crowd.set(state([talk('ada', 'bo'), talk('bo', 'ada')]), [0, 0], { nowMs: 0, intervalMs: 8_000, conversationMetres: 1.2 });
    run(crowd, 4);
    for (const id of ['ada', 'bo']) {
      const pose = seen.get(id)!.poses.at(-1)!;
      // Stepped aside east or west of the point they share, where the ridge stands at another height.
      expect(Math.abs(pose.position[0] - 3)).toBeGreaterThan(0.3);
      expect(pose.position[1]).toBe(RIDGE(pose.position[0], pose.position[2]));
    }
    crowd.destroy();
  });
});

describe('people on level ground', () => {
  it('stand on the plane at 0 exactly as before, and a ground of 0 everywhere draws the same', () => {
    const none = walkOver();
    const zero = walkOver(() => 0);
    for (const id of ['crossing', 'standing']) {
      const level = none.seen.get(id)!;
      expect(level.poses.every((pose) => pose.position[1] === 0 && !('groundY' in pose))).toBe(true);
      expect(zero.seen.get(id)!.poses).toEqual(level.poses);
      expect(zero.seen.get(id)!.follows).toEqual(level.follows);
    }
  });
});

describe('a society hosted on land', () => {
  /** Where a host keeps its society. */
  const host = () => {
    const canvas = document.createElement('canvas');
    const device = new pc.NullGraphicsDevice(canvas);
    const app = new pc.AppBase(canvas);
    const options = new pc.AppOptions();
    options.graphicsDevice = device;
    options.componentSystems = [pc.RenderComponentSystem];
    app.init(options);
    const environmentRoot = new pc.Entity('environment');
    app.root.addChild(environmentRoot);
    return { device, environmentRoot, authoredSociety: null as AuthoredRegionSociety | null };
  };

  it('hangs its region at the land\'s datum, stands its people on the land and meets the land with a click', () => {
    const onLand = host();
    const society = hostGeneratedSociety(onLand, 'region:generated', 6_500, RIDGE)!;
    expect(society.root.parent!.getLocalPosition().y).toBe(0);
    expect(society.groundHeightAt).toBe(RIDGE);
    // Looking straight down from 20 m over east 4 m: the land is 6.2 m high there, not at the datum.
    const hit = society.groundPoint([4, 20, -2], [0, -1, 0]);
    expect(hit).toEqual({ xMm: 4000, zMm: -2000 });
    // Looking east along the ground from the west, low: the first slope met, not the datum beyond.
    const slope = society.groundPoint([-20, 5.5, 0], [1, 0, 0])!;
    expect(RIDGE(slope.xMm / 1000, 0)).toBeCloseTo(5.5, 3);
    expect(society.groundPoint([0, 1, 0], [0, -1, 0])).toBeNull();
    society.destroy();
  });

  it('walks a ray against the land no further than its reach, so pointing at the sky costs little', () => {
    const root = new pc.Entity('root');
    let samples = 0;
    const counted: CrowdGround = (east, south) => { samples += 1; return RIDGE(east, south); };
    expect(visitorRayOnRootLand(root, { x: 0, y: 0, z: 0 }, [0, 20, 0], [0, 1, 0], counted)).toBeNull();
    expect(samples).toBeLessThanOrEqual(LAND_RAY_REACH_M / 0.5 + 1);
    expect(LAND_RAY_REACH_M).toBe(400);
    // Land met within the reach is found; land only beyond it is not.
    const wall = (at: number): CrowdGround => (east) => (east > at ? 100 : 0);
    expect(visitorRayOnRootLand(root, { x: 0, y: 0, z: 0 }, [0, 5, 0], [1, 0, 0], wall(300))?.xMm).toBe(300_000);
    expect(visitorRayOnRootLand(root, { x: 0, y: 0, z: 0 }, [0, 5, 0], [1, 0, 0], wall(500))).toBeNull();
  });

  it('hangs a level site\'s region at its floor with no ground, as before', () => {
    const level = host();
    const society = hostGeneratedSociety(level, 'region:generated', 1_200)!;
    expect(society.root.parent!.getLocalPosition().y).toBeCloseTo(1.2, 9);
    expect(society.groundHeightAt).toBeUndefined();
    expect(society.groundPoint([4, 20, -2], [0, -1, 0])).toEqual(visitorRayOnRootGround(society.root, { x: 0, y: 0, z: 0 }, [4, 20, -2], [0, -1, 0]));
    society.destroy();
  });
});

describe('things on land', () => {
  /** A container instance as the engine's reader would make one: one part. */
  const instance = (look: LookDrawing) => {
    const model = new pc.Entity(`model:${look.look}`);
    model.addChild(new pc.Entity(`part:${look.look}`));
    return Promise.resolve({ model, tracks: new Map<string, pc.AnimTrack>() });
  };

  function layerOn(ground?: CrowdGround) {
    const canvas = document.createElement('canvas');
    const device = new pc.NullGraphicsDevice(canvas);
    const app = new pc.AppBase(canvas);
    const options = new pc.AppOptions();
    options.graphicsDevice = device;
    options.componentSystems = [pc.RenderComponentSystem, pc.LightComponentSystem, pc.CameraComponentSystem];
    app.init(options);
    const region = new pc.Entity('region');
    app.root.addChild(region);
    const crowdRoot = new pc.Entity('society');
    region.addChild(crowdRoot);
    const camera = new pc.Entity('camera');
    camera.addComponent('camera');
    app.root.addChild(camera);
    const society: DrawnSociety = { root: crowdRoot, groundOf: () => false, ...(ground === undefined ? {} : { groundHeightAt: ground }) };
    const served = servedLibrary();
    const layer = new ThingLayer({
      app, camera, library: new ThingLibrary(served.list, (digest) => served.fetch(digest)), regionRoot: (id) => (id === 'a' ? region : null),
      ringColour: '#f4ff91', instantiate: instance, society: () => society,
    });
    return { app, layer, served };
  }

  /** Where a ring under this holder stands, world metres, or null. */
  const ringAt = (app: pc.AppBase, holder: string): number[] | null => {
    const entity = (app.root.findByName(holder) as pc.Entity | null)?.children.find((child) => child.name === 'thing-pick-ring') as pc.Entity | undefined;
    return entity === undefined || !entity.enabled ? null : entity.getPosition().toArray();
  };

  it('ring where the next walk goes on the land under it, and on the plane with no ground', () => {
    const onLand = layerOn(RIDGE);
    onLand.layer.setDestination({ xMm: 2500, zMm: -1500 });
    expect(ringAt(onLand.app, 'thing-destination-at')![1]).toBeCloseTo(RIDGE(2.5, -1.5) + 0.012, 6);
    const level = layerOn();
    level.layer.setDestination({ xMm: 2500, zMm: -1500 });
    expect(ringAt(level.app, 'thing-destination-at')![1]).toBeCloseTo(0.012, 6);
    onLand.layer.destroy();
    level.layer.destroy();
  });

  it('stand a society\'s thing its height above the land under it, and at its height with no ground', async () => {
    for (const [ground, expected] of [[RIDGE, RIDGE(4, -2) + 0.3], [undefined, 0.3]] as const) {
      const { app, layer, served } = layerOn(ground);
      const kind = served.kindRef('gate', 1);
      await layer.setPlaced([{ thingId: 'gate-1', kind, regionId: 'a', transform: { xMm: 0, yMm: 0, zMm: 0, yawMicroradians: 0, scaleMilli: 1000 }, removed: false }]);
      layer.setSociety({ things: [{ id: 'society-gate', placed_id: 'gate-1', kind, position_mm: [4000, -2000], height_mm: 300, yaw_microradians: 0, held_by: null }], inhabitants: [] } as never, null);
      app.fire('update', 0.016);
      const figure = layer.figureOf('gate-1')!;
      expect(figure.root.getPosition().x).toBeCloseTo(4, 6);
      expect(figure.root.getPosition().y).toBeCloseTo(expected, 6);
      layer.destroy();
    }
  });
});
