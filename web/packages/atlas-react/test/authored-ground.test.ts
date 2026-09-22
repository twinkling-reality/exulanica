// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import * as pc from 'playcanvas';
import { buildNavigationWorld, makeScene } from '@exulanica/atlas-core';
import { ORIGIN_LANDSCAPE, SURVEY_RELIEF, unitRgb, worldSilhouetteTone, DAWN_THEME } from '@exulanica/presentation';
import { atlasVec3 } from '@exulanica/atlas-core';
import {
  AUTHORED_GROUND_SCALE_SPACING_M,
  authoredGroundGeometry,
  authoredGroundScaleCue,
  createWorldField,
  endlessAuthoredGroundSurface,
} from '../src/playcanvas/world-field.js';

describe('authored ground geometry', () => {
  it('ends at the descriptor bounds and keeps the walking face at its elevation', () => {
    const ground = authoredGroundGeometry({
      halfWidth: 12,
      halfDepth: 8,
      elevation: 1.25,
    });

    const triples = (positions: readonly number[]): readonly (readonly number[])[] =>
      Array.from({ length: positions.length / 3 }, (_, index) => positions.slice(index * 3, index * 3 + 3));
    const surface = triples(ground.surface.positions);
    const boundary = triples(ground.boundary.positions);
    const all = [...surface, ...boundary];

    expect(surface).toEqual([
      [-11.68, 1.25, -7.68],
      [11.68, 1.25, -7.68],
      [11.68, 1.25, 7.68],
      [-11.68, 1.25, 7.68],
    ]);
    expect(Math.min(...all.map(([x]) => x!))).toBe(-12);
    expect(Math.max(...all.map(([x]) => x!))).toBe(12);
    expect(Math.min(...all.map(([, , z]) => z!))).toBe(-8);
    expect(Math.max(...all.map(([, , z]) => z!))).toBe(8);
    expect(Math.max(...boundary.map(([, y]) => y!))).toBe(1.25);
    expect(Math.min(...boundary.map(([, y]) => y!))).toBeLessThan(1.25);

    const horizontalArea = (data: typeof ground.surface): number => {
      let area = 0;
      for (let index = 0; index < data.indices.length; index += 3) {
        const vertices = data.indices.slice(index, index + 3).map((vertex) =>
          data.positions.slice(vertex * 3, vertex * 3 + 3));
        if (!vertices.every(([, y]) => y === 1.25)) continue;
        const [a, b, c] = vertices;
        area += Math.abs(
          (b![0]! - a![0]!) * (c![2]! - a![2]!) -
          (b![2]! - a![2]!) * (c![0]! - a![0]!),
        ) / 2;
      }
      return area;
    };
    expect(horizontalArea(ground.surface) + horizontalArea(ground.boundary)).toBeCloseTo(24 * 16);
  });

  it('lays metre marks and origin axes inside the walking face', () => {
    expect(AUTHORED_GROUND_SCALE_SPACING_M).toBe(1);
    const cue = authoredGroundScaleCue({
      halfWidth: 12,
      halfDepth: 8,
      elevation: 1.25,
    });
    const triples = Array.from(
      { length: cue.positions.length / 3 },
      (_, index) => cue.positions.slice(index * 3, index * 3 + 3),
    );
    expect(cue.indices.length).toBeGreaterThan(0);
    expect(Math.min(...triples.map(([x]) => x!))).toBeGreaterThanOrEqual(-11.68);
    expect(Math.max(...triples.map(([x]) => x!))).toBeLessThanOrEqual(11.68);
    expect(Math.min(...triples.map(([, , z]) => z!))).toBeGreaterThanOrEqual(-7.68);
    expect(Math.max(...triples.map(([, , z]) => z!))).toBeLessThanOrEqual(7.68);
    expect(new Set(triples.map(([, y]) => y!))).toEqual(new Set([1.258]));

    // Every mark centre sits on an integer metre of the authored spacing.
    const centresX = new Set<number>();
    for (let index = 0; index < cue.indices.length; index += 6) {
      const verts = cue.indices.slice(index, index + 4).map((vertex) =>
        cue.positions.slice(vertex * 3, vertex * 3 + 3));
      const xs = verts.map(([x]) => x!);
      const zs = verts.map(([, , z]) => z!);
      const spanX = Math.max(...xs) - Math.min(...xs);
      const spanZ = Math.max(...zs) - Math.min(...zs);
      if (spanZ > spanX) centresX.add(Number(((Math.min(...xs) + Math.max(...xs)) / 2).toFixed(6)));
    }
    expect([...centresX].every((x) => Number.isInteger(x / AUTHORED_GROUND_SCALE_SPACING_M))).toBe(true);
    expect(centresX.has(0)).toBe(true);
  });

  it('refuses support that cannot describe a finite positive rectangle', () => {
    expect(() => authoredGroundGeometry({ halfWidth: 0, halfDepth: 8, elevation: 0 }))
      .toThrow('finite positive extents');
    expect(() => authoredGroundGeometry({ halfWidth: 12, halfDepth: Number.NaN, elevation: 0 }))
      .toThrow('finite positive extents');
  });

  it('receives shadows, draws the scale cue, and follows saved or previewed world appearance', () => {
    const canvas = document.createElement('canvas');
    const device = new pc.NullGraphicsDevice(canvas);
    const app = new pc.AppBase(canvas);
    const options = new pc.AppOptions();
    options.graphicsDevice = device;
    options.componentSystems = [pc.RenderComponentSystem];
    app.init(options);
    const world = buildNavigationWorld(makeScene([], 1, 1));
    const field = createWorldField(
      device,
      world,
      ORIGIN_LANDSCAPE,
      undefined,
      false,
      { halfWidth: 12, halfDepth: 8, elevation: 1.25 },
    );
    app.root.addChild(field.entity);

    const instances = field.entity.render!.meshInstances;
    expect(instances).toHaveLength(3);
    expect(instances[0]!.receiveShadow).toBe(true);
    expect(instances[1]!.receiveShadow).toBe(true);
    expect(instances[2]!.receiveShadow).toBe(false);
    field.setProfile(SURVEY_RELIEF);
    const surface = instances[0]!.material as pc.StandardMaterial;
    const boundary = instances[1]!.material as pc.StandardMaterial;
    const scaleCue = instances[2]!.material as pc.StandardMaterial;
    expect([surface.diffuse.r, surface.diffuse.g, surface.diffuse.b])
      .toEqual(unitRgb(SURVEY_RELIEF.palette.terrain));
    expect([boundary.diffuse.r, boundary.diffuse.g, boundary.diffuse.b])
      .toEqual(unitRgb(worldSilhouetteTone(SURVEY_RELIEF.palette)));
    expect([scaleCue.diffuse.r, scaleCue.diffuse.g, scaleCue.diffuse.b])
      .toEqual(unitRgb(worldSilhouetteTone(SURVEY_RELIEF.palette)));
    expect(surface.useLighting).toBe(true);
    expect(boundary.useLighting).toBe(true);
    expect(scaleCue.useLighting).toBe(false);
    expect(surface.emissiveIntensity).toBeLessThan(boundary.emissiveIntensity);
    expect(scaleCue.emissiveIntensity).toBeGreaterThan(surface.emissiveIntensity);

    const surfaceDestroy = vi.spyOn(surface, 'destroy');
    const boundaryDestroy = vi.spyOn(boundary, 'destroy');
    const scaleCueDestroy = vi.spyOn(scaleCue, 'destroy');
    field.destroy();
    expect(surfaceDestroy).toHaveBeenCalledOnce();
    expect(boundaryDestroy).toHaveBeenCalledOnce();
    expect(scaleCueDestroy).toHaveBeenCalledOnce();
    app.destroy();
  });

  it('shows a placement landing mark distinct from the Map pose marker', () => {
    const canvas = document.createElement('canvas');
    const device = new pc.NullGraphicsDevice(canvas);
    const app = new pc.AppBase(canvas);
    const options = new pc.AppOptions();
    options.graphicsDevice = device;
    options.componentSystems = [pc.RenderComponentSystem];
    app.init(options);
    const world = buildNavigationWorld(makeScene([], 1, 1));
    const field = createWorldField(
      device,
      world,
      ORIGIN_LANDSCAPE,
      DAWN_THEME,
      false,
      { halfWidth: 12, halfDepth: 8, elevation: 1.25 },
    );
    app.root.addChild(field.entity);

    const map = field.entity.findByName('atlas-map-user-marker') as pc.Entity;
    const landing = field.entity.findByName('atlas-placement-landing-marker') as pc.Entity;
    expect(map).not.toBeNull();
    expect(landing).not.toBeNull();
    expect(map.enabled).toBe(false);
    expect(landing.enabled).toBe(false);

    field.setMapGroundPose({
      position: atlasVec3(1, 1.25, 2),
      yaw: 0,
      pitch: 0,
    });
    field.setPlacementLandingPose({
      position: atlasVec3(-2, 1.25, -3),
      yaw: Math.PI / 2,
      pitch: 0,
    });
    expect(map.enabled).toBe(true);
    expect(landing.enabled).toBe(true);
    expect(landing.getPosition().x).toBeCloseTo(-2, 5);
    expect(landing.getPosition().z).toBeCloseTo(-3, 5);
    expect(landing.getEulerAngles().y).toBeCloseTo(90, 5);

    const mapMaterial = map.render!.meshInstances[0]!.material as pc.StandardMaterial;
    const landingMaterial = landing.render!.meshInstances[0]!.material as pc.StandardMaterial;
    expect([landingMaterial.diffuse.r, landingMaterial.diffuse.g, landingMaterial.diffuse.b])
      .toEqual(unitRgb(DAWN_THEME.accent));
    expect([mapMaterial.diffuse.r, mapMaterial.diffuse.g, mapMaterial.diffuse.b])
      .toEqual(unitRgb(DAWN_THEME.focus));
    expect(landingMaterial.diffuse.r !== mapMaterial.diffuse.r
      || landingMaterial.diffuse.g !== mapMaterial.diffuse.g
      || landingMaterial.diffuse.b !== mapMaterial.diffuse.b).toBe(true);

    field.setPlacementLandingPose(null);
    expect(landing.enabled).toBe(false);
    expect(map.enabled).toBe(true);
    field.destroy();
    app.destroy();
  });
});

