// @vitest-environment happy-dom
/**
 * A world kind's site in the browser: its served drawing is read or refused by name, a person
 * walks its floor and keeps out of its walls, and its slots are drawn and taken away again.
 *
 * The drawing below is hand-written in the served shape (`exulanica.site-drawing/v1`): a 10 m by
 * 12 m yard with one 4 m by 3 m shed whose door is a 1 m gap in its south wall, a bench and a gable
 * roof. It is a test fixture, not a site a kind generated.
 */
import { readFileSync } from 'node:fs';
import { isNavigationPositionClear, atlasVec3, readRoofForms, readSurfaceMaterials } from '@exulanica/atlas-core';
import * as pc from 'playcanvas';
import { describe, expect, it } from 'vitest';
import {
  SITE_BEYOND_DROP_M,
  baseGroundSlot,
  parseStructuredSiteDrawing,
  siteMount,
  siteNavigationWorld,
  siteStart,
  slotColour,
  drawSiteSlots,
  type StructuredSiteDrawing,
} from '../src/playcanvas/generated-site/index.js';
import type { TileLook } from '../src/playcanvas/generated-tile/look.js';
import { renderLookOfPreset } from '../src/playcanvas/style-pack/preset-look.js';

function slot(identity: string, lookRole: string, primitive: string, position: number[], yaw: number, box: number[]) {
  return {
    identity, part: identity.split(':')[0], label: identity, lookRole, positionMm: position,
    yawQuarterTurns: yaw, boxMm: box, front: '+y', fit: 'contain', primitive,
  };
}

function served(): Record<string, unknown> {
  return {
    profile: 'exulanica.site-drawing/v1',
    world_id: 'world-1',
    receipt_sha256: 'a'.repeat(64),
    kind: { kind: 'fixture_yard', version: 1, label: 'Yard' },
    extent: { widthMm: 10_000, depthMm: 12_000, enclosure: 'open' },
    arrival: { positionMm: [5000, 4000, 0], facingMm: [0, 1] },
    slots: [
      { ...slot('ground', 'ground.tilled_soil', 'plane', [5000, 6000, 0], 0, [10_000, 12_000, 0]), fit: 'surface' },
      // The shed's south wall either side of its door, its west wall turned a quarter, its door.
      slot('shed:wall:0', 'wall.plaster', 'box', [3750, 7100, 0], 0, [1500, 200, 2400]),
      slot('shed:wall:1', 'wall.plaster', 'box', [6250, 7100, 0], 0, [1500, 200, 2400]),
      slot('shed:wall:2', 'wall.plaster', 'box', [3100, 8500, 0], 1, [3000, 200, 2400]),
      { ...slot('shed:door:0', 'door.plank', 'none', [5000, 7100, 0], 0, [1000, 200, 2100]), fit: 'fill' },
      slot('shed:roof', 'roof.clay', 'gable', [5000, 8500, 2400], 0, [4000, 3000, 1050]),
      slot('bench', 'fixture.bench', 'box', [5000, 3000, 0], 2, [1800, 500, 450]),
    ],
    walk: {
      floorMm: [0, 0, 10_000, 12_000],
      blockersMm: [[3000, 7000, 4500, 7200], [5500, 7000, 7000, 7200], [3000, 7000, 3200, 10_000]],
      keepOutMm: [[8000, 1000, 9000, 2000]],
    },
    seats: [{ identity: 'bench', seatHeightMm: 450 }],
  };
}

/** The yard with its shed's own slot, every piece of the shed naming it, as the served drawing states buildings. */
function built(): Record<string, unknown> {
  const document = served();
  const slots = document['slots'] as Record<string, unknown>[];
  for (const one of slots) if (String(one['identity']).startsWith('shed:')) one['structure'] = 'shed';
  slots.push({ ...slot('shed', 'structure.shed', 'none', [5000, 8500, 0], 0, [4000, 3000, 2400]) });
  return document;
}

