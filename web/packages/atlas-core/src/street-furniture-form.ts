/**
 * Street furniture forms: how a town's bench, bin, cycle stand and sign post are drawn as made things.
 *
 * A town's street furniture is a record of its tile (`city.street_furniture`) whose `parts` are its
 * geometry: boxes and prisms in the furniture's own frame, `+x` its facing, `+y` to its left, `+z` up,
 * each offset placing a part's bottom centre (`exulanica.grammar.grammars.city.common.FormPart`). The
 * parts are what a person sits on, walks round and sees past, and the bake draws them as they are. The
 * street furniture form catalog (`assets/catalogs/world-kinds/street-furniture-form.v2.json`) states,
 * by the record's furniture class, how its parts are drawn instead: a seat as slats, a leg as a frame,
 * a bin as a turned body, a stand's posts and rail as one bent tube, a plate with a rim. Every form
 * stays inside the boxes of the parts it draws (a tube inside its parts' common box), so nothing
 * drawn reaches past what the parts already claim.
 *
 * A record is drawn by a form only when its class has one and its parts are the shapes the form
 * expects, in order; anything else is drawn as baked. A form shapes the drawing only: the walk, the
 * seats and every check still read the parts.
 *
 * A made place's fixture is a slot, a box with no parts (`site-drawing.ts`). The catalog's slot entries
 * state, by the slot's leaf, the parts a form draws in thousandths of the slot's width, depth and height
 * (centred on its base, in the slot's own frame: `+x` along its width, `+y` toward its front, `+z` up),
 * so a site's bench is drawn by the same forms inside its own box, and a boundary run whose leaf has an
 * entry (a timber fence) as posts and rails inside its own box.
 *
 * Pure: no DOM, no Node, no renderer. The catalog's text is passed in. Millimetres in the furniture's
 * own frame; `s` and `t` are the surface coordinates a texture is placed by, in millimetres, as the
 * bake states them for a part: on a side `s` runs round or along it and `t` is the furniture's base
 * height minus the height, on a top `s` is `+x` and `t` is `+y`, on an underside `t` is `-y`.
 */

export const STREET_FURNITURE_FORM_CATALOG_ID = 'street-furniture-form';

/** A part as a record states it, field for field in the furniture's own frame. */
export interface FurniturePart {
  readonly shape: 'box' | 'prism' | 'ellipsoid';
  readonly surfaceRole: string;
  readonly offsetXMm: number;
  readonly offsetYMm: number;
  readonly offsetZMm: number;
  readonly sizeXMm: number;
  readonly sizeYMm: number;
  readonly sizeZMm: number;
}

/** Which point of a part a tube runs through: its bottom centre, or its top centre less the tube's radius. */
export type PartPoint = 'bottom' | 'top';

export type FurnitureDraw =
  /** A box part drawn as its own box: a part a class keeps as stated beside parts it makes. */
  | { readonly form: 'solid'; readonly parts: readonly number[] }
  /** Slats laid along a box's longest side, side by side across its second longest, with gaps. */
  | { readonly form: 'slats'; readonly parts: readonly number[]; readonly count: number; readonly gapMm: number }
  /** A box's two ends along its longer level side as uprights, with a rail at the top and at the foot. */
  | { readonly form: 'frame'; readonly parts: readonly number[]; readonly barMm: number; readonly top: boolean; readonly foot: boolean }
  /** A turned body inside a part's cylinder: heights and radii in thousandths of the part's. */
  | { readonly form: 'lathe'; readonly parts: readonly number[]; readonly segments: number; readonly profilePermille: readonly (readonly [number, number])[] }
  /** One tube bent through part points, its radius in thousandths of the first part's half width. */
  | {
      readonly form: 'tube'; readonly parts: readonly number[]; readonly through: readonly (readonly [number, PartPoint])[];
      readonly radiusPermille: number; readonly bendMm: number; readonly segments: number;
    }
  /** A thin box as a panel framed by a rim of full thickness, the panel set in on both faces. */
  | { readonly form: 'plate'; readonly parts: readonly number[]; readonly rimMm: number; readonly insetMm: number }
  /**
   * A box as a post-and-rail fence along its longer level side: square posts as deep as the box at both ends and
   * evenly between, at most `spacingMm` apart, and rails between the end posts at heights in thousandths of the box's.
   */
  | {
      readonly form: 'rails'; readonly parts: readonly number[]; readonly postMm: number; readonly spacingMm: number;
      readonly railMm: number; readonly railDepthMm: number; readonly railsPermille: readonly number[];
    };

export interface FurnitureForm {
  /** The furniture class it draws (`street-furniture.v2.json`'s key). */
  readonly key: string;
  /** The shapes of the parts it expects, in the record's order. */
  readonly parts: readonly FurniturePart['shape'][];
  readonly draws: readonly FurnitureDraw[];
}

/** A part of a slot entry, in thousandths: offsets of the slot's width and depth from its centre and of its height from its base. */
export interface SlotPartPermille {
  readonly shape: FurniturePart['shape'];
  readonly surfaceRole: string;
  readonly offsetPermille: readonly [number, number, number];
  readonly sizePermille: readonly [number, number, number];
}

