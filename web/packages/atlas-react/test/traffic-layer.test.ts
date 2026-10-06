// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import {
  TrafficLayer,
  VehicleLookError,
  pointAlong,
  poseBetween,
} from '../src/playcanvas/traffic/traffic-layer.js';
import { SIGNAL_LOOKS_V1, SignalLookError } from '../src/playcanvas/traffic/signal-lights.js';
import type { TrafficWindow, VehicleSamples } from '../src/playcanvas/traffic/types.js';

const CAR = { length: 5790, width: 2130, height: 1300, wheelbase: 3350, frontOverhang: 910, rearOverhang: 1530 };
const DRIVING = 2;
const PARKED = 0;

function setup() {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  const root = new pc.Entity('world');
  app.root.addChild(root);
  return { app, root };
}

const toRenderer = (x: number, y: number, z: number) => [x / 1000, z / 1000, -y / 1000] as const;

/** A car driving east along y = 0, a metre a second, or parked where it starts. */
function car(id: string, seconds: number, moving: boolean, extra: Partial<VehicleSamples> = {}): VehicleSamples {
  const front: number[] = [];
  const rear: number[] = [];
  const paths: number[][] = [];
  for (let s = 0; s < seconds; s += 1) {
    const x = 10_000 + (moving ? s * 1000 : 0);
    front.push(x, 0);
    rear.push(x - CAR.wheelbase, 0);
    paths.push(moving && s > 0 ? [x - 1000 + CAR.frontOverhang, 0, x + CAR.frontOverhang, 0] : []);
  }
  return {
    vehicleId: id,
    vehicleClass: 'passenger_car',
    bodyFamily: 'sedan',
    colour: 'red',
    dimensionsMm: CAR,
    frontAxleMm: front,
    rearAxleMm: rear,
    mode: Array.from({ length: seconds }, () => (moving ? DRIVING : PARKED)),
    speedMmPerS: Array.from({ length: seconds }, () => (moving ? 1000 : 0)),
    motionPathMm: paths,
    ...extra,
  };
}

function trafficWindow(vehicles: readonly VehicleSamples[], extra: Partial<TrafficWindow> = {}): TrafficWindow {
  return {
    inputSha256: 'a'.repeat(64),
    clockSecond: 100,
    stepMs: 1000,
    fromSecond: 100,
    seconds: vehicles[0]!.mode.length,
    modes: ['parked', 'leaving', 'driving', 'arriving'],
    crossingsFed: false,
    vehicles,
    lateHome: [],
    vehicleIndications: ['green', 'amber', 'red'],
    pedestrianIndications: ['walk', 'clearance', 'dont_walk'],
    signals: [],
    ...extra,
  };
}

describe('a vehicle moved along the path the server served', () => {
  it('finds a point along a polyline by distance, never across its corner', () => {
    const corner = [[0, 0], [10, 0], [10, 10]] as const;
    expect(pointAlong(corner, 5)).toEqual([5, 0]);
    expect(pointAlong(corner, 15)).toEqual([10, 5]);
    expect(pointAlong(corner, 99)).toEqual([10, 10]);
  });

  it('keeps both axles on the trail through a turn, their distance the wheelbase along it', () => {
    // A front turning a right angle during the second: axles follow the trail, not the chord.
    const from = { front: [0, 0] as const, rear: [-3350, 0] as const, path: [] };
    const path = [[910, 0], [3000, 0], [3000, 2000]] as const;
    const to = { front: [3000, 1090] as const, rear: [0, 0] as const, path };
    const end = poseBetween(from, to, 1, CAR);
    // The front is at the path's end; the front axle 910 back along the path lies on its last piece.
    expect(end.frontAxle[0]).toBeCloseTo(3000, 6);
    expect(end.frontAxle[1]).toBeCloseTo(1090, 6);
    // The rear axle is a wheelbase further back along the trail: on its straight part, y = 0.
    expect(end.rearAxle[1]).toBeCloseTo(0, 6);
    const half = poseBetween(from, to, 0.5, CAR);
    expect(half.frontAxle[1]).toBe(0);
  });

  it('holds a vehicle whose second has no path, as a parked one or one leaving its bay', () => {
    const from = { front: [1, 2] as const, rear: [3, 4] as const, path: [] };
    expect(poseBetween(from, { front: [9, 9], rear: [8, 8], path: [] }, 0.5, CAR)).toEqual({ frontAxle: [1, 2], rearAxle: [3, 4] });
  });
});

