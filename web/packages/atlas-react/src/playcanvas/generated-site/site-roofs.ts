import { materialOfLeaf, type RoofForm, type RoofForms, type SurfaceMaterials } from '@exulanica/atlas-core';
import type { SiteDrawing, SiteSlot } from './site-drawing.js';

/**
 * A site's roofs shaped by what they are made of.
 *
 * The drawing serves every roof as a slab or as one prism. Where the roof's look role names a
 * material the roof form catalog shapes (`readRoofForms`), the page draws that roof in the
 * catalog's form instead: a ridge at the material's pitch, laid as thick and overhanging as far as
 * the entry says, its ridge running the way the entry says; a tent, whose two sides run from the
 * ridge to the ground and whose ends are canvas with the door left open; a slab with its parapet.
 * The drawing's flat or pitched still decides which a roof is.
 *
 * A TENT'S WALLS ARE NOT DRAWN: the wall pieces inside its footprint are left out, since its sides
 * and ends stand where they stood. They stay in the walk, so nobody walks through the canvas.
 *
 * Everything here is worked in the slot's own frame, in metres: x east, y up from the top of the
 * wall, z south. Nothing reaches the walk, a door or a seat. Pure: no renderer.
 */

type V3 = readonly [number, number, number];

/** A roof as the page draws it: triangles in the slot's frame, each face drawn from both sides. */
export interface RoofMesh {
  readonly positions: number[];
  readonly normals: number[];
  readonly indices: number[];
}

/** What one roof is shaped from. */
export interface RoofInput {
  /** The footprint along east and north, in metres. */
  readonly widthM: number;
  readonly depthM: number;
  /** How high the top of the wall stands above the ground, in metres. */
  readonly wallM: number;
  /** As the drawing serves it: pitched or flat, its rise or its slab's thickness, and the axis its ridge is drawn along. */
  readonly served: { readonly pitched: boolean; readonly riseM: number; readonly ridge: 'x' | 'z' };
  /** The axis the structure's door faces along (z for north or south, x for east or west), where it has a door. */
  readonly doorAxis: 'x' | 'z' | null;
  /** The structure's doors: where each stands in the slot's frame, how wide it is and how high its head is above the ground. */
  readonly doors: readonly { readonly x: number; readonly z: number; readonly widthM: number; readonly topM: number }[];
}

/** How near a tent's end a door must stand to be that end's door, in metres. */
const END_REACH_M = 0.6;
/** How far inside a footprint's edge a wall piece's centre may lie and still be that structure's, in metres. */
const WALL_REACH_M = 0.35;

class Builder {
  readonly positions: number[] = [];
  readonly normals: number[] = [];
  readonly indices: number[] = [];

  /** A flat convex polygon, drawn from both sides. Corners that coincide are dropped; one with no area draws nothing. */
  face(corners: readonly V3[]): void {
    const points = corners.filter((point, index) => {
      const before = corners[(index + corners.length - 1) % corners.length]!;
      return Math.hypot(point[0] - before[0], point[1] - before[1], point[2] - before[2]) > 1e-9;
    });
    if (points.length < 3) return;
    const [a, b, c] = points as [V3, V3, V3];
    const ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2];
    const vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2];
    let nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    const length = Math.hypot(nx, ny, nz);
    if (length < 1e-9) return;
    nx /= length; ny /= length; nz /= length;
    for (const side of [1, -1]) {
      const base = this.positions.length / 3;
      for (const point of points) {
        this.positions.push(point[0], point[1], point[2]);
        this.normals.push(nx * side, ny * side, nz * side);
      }
      for (let i = 1; i + 1 < points.length; i += 1) {
        if (side === 1) this.indices.push(base, base + i, base + i + 1);
        else this.indices.push(base, base + i + 1, base + i);
      }
    }
  }

  box(x0: number, x1: number, y0: number, y1: number, z0: number, z1: number): void {
    this.face([[x0, y1, z0], [x1, y1, z0], [x1, y1, z1], [x0, y1, z1]]);
    this.face([[x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1]]);
    this.face([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0]]);
    this.face([[x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]]);
    this.face([[x0, y0, z0], [x0, y0, z1], [x0, y1, z1], [x0, y1, z0]]);
    this.face([[x1, y0, z0], [x1, y0, z1], [x1, y1, z1], [x1, y1, z0]]);
  }

  mesh(): RoofMesh {
    return { positions: this.positions, normals: this.normals, indices: this.indices };
  }
}

