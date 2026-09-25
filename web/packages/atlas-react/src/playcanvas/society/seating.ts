/**
 * Where a person using an object is drawn: facing it at their place, or sitting on its seat.
 *
 * The simulation puts a person using an object at one of its places, and nothing here moves them
 * there or anywhere else. What this adds is presentation read from the world object catalog, which
 * the registry reads serve as each kind's `use` (`GET /world/assets`): the side of the kind a person
 * at each place faces, and the seat a resting person at that place is drawn on. Both are stated in
 * the kind's own part frame, millimetres about the bottom centre of what it draws, with `+x` across
 * it, `+y` its front and `+z` up. A placed object carries that frame by its transform: the part
 * frame's `+y` is the region's `-z`, so a point `[x, y, z]` is `[x, z, -y]` in the region's east, up
 * and south axes, then scaled by the object's scale and turned by its yaw about the vertical axis,
 * which carries the object's own `x` to `(cos, -sin)` and its `z` to `(sin, cos)` in the region.
 *
 * Which place a person holds is found from the object their action targets, never from a place
 * id's spelling: their recorded position, carried back into the object's frame, is the catalog
 * place within {@link PLACE_MATCH_MM} of it. The server turned each place with outward rounding to
 * the whole millimetre (`turned_point`), so a held place is always that close and two places, a
 * standing spacing apart, never both are. A person matched to no place, or at an object whose kind
 * states no places, is drawn by the rule for everyone else, and the reason is named.
 */

/** A side of a kind, in its part frame. */
export type KindSide = '+y' | '+x' | '-y' | '-x';

export const KIND_SIDES: readonly KindSide[] = ['+y', '+x', '-y', '-x'];

export interface KindSeat {
  /** Where the resting person's pelvis is drawn, part frame millimetres. */
  readonly positionMm: readonly [number, number, number];
  readonly faces: KindSide;
}

export interface KindPlace {
  /** Where the person stands, part frame millimetres. */
  readonly positionMm: readonly [number, number];
  readonly faces: KindSide;
  readonly seat: KindSeat | null;
}

/** A kind's use as the registry serves it; `places` is null for a marker. */
export interface KindUse {
  readonly affordance: string;
  readonly places: readonly KindPlace[] | null;
}

/** An object of the drawn version: its kind and its region-local transform. */
export interface SeatingObject {
  readonly objectId: string;
  readonly assetKey: string;
  readonly xMm: number;
  readonly yMm: number;
  readonly zMm: number;
  readonly yawMicroradians: number;
  readonly scaleMilli: number;
}

/** What the drawn version and the society's consumed input say a person can use. */
export interface SeatingLayout {
  /** Each kind's use, by asset key. */
  readonly uses: ReadonlyMap<string, KindUse>;
  readonly objects: readonly SeatingObject[];
  /** Society target id to the object it belongs to, or null for a district's own destination. */
  readonly targets: ReadonlyMap<string, string | null>;
}

/** Where a person at a place is drawn. Metres and radians in the society root's frame. */
export interface PlaceDrawing {
  readonly objectId: string;
  readonly placeIndex: number;
  /** Facing at the place, about +Y with -Z forward, as a full character faces. */
  readonly facing: number;
  readonly seat: {
    /** The seat point: east, up (the seat's top) and south. */
    readonly position: readonly [number, number, number];
    readonly facing: number;
  } | null;
}

/**
 * Why a person using an object is drawn by the rule for everyone else:
 * - `target-unknown`: their action names a target the consumed input does not hold;
 * - `target-has-no-object`: the target is a district's own destination, not a placed object;
 * - `object-not-drawn`: the object is not in the version being drawn;
 * - `kind-has-no-use`: the registry serves no use for the object's kind;
 * - `kind-states-no-places`: the kind is a marker, whose places the society derives itself;
 * - `no-place-within-rounding`: no place of the kind lies within {@link PLACE_MATCH_MM} of them.
 */
export type SeatingMiss =
  | 'target-unknown'
  | 'target-has-no-object'
  | 'object-not-drawn'
  | 'kind-has-no-use'
  | 'kind-states-no-places'
  | 'no-place-within-rounding';

export type SeatingResult =
  | { readonly kind: 'place'; readonly drawing: PlaceDrawing }
  | { readonly kind: 'miss'; readonly reason: SeatingMiss };

/**
 * How far a person's recorded position may lie from the place they hold, in millimetres. The
 * server turns a place and moves each coordinate outward to the whole millimetre, less than one
 * millimetre on each axis, so under the square root of two away; a double carries positions of up
 * to the registry's 10 m reach to far better than a micrometre, which the added micrometre covers.
 */
export const PLACE_MATCH_MM = Math.SQRT2 + 0.001;

const MILLIMETRES_PER_METRE = 1000;
const MICRORADIANS_PER_RADIAN = 1_000_000;
/** The transform's scale unit: 1000 is the kind's own size. */
const SCALE_UNIT = 1000;

/** A unit direction in the part frame, for each side. */
const SIDE_DIRECTIONS: Readonly<Record<KindSide, readonly [number, number]>> = {
  '+y': [0, 1],
  '-y': [0, -1],
  '+x': [1, 0],
  '-x': [-1, 0],
};

/** A part frame plan offset, `[x, y]`, as region east and south offsets after the object's turn. */
export function turnedOffset(
  object: Pick<SeatingObject, 'yawMicroradians' | 'scaleMilli'>,
  offset: readonly [number, number],
): readonly [number, number] {
  const theta = object.yawMicroradians / MICRORADIANS_PER_RADIAN;
  const c = Math.cos(theta), s = Math.sin(theta);
  const scale = object.scaleMilli / SCALE_UNIT;
  const dx = offset[0] * scale, dz = -offset[1] * scale;
  return [dx * c + dz * s, -dx * s + dz * c];
}

