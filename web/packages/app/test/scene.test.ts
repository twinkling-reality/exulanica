import { describe, expect, it } from 'vitest';
import type { GraphSnapshot, OccurrenceRecord } from '@exulanica/graph-client';
import {
  asMetricLocal,
  atlasLandscapeHeight,
  atlasVec3,
  islandId,
  localVec3,
  makeAtlasLayoutSnapshot,
  placement,
  rendersAsPresenceMarker,
} from '@exulanica/atlas-core';

import { buildScene, buildSceneFromLayout } from '../src/scene.js';

/**
 * The adapter from graph data to the scene graph, which is where three product rules stop being
 * sentences in a document and become properties of an object.
 *
 * The one that matters most is the third: a person anchor must render as a presence marker and
 * never as world geometry. `rendersAsPresenceMarker` is a predicate in atlas-core precisely so it
 * cannot be set false by mistake, but it reads the anchor's KIND, and the kind is set here. An
 * adapter that mapped every occurrence to `object` would produce anchors for which the predicate
 * correctly returns false, and a person would be baked into a reconstruction with every guard in
 * the system reporting green.
 */

function occurrence(
  id: string,
  islandId: string,
  kind: OccurrenceRecord['kind'] = 'object',
  entityId: string | null = null,
): OccurrenceRecord {
  return {
    occurrenceId: id,
    anchorId: id,
    islandId,
    kind,
    entityId,
    linkState: entityId === null ? 'proposed' : 'confirmed',
    confidence: 'low',
    evidence: [`span-${id}`],
    capturedAtMs: 1_700_000_000_000,
  };
}

function island(islandId: string, firstMs: number | null = 1_700_000_000_000) {
  return {
    islandId,
    captureIds: [`capture-${islandId}`],
    firstCapturedAtMs: firstMs,
    lastCapturedAtMs: firstMs,
    positionedCaptureCount: 1,
    spreadMetres: 12,
    rung: null as 1 | 2 | 3 | 4 | null,
    rungCaptureCount: 0,
  };
}

function snapshotOf(
  islands: readonly ReturnType<typeof island>[],
  occurrences: readonly OccurrenceRecord[],
): GraphSnapshot {
  return {
    stateVersion: 5,
    entities: [],
    occurrences,
    islands,
    matchProposals: [],
    neverSame: [],
    deletedEntityIds: [],
  };
}