/** A slot's form: by the slot's leaf, its parts in its box and how they are drawn. */
export interface SlotFurnitureForm extends FurnitureForm {
  readonly partsPermille: readonly SlotPartPermille[];
}

export interface FurnitureForms {
  readonly version: number;
  readonly byClass: ReadonlyMap<string, FurnitureForm>;
  /** Slot forms by the slot's leaf; empty when the catalog states none. */
  readonly bySlotLeaf: ReadonlyMap<string, SlotFurnitureForm>;
}

/** One surface of a drawn piece of furniture: one part role, positions, surface coordinates and triangles. */
export interface FurnitureSurface {
  readonly role: string;
  /** Millimetres in the furniture's own frame, three to a vertex: along, left, up. */
  readonly positions: readonly number[];
  /** `s` and `t`, millimetres, two to a vertex. */
  readonly st: readonly number[];
  /** Counter-clockwise seen from outside, three to a triangle. */
  readonly indices: readonly number[];
}

const KEY = /^[a-z][a-z0-9_]{0,39}$/;
const ROLE = /^[a-z][a-z_]{0,39}$/;
const SHAPES: readonly FurniturePart['shape'][] = ['box', 'prism', 'ellipsoid'];
const SEGMENTS: readonly number[] = [8, 16, 32, 64];

function refuse(where: string, detail: string): never {
  throw new TypeError(`street furniture form catalog: ${where} ${detail}`);
}

function whole(value: unknown, where: string, min: number, max: number): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < min || value > max) return refuse(where, `must be a whole number from ${min} to ${max}`);
  return value;
}

function flag(value: unknown, where: string): boolean {
  if (typeof value !== 'boolean') return refuse(where, 'must be true or false');
  return value;
}

function partList(value: unknown, where: string, count: number): number[] {
  if (!Array.isArray(value) || value.length === 0) return refuse(where, 'must name the parts it draws');
  return value.map((one, at) => whole(one, `${where}[${at}]`, 0, count - 1));
}

function readDraw(raw: Record<string, unknown>, where: string, shapes: readonly FurniturePart['shape'][]): FurnitureDraw {
  const parts = partList(raw['parts'], `${where}.parts`, shapes.length);
  const one = (form: string, shape: FurniturePart['shape'] | null): void => {
    if (parts.length !== 1) refuse(where, `draws one part as ${form}`);
    if (shape !== null && shapes[parts[0]!] !== shape) refuse(where, `draws a ${shapes[parts[0]!]} as ${form}, which needs a ${shape}`);
  };
  switch (raw['form']) {
    case 'solid':
      one('itself', 'box');
      return { form: 'solid', parts };
    case 'slats':
      one('slats', 'box');
      return { form: 'slats', parts, count: whole(raw['count'], `${where}.count`, 1, 12), gapMm: whole(raw['gap_mm'], `${where}.gap_mm`, 0, 200) };
    case 'frame':
      one('a frame', 'box');
      return {
        form: 'frame', parts, barMm: whole(raw['bar_mm'], `${where}.bar_mm`, 10, 200),
        top: flag(raw['top'], `${where}.top`), foot: flag(raw['foot'], `${where}.foot`),
      };
    case 'lathe': {
      one('a lathe', null);
      if (shapes[parts[0]!] === 'box') refuse(where, 'turns a box');
      const segments = whole(raw['segments'], `${where}.segments`, 8, 64);
      if (!SEGMENTS.includes(segments)) refuse(`${where}.segments`, 'must be 8, 16, 32 or 64');
      const profile = raw['profile_permille'];
      if (!Array.isArray(profile) || profile.length < 2 || profile.length > 24) return refuse(`${where}.profile_permille`, 'must state 2 to 24 points');
      const points = profile.map((point, at) => {
        if (!Array.isArray(point) || point.length !== 2) return refuse(`${where}.profile_permille[${at}]`, 'must be a height and a radius');
        return [whole(point[0], `${where}.profile_permille[${at}][0]`, 0, 1000), whole(point[1], `${where}.profile_permille[${at}][1]`, 0, 1000)] as const;
      });
      if (points[0]![0] !== 0 || points[points.length - 1]![0] !== 1000) refuse(`${where}.profile_permille`, 'must run from height 0 to 1000');
      for (let at = 1; at < points.length; at += 1) {
        if (points[at]![0] < points[at - 1]![0]) refuse(`${where}.profile_permille`, 'must not go down');
      }
      return { form: 'lathe', parts, segments, profilePermille: points };
    }
    case 'tube': {
      if (parts.some((part) => shapes[part] !== 'box')) refuse(where, 'bends a tube through a part that is not a box');
      const through = raw['through'];
      if (!Array.isArray(through) || through.length < 2 || through.length > 8) return refuse(`${where}.through`, 'must state 2 to 8 points');
      const points = through.map((point, at) => {
        if (!Array.isArray(point) || point.length !== 2 || (point[1] !== 'bottom' && point[1] !== 'top')) {
          return refuse(`${where}.through[${at}]`, 'must be a part and bottom or top');
        }
        const part = whole(point[0], `${where}.through[${at}][0]`, 0, shapes.length - 1);
        if (!parts.includes(part)) refuse(`${where}.through[${at}]`, 'runs through a part the tube does not draw');
        return [part, point[1] as PartPoint] as const;
      });
      const segments = whole(raw['segments'], `${where}.segments`, 6, 32);
      return {
        form: 'tube', parts, through: points, radiusPermille: whole(raw['radius_permille'], `${where}.radius_permille`, 100, 1000),
        bendMm: whole(raw['bend_mm'], `${where}.bend_mm`, 0, 2000), segments,
      };
    }
    case 'rails': {
      one('a fence of posts and rails', 'box');
      const heights = raw['rails_permille'];
      if (!Array.isArray(heights) || heights.length === 0 || heights.length > 6) return refuse(`${where}.rails_permille`, 'must state 1 to 6 rail heights');
      return {
        form: 'rails', parts, postMm: whole(raw['post_mm'], `${where}.post_mm`, 20, 500), spacingMm: whole(raw['spacing_mm'], `${where}.spacing_mm`, 500, 10000),
        railMm: whole(raw['rail_mm'], `${where}.rail_mm`, 10, 500), railDepthMm: whole(raw['rail_depth_mm'], `${where}.rail_depth_mm`, 10, 500),
        railsPermille: heights.map((one, at) => whole(one, `${where}.rails_permille[${at}]`, 0, 1000)),
      };
    }
    case 'plate':
      one('a plate', 'box');
      return { form: 'plate', parts, rimMm: whole(raw['rim_mm'], `${where}.rim_mm`, 1, 500), insetMm: whole(raw['inset_mm'], `${where}.inset_mm`, 0, 100) };
    default:
      return refuse(`${where}.form`, 'must be solid, slats, frame, lathe, tube, plate or rails');
  }
}

