/**
 * Borders between a made place's grounds: how the edge of one ground is broken where it meets another.
 *
 * A site's grounds are flat rectangles laid one over another, and each meets its neighbours on a
 * ruled line. The ground border catalog (`assets/catalogs/world-kinds/ground-border.v1.json`) states,
 * by surface material, how that line is broken where the ground is the upper of two: a small ragged
 * break at the edge itself (`edge`), over a gentler wander of the line (`wander`, over `period`),
 * small enough that a path keeps its width and its direction. One rule, no table of pairs: THE UPPER
 * GROUND BREAKS OVER THE LOWER ONE, and the lower runs on under it, so what shows in a break is the
 * neighbour and never a third ground under both. Which is upper is the drawing's own layering, with
 * one exception the catalog states: water lies under whatever ground it meets. At a shore THE LAND
 * BREAKS OVER THE WATER by the land's own edge, in tongues only: the water is never drawn past its
 * own ruled line, so the picture may show land where the walk says water and never water where a
 * person walks. A place's outer edge is its base ground breaking over the ground beyond.
 *
 * Colour only. A border changes where a ground is DRAWN, within its reach of the ruled line (the
 * catalog's greatest reach is how far the picture and the walk may disagree anywhere). The walked
 * surface, every box, what hides a being and a click read the drawing's rectangles as before; a
 * rectangle stays a rectangle with a rough edge, and nothing is raised. A material with no entry
 * (a floor, a deck, a carpet) keeps its ruled edge.
 *
 * Pure: no DOM, no Node, no renderer. The catalog's text is passed in.
 */

export const GROUND_BORDER_CATALOG_ID = 'ground-border';

export interface GroundBorder {
  /** The surface material whose edge this breaks. */
  readonly key: string;
  /** Whether it breaks over the grounds it meets, or lies under them all (water). */
  readonly lies: 'over' | 'under';
  /** The width of the ragged break at the edge itself, millimetres. */
  readonly edgeMm: number;
  /** How far the line wanders to either side of the ruled one, and over what length, millimetres. */
  readonly wanderMm: number;
  readonly periodMm: number;
}

export interface GroundBorders {
  readonly version: number;
  readonly byMaterial: ReadonlyMap<string, GroundBorder>;
  /** The farthest any ground's edge is drawn from its ruled line, either way, millimetres. */
  readonly greatestReachMm: number;
}

/** How far a border's edge can lie from its ruled line: its wander and half its break. */
export const borderReachMm = (border: GroundBorder): number => border.wanderMm + Math.ceil(border.edgeMm / 2);

const KEY = /^[a-z][a-z0-9_]{0,39}$/;

function refuse(where: string, detail: string): never {
  throw new TypeError(`ground border catalog: ${where} ${detail}`);
}

function whole(value: unknown, where: string, min: number, max: number): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < min || value > max) {
    return refuse(where, `must be a whole number from ${min} to ${max}`);
  }
  return value;
}

/** Read the catalog's text, or refuse it by naming the first entry that is not a border. */
export function readGroundBorders(text: string): GroundBorders {
  const document = JSON.parse(text) as { readonly catalog_id?: unknown; readonly catalog_version?: unknown; readonly entries?: unknown };
  if (document.catalog_id !== GROUND_BORDER_CATALOG_ID || !Array.isArray(document.entries)) return refuse('the file', 'is not the ground border catalog');
  const version = whole(document.catalog_version, 'catalog_version', 1, 1_000_000);
  const byMaterial = new Map<string, GroundBorder>();
  let shoreMost = Number.POSITIVE_INFINITY;
  for (const entry of document.entries as readonly Record<string, unknown>[]) {
    const key = entry?.['key'];
    if (typeof key !== 'string' || !KEY.test(key)) return refuse('an entry', `has the key ${JSON.stringify(key)}`);
    if (byMaterial.has(key)) return refuse(key, 'is stated twice');
    const reason = entry['reason'];
    if (typeof reason !== 'string' || reason.trim() === '') return refuse(key, 'gives no reason');
    const lies = entry['lies'];
    if (lies !== 'over' && lies !== 'under') return refuse(`${key}.lies`, 'must be over or under');
    const border: GroundBorder = {
      key, lies,
      edgeMm: whole(entry['edge_mm'], `${key}.edge_mm`, 0, 5000),
      wanderMm: whole(entry['wander_mm'], `${key}.wander_mm`, 0, 5000),
      periodMm: whole(entry['wander_period_mm'], `${key}.wander_period_mm`, 100, 1_000_000),
    };
    if (border.edgeMm === 0 && border.wanderMm === 0) return refuse(key, 'breaks nothing');
    // What lies under states how far a ground may reach over it; what breaks over states none.
    if ((lies === 'under') !== ('shore_reach_most_mm' in entry)) return refuse(key, 'states a shore reach unless it lies under, or none though it does');
    if (lies === 'under') shoreMost = Math.min(shoreMost, whole(entry['shore_reach_most_mm'], `${key}.shore_reach_most_mm`, 1, 5000));
    byMaterial.set(key, Object.freeze(border));
  }
  let greatest = 0;
  for (const border of byMaterial.values()) {
    const reach = borderReachMm(border);
    // No ground reaches farther from its ruled line than land may reach over water: one greatest
    // distance by which the picture and the walk disagree, at a shore and everywhere else.
    if (reach > shoreMost) return refuse(border.key, `reaches ${reach} mm, farther than the ${shoreMost} mm a ground may reach over water`);
    greatest = Math.max(greatest, reach);
  }
  return Object.freeze({ version, byMaterial, greatestReachMm: greatest });
}

