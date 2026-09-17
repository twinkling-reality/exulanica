import { describe, expect, it } from 'vitest';
import { CATALOG } from '../src/catalog.js';
import { SET_PROFILE_V1 } from '../src/classes.js';
import { readContainer } from '../src/container.js';
import type { TextureSetDefinition } from '../src/definition.js';
import { floorMod } from '../src/integer.js';
import { type Fields, bakeClassMaps, bakeMaps, sampleFields } from '../src/maps.js';
import {
  FIELD_NAMES,
  continuous,
  readPublished,
  rollMismatches,
  seamReports,
} from './support.js';

/**
 * Tiling, proved two ways.
 *
 * BY CONSTRUCTION. A recipe receives the unwrapped position of each texel (see `src/tile.ts`), so
 * baking with the sampling window shifted by (du, dv) texels evaluates the same recipe on a
 * different stretch of the plane. If every field is periodic with the tile, that bake is exactly
 * the unshifted bake rolled by (du, dv): the texels that sat on either side of the wrap edge now
 * sit side by side in the interior, computed in one pass. Exact equality, every field and every
 * derived map, for every set. The shifts include a negative one several tiles away, which is
 * where floor division and modular indexing go wrong if they are going to.
 *
 * NUMERICALLY, ON THE PINNED BYTES. The committed containers are decoded and every channel of
 * every map is measured across both wrap edges against its own interior (see `support.ts`).
 *
 * The construction test runs at an eighth of the published resolution. Recipes are defined on the
 * tile, not on the texel grid, so a coarser grid samples the same functions.
 */
const SCALE = 8;
const SHIFTS: readonly (readonly [number, number])[] = [
  [37, 23],
  [-3 * 128 - 5, 2 * 128 + 11],
];

const fieldPlanes = (base: Fields, shifted: Fields) =>
  Object.fromEntries(
    FIELD_NAMES.map((name) => [name, [base[name], shifted[name], 1] as const]),
  );

function checkConstruction(def: TextureSetDefinition): void {
  const width = def.width / SCALE;
  const height = def.height / SCALE;
  const base = sampleFields(def, { width, height });
  if (def.containerProfile !== SET_PROFILE_V1) {
    // A set of a material class: its class's maps, each rolled with the window.
    const maps = bakeClassMaps(def, { width, height });
    for (const [du, dv] of SHIFTS) {
      const shifted = sampleFields(def, { width, height, offsetU: du, offsetV: dv });
      expect(rollMismatches(width, height, fieldPlanes(base, shifted), du, dv)).toEqual(
        Object.fromEntries(FIELD_NAMES.map((name) => [name, 0])),
      );
      const moved = bakeClassMaps(def, { width, height, offsetU: du, offsetV: dv });
      const planes = Object.fromEntries(maps.map((map, index) => [
        map.descriptor.name,
        [map.bytes, moved[index]!.bytes, map.descriptor.components] as const,
      ]));
      expect(rollMismatches(width, height, planes, du, dv), `${def.setId} maps shifted by (${du}, ${dv})`)
        .toEqual(Object.fromEntries(maps.map((map) => [map.descriptor.name, 0])));
    }
    return;
  }
  const maps = bakeMaps(def, { width, height });
  for (const [du, dv] of SHIFTS) {
    const shifted = sampleFields(def, { width, height, offsetU: du, offsetV: dv });
    const fieldMismatch = rollMismatches(width, height, fieldPlanes(base, shifted), du, dv);
    expect(fieldMismatch, `${def.setId} fields shifted by (${du}, ${dv})`).toEqual(
      Object.fromEntries(FIELD_NAMES.map((name) => [name, 0])),
    );
    const moved = bakeMaps(def, { width, height, offsetU: du, offsetV: dv });
    const mapMismatch = rollMismatches(
      width,
      height,
      {
        base_color: [maps.baseColor, moved.baseColor, 3],
        normal: [maps.normal, moved.normal, 3],
        orm: [maps.orm, moved.orm, 3],
        height: [maps.relief, moved.relief, 1],
      },
      du,
      dv,
    );
    expect(mapMismatch, `${def.setId} maps shifted by (${du}, ${dv})`).toEqual({
      base_color: 0,
      normal: 0,
      orm: 0,
      height: 0,
    });
  }
}

describe('every set tiles by construction', () => {
  for (const def of CATALOG) {
    it(`${def.setId} bakes the same texels wherever the window sits`, () => {
      checkConstruction(def);
    });
  }

  it('fails a recipe whose pattern does not repeat with the tile', () => {
    // Height as a sawtooth whose period does not divide the tile: the kind of field a
    // non-tiling generator produces. The construction check must refuse it.
    const broken: TextureSetDefinition = {
      ...CATALOG[0]!,
      setId: 'test.broken',
      pattern: () => (x, y, out) => {
        out.height = floorMod(x + y, 300007) >> 4;
        out.red = 0;
        out.green = 0;
        out.blue = 0;
        out.roughness = 0;
        out.metalness = 0;
        out.occlusion = 65536;
      },
    };
    expect(() => checkConstruction(broken)).toThrow();
  });
});

describe('the pinned bytes are continuous across both wrap edges', () => {
  it('every channel of every map of every published set', () => {
    const manifest = JSON.parse(new TextDecoder().decode(readPublished('manifest.json'))) as {
      sets: { set_id: string; content_sha256: string }[];
    };
    expect(manifest.sets.length).toBeGreaterThanOrEqual(6);
    const failures: string[] = [];
    for (const entry of manifest.sets) {
      const read = readContainer(readPublished(`blobs/${entry.content_sha256}.ltex`));
      const resolution = read.header.resolution as { width: number; height: number };
      const reports = seamReports(
        resolution.width,
        resolution.height,
        Object.fromEntries(read.maps),
        read.layout,
      );
      // Every channel of every map the set stores, each across two edges: 3 + 3 + 3 + 1 for a v1
      // set, and its class's channels for any other.
      expect(reports).toHaveLength(2 * read.layout.reduce((sum, map) => sum + map.components, 0));
      for (const report of reports.filter((r) => !continuous(r))) {
        failures.push(`${entry.set_id} ${report.map}[${report.channel}] ${report.axis}: ${report.seam}`);
      }
    }
    expect(failures).toEqual([]);
  });

  it('flags a plane that does not tile', () => {
    // A brick base colour, stretched so its left half fills the tile: the interior stays
    // continuous and the wrap edge now joins texels half a tile apart.
    const def = CATALOG.find((d) => d.setId === 'cc0.brick-running-bond')!;
    const width = def.width / SCALE;
    const height = def.height / SCALE;
    const maps = bakeMaps(def, { width, height });
    const stretched = new Uint8Array(maps.baseColor.length);
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const from = (y * width + (x >> 1)) * 3;
        stretched.set(maps.baseColor.subarray(from, from + 3), (y * width + x) * 3);
      }
    }
    const reports = seamReports(width, height, {
      base_color: stretched,
      normal: maps.normal,
      orm: maps.orm,
      height: maps.relief,
    });
    const across = reports.filter((r) => r.map === 'base_color' && r.axis === 'u');
    expect(across.some((r) => !continuous(r))).toBe(true);
    // The untouched maps, from the same bake, still pass.
    expect(reports.filter((r) => r.map !== 'base_color').every(continuous)).toBe(true);
  });
});