/** Read the catalog's text, or refuse it by naming the first entry that is not a street furniture form. */
export function readStreetFurnitureForms(text: string): FurnitureForms {
  const document = JSON.parse(text) as { readonly catalog_id?: unknown; readonly catalog_version?: unknown; readonly entries?: unknown };
  if (document.catalog_id !== STREET_FURNITURE_FORM_CATALOG_ID || !Array.isArray(document.entries)) return refuse('the file', 'is not the street furniture form catalog');
  const version = whole(document.catalog_version, 'catalog_version', 1, 1_000_000);
  const byClass = new Map<string, FurnitureForm>();
  for (const entry of document.entries as readonly Record<string, unknown>[]) {
    const key = keyOf(entry, byClass, 'an entry');
    const stated = entry['parts'];
    if (!Array.isArray(stated) || stated.length === 0 || stated.length > 16 || stated.some((shape) => !SHAPES.includes(shape as FurniturePart['shape']))) {
      return refuse(`${key}.parts`, `must be 1 to 16 of ${SHAPES.join(', ')}`);
    }
    const shapes = stated as FurniturePart['shape'][];
    byClass.set(key, Object.freeze({ key, parts: Object.freeze([...shapes]), draws: drawsOf(entry, key, shapes) }));
  }
  const bySlotLeaf = new Map<string, SlotFurnitureForm>();
  const slotEntries = (document as { readonly slot_entries?: unknown }).slot_entries;
  if (slotEntries !== undefined && !Array.isArray(slotEntries)) return refuse('slot_entries', 'must be a list');
  for (const entry of (slotEntries ?? []) as readonly Record<string, unknown>[]) {
    const key = keyOf(entry, bySlotLeaf, 'a slot entry');
    const stated = entry['parts_permille'];
    if (!Array.isArray(stated) || stated.length === 0 || stated.length > 16) return refuse(`${key}.parts_permille`, 'must state 1 to 16 parts');
    const parts = stated.map((raw, at) => slotPart(raw as Record<string, unknown>, `${key}.parts_permille[${at}]`));
    const shapes = parts.map((part) => part.shape);
    bySlotLeaf.set(key, Object.freeze({ key, parts: Object.freeze(shapes), draws: drawsOf(entry, key, shapes), partsPermille: Object.freeze(parts) }));
  }
  return Object.freeze({ version, byClass, bySlotLeaf });
}

function keyOf(entry: Record<string, unknown>, held: ReadonlyMap<string, unknown>, what: string): string {
  const key = entry?.['key'];
  if (typeof key !== 'string' || !KEY.test(key)) return refuse(what, `has the key ${JSON.stringify(key)}`);
  if (held.has(key)) return refuse(key, 'is stated twice');
  const reason = entry['reason'];
  if (typeof reason !== 'string' || reason.trim() === '') return refuse(key, 'gives no reason');
  return key;
}

function drawsOf(entry: Record<string, unknown>, key: string, shapes: readonly FurniturePart['shape'][]): readonly FurnitureDraw[] {
  const draws = entry['draws'];
  if (!Array.isArray(draws) || draws.length === 0) return refuse(`${key}.draws`, 'must state what it draws');
  const read = draws.map((draw, at) => readDraw(draw as Record<string, unknown>, `${key}.draws[${at}]`, shapes));
  // Every part is drawn by exactly one form: none drawn twice, none left as baked beside a made one.
  const drawn = read.flatMap((draw) => draw.parts);
  if (new Set(drawn).size !== drawn.length) refuse(`${key}.draws`, 'draws a part twice');
  if (drawn.length !== shapes.length) refuse(`${key}.draws`, 'leaves a part undrawn');
  return Object.freeze(read);
}

