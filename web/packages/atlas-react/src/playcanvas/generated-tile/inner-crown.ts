import * as pc from 'playcanvas';
import type { DecodedTextureSet } from '@exulanica/atlas-core';
import { isRenderLook, type TileLook } from './look.js';
import { applyShading } from './shading.js';

/**
 * A tree's inner crown: what the gaps between its outer leaves show.
 *
 * A street tree's crown is a closed shell drawn with a cutout set, leaves with gaps between them
 * (`cc0.broadleaf-foliage`), so through every gap a viewer sees straight through the tree to the
 * sky or the wall behind it, and the crown reads as a speckled shell with pale holes in it. A real
 * crown is leaves all the way in, darker inward because the outer leaves shade them. So under each
 * closed shell a cutout set draws, the page draws that shell again, moved in along its own normals
 * by `INNER_CROWN_INSET_M`, opaque, in the set's own leaf colour (the mean of its opaque texels,
 * averaged in linear light) at `INNER_CROWN_SHADE` of its light: through a gap the viewer sees
 * leaves in shade, and the crown's edge stays the leaves' own.
 *
 * ONLY SHELLS THAT CLOSE. A piece of the surface is drawn again only where every edge of its
 * triangles, matched by its end points to a tenth of a millimetre, is shared by exactly two of
 * them, so a cutout laid on an open card keeps its holes. Each closed piece moves in on its own,
 * every point along the mean normal of the vertices that stand there, so a seam where the surface's
 * vertices are split moves as one and opens no crack.
 *
 * PRESENTATION ONLY. The inner crown casts no shadow (the dappled shadow is the leaves'), is never
 * inked or dressed by a pack (its entity is not named as a tile's texture set is), and nothing
 * walks on, picks or collides with it. Its two figures were judged from pictures of generated towns
 * in the shipped looks.
 */

/** How far inside its leaves a crown's inner shell lies: deep enough that a gap shows depth, metres. */
export const INNER_CROWN_INSET_M = 0.3;
/** The share of the leaves' own colour, in linear light, the inner shell is drawn in: leaves in shade. */
export const INNER_CROWN_SHADE = 0.6;
/** How finely points are matched when an edge is looked for twice, metres: a tenth of a millimetre. */
const WELD_M = 0.0001;

/** Triangles in the renderer frame: metres, unit normals, three vertex numbers a triangle. */
export interface ShellGeometry {
  readonly positions: number[];
  readonly normals: number[];
  readonly indices: number[];
}

/**
 * The closed pieces of a surface's triangles, each moved in along its normals by `insetM`; null when
 * no piece closes. Winding and normals are the surface's own, so the inner shell faces out as its
 * leaves do.
 */
export function innerShells(
  positions: ArrayLike<number>,
  normals: ArrayLike<number>,
  indices: ArrayLike<number>,
  insetM: number = INNER_CROWN_INSET_M,
): ShellGeometry | null {
  const vertices = positions.length / 3;
  // One number for every point the surface's vertices stand at.
  const weld = new Int32Array(vertices);
  const points = new Map<string, number>();
  for (let vertex = 0; vertex < vertices; vertex += 1) {
    const key = `${Math.round(positions[vertex * 3]! / WELD_M)},${Math.round(positions[vertex * 3 + 1]! / WELD_M)},${Math.round(positions[vertex * 3 + 2]! / WELD_M)}`;
    let point = points.get(key);
    if (point === undefined) {
      point = points.size;
      points.set(key, point);
    }
    weld[vertex] = point;
  }
  // The pieces: points joined by a triangle are one piece.
  const parent = new Int32Array(points.size);
  for (let point = 0; point < parent.length; point += 1) parent[point] = point;
  const find = (point: number): number => {
    let root = point;
    while (parent[root] !== root) root = parent[root]!;
    while (parent[point] !== root) {
      const next = parent[point]!;
      parent[point] = root;
      point = next;
    }
    return root;
  };
  const edges = new Map<string, number>();
  for (let corner = 0; corner < indices.length; corner += 3) {
    const triangle = [weld[indices[corner]!]!, weld[indices[corner + 1]!]!, weld[indices[corner + 2]!]!];
    for (let side = 0; side < 3; side += 1) {
      const a = triangle[side]!;
      const b = triangle[(side + 1) % 3]!;
      const key = a < b ? `${a},${b}` : `${b},${a}`;
      edges.set(key, (edges.get(key) ?? 0) + 1);
      const ra = find(a);
      const rb = find(b);
      if (ra !== rb) parent[ra] = rb;
    }
  }
  // A piece is open where any edge of it is met by one triangle, or by more than two.
  const open = new Set<number>();
  for (const [key, count] of edges) {
    if (count !== 2) open.add(find(Number(key.slice(0, key.indexOf(',')))));
  }
  // Each point moves along the mean of the normals of the vertices that stand at it.
  const along = new Float64Array(points.size * 3);
  for (let vertex = 0; vertex < vertices; vertex += 1) {
    const point = weld[vertex]!;
    for (let axis = 0; axis < 3; axis += 1) along[point * 3 + axis] = along[point * 3 + axis]! + normals[vertex * 3 + axis]!;
  }
  const out: ShellGeometry = { positions: [], normals: [], indices: [] };
  const made = new Map<number, number>();
  for (let corner = 0; corner < indices.length; corner += 3) {
    const first = indices[corner]!;
    if (open.has(find(weld[first]!))) continue;
    for (let at = 0; at < 3; at += 1) {
      const vertex = indices[corner + at]!;
      let index = made.get(vertex);
      if (index === undefined) {
        const point = weld[vertex]!;
        const nx = along[point * 3]!, ny = along[point * 3 + 1]!, nz = along[point * 3 + 2]!;
        const length = Math.hypot(nx, ny, nz);
        const [ux, uy, uz] = length > 0 ? [nx / length, ny / length, nz / length] : [0, 1, 0];
        index = out.positions.length / 3;
        made.set(vertex, index);
        out.positions.push(
          positions[vertex * 3]! - ux * insetM,
          positions[vertex * 3 + 1]! - uy * insetM,
          positions[vertex * 3 + 2]! - uz * insetM,
        );
        out.normals.push(ux, uy, uz);
      }
      out.indices.push(index);
    }
  }
  return out.indices.length === 0 ? null : out;
}