describe('reading a site drawing', () => {
  it('reads the served shape, splitting each look role into its family and leaf', () => {
    const drawing = parseStructuredSiteDrawing(served());
    expect(drawing.kind.label).toBe('Yard');
    expect(drawing.slots).toHaveLength(7);
    expect(drawing.slots[5]).toMatchObject({ family: 'roof', leaf: 'clay', primitive: 'gable' });
    expect(drawing.walk.blockersMm).toHaveLength(3);
  });

  it('reads which building a slot is a piece of, and states none where the drawing says none', () => {
    const document = built();
    const drawing = parseStructuredSiteDrawing(document);
    expect(drawing.slots.filter((one) => one.structure === 'shed').map((one) => one.identity))
      .toEqual(['shed:wall:0', 'shed:wall:1', 'shed:wall:2', 'shed:door:0', 'shed:roof']);
    expect(drawing.slots.find((one) => one.identity === 'shed')!.structure).toBeUndefined();
    expect('structure' in parseStructuredSiteDrawing(served()).slots[1]!).toBe(false);
  });

  it("reads a building's own storey height, and states none where the drawing states none", () => {
    const document = built();
    (document['slots'] as Record<string, unknown>[]).at(-1)!['storeyHeightMm'] = 2400;
    const drawing = parseStructuredSiteDrawing(document);
    expect(drawing.slots.find((one) => one.identity === 'shed')!.storeyHeightMm).toBe(2400);
    expect(drawing.slots.filter((one) => one.storeyHeightMm !== undefined)).toHaveLength(1);
    expect(parseStructuredSiteDrawing(built()).slots.some((one) => 'storeyHeightMm' in one)).toBe(false);
  });

  it("reads a building's arcade, and states none where the drawing states none", () => {
    const document = built();
    Object.assign((document['slots'] as Record<string, unknown>[]).at(-1)!, { arcadeBays: 3, loggiaDepthMm: 2000 });
    const shed = parseStructuredSiteDrawing(document).slots.find((one) => one.identity === 'shed')!;
    expect([shed.arcadeBays, shed.loggiaDepthMm, shed.arcadeSides]).toEqual([3, 2000, undefined]);
    Object.assign((document['slots'] as Record<string, unknown>[]).at(-1)!, { arcadeSides: 2 });
    expect(parseStructuredSiteDrawing(document).slots.find((one) => one.identity === 'shed')!.arcadeSides).toBe(2);
    expect(parseStructuredSiteDrawing(built()).slots.some((one) => 'arcadeBays' in one || 'loggiaDepthMm' in one)).toBe(false);
  });

  it.each([
    ['another profile', (d: Record<string, unknown>) => { d['profile'] = 'exulanica.site-drawing/unsupported'; }, 'is not exulanica.site-drawing/v1'],
    ['a float', (d: Record<string, unknown>) => { (d['arrival'] as { positionMm: number[] }).positionMm[0] = 0.5; }, 'not a whole number'],
    ['a look role with no family', (d: Record<string, unknown>) => { (d['slots'] as { lookRole: string }[])[1]!.lookRole = 'plaster'; }, 'family.leaf'],
    ['a fifth quarter turn', (d: Record<string, unknown>) => { (d['slots'] as { yawQuarterTurns: number }[])[1]!.yawQuarterTurns = 4; }, '0 to 3 quarter turns'],
    ['two slots of one identity', (d: Record<string, unknown>) => { (d['slots'] as { identity: string }[])[2]!.identity = 'shed:wall:0'; }, 'share an identity'],
    ['a rectangle from its far corner', (d: Record<string, unknown>) => { (d['walk'] as { floorMm: number[] }).floorMm = [10_000, 0, 0, 12_000]; }, 'from its least corner'],
    ['a structure that is not text', (d: Record<string, unknown>) => { (d['slots'] as Record<string, unknown>[])[1]!['structure'] = 7; }, 'slot 1 structure is not text'],
    ['a structure the drawing has no slot for', (d: Record<string, unknown>) => { (d['slots'] as Record<string, unknown>[])[1]!['structure'] = 'barn'; }, 'is a piece of barn, which is no slot of the drawing'],
    ['a building that is a piece of another', (d: Record<string, unknown>) => { (d['slots'] as Record<string, unknown>[]).at(-1)!['structure'] = 'bench'; }, "slot shed is a building's own slot and a piece of another"],
    ['a storey height on a slot that is no building', (d: Record<string, unknown>) => { (d['slots'] as Record<string, unknown>[])[1]!['storeyHeightMm'] = 2400; }, "states a storey height, and only a building's own slot does"],
    ['a storey height that is not a whole number', (d: Record<string, unknown>) => { (d['slots'] as Record<string, unknown>[]).at(-1)!['storeyHeightMm'] = 1200.5; }, 'storey height is not a whole number'],
    ["a storey height that does not divide the building's height", (d: Record<string, unknown>) => { (d['slots'] as Record<string, unknown>[]).at(-1)!['storeyHeightMm'] = 1000; }, 'storey height does not divide its 2400 mm height'],
    ['a storey height of nothing', (d: Record<string, unknown>) => { (d['slots'] as Record<string, unknown>[]).at(-1)!['storeyHeightMm'] = 0; }, 'storey height does not divide its 2400 mm height'],
    ['an arcade on a slot that is no building', (d: Record<string, unknown>) => { Object.assign((d['slots'] as Record<string, unknown>[])[1]!, { arcadeBays: 3, loggiaDepthMm: 2000 }); }, "states an arcade, and only a building's own slot does"],
    ["an arcade's bays without its covered walk", (d: Record<string, unknown>) => { (d['slots'] as Record<string, unknown>[]).at(-1)!['arcadeBays'] = 3; }, "states an arcade's bays and its covered walk's depth together"],
    ['an arcade of no bay', (d: Record<string, unknown>) => { Object.assign((d['slots'] as Record<string, unknown>[]).at(-1)!, { arcadeBays: 0, loggiaDepthMm: 2000 }); }, 'arcade has no bay'],
    ["an arcade's sides without its bays", (d: Record<string, unknown>) => { (d['slots'] as Record<string, unknown>[]).at(-1)!['arcadeSides'] = 2; }, "states an arcade's sides only as 2, beside its bays"],
    ['an arcade on one side stated as its sides', (d: Record<string, unknown>) => { Object.assign((d['slots'] as Record<string, unknown>[]).at(-1)!, { arcadeBays: 3, loggiaDepthMm: 1000, arcadeSides: 1 }); }, "states an arcade's sides only as 2, beside its bays"],
    ['a covered walk as deep as its building', (d: Record<string, unknown>) => { Object.assign((d['slots'] as Record<string, unknown>[]).at(-1)!, { arcadeBays: 3, loggiaDepthMm: 3000 }); }, 'covered walk is not inside its 3000 mm depth'],
  ])('refuses %s by name', (_name, change, words) => {
    const document = built();
    change(document);
    expect(() => parseStructuredSiteDrawing(document)).toThrow(words);
  });
});

