/**
 * A planar uniform grid over x and z. Items are inserted by bounding box and returned in
 * insertion order, deduplicated, so every query is deterministic.
 */

export class PlanarGrid {
  private readonly cells = new Map<number, number[]>();
  private readonly stamps: Uint32Array;
  private stamp = 0;

  constructor(
    private readonly cellSize: number,
    capacity: number,
  ) {
    if (!(cellSize > 0)) throw new Error('grid cell size must be positive');
    this.stamps = new Uint32Array(capacity);
  }

  private static key(ix: number, iz: number): number {
    // Cells stay within +/- 2^20 on each axis for any district this gate measures.
    return (ix + 1_048_576) * 2_097_152 + (iz + 1_048_576);
  }

  private index(value: number): number {
    return Math.floor(value / this.cellSize);
  }

  insert(item: number, minX: number, minZ: number, maxX: number, maxZ: number): void {
    const x0 = this.index(minX);
    const x1 = this.index(maxX);
    const z0 = this.index(minZ);
    const z1 = this.index(maxZ);
    for (let ix = x0; ix <= x1; ix += 1) {
      for (let iz = z0; iz <= z1; iz += 1) {
        const key = PlanarGrid.key(ix, iz);
        const held = this.cells.get(key);
        if (held === undefined) this.cells.set(key, [item]);
        else held.push(item);
      }
    }
  }

  /** Every item whose inserted box shares a cell with the query box, each once. */
  query(minX: number, minZ: number, maxX: number, maxZ: number, visit: (item: number) => void): void {
    this.stamp += 1;
    if (this.stamp === 0xffffffff) {
      this.stamps.fill(0);
      this.stamp = 1;
    }
    const x0 = this.index(minX);
    const x1 = this.index(maxX);
    const z0 = this.index(minZ);
    const z1 = this.index(maxZ);
    for (let ix = x0; ix <= x1; ix += 1) {
      for (let iz = z0; iz <= z1; iz += 1) {
        const held = this.cells.get(PlanarGrid.key(ix, iz));
        if (held === undefined) continue;
        for (const item of held) {
          if (this.stamps[item] === this.stamp) continue;
          this.stamps[item] = this.stamp;
          visit(item);
        }
      }
    }
  }
}