const toLinear = (byte: number): number => {
  const c = byte / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
};
const toSrgb = (linear: number): number => {
  const c = Math.min(1, Math.max(0, linear));
  return c <= 0.0031308 ? c * 12.92 : 1.055 * c ** (1 / 2.4) - 0.055;
};

/**
 * The colour of a cutout set's leaves in their own shade: the mean of its texels at or above its
 * cutoff (sRGB bytes with coverage, four to a texel), in linear light, times `shade`, as the 0 to 1
 * sRGB a material's colour takes; null for a set that is not a cutout or has no texel that stands.
 */
export function shadedLeafColour(set: Pick<DecodedTextureSet, 'classParameters' | 'maps'>, shade: number = INNER_CROWN_SHADE): readonly [number, number, number] | null {
  if (set.classParameters.materialClass !== 'cutout') return null;
  const texels = set.maps.base_color_coverage;
  if (texels === undefined) return null;
  const cutoff = set.classParameters.alphaCutoff;
  let r = 0, g = 0, b = 0, counted = 0;
  for (let at = 0; at + 3 < texels.length; at += 4) {
    if (texels[at + 3]! < cutoff) continue;
    r += toLinear(texels[at]!);
    g += toLinear(texels[at + 1]!);
    b += toLinear(texels[at + 2]!);
    counted += 1;
  }
  if (counted === 0) return null;
  return [toSrgb((r / counted) * shade), toSrgb((g / counted) * shade), toSrgb((b / counted) * shade)];
}

/** The material a cutout set's inner crowns are drawn in, in the look's shading; null where the set has none. */
export function innerCrownMaterial(set: DecodedTextureSet, look: TileLook): pc.StandardMaterial | null {
  const colour = shadedLeafColour(set);
  if (colour === null) return null;
  const material = new pc.StandardMaterial();
  material.name = `generated-tile-crown:${set.entry.setId}`;
  material.diffuse = new pc.Color(colour[0], colour[1], colour[2]);
  material.useMetalness = true;
  material.metalness = 0;
  // Leaves in shade are matt.
  material.gloss = 0.2;
  material.useSkybox = true;
  material.cull = pc.CULLFACE_BACK;
  material.update();
  if (isRenderLook(look)) applyShading(material, look.shading);
  return material;
}

/** A mesh of the inner shells, for the renderer. */
export function innerCrownMesh(device: pc.GraphicsDevice, shells: ShellGeometry): pc.Mesh {
  const mesh = new pc.Mesh(device);
  mesh.setPositions(shells.positions);
  mesh.setNormals(shells.normals);
  mesh.setIndices(shells.indices);
  mesh.update(pc.PRIMITIVE_TRIANGLES);
  return mesh;
}