describe('walking a site', () => {
  const drawing = parseStructuredSiteDrawing(served());
  const world = siteNavigationWorld(drawing);
  // A site point (x east, y north, in millimetres) in the renderer's frame (east, up, south, metres).
  const at = (x: number, y: number) => atlasVec3(x / 1000, 0, -y / 1000);

  it('stands a person on the site floor and on nothing beyond it', () => {
    expect(world.surface.sample(5, -6)?.height).toBe(0);
    expect(world.surface.sample(-0.5, -6)).toBeNull();
    expect(world.surface.sample(5, 0.5)).toBeNull();
  });

  it('keeps a person out of the walls and water but lets them through the door', () => {
    expect(isNavigationPositionClear(world, at(3800, 7100))).toBe(false);
    expect(isNavigationPositionClear(world, at(3100, 9000))).toBe(false);
    expect(isNavigationPositionClear(world, at(8500, 1500))).toBe(false);
    // The door is 1,000 mm wide and the walker 340 mm in radius: its middle is clear.
    expect(isNavigationPositionClear(world, at(5000, 7100))).toBe(true);
    // A walker a hand's breadth from the wall's face touches it.
    expect(isNavigationPositionClear(world, at(3800, 6750))).toBe(false);
  });

  it('opens a person at the arrival, eye high, facing the way it states', () => {
    const start = siteStart(drawing, world);
    expect(start).toMatchObject({ x: 5, y: world.eyeHeight, z: -4, pitch: 0 });
    expect(start.yaw).toBeCloseTo(0);
    const east = parseStructuredSiteDrawing({ ...served(), arrival: { positionMm: [5000, 4000, 0], facingMm: [1, 0] } });
    expect(siteStart(east, world).yaw).toBeCloseTo(-Math.PI / 2);
  });
});

