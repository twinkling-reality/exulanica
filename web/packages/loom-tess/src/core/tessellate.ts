/**
 * From a validated tile document to one integer mesh per materialised projection.
 *
 * Every record gets exactly one entry in every materialised projection, in the canonical record
 * order `triangle-digest.ts` defines: drawn; unavailable, with what it needs; not admitted (its
 * grammar's declared semantics do not admit the projection); not a surface in the projection; or
 * halo, context the document carries and the bake never draws. A drawn entry is a contiguous range
 * of vertices and triangles, so "which record does this triangle belong to" is one lookup, and the
 * range carries its own integer extent, so "what is that record's extent" is another. An entry
 * that is not drawn has no extent: an extent nobody measured is not written. In a projection that
 * carries surfaces a drawn entry is made of surfaces, contiguous sub-ranges in the expander's order
 * that share no vertex, each with the grammar's surface role, its orientation and its material.
 *
 * TWO CLAIMS ARE CHECKED HERE RATHER THAN TRUSTED.
 *   - Every vertex of a drawn range lies inside the extent its record states, corners included.
 *     A record's extent is a promise about everything it generates, and a tessellation that
 *     breaks it is refused, not written.
 *   - Each surface of a drawn entry is dressed by the one surface material record that names the
 *     entry's record as its surface and the surface's role as its role. With none, the surface is
 *     still drawn and states that none exists; with two, or one that names another kind of
 *     surface, the tile is refused. An entry repeats a role only on another orientation.
 */
import { canonicalBytes, compareCodeUnits } from './canonical-json.js';
import type { Membership, RecordPayload, TileDocument } from './document.js';
import { statedIdentity, tableOf } from './document.js';
import { coversGround, PROJECTION_DEFINITIONS, ruleFor, TessellationError } from './expand.js';
import type { ExpandContext, Need, Piece, PlanBox } from './expand.js';
import { MATERIAL_RECORD_KIND, recordShapeOf } from './record-shapes.js';
import type { ProjectionName } from './record-shapes.js';
import {
  COORDINATES_PER_TRIANGLE,
  IDENTITY_NOT_STATED,
  MATERIAL_NONE_EXISTS,
  SURFACE_COORDINATES_PER_TRIANGLE,
} from './triangle-digest.js';
import type { DigestEntry, DigestSurface, SurfaceOrientation } from './triangle-digest.js';

export interface PlacedRecord {
  readonly payload: RecordPayload;
  /** Lowercase hex SHA-256 of `recordBytes(payload)`. */
  readonly sha256: string;
  /** The identity the record states, or `not-stated`. */
  readonly identity: string;
  /** Index into the document's grammars. */
  readonly grammar: number;
  readonly membership: Membership;
}

export type MaterialRef =
  | {
      readonly state: 'record';
      /** Index into the records, of the surface material record that dresses the range. */
      readonly record: number;
    }
  /** No material record dresses the range's record and role: the statement that none exists. */
  | { readonly state: typeof MATERIAL_NONE_EXISTS };

export type Triple = readonly [number, number, number];

/** One surface of a drawn entry: a contiguous sub-range with its role, material and orientation. */
export interface DrawnSurface {
  /** The grammar's surface role. */
  readonly role: string;
  /** The surface material record for (entry's record identity, role), or the statement that none exists. */
  readonly material: MaterialRef;
  readonly orientation: SurfaceOrientation;
  readonly first_vertex: number;
  readonly vertex_count: number;
  readonly first_triangle: number;
  readonly triangle_count: number;
}

export interface DrawnEntry {
  readonly record: number;
  readonly state: 'drawn';
  readonly first_vertex: number;
  readonly vertex_count: number;
  readonly first_triangle: number;
  readonly triangle_count: number;
  readonly extent_mm: { readonly min: Triple; readonly max: Triple };
  /** Present exactly in a projection that carries surfaces, covering the entry's range exactly. */
  readonly surfaces?: readonly DrawnSurface[];
}

export type Entry =
  | DrawnEntry
  | { readonly record: number; readonly state: 'unavailable'; readonly needs: readonly Need[] }
  | { readonly record: number; readonly state: 'not_admitted' }
  | { readonly record: number; readonly state: 'not_in_projection' }
  | { readonly record: number; readonly state: 'halo' };