describe('graph data becomes a scene', () => {
  it('preserves a persisted full transform across a scene rebuild', () => {
    const input = snapshotOf([island('a')], [occurrence('o1', 'a')]);
    const pinned = placement(atlasVec3(42, 0.5, -18), 0.75, 1.4);
    const built = buildScene(input, 8, new Map([[islandId('a'), pinned]]));

    expect(built.scene.layoutVersion).toBe(8);
    expect(built.scene.islands[0]!.placement).toEqual(pinned);
  });

  it('allocates incomplete ordinal input above persisted history without collisions', () => {
    const input = snapshotOf(
      [island('a'), island('b')],
      [occurrence('o1', 'a'), occurrence('o2', 'b')],
    );
    const built = buildScene(input, 2, new Map(), new Map([[islandId('a'), 17]]));
    expect(built.scene.islands.map((value) => value.creationOrdinal)).toEqual([17, 18]);
  });

  it('consumes the durable layout artifact as full transform and stable creation order', () => {
    const pinned = placement(atlasVec3(42, 0.5, -18), 0.75, 1.4);
    const stored = makeAtlasLayoutSnapshot({
      layoutVersion: 8,
      previousLayoutVersion: 7,
      reason: 'new-regions',
      entries: [{ islandId: islandId('a'), creationOrdinal: 17, placement: pinned }],
    });
    const built = buildSceneFromLayout(
      snapshotOf([island('a')], [occurrence('o1', 'a')]),
      stored,
    );
    expect(built.scene.layoutVersion).toBe(8);
    expect(built.scene.islands[0]).toMatchObject({ creationOrdinal: 17, placement: pinned });
    expect(built.layoutCoverage).toEqual({
      present: [islandId('a')],
      missing: [],
      stale: [],
    });
  });

  it('marks a new region as a draft layout addition instead of pretending it was persisted', () => {
    const stored = makeAtlasLayoutSnapshot({
      layoutVersion: 3,
      previousLayoutVersion: 2,
      reason: 'initial',
      entries: [{
        islandId: islandId('a'),
        creationOrdinal: 9,
        placement: placement(atlasVec3(4, 0, 2), 0.1, 1),
      }],
    });
    const built = buildSceneFromLayout(
      snapshotOf(
        [island('a'), island('new')],
        [occurrence('o1', 'a'), occurrence('o2', 'new')],
      ),
      stored,
    );
    expect(built.scene.layoutVersion).toBe(4);
    expect(built.scene.islands.find((value) => value.islandId === islandId('new'))?.creationOrdinal)
      .toBe(10);
    expect(built.layoutCoverage?.missing).toEqual([islandId('new')]);
  });

  it('puts every anchor of one island in that island', () => {
    const built = buildScene(
      snapshotOf(
        [island('a'), island('b', 1_700_000_100_000)],
        [occurrence('o1', 'a'), occurrence('o2', 'a'), occurrence('o3', 'b')],
      ),
    );
    const byId = new Map(built.scene.islands.map((i) => [i.islandId as string, i]));
    expect(byId.get('a')!.anchors).toHaveLength(2);
    expect(byId.get('b')!.anchors).toHaveLength(1);
  });

  it('counts a bare detection as the occurrence it visibly is', () => {
    const built = buildScene(snapshotOf([island('a')], [occurrence('o1', 'a')]));
    expect(built.scene.islands[0]!.anchors[0]!.occurrenceCount).toBe(1);
  });

  it('stands a reconstructed region on the landscape so its ground, cameras and arrival agree', () => {
    const reconstructions = new Map([[islandId('a'), {
      rung: 3 as const, viewpointLocal: localVec3(0, 1.6, 0), footprintRadiusLocal: 4,
    }]]);
    const built = buildScene(snapshotOf([island('a')], [occurrence('o1', 'a')]), 1, new Map(), new Map(), reconstructions);
    const placed = built.scene.islands[0]!.placement;
    expect(placed.position.y).toBeCloseTo(atlasLandscapeHeight(placed.position.x, placed.position.z), 9);
    const plain = buildScene(snapshotOf([island('a')], [occurrence('o1', 'a')])).scene.islands[0]!.placement;
    expect(plain.position.y).toBe(0);
    expect([placed.position.x, placed.position.z, placed.yaw, placed.scale])
      .toEqual([plain.position.x, plain.position.z, plain.yaw, plain.scale]);
  });

  it('reports rung 4, because nothing reconstructed anything', () => {
    const built = buildScene(snapshotOf([island('a')], [occurrence('o1', 'a')]));
    expect(built.scene.islands[0]!.rung).toBe(4);
  });

  it('refuses to measure inside an island, because no island is metric', () => {
    // This is the gate on a spatial answer. A layout position is not a measurement, and the null
    // is what makes a spatial question refuse with a reason instead of estimating one.
    const built = buildScene(snapshotOf([island('a')], [occurrence('o1', 'a')]));
    expect(asMetricLocal(built.scene.islands[0]!, localVec3(1, 0, 1))).toBeNull();
  });

  it('renders a person as a presence marker and never as geometry', () => {
    const built = buildScene(
      snapshotOf([island('a')], [occurrence('p1', 'a', 'person'), occurrence('o1', 'a', 'object')]),
    );
    const anchors = built.scene.islands[0]!.anchors;
    const person = anchors.find((a) => a.anchorId === ('p1' as never))!;
    const object = anchors.find((a) => a.anchorId === ('o1' as never))!;
    expect(rendersAsPresenceMarker(person)).toBe(true);
    expect(rendersAsPresenceMarker(object)).toBe(false);
  });

  it('drops an occurrence class the scene graph has no shape for, and says how many', () => {
    // `voice` and `conversation` are real occurrence classes with no anchor kind. Coercing one to
    // the nearest available kind would draw a conversation as an object sitting in a room.
    const built = buildScene(
      snapshotOf(
        [island('a')],
        [occurrence('v1', 'a', 'voice'), occurrence('c1', 'a', 'conversation'), occurrence('o1', 'a')],
      ),
    );
    expect(built.scene.islands[0]!.anchors).toHaveLength(1);
    expect(built.undrawable.get('voice')).toBe(1);
    expect(built.undrawable.get('conversation')).toBe(1);
  });

  it("omits islands past the solver's limit rather than throwing or arranging them anyway", () => {
    // `solveLayout` refuses more than five and says why. A caller that let the exception through
    // would render nothing at all for a library of six regions; one that raised the limit would be
    // arranging a world nobody has examined.
    const islands = Array.from({ length: 8 }, (_, i) => island(`i${i}`, 1_700_000_000_000 + i));
    const built = buildScene(snapshotOf(islands, islands.map((i) => occurrence(`o${i.islandId}`, i.islandId))));
    expect(built.scene.islands).toHaveLength(5);
    expect(built.omitted).toHaveLength(3);
  });

  it('arranges anchors deterministically, so one graph is one world on every machine', () => {
    const input = snapshotOf([island('a')], [occurrence('o1', 'a'), occurrence('o2', 'a')]);
    const first = buildScene(input).scene.islands[0]!.anchors.map((a) => a.local);
    const second = buildScene(input).scene.islands[0]!.anchors.map((a) => a.local);
    expect(second).toEqual(first);
  });

  it('gives every island a footprint that contains its anchors', () => {
    const built = buildScene(
      snapshotOf([island('a')], Array.from({ length: 12 }, (_, i) => occurrence(`o${i}`, 'a'))),
    );
    const region = built.scene.islands[0]!;
    for (const anchor of region.anchors) {
      expect(Math.hypot(anchor.local.x, anchor.local.z)).toBeLessThan(region.footprintRadiusLocal);
    }
  });
});
