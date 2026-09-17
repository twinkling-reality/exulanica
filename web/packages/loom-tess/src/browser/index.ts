/**
 * `@exulanica/loom-tess/browser`: the edit-time preview. PREVIEW ONLY.
 *
 * It receives a tile document, runs the same core the Node bake runs, hashes with Web Crypto and
 * hands typed arrays out. It never writes an artifact, and nothing it returns is served: the
 * served bytes are the Node bake's, and this entry is held to the same triangle digest by
 * `test/triangle-digest-conformance.test.ts`.
 *
 * It compiles with lib.dom and without @types/node (`tsconfig.browser.json`), so a `node:` import
 * reachable from here is a compile error, not a review comment.
 *
 * **Without `crypto.subtle` there is no preview at all**, the posture
 * `web/packages/app/src/geometry-api.ts` sets for geometry. A page on a non-secure origin has no
 * SubtleCrypto, so the digests cannot be taken, and a preview whose digest nobody took is one
 * nobody can hold to the bake.
 */
import { bakeTile } from '../core/bake.js';
import type { Sha256Hex } from '../core/bake.js';
import { decodeOwd } from '../core/owd.js';
import type { DecodedProjection } from '../core/owd.js';
import type { ProjectionName } from '../core/record-shapes.js';

export class PreviewUnavailable extends Error {}

export interface TilePreview {
  readonly tileInputsDigest: string;
  readonly triangleDigests: ReadonlyMap<ProjectionName, string>;
  /** SHA-256 of the container this preview built in memory. Compared, never served. */
  readonly containerSha256: string;
  /** Typed-array views per projection, with the entries that say which record each range is. */
  readonly projections: readonly DecodedProjection[];
}

function hex(bytes: Uint8Array): string {
  let out = '';
  for (const byte of bytes) out += byte.toString(16).padStart(2, '0');
  return out;
}

function webSha256(subtle: SubtleCrypto): Sha256Hex {
  return async (bytes) => hex(new Uint8Array(await subtle.digest('SHA-256', new Uint8Array(bytes))));
}

/** Preview one tile document. Refuses outright where Web Crypto is missing. */
export async function previewTile(documentBytes: Uint8Array): Promise<TilePreview> {
  const subtle: SubtleCrypto | undefined = globalThis.crypto?.subtle;
  if (subtle === undefined) {
    throw new PreviewUnavailable(
      'there is no crypto.subtle here, so no digest can be taken and there is no preview at all',
    );
  }
  const sha256 = webSha256(subtle);
  const bake = await bakeTile(documentBytes, sha256);
  return {
    tileInputsDigest: bake.tileInputsDigest,
    triangleDigests: bake.triangleDigests,
    containerSha256: await sha256(bake.container),
    projections: decodeOwd(bake.container).projections,
  };
}