/** A slot part, held inside its slot's box: no part reaches past the box it is stated in. */
function slotPart(raw: Record<string, unknown>, where: string): SlotPartPermille {
  const shape = raw?.['shape'];
  if (!SHAPES.includes(shape as FurniturePart['shape'])) return refuse(`${where}.shape`, `must be one of ${SHAPES.join(', ')}`);
  const role = raw['surface_role'];
  if (typeof role !== 'string' || !ROLE.test(role)) return refuse(`${where}.surface_role`, 'must name a role');
  const triple = (name: string, min: number, max: number): [number, number, number] => {
    const value = raw[name];
    if (!Array.isArray(value) || value.length !== 3) return refuse(`${where}.${name}`, 'must be three numbers');
    return value.map((one, at) => whole(one, `${where}.${name}[${at}]`, min, max)) as [number, number, number];
  };
  const offset = triple('offset_permille', -500, 1000);
  const size = triple('size_permille', 1, 1000);
  if (Math.abs(offset[0]) * 2 + size[0] > 1000 || Math.abs(offset[1]) * 2 + size[1] > 1000 || offset[2] < 0 || offset[2] + size[2] > 1000) {
    refuse(where, 'reaches past its slot\'s box');
  }
  return Object.freeze({ shape: shape as FurniturePart['shape'], surfaceRole: role, offsetPermille: offset, sizePermille: size });
}

// ---------------------------------------------------------------------------------------- the maker

type Vec3 = readonly [number, number, number];

/** One role's growing surface. */
class Builder {
  readonly positions: number[] = [];
  readonly st: number[] = [];
  readonly indices: number[] = [];
  constructor(readonly role: string) {}

  vertex(p: Vec3, s: number, t: number): number {
    this.positions.push(p[0], p[1], p[2]);
    this.st.push(s, t);
    return this.positions.length / 3 - 1;
  }

  /** A flat quad, its corners counter-clockwise seen from outside; s and t by its own normal. */
  quad(a: Vec3, b: Vec3, c: Vec3, d: Vec3): void {
    const n = normalOf(a, b, c);
    const corners = [a, b, c, d].map((p) => this.vertex(p, ...flatSt(p, n)));
    this.indices.push(corners[0]!, corners[1]!, corners[2]!, corners[0]!, corners[2]!, corners[3]!);
  }

  /** A box between its corners, every face flat. */
  box(min: Vec3, max: Vec3): void {
    const [x0, y0, z0] = min;
    const [x1, y1, z1] = max;
    if (!(x1 > x0 && y1 > y0 && z1 > z0)) return;
    this.quad([x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]); // top
    this.quad([x0, y1, z0], [x1, y1, z0], [x1, y0, z0], [x0, y0, z0]); // underside
    this.quad([x1, y0, z0], [x1, y1, z0], [x1, y1, z1], [x1, y0, z1]); // +x
    this.quad([x0, y1, z0], [x0, y0, z0], [x0, y0, z1], [x0, y1, z1]); // -x
    this.quad([x1, y1, z0], [x0, y1, z0], [x0, y1, z1], [x1, y1, z1]); // +y
    this.quad([x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1]); // -y
  }
}

