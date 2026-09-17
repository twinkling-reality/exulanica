import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import type { MapDescriptor } from '../src/classes.js';
import { MAP_LAYOUT } from '../src/container.js';
import type { Fields } from '../src/maps.js';

/** The repository root: web/packages/loom-texture/test -> root. */
export const REPOSITORY = fileURLToPath(new URL('../../../../', import.meta.url));

/** The published directory, at the repository root. */
export const PUBLISHED = fileURLToPath(new URL('../../../../assets/textures/', import.meta.url));

export function readPublished(path: string): Uint8Array {
  return new Uint8Array(readFileSync(`${PUBLISHED}${path}`));
}

/**
 * How a channel behaves across its wrap edge, in integer units: the summed absolute difference
 * across the edge pair (last column to first, or last row to first), against the same sum for
 * every interior neighbour pair along that axis.
 */
export interface SeamReport {
  readonly map: string;
  readonly channel: number;
  readonly axis: 'u' | 'v';
  readonly seam: number;
  readonly interiorSum: number;
  readonly interiorCount: number;
}

export function seamReports(
  width: number,
  height: number,
  maps: Readonly<Record<string, Uint8Array>>,
  layout: readonly MapDescriptor[] = MAP_LAYOUT,
): SeamReport[] {
  const reports: SeamReport[] = [];
  for (const descriptor of layout) {
    const data = maps[descriptor.name]!;
    const stride = descriptor.components;
    for (let channel = 0; channel < stride; channel += 1) {
      const columns = new Float64Array(width);
      const rows = new Float64Array(height);
      for (let y = 0; y < height; y += 1) {
        const row = y * width;
        const below = (y + 1 === height ? 0 : y + 1) * width;
        for (let x = 0; x < width; x += 1) {
          const here = data[(row + x) * stride + channel]!;
          const right = data[(row + (x + 1 === width ? 0 : x + 1)) * stride + channel]!;
          const down = data[(below + x) * stride + channel]!;
          columns[x] = columns[x]! + Math.abs(here - right);
          rows[y] = rows[y]! + Math.abs(here - down);
        }
      }
      for (const [axis, sums] of [['u', columns], ['v', rows]] as const) {
        let interiorSum = 0;
        for (let k = 0; k < sums.length - 1; k += 1) interiorSum += sums[k]!;
        reports.push({
          map: descriptor.name,
          channel,
          axis,
          seam: sums[sums.length - 1]!,
          interiorSum,
          interiorCount: sums.length - 1,
        });
      }
    }
  }
  return reports;
}

/**
 * The continuity criterion: the difference across the wrap edge is at most twice the mean
 * difference between interior neighbours. A seam a person can see is one that stands out from the
 * texture's own neighbour-to-neighbour variation; a torus-sampled field sits near 1, and the
 * measured worst across the published sets is about 1.5, where the texel grid beats against a
 * fine lattice. Integer arithmetic throughout.
 */
export const continuous = (report: SeamReport): boolean =>
  report.seam * report.interiorCount <= 2 * report.interiorSum;

export const FIELD_NAMES = [
  'relief',
  'red',
  'green',
  'blue',
  'roughness',
  'metalness',
  'occlusion',
  'coverage',
  'transmission',
] as const satisfies readonly (keyof Fields)[];

/** Where `shifted` disagrees with `base` rolled by (du, dv), as a count per named plane. */
export function rollMismatches(
  width: number,
  height: number,
  planes: Readonly<Record<string, readonly [ArrayLike<number>, ArrayLike<number>, number]>>,
  du: number,
  dv: number,
): Record<string, number> {
  const wrap = (value: number, size: number): number => ((value % size) + size) % size;
  const out: Record<string, number> = {};
  for (const [name, [base, shifted, stride]] of Object.entries(planes)) {
    let mismatches = 0;
    for (let y = 0; y < height; y += 1) {
      const sourceRow = wrap(y + dv, height) * width;
      for (let x = 0; x < width; x += 1) {
        const from = (sourceRow + wrap(x + du, width)) * stride;
        const to = (y * width + x) * stride;
        for (let c = 0; c < stride; c += 1) {
          if (base[from + c] !== shifted[to + c]) mismatches += 1;
        }
      }
    }
    out[name] = mismatches;
  }
  return out;
}
