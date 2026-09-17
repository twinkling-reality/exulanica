import type { IslandPlacement } from '../coords.js';
import { atlasVec3, placement as makePlacement } from '../coords.js';
import type { EntityId, IslandId } from '../ids.js';
import { atlasGroundDistance } from '../presentation-metrics.js';
import { phyllotaxisSeed } from './phyllotaxis.js';
import { semanticSimilarity } from './similarity.js';

/**
 * The layout solver.
 *
 * interaction-model.md 1.4, and every sentence of it is load-bearing:
 *
 *   - "Layout is a stored artifact, never recomputed at runtime." This function runs on ingest
 *     and its output is persisted with a layout version. It is not called from a frame loop and
 *     nothing in atlas-core calls it.
 *   - "A deterministic seed (phyllotaxis) plus a pinned force relaxation, ordered by creation
 *     time." No PRNG appears anywhere in this file, and no `Date.now()`. Same input, byte-
 *     identical output, on any machine.
 *   - "Pre-existing regions are pinned during relaxation and then hard clamped inside a small
 *     drift radius, so adding a fourth capture cannot scramble the user's spatial memory of the
 *     first three."
 *   - "Speculative links must never move the world." Enforced upstream in `layoutEntitiesOf`.
 *
 * FRAME. The output is a `nonmetric_arrangement`. The seed spacing, the separations and the drift
 * radius are arrangement parameters, not distances anybody measured, so nothing read from a
 * placement here is a length in metres. A consumer reads the placements through the frame's name,
 * and a surface whose own frame carries real units must not take an arranged position as a place
 * in it.
 *
 * SCOPE. This solves 1 to 5 islands and refuses more. The brief says three to five; the product
 * says most users upload one or two photographs, and one photograph is one island, so the low
 * end has to work. Refusing at six is deliberate: "Do not solve infinite worlds." A force layout
 * whose behaviour was never examined above five islands should fail loudly rather than produce
 * a plausible-looking arrangement nobody has checked.
 */

export const MAX_ISLANDS = 5;

/** The frame every solver placement is in. An arrangement, not a measurement. */
export const LAYOUT_FRAME = 'nonmetric_arrangement' as const;
export type LayoutFrame = typeof LAYOUT_FRAME;

/** "Regions glide over about 1.2 s" when the persisted layout changes. Never a cut. */
export const LAYOUT_GLIDE_MS = 1200;

export interface LayoutInputIsland {
  readonly islandId: IslandId;
  /** Monotonic persisted region-creation order. Never derived from a capture clock. */
  readonly creationOrdinal: number;
  readonly footprintRadiusLocal: number;
  readonly scale: number;
  /** Confirmed entities only. Built by `layoutEntitiesOf`. */
  readonly layoutEntities: ReadonlySet<EntityId>;
  /**
   * The placement this island already has in the persisted layout, if any. Pinned islands are
   * sprung toward this position during relaxation and hard clamped to `driftRadius` of it after.
   */
  readonly pinned: IslandPlacement | null;
}

export type LayoutStrategy =
  /** The default: phyllotaxis seed, then pinned relaxation. */
  | 'phyllotaxis-relaxed'
  /** Seed only, no relaxation. */
  | 'seed-only'
  /** Every island must supply `pinned`; the solver only computes yaw. For experiment I-4. */
  | 'hand-placed';

export interface LayoutConfig {
  readonly strategy: LayoutStrategy;
  /** Arrangement units, not metres. Sets the scale of the phyllotaxis seed. */
  readonly seedSpacing: number;
  /** Target arrangement separation at similarity 1 (identical entity sets). Unitless. */
  readonly minSeparation: number;
  /** Target arrangement separation at similarity 0 (nothing in common). Unitless. */
  readonly maxSeparation: number;
  /** Extra clearance between footprint boundaries, as a fraction of the summed radii. */
  readonly footprintGap: number;
  /** Fixed iteration count. Fixed, not convergence-based, because convergence is not portable. */
  readonly iterations: number;
  /** Per-iteration fraction of the separation error that is corrected. */
  readonly stepSize: number;
  /** Spring pulling a pinned island back toward its stored position, per iteration. */
  readonly pinStrength: number;
  /**
   * Hard clamp, in arrangement units. A pinned island may never end further than this from where
   * it was in the arrangement. It bounds a rearrangement, not a distance on the ground.
   */
  readonly driftRadius: number;
}

