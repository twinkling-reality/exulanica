// @vitest-environment happy-dom
/**
 * Traffic drawn in a style pack's vehicles, with a committed pack: the piece for the vehicle's body
 * family, fitted into the record's own size, turned to face the way a vehicle at yaw 0 faces, its
 * body swatch in the vehicle's colour as the pack draws it.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { readStylePackManifest, resolveStylePack, type LookFamily } from '@exulanica/atlas-core';
import { VEHICLE_BODY_SWATCH, loadPackPieces, packVehicleBodies } from '../src/playcanvas/style-pack/index.js';
import type { VehicleSamples } from '../src/playcanvas/traffic/types.js';

// Relative to web/, where the suite runs.
const PACK = '../assets/style-packs/packs/exulanica.toon-town';
const catalog = JSON.parse(readFileSync('../assets/catalogs/world-kinds/look-family.v1.json', 'utf8')) as {
  entries: { key: string; fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }[];
};
const families = new Map<string, LookFamily>(catalog.entries.map((e) => [e.key, { fit: e.fit, dressing: e.dressing, fillMinimumPermille: e.fill_minimum_permille, fillMaximumPermille: e.fill_maximum_permille }]));
const textureSets = new Set<string>((JSON.parse(readFileSync('../assets/textures/manifest.json', 'utf8')) as { sets: { set_id: string }[] }).sets.map((s) => s.set_id));
const TABLE = JSON.parse(readFileSync('../assets/colour/srgb8-linear16.v1.json', 'utf8')).values as number[];
const pack = resolveStylePack([readStylePackManifest(JSON.parse(readFileSync(`${PACK}/manifest.json`, 'utf8')), { families, textureSets })]);

function device(): pc.GraphicsDevice {
  const canvas = document.createElement('canvas');
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = new pc.NullGraphicsDevice(canvas);
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  return app.graphicsDevice;
}

const row = (vehicleId: string, bodyFamily: string, colour: string): VehicleSamples => ({
  vehicleId, vehicleClass: 'passenger_car', bodyFamily, colour,
  // The traffic catalog's passenger car: 5,790 long, 2,130 wide, 1,300 tall.
  dimensionsMm: { length: 5790, width: 2130, height: 1300, wheelbase: 3350, frontOverhang: 910, rearOverhang: 1530 },
  frontAxleMm: [], rearAxleMm: [], mode: [], speedMmPerS: [], motionPathMm: [],
});

describe('vehicles in a style pack', () => {
  it('draw a body family\'s piece, fitted into the record\'s size, facing -Z, in the vehicle\'s colour', async () => {
    const pieces = await loadPackPieces(device(), pack, Object.keys(pack.modules), TABLE, async (file) => new Uint8Array(readFileSync(`${PACK}/${file.path}`)));
    const bodies = packVehicleBodies(pack, families, pieces, { model: 'pbr', toon: null, ink: null });
    const sedan = bodies.body(row('v1', 'sedan', 'red'))!;
    expect(sedan.name).toBe('style-pack:vehicle.sedan');
    // The sedan piece is 1,800 by 4,600 by 1,440 mm: contained by its height, 1,300 / 1,440.
    const scale = sedan.getLocalScale();
    for (const value of [scale.x, scale.y, scale.z]) expect(value).toBeCloseTo(1300 / 1440, 6);
    // The piece's front (+Z) turned to the way a vehicle at yaw 0 faces (-Z), its up kept.
    const front = sedan.getLocalRotation().transformVector(new pc.Vec3(0, 0, 1));
    const up = sedan.getLocalRotation().transformVector(new pc.Vec3(0, 1, 0));
    [front.x, front.y, front.z].forEach((value, i) => expect(value).toBeCloseTo([0, 0, -1][i]!, 6));
    [up.x, up.y, up.z].forEach((value, i) => expect(value).toBeCloseTo([0, 1, 0][i]!, 6));
    const names = sedan.render!.meshInstances.map((instance) => instance.material.name);
    expect(names).toContain('style-pack:swatch:vehicle_red');
    expect(names).not.toContain(`style-pack:swatch:${VEHICLE_BODY_SWATCH}`);
    // A colour the pack does not state keeps the piece's own body swatch.
    expect(bodies.body(row('v2', 'hatchback', 'chartreuse'))!.render!.meshInstances.map((instance) => instance.material.name)).toContain(`style-pack:swatch:${VEHICLE_BODY_SWATCH}`);
    // A body family the pack does not dress keeps the traffic layer's boxes.
    expect(bodies.body(row('v3', 'upright_bicycle', 'red'))).toBeNull();
    bodies.dispose();
    pieces.dispose();
  });
});