/** The axis a shaped ridge runs along. */
export function ridgeAxis(input: RoofInput, form: NonNullable<RoofForm['ridge']>): 'x' | 'z' {
  const longer = input.widthM >= input.depthM ? 'x' : 'z';
  if (form.runs === 'as_served') return input.served.ridge;
  if (form.runs === 'door_axis') return input.doorAxis ?? longer;
  return longer;
}

/**
 * A roof in its material's form, or null where the form shapes nothing of what the drawing serves
 * (a pitched roof of a material that shapes only slabs, or the other way), which is then drawn as
 * served.
 */
export function roofMesh(input: RoofInput, form: RoofForm): RoofMesh | null {
  const builder = new Builder();
  if (!input.served.pitched) {
    if (form.slab === null) return null;
    const hw = input.widthM / 2, hd = input.depthM / 2;
    const top = input.served.riseM;
    const rim = top + form.slab.parapetMm / 1000;
    const thick = Math.min(form.slab.parapetThicknessMm / 1000, hw, hd);
    builder.box(-hw, hw, 0, top, -hd, hd);
    builder.box(-hw, hw, top, rim, -hd, -hd + thick);
    builder.box(-hw, hw, top, rim, hd - thick, hd);
    builder.box(-hw, -hw + thick, top, rim, -hd + thick, hd - thick);
    builder.box(hw - thick, hw, top, rim, -hd + thick, hd - thick);
    return builder.mesh();
  }
  if (form.ridge === null) return null;
  const axis = ridgeAxis(input, form.ridge);
  const length = axis === 'x' ? input.widthM : input.depthM;
  const span = axis === 'x' ? input.depthM : input.widthM;
  // (along the ridge, up, across it) in the slot's frame.
  const at = (u: number, y: number, v: number): V3 => (axis === 'x' ? [u, y, v] : [v, y, u]);
  const pitch = form.ridge.pitchPermille / 1000;
  const half = span / 2;
  if (form.ridge.eaves === 'ground') {
    const ground = -input.wallM;
    const apex = ground + pitch * half;
    const heightAt = (v: number): number => ground + (apex - ground) * (1 - Math.abs(v) / half);
    for (const side of [-1, 1]) {
      builder.face([at(-length / 2, apex, 0), at(length / 2, apex, 0), at(length / 2, ground, side * half), at(-length / 2, ground, side * half)]);
    }
    for (const end of [-1, 1]) {
      const u = (end * length) / 2;
      const door = input.doors
        .map((one) => ({ along: axis === 'x' ? one.x : one.z, across: axis === 'x' ? one.z : one.x, widthM: one.widthM, topM: one.topM }))
        .find((one) => Math.abs(one.along - u) <= END_REACH_M);
      if (door === undefined) {
        builder.face([at(u, ground, -half), at(u, ground, half), at(u, apex, 0)]);
        continue;
      }
      const v0 = Math.max(-half + 0.05, door.across - door.widthM / 2);
      const v1 = Math.min(half - 0.05, door.across + door.widthM / 2);
      const head = Math.min(ground + door.topM, heightAt(v0), heightAt(v1));
      builder.face([at(u, ground, -half), at(u, ground, v0), at(u, heightAt(v0), v0)]);
      builder.face([at(u, ground, v1), at(u, ground, half), at(u, heightAt(v1), v1)]);
      const above: V3[] = [at(u, head, v0), at(u, head, v1), at(u, heightAt(v1), v1)];
      if (v0 < 0 && v1 > 0) above.push(at(u, apex, 0));
      above.push(at(u, heightAt(v0), v0));
      builder.face(above);
    }
    return builder.mesh();
  }
  const rise = pitch * half;
  const over = form.ridge.overhangMm / 1000;
  const thick = form.ridge.thicknessMm / 1000;
  const reach = length / 2 + over;
  const eave = -pitch * over;
  for (const side of [-1, 1]) {
    const out = side * (half + over);
    builder.face([at(-reach, rise + thick, 0), at(reach, rise + thick, 0), at(reach, eave + thick, out), at(-reach, eave + thick, out)]);
    if (thick > 0) {
      builder.face([at(-reach, rise, 0), at(reach, rise, 0), at(reach, eave, out), at(-reach, eave, out)]);
      builder.face([at(-reach, eave, out), at(reach, eave, out), at(reach, eave + thick, out), at(-reach, eave + thick, out)]);
      for (const end of [-reach, reach]) {
        builder.face([at(end, rise, 0), at(end, rise + thick, 0), at(end, eave + thick, out), at(end, eave, out)]);
      }
    }
  }
  // The walls' ends, closed up to the ridge.
  for (const end of [-length / 2, length / 2]) {
    builder.face([at(end, 0, -half), at(end, 0, half), at(end, rise, 0)]);
  }
  return builder.mesh();
}