export const DEFAULT_LAYOUT_CONFIG: LayoutConfig = Object.freeze({
  strategy: 'phyllotaxis-relaxed',
  seedSpacing: 260,
  minSeparation: 210,
  maxSeparation: 560,
  footprintGap: 0.45,
  iterations: 240,
  stepSize: 0.08,
  pinStrength: 0.25,
  driftRadius: 40,
});

export interface LayoutMove {
  readonly islandId: IslandId;
  /** Arrangement units moved from the pinned position. Presentation only; drives the glide and the copy. */
  readonly distance: number;
}

export interface LayoutResult {
  readonly layoutVersion: number;
  readonly strategy: LayoutStrategy;
  /** What the placements are. Never a metric frame. */
  readonly frame: LayoutFrame;
  /** The placements, read through the frame's own name so no caller can take them for places. */
  readonly nonmetric_arrangement: ReadonlyMap<IslandId, IslandPlacement>;
  /**
   * Islands that moved from their pinned position, largest first.
   *
   * "When layout does change it is never a cut: regions glide over about 1.2 s and the Companion
   * states the reason in one line. Under reduced motion the move is instant and the line becomes
   * mandatory." This list is what that line is generated from, so it must be non-empty whenever
   * anything moved.
   */
  readonly moved: readonly LayoutMove[];
}

export class LayoutScopeError extends RangeError {
  constructor(message: string) {
    super(message);
    this.name = 'LayoutScopeError';
  }
}

/** Total order: persisted creation ordinal, then island id as a defensive deterministic tie. */
function ordered(islands: readonly LayoutInputIsland[]): LayoutInputIsland[] {
  return [...islands].sort(
    (a, b) =>
      a.creationOrdinal - b.creationOrdinal ||
      (a.islandId < b.islandId ? -1 : a.islandId > b.islandId ? 1 : 0),
  );
}

function targetSeparation(
  cfg: LayoutConfig,
  a: LayoutInputIsland,
  b: LayoutInputIsland,
): number {
  const s = semanticSimilarity(a.layoutEntities, b.layoutEntities);
  const semantic = cfg.maxSeparation - (cfg.maxSeparation - cfg.minSeparation) * s;
  // Footprints must not intersect no matter how similar two islands are. Semantic proximity is
  // expressed by being closer, never by overlapping.
  const radii = a.footprintRadiusLocal * a.scale + b.footprintRadiusLocal * b.scale;
  return Math.max(semantic, radii * (1 + cfg.footprintGap));
}

