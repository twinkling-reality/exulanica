import type {
  Anchor,
  AtlasScene,
  ConfidenceBand,
  EntityId,
  Island,
  LinkState,
  ProvenanceClass,
} from '../src/index.js';
import {
  anchorId,
  entityId,
  evidenceRef,
  islandId,
  localVec3,
  makeIsland,
  makeScene,
  occurrenceId,
  placement,
  atlasVec3,
} from '../src/index.js';

export interface AnchorSpec {
  readonly key: string;
  readonly local: readonly [number, number, number];
  readonly radius?: number;
  readonly entity?: string | null;
  readonly linkState?: LinkState;
  readonly provenance?: ProvenanceClass;
  readonly confidence?: ConfidenceBand;
  readonly resolved?: boolean;
  readonly occurrences?: number;
}

export function anchor(island: string, spec: AnchorSpec): Anchor {
  return Object.freeze({
    anchorId: anchorId(`${island}/${spec.key}`),
    islandId: islandId(island),
    occurrenceId: occurrenceId(`occ/${island}/${spec.key}`),
    kind: 'person' as const,
    local: localVec3(spec.local[0], spec.local[1], spec.local[2]),
    focusRadiusLocal: spec.radius ?? 0.4,
    entityId: spec.entity === undefined || spec.entity === null ? null : entityId(spec.entity),
    linkState: spec.linkState ?? 'confirmed',
    provenance: spec.provenance ?? 'inference',
    confidence: spec.confidence ?? 'high',
    occurrenceCount: spec.occurrences ?? 1,
    resolved: spec.resolved ?? true,
    evidence: Object.freeze([evidenceRef(`span/${island}/${spec.key}`)]),
  });
}

export interface IslandSpec {
  readonly key: string;
  readonly createdAt: number;
  readonly anchors: readonly AnchorSpec[];
  readonly entities?: readonly string[];
  readonly position?: readonly [number, number, number];
  readonly yaw?: number;
  readonly scale?: number;
  readonly metric?: boolean;
  readonly footprint?: number;
}

/**
 * A fixture region has a real location.
 *
 * Production regions mostly do not, and the composer now refuses to give those a body. Tests about
 * recipes, layout and navigation are not about that refusal, so the fixture states the location is
 * known and `world-composer.test.ts` covers the refusal directly.
 */
export function island(spec: IslandSpec): Island {
  const p = spec.position ?? [0, 0, 0];
  const entities = new Set<EntityId>((spec.entities ?? []).map(entityId));
  return makeIsland({
    islandId: islandId(spec.key),
    createdAt: spec.createdAt,
    placement: placement(atlasVec3(p[0], p[1], p[2]), spec.yaw ?? 0, spec.scale ?? 1),
    placementLocated: true,
    rung: 3,
    scaleIsMetric: spec.metric ?? true,
    footprintRadiusLocal: spec.footprint ?? 30,
    viewpointLocal: localVec3(0, 1.55, 0),
    anchors: spec.anchors.map((a) => anchor(spec.key, a)),
    layoutEntities: entities,
  });
}

export function scene(islands: readonly Island[], stateVersion = 1): AtlasScene {
  return makeScene(islands, 1, stateVersion);
}

/** Recursively freeze, so any attempt to mutate throws in strict mode rather than passing quietly. */
export function deepFreeze<T>(value: T): T {
  if (value === null || typeof value !== 'object') return value;
  if (Object.isFrozen(value)) return value;
  Object.freeze(value);
  for (const key of Object.getOwnPropertyNames(value)) {
    deepFreeze((value as Record<string, unknown>)[key]);
  }
  return value;
}

/** Structural snapshot that survives Maps and Sets, for before/after comparison. */
export function snapshot(value: unknown): string {
  return JSON.stringify(value, (_k, v: unknown) => {
    if (v instanceof Map) return { __map: [...v.entries()] };
    if (v instanceof Set) return { __set: [...v] };
    return v;
  });
}
