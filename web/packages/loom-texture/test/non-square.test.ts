import { describe, expect, it } from 'vitest';
import { classLayout } from '../src/classes.js';
import { encodeContainerV2, readContainer } from '../src/container.js';
import type { TextureSetDefinition } from '../src/definition.js';
import { FULL, ONE, floorDiv } from '../src/integer.js';
import { bakeClassMaps } from '../src/maps.js';
import { publishSet } from '../src/publish.js';
import { MM, TILE, texelToTile, tileToLength } from '../src/tile.js';

/**
 * A tile that is not square, through the bake, the container, the reader and the publishing path.
 *
 * `cc0.kerb-stone` has been 1024 by 256 texels over 1800 by 450 mm since migration 0065 and the
 * road paint is 256 by 64 over 1000 by 250, so a tile longer than it is wide is not new; what the
 * published sets do not exercise is a NON-SQUARE V2 CONTAINER on a pattern built to catch an axis
 * mistake. The pattern below differs in each axis and differently on each, so a swapped axis, a
 * reused stride or one extent used for both cannot produce these bytes.
 *
 * This began as a scratch script run once while writing the road paint. A run is a record of one
 * moment; a test is the same proof re-run whenever anything here changes, which is the difference
 * this project draws between evidence and a check.
 */
/** Any digest: nothing here checks the licence, only that the writer takes one. */
const LICENCE = 'd'.repeat(64);
const WIDTH = 256;
const HEIGHT = 64;
const EXTENT_U = 1000;
const EXTENT_V = 250;

/**
 * Red rises with x across the tile, green with y down it, blue marks the third of the tile nearest
 * the far v edge, coverage steps an eighth along u, and the height rises with y alone, so the
 * normal must point along v and sit at its zero along u.
 */
const definition: TextureSetDefinition = {
  setId: 'scratch.non-square',
  version: 1,
  seed: 1,
  family: 'paint',
  title: 'A tile that is not square',
  summary: 'Synthetic texels for the non-square proof. Never published.',
  licenceId: 'CC0-1.0',
  width: WIDTH,
  height: HEIGHT,
  extentU: EXTENT_U,
  extentV: EXTENT_V,
  surface: 'horizontal',
  containerProfile: 'exulanica.texture-set/v2',
  materialClass: 'decal',
  heightRangeMm: 4,
  cavity: { radiusMm: 4, depthMm: 1, strengthPermille: 400 },
  film: null,
  parameters: { proof: 1 },
  pattern: () => (x, y, out) => {
    out.red = floorDiv(x * ONE, TILE);
    out.green = floorDiv(y * ONE, TILE);
    out.blue = y * 3 > TILE * 2 ? ONE : 0;
    out.height = floorDiv(y * FULL, TILE);
    out.roughness = ONE >> 1;
    out.metalness = 0;
    out.occlusion = ONE;
    out.coverage = x * 8 > TILE ? FULL : 0;
    out.transmission = 0;
  },
};

const maps = bakeClassMaps(definition);
const named = (name: string): Uint8Array =>
  maps.find((map) => map.descriptor.name === name)!.bytes;

describe('a tile that is not square', () => {
  it('bakes one map per stored channel, each as long as BOTH dimensions say', () => {
    const layout = classLayout('decal', 'procedural');
    expect(maps.map((map) => map.descriptor.name)).toEqual(layout.map((map) => map.name));
    for (const map of maps) {
      expect({ map: map.descriptor.name, bytes: map.bytes.length }).toEqual({
        map: map.descriptor.name,
        bytes: WIDTH * HEIGHT * map.descriptor.components,
      });
    }
  });

  it('reads u along the row and v down the column, with neither leaking into the other', () => {
    const colour = named('base_color_coverage');
    const at = (x: number, y: number, channel: number): number => colour[(y * WIDTH + x) * 4 + channel]!;
    expect(at(0, 0, 0)).toBeLessThan(at(WIDTH - 1, 0, 0));
    expect(at(0, 0, 1)).toBe(at(WIDTH - 1, 0, 1));
    expect(at(0, 0, 1)).toBeLessThan(at(0, HEIGHT - 1, 1));
    expect(at(0, 0, 0)).toBe(at(0, HEIGHT - 1, 0));
    // The blue mark is a statement about the ROWS, so it cannot be right if the axes are swapped.
    expect({ first: at(0, 0, 2), last: at(0, HEIGHT - 1, 2) }).toEqual({ first: 0, last: 255 });
    // Coverage steps an eighth along u: a reused stride would put the step somewhere else.
    const step = Array.from({ length: WIDTH }, (_, x) => at(x, 7, 3)).findIndex((value) => value === 255);
    expect(step).toBe(Math.ceil(WIDTH / 8));
  });

  it('keeps the texel square in millimetres, each axis asked with its own extent', () => {
    const pitch = (size: number, extent: number): number =>
      floorDiv(tileToLength(texelToTile(1, size) - texelToTile(0, size), extent) * 1000, MM);
    expect(pitch(WIDTH, EXTENT_U)).toBe(pitch(HEIGHT, EXTENT_V));
    expect(pitch(WIDTH, EXTENT_U)).toBe(3906);
  });

  it('builds the normal from each axis with its own extent', () => {
    const normal = named('normal');
    const at = (x: number, y: number): { x: number; y: number } => ({
      x: normal[(y * WIDTH + x) * 2]!,
      y: normal[(y * WIDTH + x) * 2 + 1]!,
    });
    // The height rises with y alone, so x sits at its zero and y does not, everywhere inside.
    for (const [x, y] of [[10, 10], [200, 40], [128, 32]] as const) {
      expect(at(x, y).x, `${x},${y}`).toBeGreaterThanOrEqual(127);
      expect(at(x, y).x, `${x},${y}`).toBeLessThanOrEqual(128);
      expect([127, 128], `${x},${y}`).not.toContain(at(x, y).y);
    }
  });

  it('states both dimensions in its header and reads back the bytes it wrote', () => {
    const container = encodeContainerV2(definition, maps, LICENCE);
    const read = readContainer(container);
    const header = read.header as { resolution: { width: number; height: number }; extent_mm: { u: number; v: number } };
    expect(header.resolution).toEqual({ width: WIDTH, height: HEIGHT });
    expect(header.extent_mm).toEqual({ u: EXTENT_U, v: EXTENT_V });
    for (const map of maps) {
      const back = read.maps.get(map.descriptor.name)!;
      expect(Buffer.from(back).equals(Buffer.from(map.bytes)), map.descriptor.name).toBe(true);
    }
  });

  it('goes through the publishing path, which is where a size rule would refuse it', () => {
    const published = publishSet(definition, LICENCE);
    expect({
      resolution: published.entry.resolution,
      extent: published.entry.extent_mm,
      byteSize: published.entry.byte_size,
    }).toEqual({
      resolution: { width: WIDTH, height: HEIGHT },
      extent: { u: EXTENT_U, v: EXTENT_V },
      byteSize: published.container.length,
    });
  });
});