export function solveLayout(
  islands: readonly LayoutInputIsland[],
  layoutVersion: number,
  config: Partial<LayoutConfig> = {},
): LayoutResult {
  const cfg: LayoutConfig = { ...DEFAULT_LAYOUT_CONFIG, ...config };

  if (islands.length === 0) {
    throw new LayoutScopeError('the layout solver needs at least one island');
  }
  if (islands.length > MAX_ISLANDS) {
    throw new LayoutScopeError(
      `the layout solver is specified for 1 to ${MAX_ISLANDS} islands and was given ${islands.length}; ` +
        'this is a deliberate refusal, not a missing feature (interaction-model.md 1.4)',
    );
  }

  const list = ordered(islands);
  const n = list.length;

  if (cfg.strategy === 'hand-placed') {
    const missing = list.filter((i) => i.pinned === null).map((i) => i.islandId);
    if (missing.length > 0) {
      throw new LayoutScopeError(
        `the hand-placed strategy requires a pinned placement for every island; missing: ${missing.join(', ')}`,
      );
    }
  }

  const seed = phyllotaxisSeed(n, cfg.seedSpacing);
  const x = new Float64Array(n);
  const z = new Float64Array(n);
  for (let i = 0; i < n; i += 1) {
    const p = list[i]!.pinned;
    if (p !== null) {
      x[i] = p.position.x;
      z[i] = p.position.z;
    } else {
      x[i] = seed[i]!.x;
      z[i] = seed[i]!.z;
    }
  }

  if (cfg.strategy === 'phyllotaxis-relaxed') {
    const fx = new Float64Array(n);
    const fz = new Float64Array(n);

    for (let iter = 0; iter < cfg.iterations; iter += 1) {
      fx.fill(0);
      fz.fill(0);

      // Jacobi sweep: all forces are accumulated from the same snapshot and applied after, so
      // the result does not depend on the order pairs are visited. Gauss-Seidel would be faster
      // and would make the output depend on iteration order, which is exactly what determinism
      // cannot tolerate.
      for (let i = 0; i < n; i += 1) {
        for (let j = i + 1; j < n; j += 1) {
          let dx = x[j]! - x[i]!;
          let dz = z[j]! - z[i]!;
          let d = Math.hypot(dx, dz);
          if (d < 1e-9) {
            // Degenerate coincidence. Separate along a direction derived from the index pair, so
            // it is reproducible rather than random.
            const angle = ((i * 31 + j * 17) % 360) * (Math.PI / 180);
            dx = Math.cos(angle);
            dz = Math.sin(angle);
            d = 1;
          }
          const target = targetSeparation(cfg, list[i]!, list[j]!);
          const correction = ((d - target) / d) * cfg.stepSize * 0.5;
          fx[i]! += dx * correction;
          fz[i]! += dz * correction;
          fx[j]! -= dx * correction;
          fz[j]! -= dz * correction;
        }
      }

      for (let i = 0; i < n; i += 1) {
        const pinned = list[i]!.pinned;
        if (pinned !== null) {
          fx[i]! += (pinned.position.x - x[i]!) * cfg.pinStrength;
          fz[i]! += (pinned.position.z - z[i]!) * cfg.pinStrength;
        }
        x[i]! += fx[i]!;
        z[i]! += fz[i]!;
      }

      // Hard clamp, every iteration, so a pinned island can never wander far even transiently.
      for (let i = 0; i < n; i += 1) {
        const pinned = list[i]!.pinned;
        if (pinned === null) continue;
        const dx = x[i]! - pinned.position.x;
        const dz = z[i]! - pinned.position.z;
        const d = Math.hypot(dx, dz);
        if (d > cfg.driftRadius) {
          const k = cfg.driftRadius / d;
          x[i] = pinned.position.x + dx * k;
          z[i] = pinned.position.z + dz * k;
        }
      }
    }
  }

  // Yaw for a NEW island: turn its CAPTURE_FORWARD_LOCAL axis toward the atlas centroid.
  //
  // The documents do not specify island yaw. This is a decision, and it is not cosmetic: a
  // single-photo island is a 2.5D shell with observed surfaces on one side and nothing at all on
  // the other, so an island facing the wrong way is a hole the user walks into. Orienting a new
  // capture direction inward puts the observed content between the user and the island origin,
  // which means anyone approaching from the middle of the Atlas sees the photographed surfaces
  // from the front. Islands are never pitched or rolled, so yaw is the only freedom there is.
  let cx = 0;
  let cz = 0;
  for (let i = 0; i < n; i += 1) {
    cx += x[i]!;
    cz += z[i]!;
  }
  cx /= n;
  cz /= n;

  const placements = new Map<IslandId, IslandPlacement>();
  const moved: LayoutMove[] = [];

  for (let i = 0; i < n; i += 1) {
    const island = list[i]!;
    const dx = cx - x[i]!;
    const dz = cz - z[i]!;
    // Solve localDirectionToAtlas(placement, CAPTURE_FORWARD_LOCAL) == normalize(centroid - p).
    // With CAPTURE_FORWARD_LOCAL = (0, 0, -1) that direction is (-sin yaw, 0, -cos yaw).
    // A persisted placement is a FULL transform. Recomputing yaw while calling the island pinned
    // silently turns one-sided panels and is spatial-memory breakage even when X/Z do not move.
    const yaw = island.pinned?.yaw ?? (dx === 0 && dz === 0 ? 0 : Math.atan2(-dx, -dz));
    const position = atlasVec3(x[i]!, island.pinned?.position.y ?? 0, z[i]!);
    const p = makePlacement(position, yaw, island.pinned?.scale ?? island.scale);
    placements.set(island.islandId, p);

    if (island.pinned !== null) {
      const distance = atlasGroundDistance(island.pinned.position, position);
      if (distance > 1e-6) moved.push({ islandId: island.islandId, distance });
    }
  }

  moved.sort((a, b) => b.distance - a.distance);

  return Object.freeze({
    layoutVersion,
    strategy: cfg.strategy,
    frame: LAYOUT_FRAME,
    nonmetric_arrangement: placements,
    moved: Object.freeze(moved),
  });
}