describe('the traffic layer', () => {
  it('draws each vehicle on the ground at its axles, moving it through the second', () => {
    const { root } = setup();
    const layer = new TrafficLayer(root, () => 0.25, toRenderer);
    layer.setWindow(trafficWindow([car('moving', 10, true), car('parked', 10, false)]), 0);
    layer.update(2500);
    expect(layer.drawnCount).toBe(2);
    expect(layer.animating).toBe(true);
    const moving = root.findByName('vehicle:moving')!;
    const [x, y] = [moving.getLocalPosition().x, moving.getLocalPosition().y];
    expect(y).toBeCloseTo(0.25, 6);
    // Half way through second 102 to 103, the body's centre has moved half a metre past 102's.
    const centreAt102 = (12_000 + CAR.frontOverhang + (12_000 - CAR.wheelbase - CAR.rearOverhang)) / 2 / 1000;
    expect(x).toBeCloseTo(centreAt102 + 0.5, 3);
  });

  it('draws a vehicle in the body a style pack gives it, and in its boxes when it gives none', () => {
    const { root } = setup();
    const asked: string[] = [];
    const bodies = {
      body: (row: VehicleSamples) => {
        asked.push(row.vehicleId);
        return row.vehicleId === 'styled' ? new pc.Entity('style-pack:vehicle.sedan') : null;
      },
    };
    const layer = new TrafficLayer(root, () => 0, toRenderer, bodies);
    layer.setWindow(trafficWindow([car('styled', 3, true), car('plain', 3, true)]), 0);
    layer.update(1500);
    layer.update(1600);
    expect(root.findByName('vehicle:styled')!.children.map((child) => child.name)).toEqual(['style-pack:vehicle.sedan']);
    expect(root.findByName('vehicle:plain')!.children.map((child) => child.name)).toContain('body');
    // A vehicle's body is asked for once, when it is first drawn.
    expect(asked.sort()).toEqual(['plain', 'styled']);
  });

  it('draws every vehicle in the new bodies from the next frame when a redraw hands them in', () => {
    const { root } = setup();
    const made = (name: string) => ({ body: () => new pc.Entity(name) });
    const layer = new TrafficLayer(root, () => 0, toRenderer, made('style-pack:cozy'));
    layer.setWindow(trafficWindow([car('one', 3, true), car('two', 3, true)]), 0);
    layer.update(1500);
    const before = root.findByName('vehicle:one')!;
    expect(before.children.map((child) => child.name)).toEqual(['style-pack:cozy']);
    layer.setBodies(made('style-pack:toon'));
    // Taken down at once, so nothing of the old pack's bodies is left to draw.
    expect(root.findByName('vehicle:one')).toBeNull();
    layer.update(1600);
    for (const id of ['one', 'two']) {
      expect(root.findByName(`vehicle:${id}`)!.children.map((child) => child.name)).toEqual(['style-pack:toon']);
    }
    expect(layer.drawnCount).toBe(2);
    layer.setBodies(null);
    layer.update(1700);
    expect(root.findByName('vehicle:one')!.children.map((child) => child.name)).toContain('body');
  });

  it('does not draw a vehicle where the drawn world has no ground', () => {
    const { root } = setup();
    const layer = new TrafficLayer(root, () => null, toRenderer);
    layer.setWindow(trafficWindow([car('off', 5, true)]), 0);
    layer.update(1000);
    expect(layer.hidden).toBe(1);
    expect(layer.drawnCount).toBe(0);
  });

  it('holds a vehicle named late at an episode end rather than moving it into the next', () => {
    const { root } = setup();
    const layer = new TrafficLayer(root, () => 0, toRenderer);
    layer.setWindow(trafficWindow([car('late', 5, true)], { lateHome: [{ second: 102, vehicleId: 'late' }] }), 0);
    layer.update(2500);
    const held = root.findByName('vehicle:late')!.getLocalPosition().x;
    layer.update(2000);
    expect(root.findByName('vehicle:late')!.getLocalPosition().x).toBeCloseTo(held, 6);
  });

  it('refuses a body family or colour its looks do not state, before anything is drawn', () => {
    const { root } = setup();
    const layer = new TrafficLayer(root, () => 0, toRenderer);
    expect(() => layer.setWindow(trafficWindow([car('odd', 3, true, { bodyFamily: 'hovercraft' })]), 0)).toThrow(VehicleLookError);
    expect(() => layer.setWindow(trafficWindow([car('odd', 3, true, { colour: 'mauve' })]), 0)).toThrow(VehicleLookError);
    expect(layer.drawnCount).toBe(0);
  });

});

