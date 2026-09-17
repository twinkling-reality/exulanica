/**
 * The conformance fixture, through the Node bake and through the browser preview.
 *
 * Both triangle digests must equal the CHECKED-IN LITERAL below, not merely each other: two
 * builds that agree on a wrong answer agree. The literal is the fixture. It moves only when the
 * fixture, the tessellator version or the digest definition moves, and each of those is a
 * deliberate commit that updates it (see `tests/test_bake_determinism.py` for regenerating the
 * fixture).
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PreviewUnavailable, previewTile } from '../src/browser/index.js';
import { bakeDocumentFile, nodeSha256 } from '../src/node/index.js';
import { bakeTile } from '../src/core/bake.js';
import { absoluteSurfaceCoordinates, absoluteVertices } from '../src/core/owd.js';
import { documentBytes, FIXTURE_PATH, fixtureBytes, fixtureObject, recordsOf, scratch } from './support.js';

/** Over `test/fixtures/tile-conformance.json`, tessellator 1, digest profile v1. */
const GOLDEN = {
  render_batch: 'a56f3b0e54cf6e65f6ceb99f83015fa42017bdcb4cd300d7e102e33e05fd437f',
  nav_envelope: '4b9616b60beab2094b9673c0773118d89fd8c1754373edef4c87738d44a97d9e',
} as const;
const GOLDEN_RENDER_BATCH = GOLDEN.render_batch;

afterEach(() => {
  vi.unstubAllGlobals();
});

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

  it('draws the terrain and states why every other record is not drawn', async () => {
    const preview = await previewTile(fixtureBytes());
    const [renderBatch, navEnvelope] = preview.projections;
    expect(renderBatch!.header.name).toBe('render_batch');
    expect(navEnvelope!.header.name).toBe('nav_envelope');
    for (const projection of [renderBatch!, navEnvelope!]) {
      expect(projection.header.vertex_count).toBe(16);
      expect(projection.header.triangle_count).toBe(18);
    }
    const count = (states: string[], state: string): number => states.filter((s) => s === state).length;
    const render = renderBatch!.header.entries.map((entry) => entry.state);
    expect([count(render, 'drawn'), count(render, 'not_in_projection'), count(render, 'unavailable')])
      .toEqual([1, 1, render.length - 2]);
    const nav = navEnvelope!.header.entries.map((entry) => entry.state);
    // Terrain supports; facades, the material, the vitrine, the premises and the tree do not.
    expect([count(nav, 'drawn'), count(nav, 'not_in_projection'), count(nav, 'unavailable')])
      .toEqual([1, 8, nav.length - 9]);
    expect(navEnvelope!.surfaceMm).toBeUndefined();
    expect(renderBatch!.surfaceMm).toHaveLength(32);
  });

  it('gives drawn terrain plan surface coordinates, s = x and t = -y, in millimetres', async () => {
    const preview = await previewTile(fixtureBytes());
    const renderBatch = preview.projections[0]!;
    const vertices = absoluteVertices(renderBatch);
    const surface = absoluteSurfaceCoordinates(renderBatch)!;
    for (let vertex = 0; vertex < renderBatch.header.vertex_count; vertex += 1) {
      expect(surface[vertex * 2]).toBe(vertices[vertex * 3]);
      expect(surface[vertex * 2 + 1]).toBe(0 - vertices[vertex * 3 + 1]!);
    }
    const drawn = renderBatch.header.entries.find((entry) => entry.state === 'drawn');
    expect(drawn).toMatchObject({ surface: 'horizontal', material: { state: 'not-carried' } });
  });

  it('samples support height exactly on the terrain plane', async () => {
    const preview = await previewTile(fixtureBytes());
    const nav = preview.projections[1]!;
    const vertices = absoluteVertices(nav);
    // The fixture's plane: z = -200 + 120 per 4 m in x and 160 per 4 m in y, from (-4000, -4000).
    for (let vertex = 0; vertex < nav.header.vertex_count; vertex += 1) {
      const [x, y, z] = [vertices[vertex * 3]!, vertices[vertex * 3 + 1]!, vertices[vertex * 3 + 2]!];
      expect(z).toBe(-200 + ((x + 4000) / 4000) * 120 + ((y + 4000) / 4000) * 160);
    }
    expect(nav.header.contract.admissible_uses).toEqual(['sampling support height']);
  });

  it('moves when one integer of the fixture moves, in both builds alike', async () => {
    const document = fixtureObject();
    recordsOf(document, 'city.terrain')[0].fields.height_mm[5] += 1;
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
    expect(node.triangleDigests.get('render_batch')).not.toBe(GOLDEN_RENDER_BATCH);
  });

  it('does not move when the document lists its records in another order', async () => {
    const document = fixtureObject();
    document.grammars[0].records.reverse();
    const node = await bakeTile(documentBytes(document), nodeSha256);
    expect(Object.fromEntries(node.triangleDigests)).toEqual(GOLDEN);
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
