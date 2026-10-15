// @vitest-environment happy-dom
/**
 * The windows a pack's facade draws on a made place's buildings: lit by the light's own share or by
 * the rule's sun, set after a wall material's own colour, emission and gloss functions without
 * replacing them, on the walls that face out of a building only, each wall's instance stating its
 * building and its rule, and taken off again with the dressing.
 *
 * The pack is the shared case that states a facade for `wall.default`
 * (`assets/style-packs/manifest-cases.v1.json`).
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { readStylePackManifest, readSurfacePatterns, resolveStylePack, type LookFamily, type StylePackFacade, type StylePackManifest } from '@exulanica/atlas-core';
import { parseStructuredSiteDrawing, siteMount } from '../src/playcanvas/generated-site/index.js';
import { renderLookOfPreset, linearRgb } from '../src/playcanvas/style-pack/preset-look.js';
import {
  applyFacadeFinish, clearFacadeWall, facadeApplied, facadeFronts, facadeRuns, facadeWears, litShareOf, setFacadeWall,
  withFacadeColour, withFacadeEmission, withFacadeGloss, type FacadeSlot,
} from '../src/playcanvas/style-pack/facade-finish.js';
import { withFinish } from '../src/playcanvas/style-pack/ground-finish.js';
import { patternChunks } from '../src/playcanvas/style-pack/pattern-material.js';
import { packSiteDresser, type SiteDressingSummary } from '../src/playcanvas/style-pack/index.js';

// Relative to web/, where the suite runs.
const CASES = JSON.parse(readFileSync('../assets/style-packs/manifest-cases.v1.json', 'utf8')) as {
  context: { families: Record<string, { fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }>; texture_sets: string[] };
  cases: { name: string; manifest: StylePackManifest }[];
};
const families = new Map<string, LookFamily>(Object.entries(CASES.context.families).map(([key, entry]) => [key, {
  fit: entry.fit, dressing: entry.dressing, fillMinimumPermille: entry.fill_minimum_permille, fillMaximumPermille: entry.fill_maximum_permille,
}]));
const caseNamed = (name: string): StylePackManifest => CASES.cases.find((one) => one.name === name)!.manifest;
const WALLS = caseNamed('a pack drawing windows on its building walls');
const NIGHT = caseNamed('a night light lighting its windows whatever its sun');
const PLAIN = caseNamed('a pack growing grass and flowers on its lawns in a wind');
const packOf = (manifest: StylePackManifest) => resolveStylePack([readStylePackManifest(manifest, { families, textureSets: new Set(CASES.context.texture_sets) })]);
const RULE: StylePackFacade = packOf(WALLS).facade['wall.default']!;

describe('the share of a facade\'s windows lit', () => {
  it('is the dusk share with the sun low, the day share with it high, and runs between without a step', () => {
    const dusk = RULE.dusk_sun_mdeg / 1000;
    const day = RULE.day_sun_mdeg / 1000;
    expect(litShareOf(RULE, dusk)).toBeCloseTo(RULE.lit_dusk_permille / 1000, 9);
    expect(litShareOf(RULE, 5)).toBeCloseTo(RULE.lit_dusk_permille / 1000, 9);
    expect(litShareOf(RULE, day)).toBeCloseTo(RULE.lit_day_permille / 1000, 9);
    expect(litShareOf(RULE, 80)).toBeCloseTo(RULE.lit_day_permille / 1000, 9);
    let last = litShareOf(RULE, dusk);
    for (let deg = dusk + 1; deg <= day; deg += 1) {
      const share = litShareOf(RULE, deg);
      expect(share).toBeLessThanOrEqual(last);
      expect(last - share).toBeLessThan(0.05);
      last = share;
    }
  });

  it('is the light\'s own share wherever the light states one, whatever its sun', () => {
    expect(litShareOf(RULE, 60, 0.65)).toBe(0.65);
    expect(litShareOf(RULE, 5, 0)).toBe(0);
  });
});

const count = (text: string, of: string) => text.split(of).length - 1;
/** A colour chunk shaped as the swatch and engine chunks are: one colour function. */
const CHUNK = 'uniform vec3 material_diffuse;\nvoid getAlbedo() {\n\tdAlbedo = material_diffuse.rgb;\n}\n';
const PATTERNS = readSurfacePatterns(readFileSync('../assets/catalogs/world-kinds/surface-pattern.v1.json', 'utf8'));
const engineChunk = (path: string): string => {
  const source = readFileSync(`packages/atlas-react/node_modules/playcanvas/build/playcanvas/src/scene/shader-lib/glsl/chunks/standard/frag/${path}`, 'utf8');
  return source.slice(source.indexOf('`') + 1, source.lastIndexOf('`'));
};

