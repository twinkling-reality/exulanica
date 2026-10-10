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
import { isNavigationPositionClear, atlasVec3, readSurfaceMaterials } from '@exulanica/atlas-core';
import * as pc from 'playcanvas';
import { describe, expect, it } from 'vitest';
import {
  parseSiteDrawing,
  siteMount,
  siteNavigationWorld,
  siteStart,
  slotColour,
  drawSiteSlots,
  type SiteDrawing,
} from '../src/playcanvas/generated-site/index.js';

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

describe('reading a site drawing', () => {
  it('reads the served shape, splitting each look role into its family and leaf', () => {
    const drawing = parseSiteDrawing(served());
    expect(drawing.kind.label).toBe('Yard');
    expect(drawing.slots).toHaveLength(7);
    expect(drawing.slots[5]).toMatchObject({ family: 'roof', leaf: 'clay', primitive: 'gable' });
    expect(drawing.walk.blockersMm).toHaveLength(3);
  });

  it.each([
    ['another profile', (d: Record<string, unknown>) => { d['profile'] = 'exulanica.site-drawing/v2'; }, 'is not exulanica.site-drawing/v1'],
    ['a float', (d: Record<string, unknown>) => { (d['arrival'] as { positionMm: number[] }).positionMm[0] = 0.5; }, 'not a whole number'],
    ['a look role with no family', (d: Record<string, unknown>) => { (d['slots'] as { lookRole: string }[])[1]!.lookRole = 'plaster'; }, 'family.leaf'],
    ['a fifth quarter turn', (d: Record<string, unknown>) => { (d['slots'] as { yawQuarterTurns: number }[])[1]!.yawQuarterTurns = 4; }, '0 to 3 quarter turns'],
    ['two slots of one identity', (d: Record<string, unknown>) => { (d['slots'] as { identity: string }[])[2]!.identity = 'shed:wall:0'; }, 'share an identity'],
    ['a rectangle from its far corner', (d: Record<string, unknown>) => { (d['walk'] as { floorMm: number[] }).floorMm = [10_000, 0, 0, 12_000]; }, 'from its least corner'],
  ])('refuses %s by name', (_name, change, words) => {
    const document = served();
    change(document);
    expect(() => parseSiteDrawing(document)).toThrow(words);
  });
});

describe('walking a site', () => {
  const drawing = parseSiteDrawing(served());
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
    const east = parseSiteDrawing({ ...served(), arrival: { positionMm: [5000, 4000, 0], facingMm: [1, 0] } });
    expect(siteStart(east, world).yaw).toBeCloseTo(-Math.PI / 2);
  });
});

// Relative to web/, where the suite runs: the catalog a deployment ships.
const MATERIALS = readSurfaceMaterials(readFileSync('../assets/catalogs/world-kinds/surface-material.v1.json', 'utf8'));
const bytes = (rgb: readonly number[]): number[] => rgb.map((channel) => Math.round(channel * 255));

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
  const drawing: SiteDrawing = parseSiteDrawing(served());

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
    const mount = siteMount(parseSiteDrawing(unread), { servedBytes: 1, materials: MATERIALS });
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
