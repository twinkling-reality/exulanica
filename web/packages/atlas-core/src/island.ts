import type { Anchor } from './anchor.js';
import type { IslandPlacement, LocalVec3, MetricVec3 } from './coords.js';
import { metricVec3 } from './coords.js';
import type { EntityId, IslandId } from './ids.js';
import type { ReconstructionRung, RungProperties } from './rung.js';
import { rungProperties } from './rung.js';

/**
 * An island is one capture, with its OWN local coordinate frame, placed into Atlas space by a
 * presentation transform.
 *
 * TERMINOLOGY. docs/architecture-overview.md 1.1 calls these "island frames"; the module
 * boundary table and the product framing both say island. docs/interaction-model.md 1.2 calls
 * the same thing `RegionFrame_i` and says "region" throughout. They are the same object. This
 * package uses `Island` and the divergence is recorded in the handover notes.
 */
export interface Island {
  readonly islandId: IslandId;

  /**
   * Monotonic region-creation order from the persisted layout authority. Unlike a photograph's
   * clock, this value is stable, unique within a layout, and exists only to preserve spatial
   * memory when new regions arrive.
   */
  readonly creationOrdinal: number;

  /**
   * Earliest available capture time, epoch milliseconds, retained for honest display ordering.
   * It is never the layout ordering key. Undated and backfilled captures are exactly why the
   * separate persisted `creationOrdinal` exists.
   */
  readonly createdAt: number;

  /** Where this island sits in the Atlas. Presentation only. Never an answer. */
  readonly placement: IslandPlacement;

  /** Which rung the reconstruction actually earned. Displayed, not hidden. */
  readonly rung: ReconstructionRung;

  /**
   * Whether this island's local frame is metric.
   *
   * interaction-model.md 1.2: a spatial question may be answered only from metric coordinates
   * inside a single island whose scale is metric. This flag is the gate, and `asMetricLocal`
   * below is the only way to obtain a MetricVec3 from an island.
   */
  readonly scaleIsMetric: boolean;

  /**
   * Radius of the island's footprint in LOCAL units.
   *
   * Representation tier distance is measured to the footprint boundary rather than the centre
   * (interaction-model.md 1.4), so the boundary has to be a real number in the graph.
   */
  readonly footprintRadiusLocal: number;

  /**
   * Where the camera stood. For a single-photo island this is the one and only viewpoint, and
   * the 2.5D shell is honestly incomplete everywhere it did not see. First run dollies to it.
   */
  readonly viewpointLocal: LocalVec3;

  /**
   * Where that camera looked, as a unit direction in the local frame, when a reconstruction
   * recovered it. Arrival then reproduces the first photograph's view instead of framing the
   * region from a fixed offset. Absent for regions without recovered cameras.
   */
  readonly viewpointForwardLocal?: LocalVec3;

  readonly anchors: readonly Anchor[];

  /**
   * Entities that count toward semantic proximity in the layout solver, already filtered to
   * confirmed by the caller (see `layout/similarity.ts`). Speculative links
   * are absent by construction rather than filtered later, so a bug cannot let a guess move the
   * world.
   */
  readonly layoutEntities: ReadonlySet<EntityId>;
}

export function islandRung(island: Island): RungProperties {
  return rungProperties(island.rung);
}

/**
 * The only way to get a MetricVec3 out of an island.
 *
 * Returns null for a non-metric island rather than throwing, because "we cannot measure that" is
 * a legitimate and expected answer, not an exceptional one. interaction-model.md 1.2: across
 * islands, and inside non-metric islands, the correct answer is a refusal with a stated reason,
 * never an estimate.
 */
export function asMetricLocal(island: Island, v: LocalVec3): MetricVec3 | null {
  if (!island.scaleIsMetric) return null;
  return metricVec3(v.x, v.y, v.z);
}

/**
 * The dissolve band: the outer fifth of the footprint, where the island's own fog ramps up and
 * the between-space particle field ramps up inversely (interaction-model.md 1.4). Islands have
 * no edges, walls or platform rims.
 */
export const DISSOLVE_BAND_FRACTION = 0.2;

/** 0 at the footprint centre, 1 at the outer boundary, with the band starting at 0.8. */
export function dissolveBandParameter(island: Island, distanceFromCentreLocal: number): number {
  const r = island.footprintRadiusLocal;
  if (r <= 0) return 1;
  const start = r * (1 - DISSOLVE_BAND_FRACTION);
  if (distanceFromCentreLocal <= start) return 0;
  return Math.min(1, (distanceFromCentreLocal - start) / (r - start));
}

export type IslandSpec = Omit<Island, 'creationOrdinal'> & { readonly creationOrdinal?: number };

/** Convenience for adapters and fixtures. Freezes so non-destructiveness is checkable. */
export function makeIsland(spec: IslandSpec): Island {
  const creationOrdinal = spec.creationOrdinal ?? 0;
  if (!Number.isSafeInteger(creationOrdinal) || creationOrdinal < 0) {
    throw new TypeError('island creationOrdinal must be a non-negative safe integer');
  }
  return Object.freeze({
    ...spec,
    creationOrdinal,
    anchors: Object.freeze([...spec.anchors]),
  });
}