describe('the facade set into a wall\'s chunks', () => {
  it('renames the colour function and calls it first, leaving one colour function, and is set once', () => {
    const wall = withFacadeColour(CHUNK);
    expect(count(wall, 'void getAlbedo() {')).toBe(1);
    expect(count(wall, 'void exuFacadeBase() {')).toBe(1);
    expect(wall.indexOf('exuFacadeBase();')).toBeGreaterThan(wall.indexOf('void getAlbedo() {'));
    expect(wall).toContain('dAlbedo = material_diffuse.rgb;');
    expect(withFacadeColour(wall)).toBe(wall);
  });

  it('composes with a pattern and with the ground finish in either order, ending with one colour function', () => {
    const pattern = patternChunks(PATTERNS.byMaterial.get('brick')!, null).glsl;
    const orders = [
      withFacadeColour(pattern),
      withFinish(withFacadeColour(pattern), 'ground'),
      withFacadeColour(withFinish(pattern, 'ground')),
      withFinish(pattern, 'ground'),
    ];
    for (const chunk of orders) expect(count(chunk, 'void getAlbedo() {')).toBe(1);
    for (const chunk of orders.slice(0, 3)) expect(count(chunk, 'exuFacadeBase();')).toBe(1);
    for (const chunk of orders.slice(1)) expect(count(chunk, 'exuFinishBase();')).toBe(1);
  });

  it('adds the lit windows after the engine\'s own emission, and the glass gloss after its own gloss', () => {
    const emission = withFacadeEmission(engineChunk('emissive.js'));
    expect(count(emission, 'void getEmission() {')).toBe(1);
    expect(count(emission, 'void exuFacadeEmissionBase() {')).toBe(1);
    expect(emission).toContain('dEmission += exuFacadeLit;');
    expect(withFacadeEmission(emission)).toBe(emission);
    const gloss = withFacadeGloss(engineChunk('gloss.js'));
    expect(count(gloss, 'void getGlossiness() {')).toBe(1);
    expect(count(gloss, 'void exuFacadeGlossBase() {')).toBe(1);
    expect(withFacadeGloss(gloss)).toBe(gloss);
  });

  it('refuses chunks with no one function of the name, as a finish set into nothing would draw none', () => {
    expect(() => withFacadeColour('void getEmission() {}')).toThrow(/no one colour function/);
    expect(() => withFacadeEmission('void getAlbedo() {}')).toThrow(/no one emission function/);
    expect(() => withFacadeGloss('void getAlbedo() {}')).toThrow(/no one gloss function/);
  });

  it('draws rooms behind lit windows only where the material is made with them, and only on WebGL2', () => {
    expect(withFacadeColour(CHUNK)).toContain('#ifdef EXU_FACADE_ROOMS');
    expect(facadeRuns({ isWebGPU: false } as never)).toBe(true);
    expect(facadeRuns({ isWebGPU: true } as never)).toBe(false);
  });
});

const at = (identity: string, family: string, structure: string | undefined, positionMm: number[], yawQuarterTurns: number, boxMm: number[], storeyHeightMm?: number): FacadeSlot =>
  ({ identity, family, ...(structure === undefined ? {} : { structure }), positionMm, yawQuarterTurns, boxMm, ...(storeyHeightMm === undefined ? {} : { storeyHeightMm }) });

