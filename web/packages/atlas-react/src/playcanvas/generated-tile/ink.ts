import * as pc from 'playcanvas';
import type { Rgb } from './look.js';

/**
 * Ink lines: the creases and outlines of a drawn world, for looks that draw them.
 *
 * WHICH EDGES. Edges are matched by their end points, quantised to a tenth of a millimetre, never by
 * vertex index, so a triangulation's diagonals and the seams between coplanar pieces of one surface
 * are never inked. An edge is inked when one triangle has it (an outline) or when triangles that
 * share it meet at more than the crease angle (a crease). An edge longer than `maxLengthM` is left
 * out: at that length it is a plot or terrain boundary, not a line a viewer reads as drawing.
 *
 * WHICH SURFACES. `attachTileInk` inks the opaque meshes a tile drew: glass (blended) and leaves
 * (alpha-tested) are never inked, so a canopy is not outlined leaf by leaf.
 *
 * WHERE. Each segment is lifted off its faces along their mean normal, so it wins the depth test
 * against the surfaces it outlines. Lines are one device pixel wide.
 *
 * NORMALS. A line's vertices carry that same direction as their normal. The ink is unlit, but the
 * standard material's shader still declares the normal attribute, and a mesh without one is drawn
 * with the driver's warning that the attribute is missing.
 */

export interface InkOptions {
  readonly creaseDeg: number;
  readonly liftM: number;
  readonly maxLengthM: number;
}

export const INK_OPTIONS: InkOptions = Object.freeze({ creaseDeg: 20, liftM: 0.025, maxLengthM: 30 });

/**
 * Inked segments of the triangles `corners` names (three vertex indices each) over `positions`
 * (x, y, z per vertex, metres): pairs of points in the same frame, flattened. With `normals`, each
 * point's unit normal is appended to it in the same order: the direction its segment is lifted.
 */
export function inkSegments(
  positions: ArrayLike<number>,
  corners: ArrayLike<number>,
  options: InkOptions = INK_OPTIONS,
  normals?: number[],
): number[] {
  const crease = Math.cos((options.creaseDeg * Math.PI) / 180);
  const faceNormals: number[] = [];
  const edges = new Map<string, { a: number; b: number; faces: number[] }>();
  const key = (v: number): string =>
    `${Math.round(positions[v * 3]! * 10_000)},${Math.round(positions[v * 3 + 1]! * 10_000)},${Math.round(positions[v * 3 + 2]! * 10_000)}`;
  for (let t = 0; t < corners.length / 3; t += 1) {
    const a = corners[t * 3]!;
    const b = corners[t * 3 + 1]!;
    const c = corners[t * 3 + 2]!;
    const ux = positions[b * 3]! - positions[a * 3]!;
    const uy = positions[b * 3 + 1]! - positions[a * 3 + 1]!;
    const uz = positions[b * 3 + 2]! - positions[a * 3 + 2]!;
    const vx = positions[c * 3]! - positions[a * 3]!;
    const vy = positions[c * 3 + 1]! - positions[a * 3 + 1]!;
    const vz = positions[c * 3 + 2]! - positions[a * 3 + 2]!;
    const nx = uy * vz - uz * vy;
    const ny = uz * vx - ux * vz;
    const nz = ux * vy - uy * vx;
    const length = Math.hypot(nx, ny, nz);
    if (length === 0) continue;
    const face = faceNormals.length / 3;
    faceNormals.push(nx / length, ny / length, nz / length);
    for (const [p, q] of [[a, b], [b, c], [c, a]] as const) {
      const kp = key(p);
      const kq = key(q);
      const id = kp < kq ? `${kp}|${kq}` : `${kq}|${kp}`;
      const seen = edges.get(id);
      if (seen === undefined) edges.set(id, { a: p, b: q, faces: [face] });
      else seen.faces.push(face);
    }
  }
  const out: number[] = [];
  for (const { a, b, faces } of edges.values()) {
    const length = Math.hypot(
      positions[a * 3]! - positions[b * 3]!, positions[a * 3 + 1]! - positions[b * 3 + 1]!, positions[a * 3 + 2]! - positions[b * 3 + 2]!,
    );
    if (length > options.maxLengthM) continue;
    let inked = faces.length === 1;
    for (let i = 0; i < faces.length && !inked; i += 1) {
      for (let j = i + 1; j < faces.length && !inked; j += 1) {
        const dot = faceNormals[faces[i]! * 3]! * faceNormals[faces[j]! * 3]!
          + faceNormals[faces[i]! * 3 + 1]! * faceNormals[faces[j]! * 3 + 1]!
          + faceNormals[faces[i]! * 3 + 2]! * faceNormals[faces[j]! * 3 + 2]!;
        if (dot < crease) inked = true;
      }
    }
    if (!inked) continue;
    let mx = 0;
    let my = 0;
    let mz = 0;
    for (const face of faces) { mx += faceNormals[face * 3]!; my += faceNormals[face * 3 + 1]!; mz += faceNormals[face * 3 + 2]!; }
    const unit = 1 / (Math.hypot(mx, my, mz) || 1);
    const lift = options.liftM * unit;
    for (const v of [a, b]) {
      out.push(positions[v * 3]! + mx * lift, positions[v * 3 + 1]! + my * lift, positions[v * 3 + 2]! + mz * lift);
      normals?.push(mx * unit, my * unit, mz * unit);
    }
  }
  return out;
}

