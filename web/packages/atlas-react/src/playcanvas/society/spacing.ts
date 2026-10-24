/**
 * How far each person standing near others is drawn off their standing point so that no two stand
 * inside each other (DESIGN's T0): any two nearer than the spacing each step half the shortfall back
 * along the line between them, two at one point parting east and west (the lesser id to the west),
 * a person's steps from all their neighbours added and held to the most one step may take, so a
 * body never reaches a wall; where the room that way is known (`Room`, the world's plan sight), the
 * step goes on toward the whole shortfall as far as the room past it holds a body (T0b). And how far
 * each walker is drawn across their way (T0b): two walking the same way nearer than a shoulder apart
 * each half the shortfall apart, and a walker passing someone standing within a body's width aside of
 * them, each held to the room beside them. Presentation only: the crowd draws the step at the
 * person's own pace and no recorded position or path changes. Plan metres, east and south.
 *
 * Pure: no renderer.
 */

/** Someone standing, by id, at the point they stand at rest. */
export interface Stander {
  readonly id: string;
  readonly at: readonly [number, number];
}

const SAME_POINT_METRES = 0.001;
/** Two walking within this of one way (cosine of 45 degrees) walk the same way. */
const SAME_WAY = Math.SQRT1_2;
/** How many pass asides ahead a walker begins to step from someone standing on their line. */
const PASS_AHEAD = 2;

/** How much room lies from a point along a unit way, metres, at most `most`; null where nothing says. */
export type Room = (at: readonly [number, number], way: readonly [number, number], most: number) => number | null;

/** Someone walking, by id: where they are drawn on their path now, and the unit way they walk. */
export interface Walking {
  readonly id: string;
  readonly at: readonly [number, number];
  readonly way: readonly [number, number];
}

/**
 * Each step held to what may be taken: past `stepMost` only as far as `room` says the way is open by the step
 * and a body (`bodyDepth`) more; with nothing said, `stepMost` at the most.
 */
function holdSteps(
  steps: Map<string, [number, number]>, at: ReadonlyMap<string, readonly [number, number]>, stepMost: number, room?: Room, bodyDepth = 0,
): void {
  for (const [id, step] of steps) {
    const length = Math.hypot(step[0], step[1]);
    if (length <= stepMost) continue;
    const way = [step[0] / length, step[1] / length] as const;
    const open = room?.(at.get(id)!, way, length + bodyDepth) ?? null;
    const most = open === null ? stepMost : Math.max(stepMost, Math.min(length, open - bodyDepth));
    steps.set(id, [way[0] * most, way[1] * most]);
  }
}

/**
 * Each stander's step, by id, for `spacing` metres between any two and at most `stepMost` metres
 * for anyone; a stander with no one nearer than the spacing has none. Neighbours are found through
 * squares of the spacing's side, so a crowd of any size costs about its count.
 */
export function spacingSteps(
  standers: readonly Stander[], spacing: number, stepMost: number, room?: Room, bodyDepth = 0,
): ReadonlyMap<string, readonly [number, number]> {
  const steps = new Map<string, [number, number]>();
  if (!(spacing > 0) || !(stepMost > 0)) return steps;
  const ordered = [...standers].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const cells = new Map<string, Stander[]>();
  const cell = (x: number, z: number) => `${Math.floor(x / spacing)},${Math.floor(z / spacing)}`;
  for (const one of ordered) {
    const key = cell(one.at[0], one.at[1]);
    const held = cells.get(key);
    if (held === undefined) cells.set(key, [one]);
    else held.push(one);
  }
  const add = (id: string, dx: number, dz: number) => {
    const held = steps.get(id);
    if (held === undefined) steps.set(id, [dx, dz]);
    else { held[0] += dx; held[1] += dz; }
  };
  for (const a of ordered) {
    const cx = Math.floor(a.at[0] / spacing), cz = Math.floor(a.at[1] / spacing);
    for (let x = cx - 1; x <= cx + 1; x += 1) {
      for (let z = cz - 1; z <= cz + 1; z += 1) {
        for (const b of cells.get(`${x},${z}`) ?? []) {
          // Each pair once, the lesser id first.
          if (!(a.id < b.id)) continue;
          const dx = a.at[0] - b.at[0], dz = a.at[1] - b.at[1];
          const between = Math.hypot(dx, dz);
          if (between >= spacing) continue;
          const back = (spacing - between) / 2;
          const [ux, uz] = between > SAME_POINT_METRES ? [dx / between, dz / between] : [-1, 0];
          add(a.id, ux * back, uz * back);
          add(b.id, -ux * back, -uz * back);
        }
      }
    }
  }
  holdSteps(steps, new Map(ordered.map((one) => [one.id, one.at])), stepMost, room, bodyDepth);
  return steps;
}