describe('the walls that are a building\'s facades', () => {
  /**
   * Two rooms of a house of three 3 m storeys laid as the site layout lays them (outer walls 200 mm
   * thick on the inside of the building's edges, a 100 mm wall between the rooms, a lintel over the
   * door), a shop facing east against its east wall, a garden wall, and a wall whose building has no slot.
   */
  const street = (riseMm = 0): FacadeSlot[] => [
    at('house', 'structure', undefined, [5000, 3000, riseMm], 2, [10_000, 6000, 9000], 3000),
    at('house-front:wall:0', 'wall', 'house', [2250, 100, riseMm], 2, [4500, 200, 9000]),
    at('house-front:lintel:0', 'wall', 'house', [5000, 100, riseMm + 2100], 2, [1000, 200, 6900]),
    at('house-front:wall:1', 'wall', 'house', [7750, 100, riseMm], 2, [4500, 200, 9000]),
    at('house-back:wall:0', 'wall', 'house', [5000, 5900, riseMm], 0, [10_000, 200, 9000]),
    at('house-low:wall:0', 'wall', 'house', [100, 3000, riseMm], 1, [6000, 200, 9000]),
    at('house-high:wall:0', 'wall', 'house', [9900, 3000, riseMm], 1, [6000, 200, 9000]),
    at('house-rooms:wall:0', 'wall', 'house', [4000, 3000, riseMm], 1, [5600, 100, 9000]),
    at('house-room:floor', 'ground', 'house', [5000, 3000, riseMm], 0, [9600, 5600, 0]),
    at('shop', 'structure', undefined, [12_000, 3000, riseMm], 3, [6000, 4000, 3600]),
    at('shop-front:wall:0', 'wall', 'shop', [13_900, 3000, riseMm], 3, [6000, 200, 3600]),
    at('garden:wall:0', 'wall', undefined, [5000, -2000, riseMm], 0, [10_000, 200, 1200]),
    at('barn-front:wall:0', 'wall', 'barn', [20_000, 100, riseMm], 0, [4000, 200, 3600]),
  ];
  const FRONTS = {
    'house-front:wall:0': [0, -1], 'house-front:lintel:0': [0, -1], 'house-front:wall:1': [0, -1], 'house-back:wall:0': [0, 1], 'house-low:wall:0': [-1, 0],
    'shop-front:wall:0': [1, 0],
  };
  const outOf = (slots: FacadeSlot[]) => Object.fromEntries([...facadeFronts(slots)].map(([identity, front]) => [identity, front.out]));

  it('are the walls on a building\'s edge, each facing out of it, a lintel among them: never between its rooms, against its neighbour, or of no building', () => {
    expect(outOf(street())).toEqual(FRONTS);
    const low = facadeFronts(street()).get('house-low:wall:0')!;
    // Each states its building (its rectangle, base, height and storeys), its own thickness, and its own foot and top.
    expect({ ...low, building: { ...low.building, salt: 0 } }).toEqual({
      out: [-1, 0], building: { rect: { x: 5000, y: 3000, hx: 5000, hy: 3000 }, baseMm: 0, heightMm: 9000, salt: 0, storeyMm: 3000 }, thicknessMm: 200, footMm: 0, topMm: 9000,
    });
    expect(facadeFronts(street()).get('house-front:lintel:0')).toMatchObject({ footMm: 2100, topMm: 9000 });
    expect(facadeFronts(street()).get('shop-front:wall:0')!.building.rect).toEqual({ x: 12_000, y: 3000, hx: 2000, hy: 3000 });
    // A building the drawing gives no storey height states none: the rule's is used.
    expect('storeyMm' in facadeFronts(street()).get('shop-front:wall:0')!.building).toBe(false);
    // Neighbouring buildings light different rooms.
    expect(low.building.salt).not.toBe(facadeFronts(street()).get('shop-front:wall:0')!.building.salt);
  });

  it('are the same on land, where a building and its walls stand on graded ground', () => {
    expect(outOf(street(1500))).toEqual(FRONTS);
  });
});

/** A null device an app has started, with the engine's chunks. */
function nullApp(): pc.AppBase {
  const canvas = document.createElement('canvas');
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = new pc.NullGraphicsDevice(canvas);
  options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem, pc.LightComponentSystem];
  app.init(options);
  return app;
}

/** A material and an instance standing at the world's origin, as the site's root does. */
function standing() {
  const device = nullApp().graphicsDevice;
  const material = new pc.StandardMaterial();
  const instance = new pc.MeshInstance(new pc.Mesh(device), material, new pc.GraphNode());
  return { device, material, instance, root: new pc.GraphNode('root') };
}
const said = (instance: pc.MeshInstance, name: string): number[] | null => {
  const stated = instance.getParameter(name) as { data: ArrayLike<number> } | undefined;
  return stated === undefined ? null : [...Array.from(stated.data)].map((value) => Math.round(value * 1e4) / 1e4 + 0);
};