/** What ink drew on a tile, and how to take it away again. */
export interface TileInk {
  readonly segments: number;
  dispose(): void;
}

/** A linear colour as the sRGB-encoded colour a material's colour inputs take. */
function displayColour([r, g, b]: Rgb): pc.Color {
  const encode = (c: number): number => (c <= 0.0031308 ? c * 12.92 : 1.055 * c ** (1 / 2.4) - 0.055);
  return new pc.Color(encode(r), encode(g), encode(b));
}

/**
 * Ink every opaque mesh a tile drew under `root` (the entities a tile names `generated-tile:<set>`),
 * and those of any other entity whose name starts with one of `prefixes` (a style pack's baked
 * pieces, `style-pack:pieces`), in `colour`: unlit lines, fogged like everything else, each under
 * the mesh it outlines.
 */
export function attachTileInk(
  device: pc.GraphicsDevice,
  root: pc.Entity,
  colour: Rgb,
  options: InkOptions = INK_OPTIONS,
  prefixes: readonly string[] = ['generated-tile:'],
): TileInk {
  const material = new pc.StandardMaterial();
  material.name = 'generated-tile:ink';
  material.useLighting = false;
  material.diffuse = new pc.Color(0, 0, 0);
  material.emissive = displayColour(colour);
  material.update();
  const made: { entity: pc.Entity; mesh: pc.Mesh }[] = [];
  let segments = 0;
  for (const render of root.findComponents('render') as pc.RenderComponent[]) {
    if (!prefixes.some((prefix) => render.entity.name.startsWith(prefix)) || render.entity.name === 'generated-tile:ink') continue;
    for (const instance of render.meshInstances) {
      const drawn = instance.material as pc.StandardMaterial;
      if (drawn.blendType !== pc.BLEND_NONE || drawn.alphaTest > 0) continue;
      const positions: number[] = [];
      instance.mesh.getPositions(positions);
      const indices: number[] = [];
      instance.mesh.getIndices(indices);
      const normals: number[] = [];
      const lines = inkSegments(positions, indices, options, normals);
      if (lines.length === 0) continue;
      const mesh = new pc.Mesh(device);
      mesh.setPositions(lines);
      mesh.setNormals(normals);
      mesh.update(pc.PRIMITIVE_LINES);
      const entity = new pc.Entity('generated-tile:ink');
      entity.addComponent('render', { meshInstances: [new pc.MeshInstance(mesh, material)], castShadows: false, receiveShadows: false });
      render.entity.addChild(entity);
      made.push({ entity, mesh });
      segments += lines.length / 6;
    }
  }
  return {
    segments,
    dispose() {
      for (const { entity, mesh } of made.splice(0)) {
        entity.destroy();
        mesh.destroy();
      }
      material.destroy();
    },
  };
}
