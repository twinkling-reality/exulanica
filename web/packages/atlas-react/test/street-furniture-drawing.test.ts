import { webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { beforeAll, describe, expect, it } from 'vitest';
import { parseTextureSetManifest, readStreetFurnitureForms, type TextureSetDigest } from '@exulanica/atlas-core';
import type { DecodedProjection } from '@exulanica/loom-tess/core';
import { decodedContainer } from '../src/playcanvas/generated-tile/decoded-container.js';
import { TILE_LOOK_V1 } from '../src/playcanvas/generated-tile/look.js';
import { madeStreetFurniture } from '../src/playcanvas/generated-tile/street-furniture-drawing.js';
import { STREET_FURNITURE_KIND } from '../src/playcanvas/generated-tile/street-furniture.js';
import { batchTileSurfaces, loadGeneratedTile, type DrawnTileRange, type LoadedGeneratedTile } from '../src/playcanvas/generated-tile/tile-runtime.js';

/*
 * The committed conformance tile's container (its records were baked by tess, its triangles are the
 * bake's) with its street furniture drawn by forms. Tests run from web/.
 */
const CONTAINER = new Uint8Array(readFileSync(resolve('packages/app/src/dev/tiles/tile-conformance.owd')));
const manifest = parseTextureSetManifest(new Uint8Array(readFileSync('../assets/textures/manifest.json')));
const noSets = async (): Promise<Uint8Array> => { throw new Error('this test fetches no texture set'); };
const SHIPPED = readStreetFurnitureForms(readFileSync('../assets/catalogs/world-kinds/street-furniture-form.v1.json', 'utf8'));
/** Every box part drawn as its own box: the bake's own parts, by the page's placement. */
const AS_BAKED = readStreetFurnitureForms(JSON.stringify({
  catalog_id: 'street-furniture-form', catalog_version: 1, entries: [
    { key: 'bench', parts: ['box', 'box', 'box', 'box'], draws: [0, 1, 2, 3].map((part) => ({ form: 'solid', parts: [part] })), reason: 'control' },
    { key: 'cycle_stand', parts: ['box', 'box', 'box'], draws: [0, 1, 2].map((part) => ({ form: 'solid', parts: [part] })), reason: 'control' },
  ],
}));

let tile: LoadedGeneratedTile;
let render: DecodedProjection;
let records: ReturnType<typeof decodedContainer>['header']['records'];

beforeAll(async () => {
  const decoded = decodedContainer(CONTAINER);
  records = decoded.header.records;
  render = decoded.projections.find((projection) => projection.header.name === 'render_batch')!;
  tile = await loadGeneratedTile({
    name: 'tile-conformance', bytes: CONTAINER, manifest, fetchSet: noSets,
    digest: webcrypto.subtle as unknown as TextureSetDigest, proof: 'agreeing-server-bakes',
  });
});

function bakedVertices(range: DrawnTileRange): number[][] {
  const seen = new Set<number>();
  for (let corner = range.firstTriangle * 3; corner < (range.firstTriangle + range.triangleCount) * 3; corner += 1) seen.add(render.index[corner]!);
  return [...seen].map((vertex) => [render.position[vertex * 3]!, render.position[vertex * 3 + 1]!, render.position[vertex * 3 + 2]!]);
}

const near = (a: readonly number[], b: readonly number[], metres: number): boolean =>
  Math.abs(a[0]! - b[0]!) <= metres && Math.abs(a[1]! - b[1]!) <= metres && Math.abs(a[2]! - b[2]!) <= metres;

describe('street furniture drawn by its forms', () => {
  it('places a form where the bake places the parts: a box part drawn as itself lands on the bake\'s own vertices', () => {
    const furniture = tile.ranges.filter((range): range is DrawnTileRange => range.state === 'drawn' && range.kind === STREET_FURNITURE_KIND);
    const made = madeStreetFurniture(records, tile.ranges, render.header.origin_mm, AS_BAKED);
    // Positive control: the tile holds a bench and two cycle stands, and they face two ways.
    expect(made.size).toBe(3);
    const facings = new Set([...made.keys()].map((range) => `${records[range.record]!.fields['facing_dx_mm']},${records[range.record]!.fields['facing_dy_mm']}`));
    expect(facings.size).toBe(2);
    for (const [range, surfaces] of made) {
      const baked = bakedVertices(furniture.find((one) => one === range)!);
      const drawn: number[][] = [];
      for (const surface of surfaces) for (let at = 0; at < surface.positions.length; at += 3) drawn.push(surface.positions.slice(at, at + 3));
      // The bake works in whole millimetres; the page in floats: within 1.5 mm, both ways.
      for (const vertex of drawn) expect(baked.some((one) => near(one, vertex, 0.0015)), `a made vertex of ${range.identity}`).toBe(true);
      for (const vertex of baked) expect(drawn.some((one) => near(one, vertex, 0.0015)), `a baked vertex of ${range.identity}`).toBe(true);
    }
  });

  it('turns a form by the record\'s facing as the grammar states it: the left of (dx, dy) is (-dy, dx)', () => {
    // A bench facing north at (10 m, 20 m). Its frame's +y is its left, and the left of north is west, so its
    // back part, stated 200 mm to its left negated (offset -200 mm, 60 mm deep), stands 170 to 230 mm east.
    const bench = JSON.parse(readFileSync('../assets/catalogs/street-furniture.v2.json', 'utf8')).entries
      .find((entry: { key: string }) => entry.key === 'bench').parts;
    const record = { kind: STREET_FURNITURE_KIND, fields: { furniture_class: 'bench', x_mm: 10000, y_mm: 20000, z_mm: 0, facing_dx_mm: 0, facing_dy_mm: 1000, parts: bench } };
    const range = { state: 'drawn', kind: STREET_FURNITURE_KIND, record: 0 };
    const made = madeStreetFurniture([record], [range], [0, 0, 0], AS_BAKED).get(range)!;
    const back = made.find((surface) => surface.role === 'object_primary')!;
    const xs: number[] = [];
    for (let at = 0; at < back.positions.length; at += 3) if (back.positions[at + 2]! > 0.5) xs.push(back.positions[at]!);
    // Above the seat only the back is drawn: 170 to 230 mm east of the base, along the bench's 1.8 m north to south.
    expect(Math.min(...xs)).toBeCloseTo(10.17, 6);
    expect(Math.max(...xs)).toBeCloseTo(10.23, 6);
  });

  it('draws the shipped forms in place of the baked furniture only, each in its own role\'s set, and leaves a class with no form as baked', () => {
    const made = madeStreetFurniture(records, tile.ranges, render.header.origin_mm, SHIPPED);
    const classes = [...made.keys()].map((range) => records[range.record]!.fields['furniture_class']).sort();
    expect(classes).toEqual(['bench', 'cycle_stand', 'cycle_stand']);
    const planned = tile as unknown as { readonly ranges: readonly DrawnTileRange[] };
    const placements = new Map();
    const before = batchTileSurfaces(render, new Float64Array(render.position.length / 3 * 2), planned.ranges, placements, TILE_LOOK_V1);
    const after = batchTileSurfaces(render, new Float64Array(render.position.length / 3 * 2), planned.ranges, placements, TILE_LOOK_V1, made);
    const baked = [...made.keys()].reduce((total, range) => total + (range.state === 'drawn' ? range.triangleCount : 0), 0);
    const drawn = [...made.values()].flat().reduce((total, surface) => total + surface.indices.length / 3, 0);
    const triangles = (batches: typeof before): number => batches.reduce((total, batch) => total + batch.triangles, 0);
    expect(drawn).toBeGreaterThan(baked);
    expect(triangles(after)).toBe(triangles(before) - baked + drawn);
  });

  it('draws a form\'s own normals turned with its record, so a cycle stand\'s posts read round to the ground', () => {
    // The page once made these from the triangles: where a ring's first and last vertices meet they turned 15 degrees
    // off round (a crease down the hoop's broad face), and the rest of the ring at a post's foot 5 more.
    const made = madeStreetFurniture(records, tile.ranges, render.header.origin_mm, SHIPPED);
    const stands = [...made.keys()].filter((range) => records[range.record]!.fields['furniture_class'] === 'cycle_stand');
    expect(stands).toHaveLength(2);
    const [ox, oy, oz] = render.header.origin_mm as [number, number, number];
    for (const range of stands) {
      const fields = records[range.record]!.fields as { readonly [name: string]: number };
      const [batch] = batchTileSurfaces(render, new Float64Array(render.position.length / 3 * 2), [range as DrawnTileRange], new Map(), TILE_LOOK_V1, new Map([[range, made.get(range)!]]));
      const facing = Math.hypot(fields['facing_dx_mm']!, fields['facing_dy_mm']!);
      const [ux, uy] = [fields['facing_dx_mm']! / facing, fields['facing_dy_mm']! / facing];
      let checked = 0;
      for (let at = 0; at < batch!.positions.length / 3; at += 1) {
        // The renderer's frame: x east, y up, z south. A vertex at the ground is on a post's foot or its wall.
        const [x, y, z] = [batch!.positions[at * 3]!, batch!.positions[at * 3 + 1]!, batch!.positions[at * 3 + 2]!];
        if (Math.abs(y - (fields['z_mm']! - oz) / 1000) > 1e-6) continue;
        const normal = [batch!.normals[at * 3]!, batch!.normals[at * 3 + 1]!, batch!.normals[at * 3 + 2]!];
        // Each post stands 350 mm along the facing either way from the stand's base: the nearer one's axis.
        const posts = [-350, 350].map((along) => [(fields['x_mm']! + along * ux - ox) / 1000, -(fields['y_mm']! + along * uy - oy) / 1000]);
        const [px, pz] = posts.sort((a, b) => Math.hypot(x - a[0]!, z - a[1]!) - Math.hypot(x - b[0]!, z - b[1]!))[0]!;
        const out = Math.hypot(x - px!, z - pz!);
        const expected = normal[1]! < -0.5 ? [0, -1, 0] : [(x - px!) / out, 0, (z - pz!) / out];
        expected.forEach((value, axis) => expect(normal[axis]!, `${range.identity} vertex ${at}`).toBeCloseTo(value, 6));
        checked += 1;
      }
      // Both posts' feet: each a ring of 13 (its first and last meeting where s wraps) and a foot of 13.
      expect(checked).toBe(2 * (13 + 13));
    }
  });
});