describe('a facade wall\'s own instance', () => {
  const house = at('house', 'structure', undefined, [5000, 3000, 500], 0, [10_000, 6000, 9000], 3000);
  const front = facadeFronts([house, at('house-back:wall:0', 'wall', 'house', [5000, 5900, 500], 0, [10_000, 200, 9000])]).get('house-back:wall:0')!;

  it('states its building in the world (north is -z), its storeys by the drawing, its own height, and its rule\'s figures lit at the share given', () => {
    const { instance, root } = standing();
    expect(setFacadeWall(instance, root, front, RULE, 0.3)).toBe(true);
    expect(said(instance, 'exuFacadeFrame')).toEqual([5, -3, 5, 3]);
    expect(said(instance, 'exuFacadeFloor')).toEqual([0.5, 3, 3, 0.2]);
    expect(said(instance, 'exuFacadePiece')!.slice(0, 2)).toEqual([0.5, 9.5]);
    expect(said(instance, 'exuFacadePiece')![3]).toBe(RULE.room_bays);
    expect(said(instance, 'exuFacadeWindow')).toEqual([RULE.bay_mm / 1000, RULE.window_mm[0] / 1000, RULE.window_mm[1] / 1000, RULE.sill_mm / 1000]);
    expect(said(instance, 'exuFacadeTrim')).toEqual([RULE.head_mm / 1000, RULE.clear_storeys, RULE.reveal_mm / 1000, RULE.reveal_shade_permille / 1000]);
    expect(said(instance, 'exuFacadeLight')).toEqual([0.3, RULE.light_permille / 1000, RULE.warm_permille / 1000, RULE.room_depth_mm / 1000]);
    expect(said(instance, 'exuFacadeWarm')).toEqual(linearRgb(RULE.warm).map((value) => Math.round(value * 1e4) / 1e4));
  });

  it('divides each of the drawing\'s storeys into the whole number of rows nearest the rule\'s storey height', () => {
    const tall = at('tower', 'structure', undefined, [0, 0, 0], 0, [8000, 4000, 36_000], 6000);
    const wall = facadeFronts([tall, at('tower:wall:0', 'wall', 'tower', [0, 1900, 0], 0, [8000, 200, 36_000])]).get('tower:wall:0')!;
    const { instance, root } = standing();
    setFacadeWall(instance, root, wall, { ...RULE, storey_mm: 3200 }, 0);
    // Two rows of 3 m in each 6 m storey: rows meet the storeys and the top.
    expect(said(instance, 'exuFacadeFloor')!.slice(1, 3)).toEqual([3, 12]);
    setFacadeWall(instance, root, wall, { ...RULE, storey_mm: 6500 }, 0);
    expect(said(instance, 'exuFacadeFloor')!.slice(1, 3)).toEqual([6, 6]);
  });

  it('divides a building the drawing gives no storey height into the whole number of rows nearest the rule\'s', () => {
    const shed = at('shed', 'structure', undefined, [0, 0, 0], 0, [8000, 4000, 7000]);
    const wall = facadeFronts([shed, at('shed:wall:0', 'wall', 'shed', [0, 1900, 0], 0, [8000, 200, 7000])]).get('shed:wall:0')!;
    const { instance, root } = standing();
    setFacadeWall(instance, root, wall, { ...RULE, storey_mm: 3200 }, 0);
    expect(said(instance, 'exuFacadeFloor')!.slice(1, 3)).toEqual([3.5, 2]);
  });

  it('states nothing for a building of no height, and forgets everything when the facade is taken off', () => {
    const low = at('kiosk', 'structure', undefined, [0, 0, 0], 0, [4000, 4000, 0]);
    const wall = facadeFronts([low, at('kiosk:wall:0', 'wall', 'kiosk', [0, 1900, 0], 0, [4000, 200, 2400])]).get('kiosk:wall:0')!;
    const { instance, root } = standing();
    expect(setFacadeWall(instance, root, wall, RULE, 0)).toBe(false);
    expect(said(instance, 'exuFacadeFrame')).toBeNull();
    setFacadeWall(instance, root, front, RULE, 0);
    clearFacadeWall(instance);
    for (const name of ['exuFacadeFrame', 'exuFacadeFloor', 'exuFacadePiece', 'exuFacadeWindow', 'exuFacadeTrim', 'exuFacadeSurface', 'exuFacadeLight', 'exuFacadeFade', 'exuFacadeWarm', 'exuFacadeCool', 'exuFacadeDim']) {
      expect([name, said(instance, name)]).toEqual([name, null]);
    }
  });

  it('is worn by an opaque material only, so glazing never draws windows over itself', () => {
    const { material } = standing();
    expect(facadeWears(material)).toBe(true);
    material.blendType = pc.BLEND_NORMAL;
    expect(facadeWears(material)).toBe(false);
    expect(facadeWears(new pc.ShaderMaterial())).toBe(false);
  });

  it('draws nothing on a material until a wall states its building: every figure is zero there', () => {
    const { device, material } = standing();
    applyFacadeFinish(device, material);
    expect(facadeApplied(material)).toBe(true);
    expect((material.getParameter('exuFacadeFloor') as { data: number[] }).data).toEqual([0, 0, 0, 0]);
    expect(material.defines.get('EXU_FACADE_ROOMS')).toBe(true);
  });
});

