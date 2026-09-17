/**
 * The conformance fixture, through the Node bake and through the browser preview.
 *
 * Both triangle digests must equal the CHECKED-IN LITERAL below, not merely each other: two
 * builds that agree on a wrong answer agree. The literal is the fixture. It moves only when the
 * fixture, the tessellator version or the digest definition moves, and each of those is a
 * deliberate commit that updates it. The fixture is the city vocabulary lane's version 2 tile,
 * copied byte for byte; `tests/test_bake_determinism.py` holds the copy to its source.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PreviewUnavailable, previewTile } from '../src/browser/index.js';
import { bakeDocumentFile, nodeSha256 } from '../src/node/index.js';
import { bakeTile } from '../src/core/bake.js';
import { CITY_V2 } from '../src/core/city-v2.js';
import { absoluteSurfaceCoordinates, absoluteVertices, decodeOwd } from '../src/core/owd.js';
import type { DecodedOwd } from '../src/core/owd.js';
import {
  coveringBoxes,
  documentBytes,
  dressedTerrainObject,
  FIXTURE_PATH,
  fixtureBytes,
  fixtureObject,
  recordsOf,
  scratch,
  sortList,
} from './support.js';

/** Over `test/fixtures/tile-conformance.json`, tessellator 4, digest profile v3. */
const GOLDEN = {
  render_batch: 'a2c581db847ecab6c23c2ce258f69805f89451eab8a87171f6fd517c1c6a5a4b',
  nav_envelope: '04481caa395be65a3a80d29e41c787221f99a12ab831232e0ebb6200c388cc39',
} as const;

afterEach(() => {
  vi.unstubAllGlobals();
});

const count = (states: string[], state: string): number => states.filter((s) => s === state).length;

async function decodedFixture(bytes: Uint8Array = fixtureBytes()): Promise<DecodedOwd> {
  return decodeOwd((await bakeTile(bytes, nodeSha256)).container);
}

