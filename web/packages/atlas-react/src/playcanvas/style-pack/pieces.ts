import * as pc from 'playcanvas';
import { readStylePiece, swatchKeyOf, type ResolvedModule, type ResolvedStylePack, type StylePackFile } from '@exulanica/atlas-core';

/**
 * A style pack's pieces, loaded for drawing.
 *
 * Each piece file a pack's modules name is fetched by the caller (a committed pack's files ship with
 * the page; a library pack's come from the store), held here to the size and sha256 its manifest
 * states, read as a palette piece and uploaded as one mesh per swatch. A group's swatch is named by
 * KEY, looked up in the palette of the manifest that stated the module, so a pack drawn on another
 * recolours a base pack's pieces by restating a swatch under the same key.
 *
 * Bytes that are not what the manifest states, or a piece coloured outside its palette, are refused
 * by name; nothing partial is kept. The library owns its meshes until `dispose`, whatever dressings
 * draw them.
 */

export class PackPieceRefusal extends Error {
  override readonly name = 'PackPieceRefusal';
}

export interface LoadedPieceGroup {
  /** The swatch key this group is drawn in. */
  readonly swatch: string;
  /** The group uploaded, for drawing the piece as it is (instanced). */
  readonly mesh: pc.Mesh;
  /** The group's triangles, for placing the piece stretched (baked). Metres, glTF axes. */
  readonly positions: Float32Array;
  readonly normals: Float32Array;
  readonly indices: Uint32Array;
}

export interface LoadedPiece {
  readonly groups: readonly LoadedPieceGroup[];
  readonly triangles: number;
  /** Metres, glTF axes: [minX, minY, minZ, maxX, maxY, maxZ]. */
  readonly bounds: readonly [number, number, number, number, number, number];
}

export interface PackPieces {
  /** The piece a module's file is, as that module's manifest colours it. */
  get(module: ResolvedModule, file: StylePackFile): LoadedPiece | undefined;
  readonly count: number;
  dispose(): void;
}

/** How the caller fetches a file a manifest names. */
export type PieceBytes = (file: StylePackFile) => Promise<Uint8Array<ArrayBuffer>>;

const hex = (digest: ArrayBuffer): string => [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');

const keyOf = (module: ResolvedModule, file: StylePackFile): string => `${String(module.stated)}:${file.sha256}`;

/** A piece fetched, held to its manifest and read: its triangles by swatch key, not yet uploaded. */
export interface FetchedPiece {
  readonly groups: readonly Omit<LoadedPieceGroup, 'mesh'>[];
  readonly triangles: number;
  readonly bounds: LoadedPiece['bounds'];
}

/** A pack's pieces fetched, keyed by the manifest that stated each and its digest. */
export interface FetchedPieces {
  readonly pieces: ReadonlyMap<string, FetchedPiece>;
}

/**
 * Fetch and read the pieces of the modules `roles` names (every variant's level-of-detail 0 file),
 * in the resolved `pack`, without a renderer. `table` is the 256 values of
 * `exulanica.srgb8-linear16/v1`. Every piece is checked before any is kept.
 */
export async function fetchPackPieces(
  pack: ResolvedStylePack,
  roles: readonly string[],
  table: readonly number[],
  bytesOf: PieceBytes,
): Promise<FetchedPieces> {
  const wanted = new Map<string, { module: ResolvedModule; file: StylePackFile }>();
  for (const role of roles) {
    const module = pack.modules[role];
    if (module === undefined) continue;
    for (const variant of module.variants) {
      const file = module.files.get(variant.file)!;
      wanted.set(keyOf(module, file), { module, file });
    }
  }
  const pieces = new Map<string, FetchedPiece>();
  const settled = await Promise.allSettled([...wanted].map(async ([key, { module, file }]) => {
    const bytes = await bytesOf(file);
    if (bytes.byteLength !== file.bytes) throw new PackPieceRefusal(`${file.path} is ${String(bytes.byteLength)} bytes; its manifest states ${String(file.bytes)}`);
    const digest = hex(await crypto.subtle.digest('SHA-256', bytes));
    if (digest !== file.sha256) throw new PackPieceRefusal(`${file.path} is not the bytes its manifest names`);
    const piece = readStylePiece(bytes, table);
    const groups = piece.groups.map((group) => {
      const swatch = swatchKeyOf(pack, module, group.srgb8);
      if (swatch === null) throw new PackPieceRefusal(`${file.path} is coloured ${group.srgb8.join(',')}, no swatch of its pack`);
      return { swatch, positions: group.positions, normals: group.normals, indices: group.indices };
    });
    pieces.set(key, { groups, triangles: piece.triangles, bounds: piece.bounds });
  }));
  const failed = settled.find((outcome): outcome is PromiseRejectedResult => outcome.status === 'rejected');
  if (failed !== undefined) throw failed.reason;
  return { pieces };
}

/** Upload fetched pieces as one mesh per swatch each. The library owns the meshes until `dispose`. */
export function uploadPackPieces(device: pc.GraphicsDevice, fetched: FetchedPieces): PackPieces {
  const loaded = new Map<string, LoadedPiece>();
  for (const [key, piece] of fetched.pieces) {
    const groups = piece.groups.map((group) => {
      const mesh = new pc.Mesh(device);
      mesh.setPositions(group.positions);
      mesh.setNormals(group.normals);
      mesh.setIndices(group.indices);
      mesh.update(pc.PRIMITIVE_TRIANGLES);
      // The library holds every mesh, so a dressing's instances going away never destroys one.
      mesh.incRefCount();
      return { ...group, mesh };
    });
    loaded.set(key, { groups, triangles: piece.triangles, bounds: piece.bounds });
  }
  let disposed = false;
  return {
    get: (module, file) => loaded.get(keyOf(module, file)),
    get count() {
      return loaded.size;
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      for (const piece of loaded.values()) {
        for (const group of piece.groups) {
          group.mesh.decRefCount();
          group.mesh.destroy();
        }
      }
      loaded.clear();
    },
  };
}

/** Fetch, read and upload the pieces of the modules `roles` names, as `fetchPackPieces` then `uploadPackPieces`. */
export async function loadPackPieces(
  device: pc.GraphicsDevice,
  pack: ResolvedStylePack,
  roles: readonly string[],
  table: readonly number[],
  bytesOf: PieceBytes,
): Promise<PackPieces> {
  return uploadPackPieces(device, await fetchPackPieces(pack, roles, table, bytesOf));
}