/** The inverse: a region east and south offset from the object's centre, in its part frame. */
export function partOffset(
  object: Pick<SeatingObject, 'yawMicroradians' | 'scaleMilli'>,
  regionOffset: readonly [number, number],
): readonly [number, number] {
  const theta = object.yawMicroradians / MICRORADIANS_PER_RADIAN;
  const c = Math.cos(theta), s = Math.sin(theta);
  const scale = object.scaleMilli / SCALE_UNIT;
  const [ex, ez] = regionOffset;
  const dx = ex * c - ez * s, dz = ex * s + ez * c;
  return [dx / scale, -dz / scale];
}

/** Facing, about +Y with -Z forward, of someone looking toward a side of a turned object. */
export function sideFacing(object: Pick<SeatingObject, 'yawMicroradians'>, side: KindSide): number {
  const [dx, dz] = turnedOffset({ yawMicroradians: object.yawMicroradians, scaleMilli: SCALE_UNIT }, SIDE_DIRECTIONS[side]);
  return Math.atan2(-dx, -dz);
}

/**
 * Where a person using an object is drawn, or the named reason they are drawn as everyone is.
 * `targetId` is the target their action names; `positionMm` is their recorded east and south.
 */
export function placeDrawing(
  layout: SeatingLayout,
  targetId: string,
  positionMm: readonly [number, number],
): SeatingResult {
  if (!layout.targets.has(targetId)) return { kind: 'miss', reason: 'target-unknown' };
  const objectId = layout.targets.get(targetId) ?? null;
  if (objectId === null) return { kind: 'miss', reason: 'target-has-no-object' };
  const object = layout.objects.find((held) => held.objectId === objectId);
  if (object === undefined) return { kind: 'miss', reason: 'object-not-drawn' };
  const use = layout.uses.get(object.assetKey);
  if (use === undefined) return { kind: 'miss', reason: 'kind-has-no-use' };
  if (use.places === null) return { kind: 'miss', reason: 'kind-states-no-places' };
  const [px, py] = partOffset(object, [positionMm[0] - object.xMm, positionMm[1] - object.zMm]);
  const scale = object.scaleMilli / SCALE_UNIT;
  let placeIndex = -1;
  let nearest = Number.POSITIVE_INFINITY;
  use.places.forEach((place, index) => {
    // Compared in region millimetres, where the rounding bound holds, whatever the scale.
    const apart = Math.hypot(place.positionMm[0] - px, place.positionMm[1] - py) * scale;
    if (apart < nearest) {
      nearest = apart;
      placeIndex = index;
    }
  });
  if (placeIndex < 0 || nearest >= PLACE_MATCH_MM) return { kind: 'miss', reason: 'no-place-within-rounding' };
  const place = use.places[placeIndex]!;
  let seat: PlaceDrawing['seat'] = null;
  if (place.seat !== null) {
    const [sx, sy, sz] = place.seat.positionMm;
    const [ex, ez] = turnedOffset(object, [sx, sy]);
    seat = {
      position: [
        (object.xMm + ex) / MILLIMETRES_PER_METRE,
        (object.yMm + sz * scale) / MILLIMETRES_PER_METRE,
        (object.zMm + ez) / MILLIMETRES_PER_METRE,
      ],
      facing: sideFacing(object, place.seat.faces),
    };
  }
  return {
    kind: 'place',
    drawing: { objectId, placeIndex, facing: sideFacing(object, place.faces), seat },
  };
}

/**
 * How far from a seat's point a person stands before sitting down, metres: in front of a seat
 * whose place is in front of it, or beside one reached from the side. A standing body, about 0.25 m
 * from its centre to its front, then clears a seat edge the 0.2 m ahead of the pelvis point the
 * catalog's seats put it (bench and ledge; the chairs' edges are nearer).
 */
export const SEAT_APPROACH_METRES = 0.45;
/**
 * A place within this angle of the way a seat faces is in front of it, and the seat is approached
 * from the front; from anywhere else it is approached from the side nearer the place, as a person
 * steps beside a chair at a table rather than through the table to its front.
 */
const FRONT_APPROACH_RADIANS = Math.PI / 4;

/**
 * Where a person stands before sitting on a seat, in the society root's plan (east, south): a
 * stride in front of the seat when their place is in front of it, else a stride beside it on the
 * place's side, so the walk to the seat does not pass through what it is part of.
 */
export function seatApproach(
  seat: readonly [number, number],
  seatFacing: number,
  place: readonly [number, number],
): readonly [number, number] {
  const forward = [-Math.sin(seatFacing), -Math.cos(seatFacing)] as const;
  const across = [forward[1], -forward[0]] as const;
  const dx = place[0] - seat[0], dz = place[1] - seat[1];
  const distance = Math.hypot(dx, dz);
  const ahead = distance === 0 ? 1 : (dx * forward[0] + dz * forward[1]) / distance;
  if (ahead >= Math.cos(FRONT_APPROACH_RADIANS)) {
    return [seat[0] + forward[0] * SEAT_APPROACH_METRES, seat[1] + forward[1] * SEAT_APPROACH_METRES];
  }
  const side = dx * across[0] + dz * across[1] >= 0 ? 1 : -1;
  return [seat[0] + across[0] * side * SEAT_APPROACH_METRES, seat[1] + across[1] * side * SEAT_APPROACH_METRES];
}