/** A site's shaped roofs by their slot's identity, and the wall pieces a tent stands in place of. */
export interface ShapedRoofs {
  readonly meshes: ReadonlyMap<string, RoofMesh>;
  /** Slots left out of the drawing: the wall pieces under a roof that runs to the ground. */
  readonly undrawn: ReadonlySet<string>;
}

const NONE: ShapedRoofs = Object.freeze({ meshes: new Map<string, RoofMesh>(), undrawn: new Set<string>() });

/** Every roof of a drawing that its material's form shapes. */
export function shapeRoofs(drawing: SiteDrawing, materials: SurfaceMaterials | null, forms: RoofForms | null): ShapedRoofs {
  if (materials === null || forms === null) return NONE;
  const meshes = new Map<string, RoofMesh>();
  const undrawn = new Set<string>();
  const byIdentity = new Map<string, SiteSlot>(drawing.slots.map((slot) => [slot.identity, slot]));
  for (const roof of drawing.slots) {
    if (roof.family !== 'roof' || (roof.primitive !== 'gable' && roof.primitive !== 'box') || !roof.identity.endsWith(':roof') || roof.leaf === 'default') continue;
    const material = materialOfLeaf(materials, 'roof', roof.leaf);
    const form = material === null ? undefined : forms.byMaterial.get(material.key);
    if (form === undefined) continue;
    const turned = roof.yawQuarterTurns % 2 === 1;
    const widthMm = turned ? roof.boxMm[1] : roof.boxMm[0];
    const depthMm = turned ? roof.boxMm[0] : roof.boxMm[1];
    const [cx, cy] = roof.positionMm;
    const within = (slot: SiteSlot, reachM: number): boolean =>
      Math.abs(slot.positionMm[0] - cx) <= widthMm / 2 + reachM * 1000 && Math.abs(slot.positionMm[1] - cy) <= depthMm / 2 + reachM * 1000;
    const structure = byIdentity.get(roof.identity.slice(0, -':roof'.length));
    const doors = drawing.slots
      .filter((slot) => slot.family === 'door' && slot.identity.includes(':door:') && within(slot, END_REACH_M))
      .map((slot) => ({ x: (slot.positionMm[0] - cx) / 1000, z: -(slot.positionMm[1] - cy) / 1000, widthM: slot.boxMm[0] / 1000, topM: slot.boxMm[2] / 1000 }));
    const input: RoofInput = {
      widthM: widthMm / 1000,
      depthM: depthMm / 1000,
      wallM: roof.positionMm[2] / 1000,
      served: { pitched: roof.primitive === 'gable', riseM: roof.boxMm[2] / 1000, ridge: turned ? 'z' : 'x' },
      doorAxis: structure === undefined || doors.length === 0 ? null : structure.yawQuarterTurns % 2 === 0 ? 'z' : 'x',
      doors,
    };
    const mesh = roofMesh(input, form);
    if (mesh === null) continue;
    meshes.set(roof.identity, mesh);
    if (input.served.pitched && form.ridge?.eaves === 'ground') {
      for (const slot of drawing.slots) {
        if (slot.family === 'wall' && slot.primitive === 'box' && within(slot, WALL_REACH_M)) undrawn.add(slot.identity);
      }
    }
  }
  return { meshes, undrawn };
}