describe('an endless authored ground', () => {
  const build = (ground?: Parameters<typeof createWorldField>[5]) => {
    const canvas = document.createElement('canvas');
    const device = new pc.NullGraphicsDevice(canvas);
    const app = new pc.AppBase(canvas);
    const options = new pc.AppOptions();
    options.graphicsDevice = device;
    options.componentSystems = [pc.RenderComponentSystem];
    app.init(options);
    const field = createWorldField(
      device, buildNavigationWorld(makeScene([], 1, 1)), ORIGIN_LANDSCAPE, DAWN_THEME, false, ground,
    );
    app.root.addChild(field.entity);
    return { app, field };
  };

  it('is the floor objects stand on: lit, shadow-receiving, and at the authored elevation', () => {
    const { app, field } = build({ kind: 'endless', elevation: 0.4 });
    const instances = field.entity.render!.meshInstances;
    // The walking face alone. A rim, a fascia or metre marks would all be drawn from a
    // rectangle, and this ground has none to draw them from.
    expect(instances).toHaveLength(1);
    const surface = instances[0]!;
    // The shadow that separates a placed object from the floor. The landscape shader this ground
    // used to fall through to never samples a shadow map, so this flag alone proves nothing: the
    // material has to be one that does, which is the lit standard material a bounded ground uses.
    expect(surface.receiveShadow).toBe(true);
    expect(surface.material).toBeInstanceOf(pc.StandardMaterial);
    expect((surface.material as pc.StandardMaterial).useLighting).toBe(true);
    // Where objects are placed, not 35 mm under them.
    expect(field.entity.getPosition().y).toBe(0);
    const heights = new Set<number>();
    const positions: number[] = [];
    surface.mesh.getPositions(positions);
    for (let index = 1; index < positions.length; index += 3) heights.add(positions[index]!);
    // One height, stored as float32, so compared to float32 precision rather than exactly.
    expect(heights.size).toBe(1);
    expect([...heights][0]).toBeCloseTo(0.4, 6);
    app.destroy();
  });

  it('follows the saved appearance with no rim to key it on', () => {
    const { app, field } = build({ kind: 'endless', elevation: 0 });
    field.setProfile(SURVEY_RELIEF);
    const surface = field.entity.render!.meshInstances[0]!.material as pc.StandardMaterial;
    expect([surface.diffuse.r, surface.diffuse.g, surface.diffuse.b])
      .toEqual(unitRgb(SURVEY_RELIEF.palette.terrain));
    app.destroy();
  });

  it('leaves a world with no authored ground on the landscape it always had', () => {
    // The control for the two cases above: the same builder with no authored ground still takes
    // the custom landscape shader, sunk just under zero and receiving nothing.
    const { app, field } = build(undefined);
    const surface = field.entity.render!.meshInstances[0]!;
    expect(surface.material).toBeInstanceOf(pc.ShaderMaterial);
    expect(surface.receiveShadow).toBe(false);
    expect(field.entity.getPosition().y).toBeCloseTo(-0.035, 6);
    app.destroy();
  });

  it('draws past anywhere a walk can see, and refuses a reach it cannot draw', () => {
    const surface = endlessAuthoredGroundSurface(0, 40_000);
    expect(Math.max(...surface.positions.filter((_, index) => index % 3 === 0))).toBe(40_000);
    expect(() => endlessAuthoredGroundSurface(Number.NaN, 10)).toThrow('finite elevation');
    expect(() => endlessAuthoredGroundSurface(0, 0)).toThrow('positive drawn reach');
  });
});
