// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { readStylePackManifest, resolveStylePack, type LookFamily, type StylePackManifest } from '@exulanica/atlas-core';
import { PACK_ENGINE, dressTownSurfaces, renderLookOfPreset, swatchMaterial, type TownLookRoles } from '../src/playcanvas/style-pack/index.js';

// Relative to web/, where the suite runs.
const CASES = JSON.parse(readFileSync('../assets/style-packs/manifest-cases.v1.json', 'utf8'));
const ROLES = JSON.parse(readFileSync('../assets/style-packs/town-look-roles.v1.json', 'utf8')) as TownLookRoles;
/** The committed sRGB-to-linear table, a different source from the conversion under test. */
const TABLE = JSON.parse(readFileSync('../assets/colour/srgb8-linear16.v1.json', 'utf8')).values as number[];
const families = new Map<string, LookFamily>(Object.entries(CASES.context.families as Record<string, { fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }>)
  .map(([key, value]) => [key, { fit: value.fit, dressing: value.dressing, fillMinimumPermille: value.fill_minimum_permille, fillMaximumPermille: value.fill_maximum_permille }]));
const root: StylePackManifest = readStylePackManifest(
  CASES.cases.find((c: { name: string }) => c.name === 'a complete pack with no base').manifest,
  { families, textureSets: new Set(CASES.context.texture_sets) },
);

describe('a pack preset as a render look', () => {
  const preset = root.light!.presets['day']!;
  const look = renderLookOfPreset(preset, root.shading!, root.edge);

  it('divides the stated units out', () => {
    expect(look.exposure).toBe(0.92);
    expect(look.fog).toMatchObject({ kind: 'exp2', density: 0.0003 });
    expect(look.sun.elevationDeg).toBe(50);
    expect(look.sun.azimuthDeg).toBe(150);
    expect(look.sun.intensity).toBe(2.1);
    expect(look.sky.clouds).toMatchObject({ cover: 0.42, scale: 1.2, seed: 3 });
    expect(look.shading).toMatchObject({ model: 'toon', toon: { shadowEdge: 0.11, lightEdge: 0.57, bandShare: 0.72, softness: 0.06 } });
    expect(look.edge).toMatchObject({ dropM: 0.6, reachM: 3000 });
  });

  it('turns every sRGB byte into linear light as the committed table does', () => {
    const near = (value: number, byte: number) => expect(Math.abs(value * 65535 - TABLE[byte]!)).toBeLessThanOrEqual(0.5);
    preset.sky.zenith.forEach((byte, i) => near(look.sky.zenith[i]!, byte));
    preset.sun.colour.forEach((byte, i) => near(look.sun.colour[i]!, byte));
    root.shading!.ink!.forEach((byte, i) => near(look.shading.ink![i]!, byte));
  });

  it('keeps what a pack does not choose the engine\'s', () => {
    expect(look.sun.shadow).toMatchObject({ resolution: PACK_ENGINE.shadowResolution, cascades: PACK_ENGINE.cascades, distanceM: PACK_ENGINE.shadowDistanceM, filter: 'pcf1', penumbra: 0 });
    expect(look.environment).toEqual({ intensity: 0.85, atlasSize: PACK_ENGINE.atlasSize, sourceSize: PACK_ENGINE.sourceSize });
  });
});

describe('palette materials', () => {
  const [brick, cream, roof] = root.palette.swatches;
  it('draw a swatch\'s colour, roughness and metalness in the look\'s shading', () => {
    const material = swatchMaterial(brick!, null, { model: 'toon', toon: { shadowEdge: 0.1, lightEdge: 0.6, bandShare: 0.7, softness: 0.04 }, ink: null }, 'brick');
    expect([material.diffuse.r, material.diffuse.g, material.diffuse.b]).toEqual([216 / 255, 105 / 255, 75 / 255]);
    expect(material.gloss).toBeCloseTo(0.15, 12);
    expect(material.metalness).toBe(0);
    expect(material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).has('lightDiffuseLambertPS')).toBe(true);
    expect(material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).has('diffusePS')).toBe(false);
  });
  it('colour upward faces with an up swatch, in both shader languages', () => {
    const material = swatchMaterial(cream!, roof!, { model: 'pbr', toon: null, ink: null }, 'cream');
    for (const language of [pc.SHADERLANGUAGE_GLSL, pc.SHADERLANGUAGE_WGSL]) {
      expect(material.getShaderChunks(language).get('diffusePS')).toContain('normalize(vNormalW).y');
    }
    expect(material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).has('lightDiffuseLambertPS')).toBe(false);
  });
});

describe('a town\'s surfaces dressed from a pack', () => {
  function tileEntity(app: pc.AppBase, setId: string): { entity: pc.Entity; original: pc.StandardMaterial } {
    const original = new pc.StandardMaterial();
    original.name = `generated-tile:${setId}`;
    const entity = new pc.Entity(`generated-tile:${setId}`);
    entity.addComponent('render', { meshInstances: [new pc.MeshInstance(pc.Mesh.fromGeometry(app.graphicsDevice, new pc.BoxGeometry()), original)] });
    return { entity, original };
  }

  it('replaces the sets the pack dresses, by leaf then family default, and puts every material back', () => {
    const canvas = document.createElement('canvas');
    const app = new pc.AppBase(canvas);
    const options = new pc.AppOptions();
    options.graphicsDevice = new pc.NullGraphicsDevice(canvas);
    options.componentSystems = [pc.RenderComponentSystem];
    app.init(options);
    const tiles = new pc.Entity('generated-tile:t');
    app.root.addChild(tiles);
    const made = Object.fromEntries(['cc0.brick-running-bond', 'cc0.cast-concrete', 'cc0.footway-paving', 'cc0.sign-panel'].map((setId) => {
      const one = tileEntity(app, setId);
      tiles.addChild(one.entity);
      return [setId, one];
    }));
    const pack = resolveStylePack([root]);
    const dressing = dressTownSurfaces(tiles, pack, ROLES, families, { model: 'pbr', toon: null, ink: null });
    const drawn = (setId: string) => (made[setId]!.entity.render!.meshInstances[0]!.material as pc.StandardMaterial);
    // Brick names its leaf: the brick swatch, with the roof swatch above.
    expect(drawn('cc0.brick-running-bond').name).toBe('style-pack:wall.brick_running_bond');
    expect(drawn('cc0.brick-running-bond').getShaderChunks(pc.SHADERLANGUAGE_GLSL).has('diffusePS')).toBe(true);
    // Concrete's leaf is not dressed: the wall family's default, cream.
    expect(drawn('cc0.cast-concrete').name).toBe('style-pack:wall.default');
    expect(drawn('cc0.cast-concrete').diffuse.r).toBeCloseTo(243 / 255, 12);
    // The pack dresses path.footway, not path.footway_paving, and no path default: the tile's own.
    expect(drawn('cc0.footway-paving')).toBe(made['cc0.footway-paving']!.original);
    // A set the roles do not name keeps its own material.
    expect(drawn('cc0.sign-panel')).toBe(made['cc0.sign-panel']!.original);
    expect(dressing.dressed.map((d) => [d.setId, d.role, d.by]).sort()).toEqual([
      ['cc0.brick-running-bond', 'wall.brick_running_bond', 'swatch'],
      ['cc0.cast-concrete', 'wall.default', 'swatch'],
    ]);
    dressing.dispose();
    for (const setId of Object.keys(made)) expect(drawn(setId)).toBe(made[setId]!.original);
  });
});