/**
 * A terrace: a house of three storeys whose front walls wear the pack's default wall, with a wall
 * between its two rooms and a lintel over its door, whose side wall's look the pack states nothing
 * for and draws as its default wall, and whose back wall wears the pack's brick, for which it states
 * no facade; and a garden wall of no building in the default wall's look.
 */
function terrace() {
  const box = (identity: string, lookRole: string, positionMm: number[], yawQuarterTurns: number, boxMm: number[], structure?: string) =>
    ({ identity, part: identity, label: identity, lookRole, positionMm, yawQuarterTurns, boxMm, front: '+y', fit: 'surface', primitive: 'box', ...(structure === undefined ? {} : { structure }) });
  return parseStructuredSiteDrawing({
    profile: 'exulanica.site-drawing/v1', world_id: 'world-terrace', receipt_sha256: 'a'.repeat(64),
    kind: { kind: 'fixture_terrace', version: 1, label: 'Terrace' },
    extent: { widthMm: 20_000, depthMm: 20_000, enclosure: 'open' },
    arrival: { positionMm: [10_000, 2000, 0], facingMm: [0, 1] },
    slots: [
      { identity: 'ground', part: 'ground', label: 'ground', lookRole: 'ground.lawn', positionMm: [10_000, 10_000, 0], yawQuarterTurns: 0, boxMm: [20_000, 20_000, 0], front: '+y', fit: 'surface', primitive: 'plane' },
      { identity: 'house', part: 'house', label: 'house', lookRole: 'structure.house', positionMm: [10_000, 10_000, 0], yawQuarterTurns: 0, boxMm: [10_000, 6000, 9000], front: '+y', fit: 'contain', primitive: 'none', storeyHeightMm: 3000 },
      box('house-front:wall:0', 'wall.default', [7250, 7100, 0], 0, [4500, 200, 9000], 'house'),
      box('house-front:lintel:0', 'wall.default', [10_000, 7100, 2100], 0, [1000, 200, 6900], 'house'),
      box('house-front:wall:1', 'wall.default', [12_750, 7100, 0], 0, [4500, 200, 9000], 'house'),
      box('house-back:wall:0', 'wall.brick_running_bond', [10_000, 12_900, 0], 0, [10_000, 200, 9000], 'house'),
      box('house-side:wall:0', 'wall.stucco', [5100, 10_000, 0], 1, [6000, 200, 9000], 'house'),
      box('house-rooms:wall:0', 'wall.default', [9000, 10_000, 0], 1, [5600, 100, 9000], 'house'),
      box('garden:wall:0', 'wall.default', [10_000, 2000, 0], 0, [10_000, 200, 1200]),
    ],
    walk: { floorMm: [0, 0, 20_000, 20_000], blockersMm: [], keepOutMm: [] },
    seats: [],
  });
}
const FACADES = ['house-front:wall:0', 'house-front:lintel:0', 'house-front:wall:1', 'house-side:wall:0'];
const OTHERS = ['ground', 'house-back:wall:0', 'house-rooms:wall:0', 'garden:wall:0'];