export interface ProjectionMesh {
  readonly name: ProjectionName;
  readonly entries: readonly Entry[];
  /** Absolute integer vertices, three per vertex. */
  readonly vertices: readonly number[];
  /** Indices into `vertices`, three per triangle. */
  readonly indices: readonly number[];
  /** Absolute surface coordinates, two per vertex, in a projection that carries surfaces. */
  readonly surfaceCoordinates?: readonly number[];
}

export interface TessellatedTile {
  readonly document: TileDocument;
  readonly records: readonly PlacedRecord[];
  readonly projections: readonly ProjectionMesh[];
}

/** The canonical bytes a record digest is taken over: `canonical_record` in Python. */
export function recordBytes(payload: RecordPayload): Uint8Array {
  return canonicalBytes({ fields: payload.fields, kind: payload.kind, version: payload.version });
}

/** Every record with its grammar and membership, in the order `tessellate` expects digests in. */
export function documentRecords(
  document: TileDocument,
): readonly { readonly payload: RecordPayload; readonly grammar: number; readonly membership: Membership }[] {
  return document.grammars.flatMap((grammar, index) => [
    ...grammar.owned.map((payload) => ({ payload, grammar: index, membership: 'owned' as const })),
    ...grammar.halo.map((payload) => ({ payload, grammar: index, membership: 'halo' as const })),
  ]);
}

type Box = { min: number[]; max: number[] };

function extentOf(vertices: readonly number[]): { min: Triple; max: Triple } {
  const box: Box = { min: vertices.slice(0, 3), max: vertices.slice(0, 3) };
  vertices.forEach((value, index) => {
    const axis = index % 3;
    if (value < box.min[axis]!) box.min[axis] = value;
    if (value > box.max[axis]!) box.max[axis] = value;
  });
  return { min: [box.min[0]!, box.min[1]!, box.min[2]!], max: [box.max[0]!, box.max[1]!, box.max[2]!] };
}

/** The stated extent of a record, as `[min, max]`, or undefined for a kind that states none. */
function statedExtent(document: TileDocument, record: PlacedRecord): Box | undefined {
  const table = tableOf(document.grammars[record.grammar]!);
  const field = recordShapeOf(table, record.payload.kind)!.extent_field;
  if (field === undefined) return undefined;
  const extent = record.payload.fields[field] as { readonly [corner: string]: number };
  return {
    min: [extent.min_x_mm!, extent.min_y_mm!, extent.min_z_mm!],
    max: [extent.max_x_mm!, extent.max_y_mm!, extent.max_z_mm!],
  };
}

function groundCover(document: TileDocument, records: readonly PlacedRecord[]): PlanBox[] {
  const cover: PlanBox[] = [];
  for (const record of records) {
    if (!coversGround(record.payload.kind)) continue;
    const extent = statedExtent(document, record)!;
    cover.push({ min_x: extent.min[0]!, min_y: extent.min[1]!, max_x: extent.max[0]!, max_y: extent.max[1]! });
  }
  return cover;
}

/**
 * The capsule radius the record's grammar measures for nav_envelope, from its descriptor's
 * contract, or undefined when it measures none.
 */
function capsuleRadius(document: TileDocument, record: PlacedRecord): number | undefined {
  const measures = tableOf(document.grammars[record.grammar]!).measures;
  const clearance = measures.nav_envelope?.capsule_clearance;
  if (clearance === undefined) return undefined;
  return clearance.radius_mm;
}

/** Every surface material record, by the surface it names and the role it dresses. */
function dressings(records: readonly PlacedRecord[]): ReadonlyMap<string, number> {
  const byRole = new Map<string, number>();
  records.forEach((record, index) => {
    if (record.payload.kind !== MATERIAL_RECORD_KIND) return;
    const fields = record.payload.fields;
    const key = `${fields.surface_identity as string} ${fields.role as string}`;
    if (byRole.has(key)) throw new TessellationError(`two material records dress ${key}`);
    byRole.set(key, index);
  });
  return byRole;
}

/** A piece draws whole triangles on whole vertices of its own, and at least one triangle. */
function requireWholePiece(piece: Piece, record: PlacedRecord): void {
  const where = `${record.payload.kind} ${record.identity}`;
  if (piece.vertices.length % 3 !== 0) throw new TessellationError(`${where} draws a piece of partial vertices`);
  if (piece.triangles.length % 3 !== 0) throw new TessellationError(`${where} draws a piece of partial triangles`);
  if (piece.triangles.length === 0) throw new TessellationError(`${where} draws a piece with no triangle`);
  const outside = (): never => {
    throw new TessellationError(`${where} draws a piece whose triangles index outside it`);
  };
  for (const index of piece.triangles) {
    if (!Number.isSafeInteger(index)) outside();
    if (index < 0) outside();
    if (index >= piece.vertices.length / 3) outside();
  }
}