describe('the traffic signals', () => {
  const signals = [{
    signalId: 's1',
    junctionId: 'j1',
    groups: [
      { group: 'phase_a', kind: 'vehicle' as const, pointsMm: [0, 0, 10_000, 0], codes: Array.from({ length: 10 }, (_, s) => (s < 5 ? 0 : 2)) },
      { group: 'walk_a', kind: 'pedestrian' as const, pointsMm: [5_000, 5_000], codes: Array.from({ length: 10 }, (_, s) => (s < 5 ? 2 : 0)) },
    ],
  }];

  function lampColour(root: pc.Entity, name: string): string {
    const head = root.findByName(name) as pc.Entity;
    const lamp = head.findByName('lamp') as pc.Entity;
    const colour = (lamp.render!.material as pc.StandardMaterial).diffuse;
    return [colour.r, colour.g, colour.b].map((c) => Math.round(c * 255).toString(16).padStart(2, '0')).join('');
  }

  it('lights each head as its group shows at the second drawn, and a head with no ground is not lit', () => {
    const { root } = setup();
    const layer = new TrafficLayer(root, (x) => (x > 9_000 ? null : 0), toRenderer);
    layer.setWindow(trafficWindow([car('parked', 10, false)], { signals }), 0);
    layer.update(2500);
    // Second 102: the vehicle group shows green, the walk shows don't walk; the stop line at 10 m
    // stands where the drawn world has no ground.
    expect(layer.lightsLit).toBe(2);
    expect(lampColour(root, 'signal-head:s1:phase_a:0:0')).toBe(SIGNAL_LOOKS_V1.colours['green']!.slice(1));
    expect(lampColour(root, 'signal-head:s1:walk_a:5000:5000')).toBe(SIGNAL_LOOKS_V1.colours['dont_walk']!.slice(1));
    layer.update(7500);
    // Second 107: red for the vehicles, walk for the walkers.
    expect(lampColour(root, 'signal-head:s1:phase_a:0:0')).toBe(SIGNAL_LOOKS_V1.colours['red']!.slice(1));
    expect(lampColour(root, 'signal-head:s1:walk_a:5000:5000')).toBe(SIGNAL_LOOKS_V1.colours['walk']!.slice(1));
  });

  it('refuses an indication its looks do not state, before anything is drawn', () => {
    const { root } = setup();
    const layer = new TrafficLayer(root, () => 0, toRenderer);
    expect(() => layer.setWindow(
      trafficWindow([car('parked', 10, false)], { signals, vehicleIndications: ['green', 'amber', 'purple' as never] }),
      0,
    )).toThrow(SignalLookError);
  });
});
