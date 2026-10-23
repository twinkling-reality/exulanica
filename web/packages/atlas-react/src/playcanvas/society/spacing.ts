/**
 * How far each person standing near others is drawn off their standing point so that no two stand
 * inside each other (DESIGN's T0): any two nearer than the spacing each step half the shortfall back
 * along the line between them, two at one point parting east and west (the lesser id to the west),
 * a person's steps from all their neighbours added and held to the most one step may take, so a
 * body never reaches a wall. Presentation only: the crowd draws the step at the person's own pace
 * and no recorded position changes. Plan metres, east and south.
 *
 * Pure: no renderer.
 */

/** Someone standing, by id, at the point they stand at rest. */
export interface Stander {
  readonly id: string;
  readonly at: readonly [number, number];
}

const SAME_POINT_METRES = 0.001;

/**
 * Each stander's step, by id, for `spacing` metres between any two and at most `stepMost` metres
 * for anyone; a stander with no one nearer than the spacing has none. Neighbours are found through
 * squares of the spacing's side, so a crowd of any size costs about its count.
 */
export function spacingSteps(
  standers: readonly Stander[], spacing: number, stepMost: number,
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
  for (const [id, step] of steps) {
    const length = Math.hypot(step[0], step[1]);
    if (length > stepMost) steps.set(id, [(step[0] / length) * stepMost, (step[1] / length) * stepMost]);
  }
  return steps;
}
