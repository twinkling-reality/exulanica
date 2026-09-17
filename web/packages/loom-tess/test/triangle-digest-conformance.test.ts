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
import { documentBytes, FIXTURE_PATH, fixtureBytes, fixtureObject, recordsOf, scratch } from './support.js';

/** `render_batch` over `test/fixtures/tile-conformance.json`, tessellator 1, digest profile v1. */
const GOLDEN_RENDER_BATCH = '133e1144e45e51165f3d1e2f958369d19f7ac2185d96e9fb72c6f186fe1a79cc';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('the triangle digest of the conformance fixture', () => {
  it('is the golden literal through the Node bake and through the browser preview', async () => {
    const out = join(scratch('conformance'), 'fixture.owd');
    const node = await bakeDocumentFile(FIXTURE_PATH, out);
    const browser = await previewTile(fixtureBytes());

    expect(node.triangle_digests).toEqual({ render_batch: GOLDEN_RENDER_BATCH });
    expect(browser.triangleDigests.get('render_batch')).toBe(GOLDEN_RENDER_BATCH);
    // Same container too, though the browser never writes or serves it.
    expect(browser.containerSha256).toBe(node.container_sha256);
    expect(await nodeSha256(new Uint8Array(readFileSync(out)))).toBe(node.container_sha256);
    expect(browser.tileInputsDigest).toBe(node.tile_inputs_digest);
  });

  it('draws the terrain and states why every other record is not drawn', async () => {
    const preview = await previewTile(fixtureBytes());
    const [renderBatch] = preview.projections;
    expect(renderBatch!.header.vertex_count).toBe(16);
    expect(renderBatch!.header.triangle_count).toBe(18);
    const states = renderBatch!.header.entries.map((entry) => entry.state);
    expect(states.filter((state) => state === 'drawn')).toHaveLength(1);
    expect(states.filter((state) => state === 'not_a_surface')).toHaveLength(1);
    expect(states.filter((state) => state === 'unavailable')).toHaveLength(states.length - 2);
  });

  it('moves when one integer of the fixture moves, in both builds alike', async () => {
    const document = fixtureObject();
    recordsOf(document, 'city.terrain')[0].fields.height_mm[5] += 1;
    const perturbed = documentBytes(document);
    const node = await bakeTile(perturbed, nodeSha256);
    const browser = await previewTile(perturbed);
    const digest = node.triangleDigests.get('render_batch');
    expect(digest).not.toBe(GOLDEN_RENDER_BATCH);
    expect(browser.triangleDigests.get('render_batch')).toBe(digest);
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
    expect(node.triangleDigests.get('render_batch')).toBe(GOLDEN_RENDER_BATCH);
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