describe('the triangle digest of the conformance fixture', () => {
  it('is the golden literal through the Node bake and through the browser preview', async () => {
    const out = join(scratch('conformance'), 'fixture.owd');
    const node = await bakeDocumentFile(FIXTURE_PATH, out);
    const browser = await previewTile(fixtureBytes());

    expect(node.triangle_digests).toEqual(GOLDEN);
    expect(Object.fromEntries(browser.triangleDigests)).toEqual(GOLDEN);
    // Same container too, though the browser never writes or serves it.
    expect(browser.containerSha256).toBe(node.container_sha256);
    expect(await nodeSha256(new Uint8Array(readFileSync(out)))).toBe(node.container_sha256);
    expect(browser.tileInputsDigest).toBe(node.tile_inputs_digest);
  });

  it('draws the terrain patch undressed round the streets, the segments dressed, and states why nothing else draws', async () => {
    const { header, projections } = await decodedFixture();
    const [renderBatch, navEnvelope] = projections;
    expect(renderBatch!.header.name).toBe('render_batch');
    expect(navEnvelope!.header.name).toBe('nav_envelope');
    const grammar = fixtureObject().grammars[0];
    expect(header.records).toHaveLength(grammar.owned.length + grammar.halo.length);
    expect(header.grammars[0]).toMatchObject({
      subject_identity: grammar.subject_identity,
      frame: { name: 'city_local', units: 'mm', axes: 'x_east_y_north_z_up', metric_class: 'metric_authored' },
    });
    const terrain = header.records.findIndex((record) => record.kind === 'city.terrain');

    // The terrain patch is drawn less the carriageways and gutters the three segments draw, and says
    // no material dresses it: the grammar admits none. Every other surface waits on a rule.
    const render = renderBatch!.header.entries.map((entry) => entry.state);
    expect(count(render, 'drawn')).toBe(4);
    expect(count(render, 'halo')).toBe(grammar.halo.length);
    const drawnTerrain = renderBatch!.header.entries[terrain]!;
    expect(drawnTerrain).toMatchObject({
      state: 'drawn',
      vertex_count: 483,
      triangle_count: 572,
      surfaces: [{ role: 'terrain', orientation: 'horizontal', material: { state: 'none-exists' }, triangle_count: 572 }],
    });
    // Yielding to the streets cuts the met cells into more triangles than the grid's 16 by 16.
    expect(drawnTerrain.state === 'drawn' && drawnTerrain.triangle_count).toBeGreaterThan(16 * 16 * 2);
    // Each segment draws a carriageway and a gutter, each dressed by its own material record.
    const segments = renderBatch!.header.entries.filter((_entry, index) => header.records[index]!.kind === 'city.street_segment');
    expect(segments).toHaveLength(3);
    for (const entry of segments) {
      if (entry.state !== 'drawn') throw new Error('a segment is not drawn');
      expect(entry.surfaces!.map((surface) => [surface.role, surface.orientation, surface.material.state])).toEqual([
        ['carriageway', 'horizontal', 'record'],
        ['gutter', 'horizontal', 'record'],
      ]);
      for (const surface of entry.surfaces!) {
        if (surface.material.state !== 'record') throw new Error('a segment surface cites no record');
        expect(header.records[surface.material.record]!.fields.role).toBe(surface.role);
      }
    }
    expect(renderBatch!.surfaceMm).toHaveLength(renderBatch!.header.vertex_count * 2);
    for (const entry of renderBatch!.header.entries) {
      if (entry.state === 'unavailable') expect(entry.needs.length).toBeGreaterThan(0);
    }

    const nav = navEnvelope!.header.entries.map((entry) => entry.state);
    expect(count(nav, 'drawn')).toBe(1);
    expect(count(nav, 'halo')).toBe(grammar.halo.length);
    expect(navEnvelope!.header.entries[terrain]).toMatchObject({ state: 'drawn', vertex_count: 235, triangle_count: 368 });
    expect(navEnvelope!.surfaceMm).toBeUndefined();

    // Halo is exactly what the document lists as halo.
    header.records.forEach((record, index) => {
      expect(renderBatch!.header.entries[index]!.state === 'halo').toBe(record.membership === 'halo');
    });
  });

  it('leaves out exactly the terrain cells a covering record meets, grown by the capsule radius', async () => {
    const nav = (await decodedFixture()).projections[1]!;
    const vertices = absoluteVertices(nav);
    const radius = CITY_V2.measures.nav_envelope!.capsule_clearance!.radius_mm!;
    const cover = coveringBoxes(fixtureObject()).map((box) => ({
      min_x: box.min_x - radius,
      min_y: box.min_y - radius,
      max_x: box.max_x + radius,
      max_y: box.max_y + radius,
    }));
    const terrain = recordsOf(fixtureObject(), 'city.terrain')[0].fields;
    const cell = terrain.cell_mm as number;
    const meets = (west: number, south: number): boolean =>
      cover.some((box) => west <= box.max_x && box.min_x <= west + cell && south <= box.max_y && box.min_y <= south + cell);

    const drawn = new Set<string>();
    for (let triangle = 0; triangle < nav.header.triangle_count; triangle += 1) {
      const corners = [0, 1, 2].map((corner) => nav.index[triangle * 3 + corner]!);
      const west = Math.min(...corners.map((vertex) => vertices[vertex * 3]!));
      const south = Math.min(...corners.map((vertex) => vertices[vertex * 3 + 1]!));
      expect(meets(west, south), `cell at ${west}, ${south}`).toBe(false);
      drawn.add(`${west} ${south}`);
    }
    let expected = 0;
    for (let row = 0; row + 1 < terrain.samples_per_side; row += 1) {
      for (let column = 0; column + 1 < terrain.samples_per_side; column += 1) {
        if (!meets(column * cell, row * cell)) expected += 1;
      }
    }
    expect(expected).toBeGreaterThan(0);
    expect(expected).toBeLessThan((terrain.samples_per_side - 1) ** 2);
    expect(drawn.size).toBe(expected);
    expect(nav.header.triangle_count).toBe(expected * 2);
  });

  it('samples support height exactly at the terrain samples', async () => {
    const nav = (await decodedFixture()).projections[1]!;
    const vertices = absoluteVertices(nav);
    const terrain = recordsOf(fixtureObject(), 'city.terrain')[0].fields;
    for (let vertex = 0; vertex < nav.header.vertex_count; vertex += 1) {
      const [x, y, z] = [vertices[vertex * 3]!, vertices[vertex * 3 + 1]!, vertices[vertex * 3 + 2]!];
      const sample = (y / terrain.cell_mm) * terrain.samples_per_side + x / terrain.cell_mm;
      expect(z).toBe(terrain.height_mm[sample]);
    }
    expect(nav.header.contract.admissible_uses).toEqual(['sampling support height']);
  });

  it('gives undressed terrain plan surface coordinates, s = x and t = y', async () => {
    const decoded = await decodedFixture();
    const renderBatch = decoded.projections[0]!;
    const vertices = absoluteVertices(renderBatch);
    const surface = absoluteSurfaceCoordinates(renderBatch)!;
    const terrain = renderBatch.header.entries.find((_entry, index) => decoded.header.records[index]!.kind === 'city.terrain')!;
    if (terrain.state !== 'drawn') throw new Error('the terrain is not drawn');
    for (let step = 0; step < terrain.vertex_count; step += 1) {
      const vertex = terrain.first_vertex + step;
      expect(surface[vertex * 2]).toBe(vertices[vertex * 3]);
      expect(surface[vertex * 2 + 1]).toBe(vertices[vertex * 3 + 1]);
    }
  });

  it('draws dressed terrain citing its material record', async () => {
    const decoded = await decodedFixture(documentBytes(dressedTerrainObject()));
    const renderBatch = decoded.projections[0]!;
    const entry = renderBatch.header.entries.find((_candidate, index) => decoded.header.records[index]!.kind === 'city.terrain')!;
    if (entry.state !== 'drawn') throw new Error('unreachable');
    const [surface] = entry.surfaces!;
    expect(surface).toMatchObject({ role: 'terrain', orientation: 'horizontal' });
    if (surface!.material.state !== 'record') throw new Error('the dressed terrain cites no record');
    const material = decoded.header.records[surface!.material.record]!;
    expect(material.kind).toBe('city.surface_material');
    expect(material.fields.surface_identity).toBe(decoded.header.records[entry.record]!.identity);
    expect(decoded.projections[0]!.header.triangle_digest).not.toBe(GOLDEN.render_batch);
  });

  it('moves when one integer of the fixture moves, in both builds alike', async () => {
    const document = fixtureObject();
    const terrain = recordsOf(document, 'city.terrain')[0].fields;
    terrain.height_mm[0] = 10;
    terrain.extent.max_z_mm = 10;
    const perturbed = documentBytes(document);
    const node = await bakeTile(perturbed, nodeSha256);
    const browser = await previewTile(perturbed);
    expect(node.triangleDigests.get('render_batch')).not.toBe(GOLDEN.render_batch);
    expect(node.triangleDigests.get('nav_envelope')).not.toBe(GOLDEN.nav_envelope);
    expect(Object.fromEntries(browser.triangleDigests)).toEqual(Object.fromEntries(node.triangleDigests));
  });

  it('moves when a record that draws nothing changes, because its entry is digested too', async () => {
    const document = fixtureObject();
    recordsOf(document, 'city.parcel')[0].fields.address_number += 1;
    const node = await bakeTile(documentBytes(document), nodeSha256);
    expect(node.triangleDigests.get('render_batch')).not.toBe(GOLDEN.render_batch);
    expect(node.triangleDigests.get('nav_envelope')).not.toBe(GOLDEN.nav_envelope);
  });

  it('moves when an owned record becomes halo, because halo is never drawn', async () => {
    const document = fixtureObject();
    const grammar = document.grammars[0];
    const index = grammar.owned.findIndex((record: any) => record.kind === 'city.premises');
    grammar.halo.push(...grammar.owned.splice(index, 1));
    sortList(grammar.halo);
    const node = await bakeTile(documentBytes(document), nodeSha256);
    expect(node.triangleDigests.get('render_batch')).not.toBe(GOLDEN.render_batch);
    expect(node.triangleDigests.get('nav_envelope')).not.toBe(GOLDEN.nav_envelope);
  });
});

describe('the browser preview', () => {
  it('refuses outright where crypto.subtle is missing', async () => {
    vi.stubGlobal('crypto', undefined);
    await expect(previewTile(fixtureBytes())).rejects.toBeInstanceOf(PreviewUnavailable);
  });

  it('refuses where crypto has no subtle member', async () => {
    vi.stubGlobal('crypto', {});
    await expect(previewTile(fixtureBytes())).rejects.toBeInstanceOf(PreviewUnavailable);
  });
});
