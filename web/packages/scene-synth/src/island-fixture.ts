import type { Anchor, AtlasScene, Island, LayoutInputIsland } from '@exulanica/atlas-core';
import {
  ATLAS_ORIGIN,
  SINGLE_PHOTO_RUNG,
  anchorId,
  entityId,
  evidenceRef,
  islandId,
  layoutEntitiesOf,
  localVec3,
  makeIsland,
  makeScene,
  occurrenceId,
  placement,
  solveLayout,
} from '@exulanica/atlas-core';
import { ANCHORS, CAMERA_HEIGHT, FOOTPRINT_RADIUS_LOCAL } from './scene.js';

/**
 * The point map as a real atlas-core Island, so the bake-off measures the whole frame.
 *
 * A renderer binding that only draws points measures half the budget. The other half is the
 * anchor overlay: manual projection into pre-allocated DOM nodes, the focus solver running every
 * frame, the emphasis instance buffer, and the overlay caps of one focus label, six pinned
 * callouts and four edge chevrons. Both bindings should be measured with all of that live.
 *
 * The anchors here deliberately span the epistemic states the UI must distinguish: a confirmed
 * user-named person, an auto-provisional high-confidence person, a proposed low-confidence
 * object, and a capture-supported place. If a binding renders all four identically, that is a
 * bake-off finding, not a detail.
 */

export interface IslandFixtureOptions {
  readonly key: string;
  readonly createdAt: number;
  /** Entities shared with other islands. Drives the layout solver's semantic proximity. */
  readonly sharedEntities: readonly string[];
}

interface AnchorEpistemics {
  readonly linkState: Anchor['linkState'];
  readonly provenance: Anchor['provenance'];
  readonly confidence: Anchor['confidence'];
  readonly resolved: boolean;
  readonly occurrenceCount: number;
  readonly entity: string | null;
}

const EPISTEMICS: Readonly<Record<string, AnchorEpistemics>> = Object.freeze({
  'person-near': {
    linkState: 'confirmed',
    provenance: 'user',
    confidence: 'high',
    resolved: true,
    occurrenceCount: 14,
    entity: 'entity-person-a',
  },
  'person-far': {
    linkState: 'auto_provisional',
    provenance: 'inference',
    confidence: 'high',
    resolved: false,
    occurrenceCount: 9,
    entity: 'entity-person-b',
  },
  boat: {
    linkState: 'proposed',
    provenance: 'inference',
    confidence: 'low',
    resolved: false,
    occurrenceCount: 2,
    entity: null,
  },
  facade: {
    linkState: 'confirmed',
    provenance: 'capture',
    confidence: 'high',
    resolved: true,
    occurrenceCount: 6,
    entity: 'entity-place-quay',
  },
  'crate-stack': {
    linkState: 'proposed',
    provenance: 'inference',
    confidence: 'medium',
    resolved: false,
    occurrenceCount: 3,
    entity: null,
  },
  planter: {
    linkState: 'auto_provisional',
    provenance: 'inference',
    confidence: 'medium',
    resolved: false,
    occurrenceCount: 1,
    entity: null,
  },
});

export function buildIslandFixture(options: IslandFixtureOptions): Island {
  const id = islandId(options.key);

  const anchors: Anchor[] = ANCHORS.map((spec) => {
    const e = EPISTEMICS[spec.key]!;
    return Object.freeze({
      anchorId: anchorId(`${options.key}/${spec.key}`),
      islandId: id,
      occurrenceId: occurrenceId(`occ/${options.key}/${spec.key}`),
      kind: spec.kind,
      local: localVec3(spec.position[0], spec.position[1], spec.position[2]),
      focusRadiusLocal: spec.focusRadius,
      entityId: e.entity === null ? null : entityId(e.entity),
      linkState: e.linkState,
      provenance: e.provenance,
      confidence: e.confidence,
      occurrenceCount: e.occurrenceCount,
      resolved: e.resolved,
      // Opaque handles. The interaction layer never parses one.
      evidence: Object.freeze([evidenceRef(`span/${options.key}/${spec.key}`)]),
    });
  });

  const layoutEntities = new Set(layoutEntitiesOf(anchors));
  for (const shared of options.sharedEntities) layoutEntities.add(entityId(shared));

  return makeIsland({
    islandId: id,
    creationOrdinal: options.createdAt,
    createdAt: options.createdAt,
    // Placeholder. The real placement comes from the layout solver; see `buildFixtureScene`.
    placement: placement(ATLAS_ORIGIN, 0, 1),
    rung: SINGLE_PHOTO_RUNG,
    // A monocular metric point map is metric by construction (rung 3 in the product spec).
    scaleIsMetric: true,
    footprintRadiusLocal: FOOTPRINT_RADIUS_LOCAL,
    viewpointLocal: localVec3(0, CAMERA_HEIGHT, 0),
    anchors,
    layoutEntities,
  });
}

/**
 * Three islands, laid out by the real solver, so the bake-off runs against the Atlas the product
 * actually ships: several islands resident at once, at different representation tiers, over one
 * never-reloaded scene graph.
 */
export function buildFixtureScene(islandCount = 3): AtlasScene {
  const base = Date.UTC(2026, 7, 27, 12, 0, 0);
  const specs: IslandFixtureOptions[] = [];
  for (let i = 0; i < islandCount; i += 1) {
    specs.push({
      key: `harbour-${i + 1}`,
      createdAt: base + i * 86_400_000,
      // Island 1 and 2 share a person; island 3 shares only a place. The layout should put 1 and
      // 2 closer together than either is to 3, and that is a property worth eyeballing.
      sharedEntities:
        i === 2 ? ['entity-place-quay'] : ['entity-person-a', 'entity-place-quay'],
    });
  }

  const draft = specs.map(buildIslandFixture);
  const inputs: LayoutInputIsland[] = draft.map((island) => ({
    islandId: island.islandId,
    creationOrdinal: island.creationOrdinal,
    footprintRadiusLocal: island.footprintRadiusLocal,
    scale: 1,
    layoutEntities: island.layoutEntities,
    pinned: null,
  }));

  const layout = solveLayout(inputs, 1);
  const placed = draft.map((island) =>
    makeIsland({ ...island, placement: layout.nonmetric_arrangement.get(island.islandId)! }),
  );

  return makeScene(placed, layout.layoutVersion, 1);
}

/**
 * Serialise an island to plain JSON.
 *
 * atlas-core's branded types erase completely at runtime (`Brand<string, 'IslandId'>` IS a
 * string; a branded vector IS `{x, y, z}`), so a renderer binding can `JSON.parse` this file and
 * cast to `Island` without importing scene-synth, which the boundary contract forbids it to do.
 * The one exception is `layoutEntities`, which is a Set and becomes an array here; rehydrate with
 * `new Set(json.layoutEntities)`.
 */
export function serializeIsland(island: Island): unknown {
  return { ...island, layoutEntities: [...island.layoutEntities] };
}

export function serializeScene(scene: AtlasScene): unknown {
  return {
    layoutVersion: scene.layoutVersion,
    stateVersion: scene.stateVersion,
    islands: scene.islands.map(serializeIsland),
  };
}