function requireInside(extent: Box | undefined, vertices: readonly number[], record: PlacedRecord): void {
  if (extent === undefined) {
    throw new TessellationError(`${record.payload.kind} ${record.identity} draws and states no extent`);
  }
  const outside = (): never => {
    throw new TessellationError(`${record.payload.kind} ${record.identity} draws a vertex outside the extent it states`);
  };
  vertices.forEach((value, index) => {
    const axis = index % 3;
    if (value < extent.min[axis]!) outside();
    if (value > extent.max[axis]!) outside();
  });
}

/**
 * Tessellate a document whose record digests have already been taken, in `documentRecords` order.
 * Digests are an argument because core cannot hash.
 */
export function tessellate(document: TileDocument, digests: readonly string[]): TessellatedTile {
  const inOrder = documentRecords(document);
  if (digests.length !== inOrder.length) {
    throw new RangeError(`${inOrder.length} records and ${digests.length} digests`);
  }
  const placed: PlacedRecord[] = inOrder.map((item, index) => {
    const identity = statedIdentity(tableOf(document.grammars[item.grammar]!), item.payload);
    return {
      payload: item.payload,
      sha256: digests[index]!,
      identity: identity === undefined ? IDENTITY_NOT_STATED : identity,
      grammar: item.grammar,
      membership: item.membership,
    };
  });
  placed.sort((a, b) => {
    const byKind = compareCodeUnits(a.payload.kind, b.payload.kind);
    if (byKind !== 0) return byKind;
    return compareCodeUnits(a.sha256, b.sha256);
  });
  placed.forEach((record, index) => {
    if (index > 0) {
      if (record.sha256 === placed[index - 1]!.sha256) {
        throw new RangeError('two records share a digest, so the record order would tie');
      }
    }
  });

  const cover = groundCover(document, placed);
  const contextFor = (record: PlacedRecord): ExpandContext => ({
    tileSizeMm: document.tile.fields.tile_size_mm as number,
    groundCover: cover,
    capsuleRadiusMm: capsuleRadius(document, record),
  });
  const dressed = dressings(placed);
  const materialFor = (record: PlacedRecord, role: string): MaterialRef => {
    const dressing = dressed.get(`${record.identity} ${role}`);
    if (dressing === undefined) return { state: MATERIAL_NONE_EXISTS };
    if (placed[dressing]!.payload.fields.surface_kind !== record.payload.kind) {
      throw new TessellationError(`the material dressing ${record.identity} names another kind of surface`);
    }
    return { state: 'record', record: dressing };
  };

  const projections = PROJECTION_DEFINITIONS.map((definition): ProjectionMesh => {
    const name = definition.name;
    const vertices: number[] = [];
    const indices: number[] = [];
    const surfaceCoordinates: number[] = [];
    const entries = placed.map((record, recordIndex): Entry => {
      if (record.membership === 'halo') return { record: recordIndex, state: 'halo' };
      const admitted = document.grammars[record.grammar]!.declared_semantics.admissible_uses;
      if (!admitted.includes(name)) return { record: recordIndex, state: 'not_admitted' };
      const rule = ruleFor(name, record.payload.kind);
      switch (rule.rule) {
        case 'not_in_projection':
          return { record: recordIndex, state: 'not_in_projection' };
        case 'needs':
          return { record: recordIndex, state: 'unavailable', needs: rule.needs };
        case 'expand': {
          const expansion = rule.expand(record.payload.fields, contextFor(record));
          if (expansion.state === 'unavailable') {
            return { record: recordIndex, state: 'unavailable', needs: expansion.needs };
          }
          const pieces = expansion.pieces;
          if (pieces.length === 0) throw new TessellationError(`${record.payload.kind} drew no piece`);
          const allVertices = pieces.flatMap((piece) => [...piece.vertices]);
          requireInside(statedExtent(document, record), allVertices, record);
          const firstVertex = vertices.length / 3;
          const firstTriangle = indices.length / 3;
          const surfaces: DrawnSurface[] = [];
          const seen = new Set<string>();
          for (const piece of pieces) {
            const pieceVertex = vertices.length / 3;
            const pieceTriangle = indices.length / 3;
            requireWholePiece(piece, record);
            for (const value of piece.vertices) vertices.push(value);
            for (const index of piece.triangles) indices.push(pieceVertex + index);
            const surface = piece.surface;
            if (!definition.surfaces) {
              if (surface !== undefined) throw new TessellationError(`${name} carries no surfaces`);
              continue;
            }
            if (surface === undefined) throw new TessellationError(`${name} needs a surface for ${record.payload.kind}`);
            if (surface.coordinates.length !== (piece.vertices.length / 3) * 2) {
              throw new TessellationError(`${record.payload.kind} gave surface coordinates for other vertices`);
            }
            const face = `${surface.role} ${surface.orientation}`;
            if (seen.has(face)) {
              throw new TessellationError(`${record.payload.kind} ${record.identity} draws the ${face} surface twice`);
            }
            seen.add(face);
            for (const value of surface.coordinates) surfaceCoordinates.push(value);
            surfaces.push({
              role: surface.role,
              material: materialFor(record, surface.role),
              orientation: surface.orientation,
              first_vertex: pieceVertex,
              vertex_count: piece.vertices.length / 3,
              first_triangle: pieceTriangle,
              triangle_count: piece.triangles.length / 3,
            });
          }
          const drawn = {
            record: recordIndex,
            state: 'drawn',
            first_vertex: firstVertex,
            vertex_count: vertices.length / 3 - firstVertex,
            first_triangle: firstTriangle,
            triangle_count: indices.length / 3 - firstTriangle,
            extent_mm: extentOf(allVertices),
          } as const;
          return definition.surfaces ? { ...drawn, surfaces } : drawn;
        }
      }
    });
    if (!definition.surfaces) return { name, entries, vertices, indices };
    return { name, entries, vertices, indices, surfaceCoordinates };
  });
  return { document, records: placed, projections };
}