// Relative to web/, where the suite runs: the catalog a deployment ships.
const MATERIALS = readSurfaceMaterials(readFileSync('../assets/catalogs/world-kinds/surface-material.v2.json', 'utf8'));
const ROOF_FORMS = readRoofForms(readFileSync('../assets/catalogs/world-kinds/roof-form.v1.json', 'utf8'));
const bytes = (rgb: readonly number[]): number[] => rgb.map((channel) => Math.round(channel * 255));
/** The default light of the committed cozy town pack, which states a ground beyond the world: a lawn, 0.6 m down. */
const COZY = JSON.parse(readFileSync('../assets/style-packs/packs/exulanica.cozy-town/manifest.json', 'utf8')) as {
  light: { default_preset: string; presets: Record<string, never> }; shading: never; edge: { ground: number[]; drop_mm: number };
};
const edgedLook = (): TileLook => renderLookOfPreset(COZY.light.presets[COZY.light.default_preset]!, COZY.shading, COZY.edge as never);

const xyz = (v: pc.Vec3): number[] => [v.x, v.y, v.z].map((n) => Math.round(n * 1e6) / 1e6);

function nullApp(): { app: pc.AppBase; camera: pc.Entity; environmentRoot: pc.Entity } {
  const canvas = document.createElement('canvas');
  canvas.width = 0;
  canvas.height = 0;
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem, pc.LightComponentSystem];
  app.init(options);
  const camera = new pc.Entity('camera');
  camera.addComponent('camera');
  app.root.addChild(camera);
  const environmentRoot = new pc.Entity('environment');
  app.root.addChild(environmentRoot);
  return { app, camera, environmentRoot };
}