/** Dress the terrace in `manifest` on a null device: what each slot wears and states, what the canvas says, and what is left after. */
function dressed(manifest: StylePackManifest) {
  const pack = packOf(manifest);
  const preset = manifest.light!.presets[manifest.light!.default_preset]!;
  const look = renderLookOfPreset(preset, manifest.shading!, manifest.edge, 1, manifest.water);
  const summaries: SiteDressingSummary[] = [];
  const dresser = packSiteDresser({ pack, families, pieces: { pieces: new Map(), pictures: new Map() }, shading: { model: 'pbr', toon: null, ink: null }, look, told: (summary) => summaries.push(summary) });
  const app = nullApp();
  const canvas = app.graphicsDevice.canvas as HTMLCanvasElement;
  const camera = new pc.Entity('camera');
  camera.addComponent('camera');
  app.root.addChild(camera);
  const environmentRoot = new pc.Entity('environment');
  app.root.addChild(environmentRoot);
  let during: { worn: Record<string, pc.Material>; lit: Record<string, number | null>; canvas: string | undefined } | null = null;
  let after: { lit: (number | null)[]; canvas: string | undefined } | null = null;
  siteMount(terrace(), {
    servedBytes: 1,
    dress: (host, drawn, dressing) => {
      const undress = dresser(host, drawn, dressing);
      const instance = (identity: string) => (drawn.root.findByName(`${identity}:shape`) as pc.Entity).render!.meshInstances[0]!;
      const lit = (identity: string) => said(instance(identity), 'exuFacadeLight')?.[0] ?? null;
      during = {
        worn: Object.fromEntries([...FACADES, ...OTHERS].map((identity) => [identity, instance(identity).material])),
        lit: Object.fromEntries([...FACADES, ...OTHERS].map((identity) => [identity, lit(identity)])),
        canvas: canvas.dataset['siteFacade'],
      };
      return () => {
        undress();
        after = { lit: FACADES.map(lit), canvas: canvas.dataset['siteFacade'] };
      };
    },
  }).attach({ app, camera, environmentRoot }).dispose();
  return { summary: summaries[0]!, during: during!, after: after!, look };
}

describe('a made place dressed in a pack with a facade', () => {
  it('draws windows on every wall facing out of a building in a look its facade names, a lintel among them, and on no other wall or ground', () => {
    const { summary, during, look } = dressed(WALLS);
    const share = litShareOf(RULE, look.sun.elevationDeg);
    for (const identity of FACADES) expect([identity, during.lit[identity]]).toEqual([identity, Math.round(share * 1e4) / 1e4]);
    for (const identity of OTHERS) expect([identity, during.lit[identity]]).toEqual([identity, null]);
    // Materials stay shared: the garden wall wears the house's material and draws its plain colour, stating no building.
    expect(during.worn['garden:wall:0']).toBe(during.worn['house-front:wall:0']);
    expect(during.worn['house-rooms:wall:0']).toBe(during.worn['house-front:wall:0']);
    for (const identity of FACADES) expect([identity, facadeApplied(during.worn[identity]!)]).toEqual([identity, true]);
    expect(facadeApplied(during.worn['ground']!)).toBe(false);
    // The brick wall is drawn in its own surface, for which the pack states no facade: it takes no other look's.
    expect(facadeApplied(during.worn['house-back:wall:0']!)).toBe(false);
    // The side wall takes the rule of the default wall it is drawn as.
    expect(summary.facade).toEqual({ walls: 4, materials: 1 });
    expect(JSON.parse(during.canvas!)).toEqual({ walls: 4, materials: 1 });
  });

  it('lights its windows by the light\'s own share where the light states one', () => {
    const { during } = dressed(NIGHT);
    for (const identity of FACADES) expect([identity, during.lit[identity]]).toEqual([identity, 0.65]);
  });

  it('takes everything back with the dressing, and draws nothing in a pack that states no facade', () => {
    const { after } = dressed(WALLS);
    expect(after).toEqual({ lit: FACADES.map(() => null), canvas: undefined });
    const plain = dressed(PLAIN);
    expect('facade' in plain.summary).toBe(false);
    expect(plain.during.canvas).toBeUndefined();
    for (const identity of FACADES) expect([identity, facadeApplied(plain.during.worn[identity]!), plain.during.lit[identity]]).toEqual([identity, false, null]);
  });
});