function sub(a: Vec3, b: Vec3): Vec3 { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
function cross(a: Vec3, b: Vec3): Vec3 { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
function normalOf(a: Vec3, b: Vec3, c: Vec3): Vec3 { return cross(sub(b, a), sub(c, a)); }

/**
 * A flat face's `s` and `t` by the bake's rule for a part: a face leaning level by 45 degrees or more is
 * a top (`s = +x`, `t = +y`) or an underside (`t = -y`); otherwise a side, `s` along it level and `t`
 * the base height (0 in this frame) minus the height.
 */
function flatSt(p: Vec3, n: Vec3): readonly [number, number] {
  if (n[2] * n[2] >= n[0] * n[0] + n[1] * n[1]) return n[2] > 0 ? [p[0], p[1]] : [p[0], -p[1]];
  const level = Math.hypot(n[0], n[1]);
  // Along the face, level, with the face's outside on the right: (-ny, nx) normalised.
  return [(-n[1] * p[0] + n[0] * p[1]) / level, -p[2]];
}

/** A box part's corners. */
function boxOf(part: FurniturePart): { readonly min: Vec3; readonly max: Vec3 } {
  return {
    min: [part.offsetXMm - part.sizeXMm / 2, part.offsetYMm - part.sizeYMm / 2, part.offsetZMm],
    max: [part.offsetXMm + part.sizeXMm / 2, part.offsetYMm + part.sizeYMm / 2, part.offsetZMm + part.sizeZMm],
  };
}

function solid(out: Builder, part: FurniturePart): boolean {
  const { min, max } = boxOf(part);
  out.box(min, max);
  return true;
}

function slats(out: Builder, part: FurniturePart, count: number, gapMm: number): boolean {
  const { min, max } = boxOf(part);
  const size = [part.sizeXMm, part.sizeYMm, part.sizeZMm];
  // Along the longest side, side by side across the second longest, as thick as the third.
  const order = [0, 1, 2].sort((a, b) => size[b]! - size[a]! || a - b);
  const across = order[1]!;
  const width = (size[across]! - gapMm * (count - 1)) / count;
  if (!(width > 0)) return false;
  for (let at = 0; at < count; at += 1) {
    const lo = [...min] as [number, number, number];
    const hi = [...max] as [number, number, number];
    lo[across] = min[across]! + at * (width + gapMm);
    hi[across] = lo[across] + width;
    out.box(lo, hi);
  }
  return true;
}

function frame(out: Builder, part: FurniturePart, barMm: number, top: boolean, foot: boolean): boolean {
  const { min, max } = boxOf(part);
  // The uprights stand at the ends of the longer level side; the thinner level side is their depth.
  const run = part.sizeXMm >= part.sizeYMm ? 0 : 1;
  const runSize = run === 0 ? part.sizeXMm : part.sizeYMm;
  if (barMm * 2 > runSize || barMm * ((top ? 1 : 0) + (foot ? 1 : 0)) > part.sizeZMm) return false;
  for (const end of [0, 1]) {
    const lo = [...min] as [number, number, number];
    const hi = [...max] as [number, number, number];
    if (end === 0) hi[run] = min[run]! + barMm; else lo[run] = max[run]! - barMm;
    out.box(lo, hi);
  }
  const rail = (z0: number, z1: number): void => {
    const lo = [...min] as [number, number, number];
    const hi = [...max] as [number, number, number];
    lo[run] = min[run]! + barMm;
    hi[run] = max[run]! - barMm;
    lo[2] = z0;
    hi[2] = z1;
    out.box(lo, hi);
  };
  if (top) rail(max[2] - barMm, max[2]);
  if (foot) rail(min[2], min[2] + barMm);
  return true;
}

function lathe(out: Builder, part: FurniturePart, segments: number, profile: readonly (readonly [number, number])[]): boolean {
  const rx = part.sizeXMm / 2;
  const ry = part.sizeYMm / 2;
  const ring = (z: number, scale: number): Vec3[] => {
    const points: Vec3[] = [];
    for (let at = 0; at < segments; at += 1) {
      const angle = (2 * Math.PI * at) / segments;
      points.push([part.offsetXMm + rx * scale * Math.cos(angle), part.offsetYMm + ry * scale * Math.sin(angle), z]);
    }
    return points;
  };
  const height = (permille: number): number => part.offsetZMm + (part.sizeZMm * permille) / 1000;
  // One band between each pair of profile points, its own vertices so a corner of the profile stays sharp;
  // round the body the vertices are shared, so it reads round.
  for (let at = 1; at < profile.length; at += 1) {
    const [h0, r0] = profile[at - 1]!;
    const [h1, r1] = profile[at]!;
    // A band of no radius draws nothing, so a body that ends below its part's top runs to it at radius 0.
    if ((h0 === h1 && r0 === r1) || (r0 === 0 && r1 === 0)) continue;
    const lower = ring(height(h0), r0 / 1000);
    const upper = ring(height(h1), r1 / 1000);
    const first = out.positions.length / 3;
    const sAt = (k: number): number => (2 * Math.PI * k * Math.max(rx, ry)) / segments;
    if (r0 === 0 || r1 === 0) {
      // A ring of no radius is one point, so the band is a fan: one triangle a segment, each with its own tip.
      // A quad's second triangle would have two corners on that point and no area, and a vertex whose only
      // triangle has no area gets no normal, which keeps a tile from drawing at all.
      const rim = r1 === 0 ? lower : upper;
      const tip = (r1 === 0 ? upper : lower)[0]!;
      for (let k = 0; k <= segments; k += 1) out.vertex(rim[k % segments]!, sAt(k), -rim[k % segments]![2]);
      for (let k = 0; k < segments; k += 1) out.vertex(tip, sAt(r1 === 0 ? k + 1 : k), -tip[2]);
      for (let k = 0; k < segments; k += 1) {
        const [a, b, t] = [first + k, first + k + 1, first + segments + 1 + k];
        // Counter-clockwise from outside, as the quads below: up the seam, then across.
        if (r1 === 0) out.indices.push(a, b, t); else out.indices.push(t, b, a);
      }
      continue;
    }
    for (let k = 0; k <= segments; k += 1) {
      const i = k % segments;
      out.vertex(lower[i]!, sAt(k), -lower[i]![2]);
      out.vertex(upper[i]!, sAt(k), -upper[i]![2]);
    }
    for (let k = 0; k < segments; k += 1) {
      const a = first + k * 2;
      // Counter-clockwise from outside: up the seam, then across.
      out.indices.push(a, a + 2, a + 3, a, a + 3, a + 1);
    }
  }
  const disc = (permille: number, scale: number, up: boolean): void => {
    if (scale === 0) return;
    const z = height(permille);
    const points = ring(z, scale);
    const centre = out.vertex([part.offsetXMm, part.offsetYMm, z], part.offsetXMm, up ? part.offsetYMm : -part.offsetYMm);
    const around = points.map((p) => out.vertex(p, p[0], up ? p[1] : -p[1]));
    for (let k = 0; k < segments; k += 1) {
      const a = around[k]!;
      const b = around[(k + 1) % segments]!;
      if (up) out.indices.push(centre, a, b); else out.indices.push(centre, b, a);
    }
  };
  disc(profile[0]![0], profile[0]![1] / 1000, false);
  disc(profile[profile.length - 1]![0], profile[profile.length - 1]![1] / 1000, true);
  return true;
}

function tube(out: Builder, parts: readonly FurniturePart[], through: readonly (readonly [number, PartPoint])[], radiusPermille: number, bendMm: number, segments: number): boolean {
  const first = parts[through[0]![0]]!;
  const radius = (Math.min(first.sizeXMm, first.sizeYMm) / 2) * (radiusPermille / 1000);
  const corners: Vec3[] = through.map(([index, point]) => {
    const part = parts[index]!;
    return [part.offsetXMm, part.offsetYMm, point === 'bottom' ? part.offsetZMm : part.offsetZMm + part.sizeZMm - radius];
  });
  // The path: straight runs between the points, each inner corner rounded by an arc of at most bendMm,
  // never more than half of either run it joins.
  const path: Vec3[] = [corners[0]!];
  for (let at = 1; at + 1 < corners.length; at += 1) {
    const [p, c, n] = [corners[at - 1]!, corners[at]!, corners[at + 1]!];
    const a = sub(p, c);
    const b = sub(n, c);
    const la = Math.hypot(...a);
    const lb = Math.hypot(...b);
    if (la === 0 || lb === 0) return false;
    const ua: Vec3 = [a[0] / la, a[1] / la, a[2] / la];
    const ub: Vec3 = [b[0] / lb, b[1] / lb, b[2] / lb];
    const cosine = Math.max(-1, Math.min(1, ua[0] * ub[0] + ua[1] * ub[1] + ua[2] * ub[2]));
    const turn = Math.PI - Math.acos(cosine);
    const reach = Math.min(la / 2, lb / 2, bendMm * Math.tan(turn / 2));
    if (turn < 1e-6 || reach <= 0) {
      path.push(c);
      continue;
    }
    // A quadratic curve from the corner's two tangent points through it bends as an arc does, near enough.
    const start: Vec3 = [c[0] + ua[0] * reach, c[1] + ua[1] * reach, c[2] + ua[2] * reach];
    const end: Vec3 = [c[0] + ub[0] * reach, c[1] + ub[1] * reach, c[2] + ub[2] * reach];
    const steps = 8;
    for (let k = 0; k <= steps; k += 1) {
      const t = k / steps;
      const w0 = (1 - t) * (1 - t), w1 = 2 * (1 - t) * t, w2 = t * t;
      path.push([w0 * start[0] + w1 * c[0] + w2 * end[0], w0 * start[1] + w1 * c[1] + w2 * end[1], w0 * start[2] + w1 * c[2] + w2 * end[2]]);
    }
  }
  path.push(corners[corners.length - 1]!);
  // A circle swept along the path, its frame carried along without twist.
  let tangent = norm(sub(path[1]!, path[0]!));
  let side = norm(Math.abs(tangent[2]) < 0.9 ? cross(tangent, [0, 0, 1]) : cross(tangent, [1, 0, 0]));
  let along = 0;
  const rings: number[][] = [];
  for (let at = 0; at < path.length; at += 1) {
    if (at > 0) along += Math.hypot(...sub(path[at]!, path[at - 1]!));
    const next = at + 1 < path.length ? norm(sub(path[at + 1]!, path[at]!)) : tangent;
    const here = at === 0 ? tangent : norm([tangent[0] + next[0], tangent[1] + next[1], tangent[2] + next[2]]);
    side = norm(sub(side, scaled(here, dot(side, here))));
    const up = cross(here, side);
    const indices: number[] = [];
    for (let k = 0; k <= segments; k += 1) {
      const angle = (2 * Math.PI * k) / segments;
      const offset: Vec3 = [
        radius * (Math.cos(angle) * side[0] + Math.sin(angle) * up[0]),
        radius * (Math.cos(angle) * side[1] + Math.sin(angle) * up[1]),
        radius * (Math.cos(angle) * side[2] + Math.sin(angle) * up[2]),
      ];
      const p: Vec3 = [path[at]![0] + offset[0], path[at]![1] + offset[1], path[at]![2] + offset[2]];
      indices.push(out.vertex(p, along, radius * angle));
    }
    rings.push(indices);
    tangent = next;
  }
  for (let at = 1; at < rings.length; at += 1) {
    const [a, b] = [rings[at - 1]!, rings[at]!];
    for (let k = 0; k < segments; k += 1) out.indices.push(a[k]!, b[k + 1]!, b[k]!, a[k]!, a[k + 1]!, b[k + 1]!);
  }
  // Its two ends closed, so the tube is a solid like every other form: each end a flat disc facing out along the
  // tube, on its own vertices as a lathe's disc is, so the end's edge stays sharp. A disc sharing the wall's ring
  // would lean the wall's normals there toward its own, shading a straight run as if it bent toward its end.
  const cap = (ring: readonly number[], centre: Vec3, facing: Vec3, start: boolean): void => {
    const corner = (index: number): Vec3 => [out.positions[index * 3]!, out.positions[index * 3 + 1]!, out.positions[index * 3 + 2]!];
    const middle = out.vertex(centre, ...flatSt(centre, facing));
    const around = ring.slice(0, segments).map((index) => out.vertex(corner(index), ...flatSt(corner(index), facing)));
    for (let k = 0; k < segments; k += 1) {
      const [a, b] = [around[k]!, around[(k + 1) % segments]!];
      // A ring runs counter-clockwise round the way the tube runs, so its start faces back against its order.
      if (start) out.indices.push(middle, b, a); else out.indices.push(middle, a, b);
    }
  };
  cap(rings[0]!, path[0]!, norm(sub(path[0]!, path[1]!)), true);
  cap(rings[rings.length - 1]!, path[path.length - 1]!, norm(sub(path[path.length - 1]!, path[path.length - 2]!)), false);
  return true;
}

function plate(out: Builder, part: FurniturePart, rimMm: number, insetMm: number): boolean {
  const { min, max } = boxOf(part);
  const size = [part.sizeXMm, part.sizeYMm, part.sizeZMm];
  // The thinnest side is its thickness; the rim frames the other two.
  const thin = [0, 1, 2].sort((a, b) => size[a]! - size[b]! || a - b)[0]!;
  const [u, v] = [0, 1, 2].filter((axis) => axis !== thin) as [number, number];
  if (rimMm * 2 >= size[u]! || rimMm * 2 >= size[v]! || insetMm * 2 >= size[thin]!) return false;
  const piece = (u0: number, u1: number, v0: number, v1: number, t0: number, t1: number): void => {
    const lo = [0, 0, 0] as [number, number, number];
    const hi = [0, 0, 0] as [number, number, number];
    lo[u] = u0; hi[u] = u1; lo[v] = v0; hi[v] = v1; lo[thin] = t0; hi[thin] = t1;
    out.box(lo, hi);
  };
  const [u0, u1, v0, v1, t0, t1] = [min[u]!, max[u]!, min[v]!, max[v]!, min[thin]!, max[thin]!];
  piece(u0, u1, v0, v0 + rimMm, t0, t1);
  piece(u0, u1, v1 - rimMm, v1, t0, t1);
  piece(u0, u0 + rimMm, v0 + rimMm, v1 - rimMm, t0, t1);
  piece(u1 - rimMm, u1, v0 + rimMm, v1 - rimMm, t0, t1);
  piece(u0 + rimMm, u1 - rimMm, v0 + rimMm, v1 - rimMm, t0 + insetMm, t1 - insetMm);
  return true;
}

function rails(out: Builder, part: FurniturePart, draw: Extract<FurnitureDraw, { form: 'rails' }>): boolean {
  const { min, max } = boxOf(part);
  // Along the longer level side; the other level side is the fence's depth.
  const run = part.sizeXMm >= part.sizeYMm ? 0 : 1;
  const across = 1 - run;
  const length = max[run]! - min[run]!;
  const depth = max[across]! - min[across]!;
  const half = draw.railMm / 2;
  const heights = draw.railsPermille.map((permille) => min[2] + (part.sizeZMm * permille) / 1000);
  if (draw.postMm * 2 >= length || draw.railDepthMm > depth || heights.some((z) => z - half < min[2] || z + half > max[2])) return false;
  // Posts at both ends and evenly between, so no gap between two is wider than the spacing.
  const gaps = Math.max(1, Math.ceil((length - draw.postMm) / draw.spacingMm));
  const step = (length - draw.postMm) / gaps;
  for (let at = 0; at <= gaps; at += 1) {
    const lo = [...min] as [number, number, number];
    const hi = [...max] as [number, number, number];
    lo[run] = min[run]! + at * step;
    hi[run] = lo[run] + draw.postMm;
    out.box(lo, hi);
  }
  // Each rail runs from the first post's inner face to the last's, through the posts between, centred in depth.
  const middle = (min[across]! + max[across]!) / 2;
  for (const z of heights) {
    const lo = [...min] as [number, number, number];
    const hi = [...max] as [number, number, number];
    lo[run] = min[run]! + draw.postMm;
    hi[run] = max[run]! - draw.postMm;
    lo[across] = middle - draw.railDepthMm / 2;
    hi[across] = middle + draw.railDepthMm / 2;
    lo[2] = z - half;
    hi[2] = z + half;
    out.box(lo, hi);
  }
  return true;
}

function norm(v: Vec3): Vec3 { const l = Math.hypot(...v) || 1; return [v[0] / l, v[1] / l, v[2] / l]; }
function dot(a: Vec3, b: Vec3): number { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
function scaled(v: Vec3, k: number): Vec3 { return [v[0] * k, v[1] * k, v[2] * k]; }

/**
 * A record's parts drawn by its class's form, one surface per part role, in the furniture's own frame;
 * null when the class has no form, the parts are not the shapes it expects, or a part is too small for
 * its form (then the record is drawn as baked).
 */
export function furnitureFormSurfaces(forms: FurnitureForms, furnitureClass: string, parts: readonly FurniturePart[]): FurnitureSurface[] | null {
  const form = forms.byClass.get(furnitureClass);
  if (form === undefined) return null;
  return drawForm(form, parts);
}

/** The parts a slot entry states, in millimetres of a slot's box: width, depth and height. */
export function slotFurnitureParts(form: SlotFurnitureForm, boxMm: readonly [number, number, number]): FurniturePart[] {
  const [width, depth, height] = boxMm;
  return form.partsPermille.map((part) => ({
    shape: part.shape, surfaceRole: part.surfaceRole,
    offsetXMm: (part.offsetPermille[0] * width) / 1000, offsetYMm: (part.offsetPermille[1] * depth) / 1000, offsetZMm: (part.offsetPermille[2] * height) / 1000,
    sizeXMm: (part.sizePermille[0] * width) / 1000, sizeYMm: (part.sizePermille[1] * depth) / 1000, sizeZMm: (part.sizePermille[2] * height) / 1000,
  }));
}

/**
 * A slot drawn by its leaf's slot form, one surface per part role, in the slot's own frame (`+x` along its
 * width, `+y` toward its front, `+z` up, millimetres from its base centre); null when its leaf has no form
 * or its box is too small for a form (then the slot is drawn as its box).
 */
export function slotFurnitureSurfaces(forms: FurnitureForms, leaf: string, boxMm: readonly [number, number, number]): FurnitureSurface[] | null {
  const form = forms.bySlotLeaf.get(leaf);
  if (form === undefined) return null;
  return drawForm(form, slotFurnitureParts(form, boxMm));
}

/**
 * Where a body rests on a slot drawn by its leaf's slot form: the top of each part the form lays as level
 * slats, across the slats and the gaps between them, at the slats' own top. A person sits across slats,
 * not between them, so a seat's contact reads these with what is drawn. Two triangles to a top,
 * counter-clockwise seen from above, millimetres in the slot's own frame; empty when the form lays no
 * level slats; null when the slot is not drawn by a form (`slotFurnitureSurfaces`).
 */
export function slotFurnitureSeatTops(forms: FurnitureForms, leaf: string, boxMm: readonly [number, number, number]): number[] | null {
  const form = forms.bySlotLeaf.get(leaf);
  if (form === undefined) return null;
  const parts = slotFurnitureParts(form, boxMm);
  if (drawForm(form, parts) === null) return null;
  const tops: number[] = [];
  for (const draw of form.draws) {
    if (draw.form !== 'slats') continue;
    const part = parts[draw.parts[0]!]!;
    // Level slats are thinnest upright, as `slats` lays them: side by side across the second longest side.
    if (!(part.sizeZMm < part.sizeXMm && part.sizeZMm < part.sizeYMm)) continue;
    const { min, max } = boxOf(part);
    const z = max[2];
    tops.push(min[0], min[1], z, max[0], min[1], z, max[0], max[1], z, min[0], min[1], z, max[0], max[1], z, min[0], max[1], z);
  }
  return tops;
}

function drawForm(form: FurnitureForm, parts: readonly FurniturePart[]): FurnitureSurface[] | null {
  if (parts.length !== form.parts.length || parts.some((part, at) => part.shape !== form.parts[at])) return null;
  const builders = new Map<string, Builder>();
  const builder = (role: string): Builder => {
    let held = builders.get(role);
    if (held === undefined) {
      held = new Builder(role);
      builders.set(role, held);
    }
    return held;
  };
  for (const draw of form.draws) {
    const part = parts[draw.parts[0]!]!;
    const out = builder(part.surfaceRole);
    const made = draw.form === 'solid' ? solid(out, part)
      : draw.form === 'slats' ? slats(out, part, draw.count, draw.gapMm)
      : draw.form === 'frame' ? frame(out, part, draw.barMm, draw.top, draw.foot)
      : draw.form === 'lathe' ? lathe(out, part, draw.segments, draw.profilePermille)
      : draw.form === 'tube' ? tube(out, parts, draw.through, draw.radiusPermille, draw.bendMm, draw.segments)
      : draw.form === 'rails' ? rails(out, part, draw)
      : plate(out, part, draw.rimMm, draw.insetMm);
    if (!made) return null;
  }
  return [...builders.values()].filter((one) => one.indices.length > 0)
    .map((one) => Object.freeze({ role: one.role, positions: one.positions, st: one.st, indices: one.indices }));
}

/**
 * The box each drawn vertex must stay inside: a slat, frame, lathe or plate inside its own part's box,
 * a tube inside the common box of the parts it draws. For the tests' invariant and for any reader.
 */
export function furnitureFormEnvelopes(form: FurnitureForm, parts: readonly FurniturePart[]): { readonly min: Vec3; readonly max: Vec3 }[] {
  return form.draws.map((draw) => {
    const boxes = draw.parts.map((index) => boxOf(parts[index]!));
    return {
      min: [Math.min(...boxes.map((b) => b.min[0])), Math.min(...boxes.map((b) => b.min[1])), Math.min(...boxes.map((b) => b.min[2]))],
      max: [Math.max(...boxes.map((b) => b.max[0])), Math.max(...boxes.map((b) => b.max[1])), Math.max(...boxes.map((b) => b.max[2]))],
    };
  });
}