describe('drawing a site', () => {
  const drawing: StructuredSiteDrawing = parseStructuredSiteDrawing(served());

  it('draws each slot but a pack-only one at its base, turned by its quarter turns', () => {
    const { app } = nullApp();
    const drawn = drawSiteSlots(app.graphicsDevice, drawing);
    expect(drawn.drawn).toBe(6);
    const west = drawn.root.findByName('shed:wall:2') as pc.Entity;
    expect(xyz(west.getLocalPosition())).toEqual([3.1, 0, -8.5]);
    expect(west.getLocalEulerAngles().y).toBeCloseTo(90);
    const shape = west.findByName('shed:wall:2:shape') as pc.Entity;
    expect(xyz(shape.getLocalScale())).toEqual([3, 2.4, 0.2]);
    expect(shape.getLocalPosition().y).toBeCloseTo(1.2);
    expect(drawn.root.findByName('shed:door:0')).toBeNull();
    const ground = drawn.root.findByName('ground:shape') as pc.Entity;
    expect(xyz(ground.getLocalScale())).toEqual([10, 1, 12]);
    drawn.destroy();
  });

  it('colours a slot by the material its leaf names in the catalog, and anything else by its family', () => {
    const [ground, wall] = drawing.slots;
    const roof = drawing.slots.find((slot) => slot.identity === 'shed:roof')!;
    const bench = drawing.slots.find((slot) => slot.identity === 'bench')!;
    const colourOf = (key: string) => [...MATERIALS.materials.find((material) => material.key === key)!.swatch.srgb8];
    // Tilled soil is soil, a plaster wall plaster and a clay roof its tiles: the catalog's colours.
    expect(bytes(slotColour(ground!, 'open', MATERIALS))).toEqual(colourOf('soil'));
    expect(bytes(slotColour(wall!, 'open', MATERIALS))).toEqual(colourOf('plaster'));
    expect(bytes(slotColour(roof, 'open', MATERIALS))).toEqual(colourOf('roof_tile'));
    // A leaf that names no material, a default leaf and a family no material serves: the family's.
    expect(slotColour({ ...ground!, leaf: 'yard' }, 'open', MATERIALS)).toEqual([0.47, 0.56, 0.33]);
    expect(slotColour({ ...ground!, leaf: 'default' }, 'open', MATERIALS)).toEqual([0.47, 0.56, 0.33]);
    expect(slotColour(bench, 'open', MATERIALS)).toEqual([0.58, 0.44, 0.3]);
    expect(slotColour({ ...ground!, leaf: 'yard' }, 'indoor', MATERIALS)).toEqual([0.66, 0.55, 0.42]);
    // With no catalog nothing is read from a leaf: one colour a family.
    expect(slotColour(ground!, 'open')).toEqual([0.47, 0.56, 0.33]);
    expect(slotColour(wall!, 'open')).toEqual([0.85, 0.82, 0.75]);
  });

  it('draws each slot in its leaf\'s material where the mount carries the catalog, and says on the canvas what it read', () => {
    const { app, camera, environmentRoot } = nullApp();
    const canvas = app.graphicsDevice.canvas as HTMLCanvasElement;
    const unread = { ...served(), slots: [
      ...(served()['slots'] as unknown[]),
      slot('yard', 'ground.play_yard', 'plane', [5000, 2000, 6], 0, [2000, 2000, 0]),
      // Two holes only a pack fills, which the engine never draws: neither is counted, whatever its words.
      slot('gap', 'wall.stone', 'none', [9000, 9000, 0], 0, [1000, 200, 2000]),
      slot('hole', 'wall.who_knows', 'none', [9000, 5000, 0], 0, [1000, 200, 2000]),
    ] };
    const mount = siteMount(parseStructuredSiteDrawing(unread), { servedBytes: 1, materials: MATERIALS });
    const attachment = mount.attach({ app, camera, environmentRoot });
    const shape = (identity: string) => ((environmentRoot.findByName(`${identity}:shape`) as pc.Entity).render!.meshInstances[0]!.material as pc.StandardMaterial).diffuse;
    const soil = MATERIALS.materials.find((material) => material.key === 'soil')!.swatch.srgb8;
    expect(bytes([shape('ground').r, shape('ground').g, shape('ground').b])).toEqual([...soil]);
    // The ground, three walls and the roof name a material; the bench is no surface; the yard names none.
    expect(canvas.dataset['siteMaterials']).toBe('5');
    expect(JSON.parse(canvas.dataset['siteUnknownLooks']!)).toEqual(['ground.play_yard']);
    attachment.dispose();
    expect('siteMaterials' in canvas.dataset || 'siteUnknownLooks' in canvas.dataset).toBe(false);
    // With no catalog the mount reads no leaf and says nothing.
    const plain = siteMount(drawing, { servedBytes: 1 }).attach({ app, camera, environmentRoot });
    expect('siteMaterials' in canvas.dataset).toBe(false);
    plain.dispose();
  });

  it('draws the ground beyond an open site in what its base ground is drawn in, just under it, and says so on the canvas', () => {
    const { app, camera, environmentRoot } = nullApp();
    const canvas = app.graphicsDevice.canvas as HTMLCanvasElement;
    expect(baseGroundSlot(drawing)?.identity).toBe('ground');
    const attachment = siteMount(drawing, { servedBytes: 1, look: edgedLook(), materials: MATERIALS }).attach({ app, camera, environmentRoot });
    const edge = app.root.findByName('generated-tile:edge-ground') as pc.Entity;
    const ground = (environmentRoot.findByName('ground:shape') as pc.Entity).render!.meshInstances[0]!;
    // The pack's own plane, out to the pack's own reach, now in the site's soil and not the pack's lawn.
    expect(edge.render!.meshInstances[0]!.material).toBe(ground.material);
    expect(bytes([...'rgb'].map((channel) => (ground.material as pc.StandardMaterial).diffuse[channel as 'r']))).toEqual([...MATERIALS.materials.find((m) => m.key === 'soil')!.swatch.srgb8]);
    expect(edge.getPosition().y).toBeCloseTo(-SITE_BEYOND_DROP_M, 5);
    // Under the ground by more than one of the drawing's 6 mm layer steps, and by too little for a step to show at the site's edge.
    expect(SITE_BEYOND_DROP_M).toBeGreaterThan(0.006);
    expect(SITE_BEYOND_DROP_M).toBeLessThanOrEqual(0.03);
    expect(canvas.dataset['siteGroundBeyond']).toBe('ground.tilled_soil');
    attachment.dispose();
    expect('siteGroundBeyond' in canvas.dataset).toBe(false);
    expect(app.root.findByName('generated-tile:edge-ground')).toBeNull();
  });

  it('keeps the look\'s own ground beyond an indoor site and beyond a site with no ground over its whole extent', () => {
    const indoor = parseStructuredSiteDrawing({ ...served(), extent: { widthMm: 10_000, depthMm: 12_000, enclosure: 'indoor' } });
    const patch = parseStructuredSiteDrawing({ ...served(), slots: (served()['slots'] as { identity: string; boxMm: number[] }[]).map((one) => (one.identity === 'ground' ? { ...one, boxMm: [9000, 12_000, 0] } : one)) });
    expect(baseGroundSlot(patch)).toBeNull();
    // The base ground is the plane over the whole extent at the site's own level: not one as wide but
    // shallower, not one of the right size laid off its centre or above the ground, and not a box.
    const groundAs = (change: Record<string, unknown>) => parseStructuredSiteDrawing({ ...served(), slots: (served()['slots'] as { identity: string }[]).map((one) => (one.identity === 'ground' ? { ...one, ...change } : one)) });
    expect(baseGroundSlot(groundAs({ boxMm: [10_000, 11_000, 0] }))).toBeNull();
    expect(baseGroundSlot(groundAs({ positionMm: [5500, 6000, 0] }))).toBeNull();
    expect(baseGroundSlot(groundAs({ positionMm: [5000, 6500, 0] }))).toBeNull();
    expect(baseGroundSlot(groundAs({ positionMm: [5000, 6000, 6] }))).toBeNull();
    expect(baseGroundSlot(groundAs({ primitive: 'box' }))).toBeNull();
    expect(baseGroundSlot(groundAs({ lookRole: 'path.tilled_soil' }))).toBeNull();
    for (const site of [indoor, patch]) {
      const { app, camera, environmentRoot } = nullApp();
      const attachment = siteMount(site, { servedBytes: 1, look: edgedLook(), materials: MATERIALS }).attach({ app, camera, environmentRoot });
      const edge = app.root.findByName('generated-tile:edge-ground') as pc.Entity;
      expect(edge.render!.meshInstances[0]!.material.name).toBe('generated-tile:edge-ground');
      expect(edge.getPosition().y).toBeCloseTo(-COZY.edge.drop_mm / 1000, 5);
      expect('siteGroundBeyond' in (app.graphicsDevice.canvas as HTMLCanvasElement).dataset).toBe(false);
      attachment.dispose();
    }
  });

  it('draws a roof in its material\'s form where the mount carries the roof forms, and not the walls a tent stands in place of', () => {
    // The yard's shed, roofed in canvas: a tent. Its three wall pieces are inside its footprint.
    const camp = parseStructuredSiteDrawing({ ...served(), slots: (served()['slots'] as { identity: string }[]).map((one) => (one.identity === 'shed:roof' ? { ...one, lookRole: 'roof.tent' } : one)) });
    const { app } = nullApp();
    const plain = drawSiteSlots(app.graphicsDevice, camp, MATERIALS);
    const shaped = drawSiteSlots(app.graphicsDevice, camp, MATERIALS, ROOF_FORMS);
    // As served: the prism, turned by the slot, and every wall piece.
    expect(plain.drawn).toBe(6);
    expect(plain.triangles).toBe(2 + 3 * 12 + 8 + 12);
    // In its form: the tent's own mesh in the site's axes, with no wall piece under it.
    expect([...shaped.entities.keys()].sort()).toEqual(['bench', 'ground', 'shed:roof']);
    const roof = shaped.entities.get('shed:roof')!;
    expect(xyz(roof.getLocalPosition())).toEqual([5, 2.4, -8.5]);
    expect(roof.getLocalEulerAngles().y).toBeCloseTo(0);
    const mesh = (roof.findByName('shed:roof:shape') as pc.Entity).render!.meshInstances[0]!;
    // Canvas, like any slot of that material; two sides and two ends, the door left open in one.
    expect(bytes([...'rgb'].map((channel) => (mesh.material as pc.StandardMaterial).diffuse[channel as 'r']))).toEqual([...MATERIALS.materials.find((m) => m.key === 'canvas')!.swatch.srgb8]);
    expect(shaped.triangles).toBe(2 + 12 + mesh.mesh.primitive[0]!.count / 3);
    expect(mesh.mesh.primitive[0]!.count / 3).toBeGreaterThan(8);
    // Without the materials a roof's leaf is not read, so nothing is shaped.
    expect(drawSiteSlots(app.graphicsDevice, camp, null, ROOF_FORMS).drawn).toBe(6);
    plain.destroy();
    shaped.destroy();
    // The mount hands the forms on: three slots drawn, not six.
    const mounted = nullApp();
    const attachment = siteMount(camp, { servedBytes: 1, materials: MATERIALS, roofForms: ROOF_FORMS }).attach(mounted);
    expect(attachment.metrics.drawBatches).toBe(3);
    attachment.dispose();
  });

  it('hands a dresser every drawn slot by identity and undresses before the slots go', () => {
    const { app, camera, environmentRoot } = nullApp();
    const seen: string[] = [];
    let stillThere: boolean | null = null;
    const mount = siteMount(drawing, {
      servedBytes: 1,
      dress: (_host, drawn, dressed) => {
        seen.push(...drawn.entities.keys());
        expect(dressed).toBe(drawing);
        const bench = drawn.entities.get('bench')!;
        bench.enabled = false;
        return () => {
          stillThere = bench.parent !== null;
          bench.enabled = true;
        };
      },
    });
    const attachment = mount.attach({ app, camera, environmentRoot });
    // Every slot but the door, which draws nothing until a pack fills it.
    expect(seen.sort()).toEqual(
      drawing.slots.filter((slot) => slot.primitive !== 'none').map((slot) => slot.identity).sort(),
    );
    attachment.dispose();
    expect(stillThere).toBe(true);
    expect(environmentRoot.children).toEqual([]);
  });

  it('attaches under the environment root with the tile look, and takes everything away again', () => {
    const { app, camera, environmentRoot } = nullApp();
    const lightsBefore = app.root.findComponents('light').length;
    const mount = siteMount(drawing, { servedBytes: 1234 });
    expect(mount.kindLabel).toBe('Yard');
    const attachment = mount.attach({ app, camera, environmentRoot });
    expect(environmentRoot.children.map((child) => child.name)).toEqual(['generated-site:world-1']);
    expect(app.root.findComponents('light').length).toBe(lightsBefore + 1);
    expect(attachment.metrics).toMatchObject({ tileName: 'site:world-1', drawBatches: 6, transferredBytes: 1234 });
    attachment.dispose();
    expect(environmentRoot.children).toEqual([]);
    expect(app.root.findComponents('light').length).toBe(lightsBefore);
  });
});