/**
 * The triangle digest's entries for one projection mesh, de-indexed. Shared by the bake and by
 * the container verifier, so the two can only disagree about their inputs, never their reading.
 */
export function digestEntries(
  records: readonly Pick<PlacedRecord, 'payload' | 'sha256' | 'identity'>[],
  mesh: {
    readonly entries: readonly Entry[];
    readonly indices: ArrayLike<number>;
    readonly vertices: ArrayLike<number>;
    readonly surfaceCoordinates?: ArrayLike<number>;
  },
): DigestEntry[] {
  return mesh.entries.map((entry): DigestEntry => {
    const record = records[entry.record]!;
    const head = { kind: record.payload.kind, recordSha256: record.sha256, identity: record.identity };
    switch (entry.state) {
      case 'drawn': {
        const deindexed = (firstTriangle: number, triangleCount: number) => {
          const triangles = new Array<number>(triangleCount * COORDINATES_PER_TRIANGLE);
          const coordinates = new Array<number>(triangleCount * SURFACE_COORDINATES_PER_TRIANGLE);
          const end = (firstTriangle + triangleCount) * 3;
          let out = 0;
          let outSurface = 0;
          for (let corner = firstTriangle * 3; corner < end; corner += 1) {
            const vertex = mesh.indices[corner]!;
            triangles[out] = mesh.vertices[vertex * 3]!;
            triangles[out + 1] = mesh.vertices[vertex * 3 + 1]!;
            triangles[out + 2] = mesh.vertices[vertex * 3 + 2]!;
            out += 3;
            if (mesh.surfaceCoordinates !== undefined) {
              coordinates[outSurface] = mesh.surfaceCoordinates[vertex * 2]!;
              coordinates[outSurface + 1] = mesh.surfaceCoordinates[vertex * 2 + 1]!;
              outSurface += 2;
            }
          }
          return { triangles, coordinates };
        };
        if (entry.surfaces === undefined) {
          return { ...head, state: 'drawn', triangles: deindexed(entry.first_triangle, entry.triangle_count).triangles };
        }
        const surfaces = entry.surfaces.map((surface): DigestSurface => {
          const { triangles, coordinates } = deindexed(surface.first_triangle, surface.triangle_count);
          return {
            role: surface.role,
            material: surface.material.state === 'record' ? records[surface.material.record]!.sha256 : MATERIAL_NONE_EXISTS,
            orientation: surface.orientation,
            triangles,
            coordinates,
          };
        });
        return { ...head, state: 'drawn', surfaces };
      }
      case 'unavailable':
        return { ...head, state: 'unavailable', needs: entry.needs };
      case 'not_admitted':
      case 'not_in_projection':
      case 'halo':
        return { ...head, state: entry.state };
    }
  });
}
