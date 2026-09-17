/**
 * `@exulanica/loom-tess/node`: the bake entry. It reads a file, calls core, hashes and writes, and
 * contains no tessellation logic of its own. This is the build the `baked_tile` stage runs, so the
 * bytes it writes are the bytes the stage digests.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { bakeTile, verifyOwd } from '../core/bake.js';
import type { DecodedOwd } from '../core/owd.js';
import { nodeSha256 } from './sha256.js';

export { nodeSha256 } from './sha256.js';

/** What a bake reports, in the shape the CLI prints and the Python stage reads. */
export interface BakeReport {
  readonly container_sha256: string;
  readonly byte_size: number;
  readonly tile_inputs_digest: string;
  readonly triangle_digests: { readonly [projection: string]: string };
}

/** Bake the tile document at `documentPath` and write the container to `outputPath`. */
export async function bakeDocumentFile(documentPath: string, outputPath: string): Promise<BakeReport> {
  const bake = await bakeTile(readFileSync(documentPath), nodeSha256);
  writeFileSync(outputPath, bake.container);
  return {
    container_sha256: await nodeSha256(bake.container),
    byte_size: bake.container.length,
    tile_inputs_digest: bake.tileInputsDigest,
    triangle_digests: Object.fromEntries(bake.triangleDigests),
  };
}

/** Decode and fully verify the container at `path`. */
export async function verifyFile(path: string): Promise<DecodedOwd> {
  return verifyOwd(readFileSync(path), nodeSha256);
}
