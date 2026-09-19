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
import { coordinateUnitOf, readTileDocument, TILE_DOCUMENT_PROFILE, TileDocumentError, tileTableOf } from './document.js';
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
  /**
   * The coordinate unit the DOCUMENT stated, or that its version fixes. Not this build's constant.
   *
   * The container header asserts a unit for the records it carries, and that assertion is true only
   * because a bake refuses a document stating another one. Reporting what was read is what ties the
   * two together: a bake that could not say which unit it had just read would be reporting a belief
   * in the shape of a reading, and the day the refusal stopped being reached the header would go on
   * asserting millimetres over records that were not.
   */
  readonly coordinateUnit: string;
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
 * Every record kind of every grammar version this tessellator reads, with EVERY version it reads
 * that kind at, ascending.
 *
 * THIS WAS ONE VERSION A KIND, and it could not stay that way. A map from kind to a single version
 * said what it named only while this tessellator read one grammar version; reading two, it has a
 * key written twice and would have taken whichever table came last, silently, into a bake
 * parameter every tile's key is built from. City version 2 and version 3 differ in `city.tile`
 * (ADR-0024's coordinate unit) and agree on every other kind, which is exactly the case a single
 * version per kind cannot state.
 *
 * A list, ascending, rather than the newest: the newest is a claim about what a producer writes,
 * and this parameter is about what the bake READS. Those are different questions and the bake key
 * must move when either does.
 */
export function recordShapeVersions(tables: readonly GrammarTable[]): { [kind: string]: number[] } {
  const versions: { [kind: string]: number[] } = {};
  for (const table of tables) {
    for (const shape of table.shapes.records) {
      if (shape.kind === undefined) throw new RangeError(`${shape.shape} is a record with no kind`);
      if (shape.version === undefined) throw new RangeError(`${shape.shape} is a record with no version`);
      const read = versions[shape.kind];
      if (read === undefined) versions[shape.kind] = [shape.version];
      else if (!read.includes(shape.version)) read.push(shape.version);
    }
  }
  for (const kind of Object.keys(versions).sort()) versions[kind]!.sort((a, b) => a - b);
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

/**
 * ADR-0024 POINT 3: one millimetre is a constant of this tessellator version, not something a
 * document may choose. Two quanta coexisting in one world would put a scaling step, and a place to
 * be wrong by a factor of a thousand while still looking like a plausible building, into every rule
 * that reads two documents.
 *
 * TWO REFUSALS, NOT ONE, AND THIS IS THE SECOND. The grammar refuses a unit its own version does
 * not admit, through the tile record's closed values. This refuses a unit THIS BUILD does not work
 * in, which is a different question with a different answer the day a grammar admits two units
 * while a build still writes one.
 *
 * SO IT IS VACUOUS TODAY, deliberately. Every city version this tessellator reads either fixes
 * millimetre or closes `coordinate_unit` to millimetre alone, so the shape check always fires
 * first and a bake never reaches this. It costs one comparison and it will fire on the day
 * somebody builds the case that invalidates it, which is the point of writing it now.
 *
 * NOTHING PROVES A BAKE CALLS THIS, and that is stated rather than papered over. The grammar
 * refuses a foreign unit before a bake reaches this, so removing the call changes no observable
 * behaviour: deleting it was tried and 83 tests passed. Returning the unit rather than nothing was
 * the second attempt, so the caller would need the value; that fails too, because `coordinateUnitOf`
 * returns a string as well and the two are interchangeable to the compiler. A branded return type
 * would settle it and is ceremony around a check that cannot fire.
 *
 * So the honest statement is the one a later reader needs: THE CALL IS NOT COVERED, its absence
 * costs nothing while every version this tessellator reads admits one unit, and whoever adds a
 * version that admits a second is the person who must check this path is still wired. The bake
 * reports the unit it read, which is tested, so what IS covered is that the unit reaches the bake.
 */
export function checkCoordinateUnit(unit: string): string {
  if (unit === COORDINATE_UNIT) return unit;
  throw new TileDocumentError(
    `tile: its coordinates are in ${JSON.stringify(unit)} and this tessellator writes `
      + `${JSON.stringify(COORDINATE_UNIT)}; the quantum is a constant of the tessellator version, `
      + 'so a document in another unit is refused rather than scaled',
  );
}

/** Bake one tile document. Same bytes in, same bytes out, on any host that hashes correctly. */
export async function bakeTile(documentBytes: Uint8Array, sha256: Sha256Hex): Promise<Bake> {
  const document = readTileDocument(documentBytes);
  if (document.tile.fields.lod !== MATERIALISED_LOD) {
    throw new TileDocumentError(
      `tile.fields.lod: this tessellator draws level of detail ${MATERIALISED_LOD} only, and a tile `
        + 'at another level is refused rather than drawn at this one',
    );
  }
  const coordinateUnit = checkCoordinateUnit(
    coordinateUnitOf(tileTableOf(GRAMMAR_TABLES, document.tile, 'tile'), document.tile),
  );
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
  return { container, coordinateUnit, tileInputsDigest, triangleDigests, tessellation };
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
