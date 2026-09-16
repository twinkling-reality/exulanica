import { bits16, hash3, stream } from './hash.js';
import { FULL, ONE, clamp, floorDiv, floorMod, isqrt, lerp, smooth } from './integer.js';
import { TILE } from './tile.js';

/**
 * Noise on a torus, in integers.
 *
 * Every field here takes a tile position in micro-units (see `tile.ts`) and a PERIOD: how many
 * lattice cells span one tile along each axis. Lattice indices are reduced modulo the period
 * before they are hashed, so the cell one tile to the right is the same cell. That is the whole
 * tiling construction: a field is periodic because its lattice is, and nothing folds a texel
 * coordinate back into the tile to make it look so.
 *
 * Periods are positive integers. An octave doubles its period exactly, which is why the
 * lacunarity is 2 rather than scene-synth's 2.03: a non-integer lacunarity cannot close on a
 * torus. Each octave is instead shifted by its own hashed offset, which breaks the lattice
 * alignment a plain doubling would show, and a constant shift keeps a periodic field periodic.
 */

function cellOf(position: number, period: number): { cell: number; fraction: number } {
  const scaled = position * period;
  const cell = floorDiv(scaled, TILE);
  // TILE is 2^20 and ONE is 2^16, so a sixteenth of the remainder is the Q16 fraction.
  return { cell, fraction: Math.floor((scaled - cell * TILE) / 16) };
}

/** Value noise in [0, 65535], smoothstep-interpolated between hashed lattice values. */
export function valueNoise(
  x: number,
  y: number,
  periodU: number,
  periodV: number,
  seed: number,
): number {
  const scaledX = x * periodU;
  const scaledY = y * periodV;
  const cellX = floorDiv(scaledX, TILE);
  const cellY = floorDiv(scaledY, TILE);
  const sx = smooth(Math.floor((scaledX - cellX * TILE) / 16));
  const sy = smooth(Math.floor((scaledY - cellY * TILE) / 16));
  const x0 = floorMod(cellX, periodU);
  const y0 = floorMod(cellY, periodV);
  const x1 = x0 + 1 === periodU ? 0 : x0 + 1;
  const y1 = y0 + 1 === periodV ? 0 : y0 + 1;
  const top = lerp(bits16(hash3(x0, y0, 0, seed)), bits16(hash3(x1, y0, 0, seed)), sx);
  const bottom = lerp(bits16(hash3(x0, y1, 0, seed)), bits16(hash3(x1, y1, 0, seed)), sx);
  return lerp(top, bottom, sy);
}

/**
 * Fractal sum of `octaves` value-noise layers, the first at (periodU, periodV) and each next one
 * at twice the period and half the weight. In [0, 65535], concentrated around the middle.
 */
export function fbm(
  x: number,
  y: number,
  periodU: number,
  periodV: number,
  seed: number,
  octaves: number,
): number {
  let sum = 0;
  let weights = 0;
  for (let octave = 0; octave < octaves; octave += 1) {
    const weight = 1 << (octaves - 1 - octave);
    const layer = stream(seed, octave + 1);
    const shiftX = hash3(octave, 1, 0, layer) >>> 12;
    const shiftY = hash3(octave, 2, 0, layer) >>> 12;
    sum
      += weight
      * valueNoise(x + shiftX, y + shiftY, periodU << octave, periodV << octave, layer);
    weights += weight;
  }
  return floorDiv(sum, weights);
}

/**
 * Stretch [low, high] of a field to [0, ONE], clamped. Used to turn fbm's middle-heavy output
 * into a usable mask, and stated per use so a reader sees which part of the range a mask keeps.
 */
export function band(value: number, low: number, high: number): number {
  return clamp(floorDiv((value - low) * ONE, high - low), 0, ONE);
}

/** Absolute distance from the middle, doubled: a ridge that peaks where the field crosses 1/2. */
export function ridge(value: number): number {
  return clamp(FULL - 2 * Math.abs(value - 32768), 0, FULL);
}

/** The nearest two feature points of a periodic cellular field, and the cell that owns the first. */
export interface CellSample {
  /** Distance to the nearest feature point, Q16 of one cell. */
  nearest: number;
  /** Distance to the second nearest, Q16 of one cell. */
  second: number;
  /** A hash identifying the nearest point's cell, stable across tiles. */
  id: number;
}

/**
 * Worley noise on a torus. `jitter` (Q16) is how far a feature point may stray from its cell
 * centre: ONE scatters freely, 0 is a regular grid.
 *
 * Distances are measured in cell units on both axes, so a tile whose physical extent is not
 * square must choose periods in the same ratio as its extents to get round cells.
 */
export function cells(
  x: number,
  y: number,
  periodU: number,
  periodV: number,
  seed: number,
  jitter: number,
  out: CellSample,
): CellSample {
  const px = cellOf(x, periodU);
  const py = cellOf(y, periodV);
  let best = Number.POSITIVE_INFINITY;
  let next = Number.POSITIVE_INFINITY;
  let owner = 0;
  for (let dj = -1; dj <= 1; dj += 1) {
    const cy = floorMod(py.cell + dj, periodV);
    for (let di = -1; di <= 1; di += 1) {
      const cx = floorMod(px.cell + di, periodU);
      const h = hash3(cx, cy, 7, seed);
      const g = hash3(cx, cy, 11, seed);
      // A feature point's offset from its cell centre, at most jitter / 2 either way.
      const fx = di * ONE + (ONE >> 1) + floorDiv((bits16(h) - 32768) * jitter, ONE);
      const fy = dj * ONE + (ONE >> 1) + floorDiv((bits16(g) - 32768) * jitter, ONE);
      const dx = fx - px.fraction;
      const dy = fy - py.fraction;
      const d2 = dx * dx + dy * dy;
      if (d2 < best) {
        next = best;
        best = d2;
        owner = hash3(cx, cy, 13, seed);
      } else if (d2 < next) {
        next = d2;
      }
    }
  }
  out.nearest = isqrt(best);
  out.second = isqrt(next);
  out.id = owner;
  return out;
}
