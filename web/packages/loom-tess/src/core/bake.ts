/**
 * The bake, and its inverse check, written once for both hosts.
 *
 * Core cannot hash, so the host's SHA-256 is an argument: the Node entry passes `node:crypto`, the
 * browser entry passes Web Crypto. Everything else, from the document's first byte to the
 * container's last, is this one code path, which is what makes "the Node bake and the browser
 * preview agree" a statement about hashing alone.
 */
import { canonicalBytes, compareCodeUnits } from './canonical-json.js';
import type { CanonicalValue } from './canonical-json.js';
import { readTileDocument, TILE_DOCUMENT_PROFILE, TileDocumentError } from './document.js';
import { MATERIALISED_LOD, MATERIALISED_PROJECTIONS, TESSELLATOR_SOURCE_VERSION } from './expand.js';
import { COORDINATE_UNIT, decodeOwd, encodeOwd, OWD_CONTAINER, OwdError } from './owd.js';
import type { DecodedOwd, OwdHeader, OwdRecord } from './owd.js';
import { GRAMMAR_TABLES, tileShapeOf } from './record-shapes.js';
import type { GrammarTable, ProjectionName } from './record-shapes.js';
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

/**
 * A tile record field's fixed bound, which is one number for the bake stage however many grammar
 * versions state it. Every version this tessellator reads must fix it to the same value: a tile
 * size or halo radius is a parameter of the bake, and two versions disagreeing about one would
 * make this parameter a statement about whichever table was read first.
 */
export function boundOf(tables: readonly GrammarTable[], name: string): number {
  const bounds: number[] = [];
  for (const table of tables) {
    const field = tileShapeOf(table).fields.find((candidate) => candidate.name === name);
    if (field === undefined) throw new RangeError(`the tile record of ${table.grammar_id} ${table.grammar_version} has no ${name}`);
    if (field.kind !== 'integer') throw new RangeError(`the tile record's ${name} is not an integer`);
    if (field.minimum === undefined) throw new RangeError(`the tile record's ${name} is not fixed`);
    if (field.minimum !== field.maximum) throw new RangeError(`the tile record's ${name} is not fixed`);
    if (!bounds.includes(field.minimum)) bounds.push(field.minimum);
  }
  if (bounds.length !== 1) throw new RangeError(`the grammars this tessellator reads fix ${name} at ${JSON.stringify(bounds)}, and a bake states one`);
  return bounds[0]!;
}

/**
 * Every record kind of every grammar version this tessellator reads, with its version.
 *
 * ONE VERSION PER KIND, AND A SECOND ONE IS REFUSED RATHER THAN OVERWRITTEN. This map keyed by
 * kind cannot say that a kind is read at two versions, so the day two tables declare one kind
 * differently it stops being able to state what it names, and a silent last-one-wins would put
 * whichever table sat last into a bake parameter that every tile's key is built from.
 */
export function recordShapeVersions(tables: readonly GrammarTable[]): { [kind: string]: number } {
  const versions: { [kind: string]: number } = {};
  for (const table of tables) {
    for (const shape of table.shapes.records) {
      if (shape.kind === undefined) throw new RangeError(`${shape.shape} is a record with no kind`);
      if (shape.version === undefined) throw new RangeError(`${shape.shape} is a record with no version`);
      const already = versions[shape.kind];
      if (already !== undefined && already !== shape.version) {
        throw new RangeError(`${shape.kind} is read at versions ${already} and ${shape.version}, and this states one version a kind`);
      }
      versions[shape.kind] = shape.version;
    }
  }
  return versions;
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
  tile_size_mm: boundOf(GRAMMAR_TABLES, 'tile_size_mm'),
  halo_radius_mm: boundOf(GRAMMAR_TABLES, 'halo_radius_mm'),
  record_shapes: recordShapeVersions(GRAMMAR_TABLES),
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
  for (const record of documentRecords(document)) recordDigests.push(await sha256(recordBytes(record.payload)));
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

/** The document's order within a membership list: kind, then version, then identity. */
function documentOrder(a: OwdRecord, b: OwdRecord): number {
  const byKind = compareCodeUnits(a.kind, b.kind);
  if (byKind !== 0) return byKind;
  if (a.version !== b.version) return a.version - b.version;
  return compareCodeUnits(a.identity, b.identity);
}

/** The tile document a container's header describes, with each membership list in document order. */
export function documentOf(header: OwdHeader): Uint8Array {
  const listed = (grammar: number, membership: OwdRecord['membership']): unknown[] =>
    header.records
      .filter((record) => record.grammar === grammar && record.membership === membership)
      .sort(documentOrder)
      .map((record) => ({ fields: record.fields, kind: record.kind, version: record.version }));
  return canonicalBytes({
    profile: TILE_DOCUMENT_PROFILE,
    tile: header.tile,
    grammars: header.grammars.map((grammar, index) => ({
      declared_semantics: grammar.declared_semantics,
      descriptor_sha256: grammar.descriptor_sha256,
      external: grammar.external,
      grammar_id: grammar.grammar_id,
      grammar_version: grammar.grammar_version,
      halo: listed(index, 'halo'),
      owned: listed(index, 'owned'),
      subject_identity: grammar.subject_identity,
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