/** A ground rectangle of a place, as its drawing lays it: site millimetres (x east, y north). */
export interface GroundPlane {
  readonly identity: string;
  /** West, south, east, north. */
  readonly rectMm: readonly [number, number, number, number];
  /** How high the drawing lays it; of two at one height the later in the drawing is the upper. */
  readonly layerMm: number;
  /** Its material's border, or null where the catalog states none for it (its edge stays ruled). */
  readonly border: GroundBorder | null;
}

/**
 * A neighbour a plane's edge is worked against: its rectangle and its border (null: a ruled edge).
 * `as` says how: a ground lying `over` the plane, which the plane gives way to and runs on under;
 * or, for land, a `water` it reaches, over which its edge only ever reaches outward.
 */
export interface BorderNeighbour {
  readonly identity: string;
  readonly rectMm: readonly [number, number, number, number];
  readonly border: GroundBorder | null;
  readonly as: 'over' | 'water';
}

/** How one ground plane is drawn so its borders are broken. */
export interface PlaneBorder {
  /** Its own border, cut where no neighbour lies over it; null keeps its own edge ruled. */
  readonly own: GroundBorder | null;
  /**
   * The neighbours it is worked against, the most overlapping first, at most
   * `BORDER_NEIGHBOURS_MOST`: the grounds that lie over it and, for land, the waters it reaches. For
   * a plane that lies under (water) they are the lands whose edge breaks over it.
   */
  readonly over: readonly BorderNeighbour[];
  /** How many more lay over it than are kept: their borders show the ground under both. */
  readonly overLeftOut: number;
}

/**
 * How many neighbours lying over one plane its drawing carries: the number of rectangles one
 * surface's colour is worked against at every point. A plane with more has the most overlapping
 * kept, and the rest counted. A drawing budget, not a fact of any place: no ground of the three
 * places this was made on has more than three.
 */
export const BORDER_NEIGHBOURS_MOST = 4;

/**
 * The borders of a place's grounds, by plane. `base` is the ground the drawing lays over the whole
 * extent (null where it lays none) and `baseBreaks` whether a ground beyond the place is drawn for
 * it to break over; with none, the base ground's outer edge stays ruled, since a break would open
 * onto nothing. Only planes whose drawing changes are in the answer.
 */
export function planBorders(
  planes: readonly GroundPlane[], base: string | null, baseBreaks: boolean, greatestReachMm: number,
): Map<string, PlaneBorder> {
  // Which is upper: what lies under is under everything; then the drawing's layer; then its order.
  const rank = planes.map((plane, order) => [plane.border?.lies === 'under' ? 0 : 1, plane.layerMm, order] as const);
  const above = (a: number, b: number): boolean => {
    for (let k = 0; k < 3; k += 1) if (rank[a]![k] !== rank[b]![k]) return rank[a]![k]! > rank[b]![k]!;
    return false;
  };
  const reachOf = (plane: GroundPlane): number => (plane.border === null ? 0 : borderReachMm(plane.border));
  const out = new Map<string, PlaneBorder>();
  planes.forEach((plane, index) => {
    if (plane.identity === base) {
      if (plane.border !== null && baseBreaks) out.set(plane.identity, { own: plane.border, over: [], overLeftOut: 0 });
      return;
    }
    const [x0, y0, x1, y1] = plane.rectMm;
    const candidates: { neighbour: BorderNeighbour; shared: number }[] = [];
    const lies = plane.border?.lies ?? 'over';
    planes.forEach((other, at) => {
      if (at === index || other.identity === base) return;
      // Land with an edge to break reaches a water it meets; anything else is worked against what
      // lies over it. A ruled ground beside water stays as it is drawn.
      const water = plane.border?.lies === 'over' && other.border?.lies === 'under';
      if (!water && !above(at, index)) return;
      // A ruled neighbour drawn higher simply covers and needs no working; under water it still says
      // where the land is.
      if (!water && lies === 'over' && other.border === null && other.layerMm > plane.layerMm) return;
      // A neighbour matters where an edge can reach this plane's drawn ground: both grown by what
      // either may reach.
      const grow = reachOf(other) + greatestReachMm;
      const [a0, b0, a1, b1] = other.rectMm;
      const width = Math.min(x1, a1 + grow) - Math.max(x0, a0 - grow);
      const depth = Math.min(y1, b1 + grow) - Math.max(y0, b0 - grow);
      if (width < 0 || depth < 0) return;
      candidates.push({
        neighbour: { identity: other.identity, rectMm: other.rectMm, border: other.border, as: water ? 'water' : 'over' },
        shared: Math.max(width, depth),
      });
    });
    if (plane.border === null && candidates.length === 0) return;
    candidates.sort((a, b) => b.shared - a.shared || (a.neighbour.identity < b.neighbour.identity ? -1 : 1));
    out.set(plane.identity, {
      own: plane.border,
      over: candidates.slice(0, BORDER_NEIGHBOURS_MOST).map((candidate) => candidate.neighbour),
      overLeftOut: Math.max(0, candidates.length - BORDER_NEIGHBOURS_MOST),
    });
  });
  return out;
}