/**
 * Each walker's step across their way, by id: from another walking the same way nearer than `apart` across it
 * and within two body depths along it (abreast, so their bodies meet), half the shortfall each (two on one line
 * part by id, the lesser to their right); from someone standing nearer
 * than `aside` across their way, from twice that ahead until that far behind, the walker alone the whole
 * shortfall away from them (from one on their line, to the side `room` says has more). Held to the room beside
 * them less a body (`room`, `bodyDepth`); with nothing said, at most `stepMost`. A walker with nobody near has none.
 */
export function walkingSteps(
  walkers: readonly Walking[], standers: readonly Stander[],
  { apart, aside, stepMost, bodyDepth, room }: { readonly apart: number; readonly aside: number; readonly stepMost: number; readonly bodyDepth: number; readonly room?: Room },
): ReadonlyMap<string, readonly [number, number]> {
  const steps = new Map<string, [number, number]>();
  if (walkers.length === 0) return steps;
  const reach = Math.max(apart, 2 * bodyDepth, PASS_AHEAD * aside);
  if (!(reach > 0)) return steps;
  const cells = new Map<string, { readonly id: string; readonly at: readonly [number, number]; readonly way: readonly [number, number] | null }[]>();
  const key = (x: number, z: number) => `${Math.floor(x / reach)},${Math.floor(z / reach)}`;
  for (const one of [...walkers, ...standers.map((still) => ({ ...still, way: null }))]) {
    const k = key(one.at[0], one.at[1]);
    const held = cells.get(k);
    if (held === undefined) cells.set(k, [one]);
    else held.push(one);
  }
  const add = (id: string, dx: number, dz: number) => {
    const held = steps.get(id);
    if (held === undefined) steps.set(id, [dx, dz]);
    else { held[0] += dx; held[1] += dz; }
  };
  for (const a of [...walkers].sort((x, y) => (x.id < y.id ? -1 : x.id > y.id ? 1 : 0))) {
    // Their right, across their way (east and south: a way (x, z) has (-z, x) on its right).
    const right = [-a.way[1], a.way[0]] as const;
    const cx = Math.floor(a.at[0] / reach), cz = Math.floor(a.at[1] / reach);
    for (let x = cx - 1; x <= cx + 1; x += 1) {
      for (let z = cz - 1; z <= cz + 1; z += 1) {
        for (const b of cells.get(`${x},${z}`) ?? []) {
          if (b.id === a.id) continue;
          const dx = a.at[0] - b.at[0], dz = a.at[1] - b.at[1];
          const across = dx * right[0] + dz * right[1], ahead = -(dx * a.way[0] + dz * a.way[1]);
          const side = Math.abs(across) > SAME_POINT_METRES ? Math.sign(across) : a.id < b.id ? 1 : -1;
          if (b.way === null) {
            // Someone standing ahead within twice the pass aside, or not yet a pass aside behind, near their line:
            // the walker is aside before they reach them, at their own pace; from one on their line, to the side
            // with more room.
            if (ahead > PASS_AHEAD * aside || ahead < -aside) continue;
            const step = aside - Math.abs(across);
            if (!(step > 0)) continue;
            const open = (way: number) => room?.(a.at, [right[0] * way, right[1] * way], step + bodyDepth) ?? null;
            const roomier = Math.abs(across) > SAME_POINT_METRES ? side : (open(-side) ?? 0) > (open(side) ?? 0) ? -side : side;
            add(a.id, right[0] * roomier * step, right[1] * roomier * step);
          } else if (a.id < b.id && Math.abs(ahead) < 2 * bodyDepth && Math.abs(across) < apart
            && a.way[0] * b.way[0] + a.way[1] * b.way[1] >= SAME_WAY) {
            // Two walking the same way abreast near enough that their bodies meet; one behind another walks on.
            const half = (apart - Math.abs(across)) / 2;
            if (half <= 0) continue;
            add(a.id, right[0] * side * half, right[1] * side * half);
            add(b.id, -right[0] * side * half, -right[1] * side * half);
          }
        }
      }
    }
  }
  holdSteps(steps, new Map(walkers.map((one) => [one.id, one.at])), stepMost, room, bodyDepth);
  return steps;
}
