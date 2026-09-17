/**
 * The bake, and its inverse check, written once for both hosts.
 *
 * Core cannot hash, so the host's SHA-256 is an argument: the Node entry passes `node:crypto`, the
 * browser entry passes Web Crypto. Everything else, from the document's first byte to the
 * container's last, is this one code path, which is what makes "the Node bake and the browser
 * preview agree" a statement about hashing alone.
 */
import { canonicalBytes } from './canonical-json.js';
import type { CanonicalValue } from './canonical-json.js';
import { readTileDocument, TILE_DOCUMENT_PROFILE, TileDocumentError } from './document.js';
import { MATERIALISED_LOD, MATERIALISED_PROJECTIONS, TESSELLATOR_SOURCE_VERSION } from './expand.js';
import { COORDINATE_UNIT, decodeOwd, encodeOwd, OWD_CONTAINER, OwdError } from './owd.js';
import type { DecodedOwd, OwdHeader } from './owd.js';
import { RECORD_SHAPES, TILE_SHAPE } from './record-shapes.js';
import type { ProjectionName } from './record-shapes.js';
import { digestEntries, documentRecords, recordBytes, tessellate } from './tessellate.js';
import type { TessellatedTile } from './tessellate.js';
import { TRIANGLE_DIGEST_PROFILE, trianglePreimage } from './triangle-digest.js';

/** A host's SHA-256, as lowercase hex. */
export type Sha256Hex = (bytes: Uint8Array) => Promise<string>;

export interface Bake {
  /** The `.owd` bytes. Their SHA-256 is the artifact's content hash. */
  readonly container: Uint8Array;
  /** SHA-256 of the tile record's canonical payload: the tile's own stable key. */
  readonly tileInputsDigest: string;
  readonly triangleDigests: ReadonlyMap<ProjectionName, string>;
  readonly tessellation: TessellatedTile;
}

function boundOf(field: string): number {
  const shape = TILE_SHAPE.fields[field];
  if (shape === undefined) throw new RangeError(`the tile record has no ${field}`);
  if (shape.type !== 'int') throw new RangeError(`the tile record's ${field} is not an integer`);
  if (shape.min === undefined) throw new RangeError(`the tile record's ${field} is not fixed`);
  if (shape.min !== shape.max) throw new RangeError(`the tile record's ${field} is not fixed`);
  return shape.min;
}

/**
 * Everything that changes the bytes a bake writes, as the bake stage's parameters must state it.
 * `tests/test_bake_determinism.py` holds `exulanica.ingest.stages.STAGES["baked_tile"].params`
 * equal to this, so the registry and the tessellator cannot drift apart unnoticed.
 */
export const BAKE_PARAMETERS = {
  container: OWD_CONTAINER,
  tessellator: TESSELLATOR_SOURCE_VERSION,
  triangle_digest: TRIANGLE_DIGEST_PROFILE,
  tile_document: TILE_DOCUMENT_PROFILE,
  coordinate_unit: COORDINATE_UNIT,
  projections: [...MATERIALISED_PROJECTIONS],
  lod: MATERIALISED_LOD,
  tile_size_mm: boundOf('tile_size_mm'),
  halo_radius_mm: boundOf('halo_radius_mm'),
  record_shapes: Object.fromEntries(
    [TILE_SHAPE, ...RECORD_SHAPES].map((shape) => [shape.kind, shape.version]),
  ),
} as const;

/** Bake one tile document. Same bytes in, same bytes out, on any host that hashes correctly. */
export async function bakeTile(documentBytes: Uint8Array, sha256: Sha256Hex): Promise<Bake> {
  const document = readTileDocument(documentBytes);
  if (document.tile.fields.lod !== MATERIALISED_LOD) {
    throw new TileDocumentError(
      `tile.fields.lod: this tessellator draws level of detail ${MATERIALISED_LOD} only, and a tile `
        + 'at another level is refused rather than drawn at this one',
    );
  }
  const recordDigests: string[] = [];
  for (const record of documentRecords(document)) recordDigests.push(await sha256(recordBytes(record)));
  const tessellation = tessellate(document, recordDigests);
  const tileInputsDigest = await sha256(canonicalBytes(document.tile as unknown as CanonicalValue));
  const triangleDigests = new Map<ProjectionName, string>();
  for (const mesh of tessellation.projections) {
    const preimage = trianglePreimage(mesh.name, digestEntries(tessellation.records, mesh));
    triangleDigests.set(mesh.name, await sha256(preimage));
  }
  const container = encodeOwd(tessellation, { tileInputs: tileInputsDigest, triangles: triangleDigests });
  return { container, tileInputsDigest, triangleDigests, tessellation };
}

/** The tile document a container's header describes, in canonical record order. */
export function documentOf(header: OwdHeader): Uint8Array {
  return canonicalBytes({
    profile: TILE_DOCUMENT_PROFILE,
    tile: header.tile,
    grammars: header.grammars.map((grammar, index) => ({
      ...grammar,
      records: header.records
        .filter((record) => record.grammar === index)
        .map((record) => ({ fields: record.fields, kind: record.kind, version: record.version })),
    })),
  } as unknown as CanonicalValue);
}

function sameBytes(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  for (let index = 0; index < a.length; index += 1) {
    if (a[index] !== b[index]) return false;
  }
  return true;
}

/**
 * Decode a container and prove its content: bake the header's own records again and require
 * every byte to match. That covers every digest in the header, every range, the float payload
 * and the layout at once, with no second reading of any of them.
 */
export async function verifyOwd(bytes: Uint8Array, sha256: Sha256Hex): Promise<DecodedOwd> {
  const decoded = decodeOwd(bytes);
  const rebaked = await bakeTile(documentOf(decoded.header), sha256);
  if (!sameBytes(rebaked.container, bytes)) {
    throw new OwdError('.owd refused: its bytes are not what its own records bake to');
  }
  return decoded;
}
