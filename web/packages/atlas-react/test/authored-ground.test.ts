// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import * as pc from 'playcanvas';
import { buildNavigationWorld, makeScene } from '@exulanica/atlas-core';
import { ORIGIN_LANDSCAPE, SURVEY_RELIEF, unitRgb, worldSilhouetteTone } from '@exulanica/presentation';
import { authoredGroundGeometry, createWorldField } from '../src/playcanvas/world-field.js';

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

  it('refuses support that cannot describe a finite positive rectangle', () => {
    expect(() => authoredGroundGeometry({ halfWidth: 0, halfDepth: 8, elevation: 0 }))
      .toThrow('finite positive extents');
    expect(() => authoredGroundGeometry({ halfWidth: 12, halfDepth: Number.NaN, elevation: 0 }))
      .toThrow('finite positive extents');
  });

  it('receives shadows and follows saved or previewed world appearance', () => {
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
    expect(instances).toHaveLength(2);
    expect(instances.every((instance) => instance.receiveShadow)).toBe(true);
    field.setProfile(SURVEY_RELIEF);
    const surface = instances[0]!.material as pc.StandardMaterial;
    const boundary = instances[1]!.material as pc.StandardMaterial;
    expect([surface.diffuse.r, surface.diffuse.g, surface.diffuse.b])
      .toEqual(unitRgb(SURVEY_RELIEF.palette.terrain));
    expect([boundary.diffuse.r, boundary.diffuse.g, boundary.diffuse.b])
      .toEqual(unitRgb(worldSilhouetteTone(SURVEY_RELIEF.palette)));

    const surfaceDestroy = vi.spyOn(surface, 'destroy');
    const boundaryDestroy = vi.spyOn(boundary, 'destroy');
    field.destroy();
    expect(surfaceDestroy).toHaveBeenCalledOnce();
    expect(boundaryDestroy).toHaveBeenCalledOnce();
    app.destroy();
  });
});
