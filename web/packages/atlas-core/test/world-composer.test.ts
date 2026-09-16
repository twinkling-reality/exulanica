import { describe, expect, it } from 'vitest';
import {
  DEFAULT_WORLD_MODULES,
  WorldModuleRegistry,
  WorldTopologyValidationError,
  composeAtlasWorld,
  entityId,
  islandId,
  makeIsland,
  makeAtlasLayoutSnapshot,
  makeAtlasNeighborhoodSnapshot,
  neighborhoodId,
  topologyReachability,
  toSpatialAuthorityCandidateDraft,
  validateWorldTopology,
} from '../src/index.js';
import { island, scene } from './fixture.js';

const region = (
  key: string,
  rung: 1 | 2 | 3 | 4,
  ordinal: number,
  position: readonly [number, number, number],
) => {
  const base = island({
    key,
    createdAt: 1_000 + ordinal,
    position,
    footprint: 8,
    entities: ['shared'],
    anchors: [],
  });
  return makeIsland({
    ...base,
    rung,
    creationOrdinal: ordinal,
    layoutEntities: new Set([entityId('shared')]),
  });
};

describe('world topology composition', () => {
  const atlas = scene([
    region('r1', 1, 0, [-12, 0, -4]),
    region('r2', 2, 1, [-4, 0, 5]),
    region('r3', 3, 2, [5, 0, -3]),
    region('r4', 4, 3, [13, 0, 4]),
  ]);

  it('is deterministic and keeps element identity stable across graph-state reloads', () => {
    const first = composeAtlasWorld(atlas, {
      seed: 'archive-seed',
      availableReconstruction: new Set([islandId('r1'), islandId('r3')]),
    });
    const reloaded = composeAtlasWorld(scene(atlas.islands, 99), {
      seed: 'archive-seed',
      availableReconstruction: new Set([islandId('r1'), islandId('r3')]),
    });

    expect(first.topologyDigest).toBe(reloaded.topologyDigest);
    expect(first.snapshotId).toBe(reloaded.snapshotId);
    expect(first.instances.map((value) => value.instanceId)).toEqual(
      reloaded.instances.map((value) => value.instanceId),
    );
    expect(first.inputStateVersion).toBe(1);
    expect(reloaded.inputStateVersion).toBe(99);
    expect(composeAtlasWorld(atlas, {
      seed: 'archive-seed',
      availableReconstruction: new Set([islandId('r1'), islandId('r3')]),
    })).toEqual(first);
  });

  it('falls back to source evidence rather than inventing unavailable reconstruction geometry', () => {
    const snapshot = composeAtlasWorld(atlas, {
      availableReconstruction: new Set([islandId('r1'), islandId('r3')]),
    });
    const contentByRegion = new Map(snapshot.instances
      .filter((value) => value.slotKey === 'content' && value.provenance.owner.kind === 'region')
      .map((value) => [value.provenance.owner.id, value]));

    expect(contentByRegion.get(islandId('r1'))?.moduleKey).toBe('region.reconstruction-volume');
    expect(contentByRegion.get(islandId('r2'))?.moduleKey).toBe('region.source-register');
    expect(contentByRegion.get(islandId('r3'))?.moduleKey).toBe('region.photographic-panels');
    expect(contentByRegion.get(islandId('r4'))?.moduleKey).toBe('region.evidence-cards');
    expect(snapshot.diagnostics.map((value) =>
      value.code === 'region-unlocated' ? value.islandId : value.instanceId)).toEqual([
      contentByRegion.get(islandId('r2'))!.instanceId,
    ]);
    for (const value of snapshot.instances) {
      expect(value.provenance.causes.length).toBeGreaterThan(0);
      expect(value.streamingKey).toContain(value.moduleKey);
    }
  });

  it('keeps every required destination reachable and aligned to its region placement', () => {
    const snapshot = composeAtlasWorld(atlas);
    expect(topologyReachability(snapshot).size).toBe(snapshot.navigation.destinations.length);
    for (const destination of snapshot.navigation.destinations) {
      const source = atlas.islands.find((value) => value.islandId === destination.islandId)!;
      expect(destination.position.x).toBe(source.placement.position.x);
      expect(destination.position.z).toBe(source.placement.position.z);
    }
  });

  it('rejects tampered topology and invalid attachment catalogs', () => {
    const snapshot = composeAtlasWorld(atlas);
    const disconnected = {
      ...snapshot,
      topologyDigest: 'tampered',
      navigation: { ...snapshot.navigation, edges: [] },
    } as typeof snapshot;
    expect(() => validateWorldTopology(disconnected)).toThrow(WorldTopologyValidationError);
    expect(() => validateWorldTopology(disconnected)).toThrow(/unreachable|digest/);

    const modules = DEFAULT_WORLD_MODULES.definitions.map((value) => ({ ...value }));
    const first = modules[0]!;
    modules[0] = { ...first, fallbackKey: first.key };
    expect(() => new WorldModuleRegistry(2, modules)).toThrow(/fall back to itself/);
  });

  it('projects the exact layout and neighborhood inputs into fixed-point authority input', () => {
    const snapshot = composeAtlasWorld(atlas);
    const layout = makeAtlasLayoutSnapshot({
      layoutVersion: atlas.layoutVersion,
      previousLayoutVersion: null,
      reason: 'initial',
      entries: atlas.islands.map((value) => ({
        islandId: value.islandId,
        creationOrdinal: value.creationOrdinal,
        placement: value.placement,
      })),
    });
    const neighborhood = makeAtlasNeighborhoodSnapshot({
      neighborhoodVersion: 1,
      previousNeighborhoodVersion: null,
      layoutVersion: atlas.layoutVersion,
      capacity: 10,
      reason: 'initial',
      entries: [{
        neighborhoodId: neighborhoodId('neighborhood:0'),
        firstCreationOrdinal: 0,
        islandIds: atlas.islands.map((value) => value.islandId),
      }],
    });
    const evidenceBindings = new Map(snapshot.instances
      .filter((value) => value.evidence === 'source-evidence')
      .map((value) => [
        value.instanceId,
        { kind: 'missing' as const, reason: 'no authorised source was recorded' },
      ]));
    const draft = toSpatialAuthorityCandidateDraft(snapshot, {
      graphSha256: 'a'.repeat(64),
      reconstructionSha256: 'b'.repeat(64),
      layout,
      neighborhood,
      evidenceBindings,
    });
    const placement = draft.placement['elements'] as readonly Record<string, unknown>[];
    expect(draft.topology['world_id']).toBe(snapshot.worldId);
    expect(placement.every((value) => Number.isSafeInteger(value['x_mm']))).toBe(true);
    expect(JSON.stringify(draft)).not.toContain(snapshot.topologyDigest);

    expect(() => toSpatialAuthorityCandidateDraft(snapshot, {
      graphSha256: 'a'.repeat(64),
      reconstructionSha256: 'b'.repeat(64),
      layout,
      neighborhood,
      evidenceBindings: new Map(),
    })).toThrow(/explicit span or missing reason/);
  });

  /*
   * The gate is a PLACE, not geometry.
   *
   * A fully reconstructed region can still be sitting wherever the phyllotaxis packing dropped it,
   * so rung cannot be the test. Measured on the Flatiron district, the packing put one memory
   * outside the district entirely, one inside a 47 metre building, and all four below the street.
   */
  it('gives a body only to a memory whose location is real', () => {
    const located = island({ key: 'located', createdAt: 1, footprint: 8, position: [10, 0, 0], anchors: [] });
    const invented = makeIsland({
      ...island({ key: 'invented', createdAt: 2, footprint: 8, position: [40, 0, 0], anchors: [] }),
      placementLocated: false,
    });
    const snapshot = composeAtlasWorld(scene([located, invented]));

    const owners = new Set(snapshot.instances
      .filter((value) => value.provenance.owner.kind === 'region')
      .map((value) => value.provenance.owner.id));
    expect(owners.has(located.islandId)).toBe(true);
    expect(owners.has(invented.islandId)).toBe(false);

    // Refused out loud, not silently dropped: a missing memory and a memory nobody placed look
    // identical in a world that simply stops drawing one.
    expect(snapshot.diagnostics.filter((value) => value.code === 'region-unlocated')
      .map((value) => (value.code === 'region-unlocated' ? value.islandId : null)))
      .toEqual([invented.islandId]);

    // Reconstruction does not buy a place. Rung 3 with an invented position stays bodiless.
    const reconstructed = makeIsland({ ...invented, rung: 3 as const });
    const withGeometry = composeAtlasWorld(scene([reconstructed]), {
      availableReconstruction: new Set([reconstructed.islandId]),
    });
    expect(withGeometry.instances.some((value) =>
      value.provenance.owner.kind === 'region' && value.provenance.owner.id === reconstructed.islandId)).toBe(false);
  });
});
