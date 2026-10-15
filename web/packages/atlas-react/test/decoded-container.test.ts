// @vitest-environment happy-dom
import { createHash, webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { parseTextureSetManifest, type TextureSetDigest } from '@exulanica/atlas-core';
import * as tess from '@exulanica/loom-tess/core';

// The decoder, counted: every reader below reaches it only through the module it imports.
vi.mock('@exulanica/loom-tess/core', async (original) => {
  const actual = await original<typeof import('@exulanica/loom-tess/core')>();
  return { ...actual, decodeOwd: vi.fn(actual.decodeOwd) };
});

const { decodedContainer } = await import('../src/playcanvas/generated-tile/decoded-container.js');
const { doorsOf, sightBlockersOf, streetFurnitureOf } = await import('../src/playcanvas/generated-tile/street-furniture.js');
const { containerOpeningSlots } = await import('../src/playcanvas/style-pack/opening-slots.js');
const { loadGeneratedTile, GeneratedTileRefusal } = await import('../src/playcanvas/generated-tile/tile-runtime.js');

// Relative to web/, where the suite runs.
const FIXTURE = 'packages/loom-tess/test/fixtures/tile-conformance.json';
const manifest = parseTextureSetManifest(new Uint8Array(readFileSync('../assets/textures/manifest.json')));
const subtle = webcrypto.subtle as unknown as TextureSetDigest;
const sha256 = async (bytes: Uint8Array): Promise<string> => createHash('sha256').update(bytes).digest('hex');
const noSets = async (): Promise<Uint8Array> => { throw new Error('this test fetches no texture set'); };
const decodes = vi.mocked(tess.decodeOwd);

let baked: Uint8Array;
beforeAll(async () => {
  baked = (await tess.bakeTile(new Uint8Array(readFileSync(FIXTURE)), sha256)).container;
}, 60_000);
// A hook that returned the mock would have it called as a cleanup after each test.
beforeEach(() => { decodes.mockClear(); });

describe('a container decoded once on a page', () => {
  it('is decoded once however many readers read it, the tile runtime among them', async () => {
    const bytes = new Uint8Array(baked);
    streetFurnitureOf(bytes);
    doorsOf(bytes);
    sightBlockersOf(bytes, 1_620);
    containerOpeningSlots([bytes]);
    await loadGeneratedTile({ name: 'once', bytes, manifest, fetchSet: noSets, digest: subtle, proof: 'agreeing-server-bakes' });
    expect(decodes).toHaveBeenCalledTimes(1);
    expect(decodedContainer(bytes)).toBe(decodedContainer(bytes));
  }, 30_000);

  it('decodes other bytes apart, even a copy that differs in one byte', () => {
    const bytes = new Uint8Array(baked);
    const changed = new Uint8Array(baked);
    const position = decodedContainer(bytes).header.sections.find((section) => section.name === 'position')!.byte_offset;
    changed[position + 1] = changed[position + 1]! ^ 1;
    const render = (one: Uint8Array) => decodedContainer(one).projections.find((projection) => projection.header.name === 'render_batch')!;
    expect(render(changed).position[0]).not.toBe(render(bytes).position[0]);
    expect(decodes).toHaveBeenCalledTimes(2);
  });

  it('keeps no layout that does not decode, so every reader is refused it', async () => {
    const short = baked.slice(0, baked.byteLength - 4);
    expect(() => decodedContainer(short)).toThrow(tess.OwdError);
    expect(() => doorsOf(short)).toThrow(tess.OwdError);
    await expect(loadGeneratedTile({ name: 'short', bytes: short, manifest, fetchSet: noSets, digest: subtle, proof: 'agreeing-server-bakes' }))
      .rejects.toBeInstanceOf(GeneratedTileRefusal);
    expect(decodes).toHaveBeenCalledTimes(3);
  });
});
