import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { atlasVec3 } from '../src/coords.js';
import { readHeightfieldGeometry } from '../src/heightfield-geometry.js';
import { HEIGHTFIELD_PERSON_POLICY, readHeightfieldContact } from '../src/heightfield-contact.js';
import { isNavigationGroundPathContinuous, isNavigationPathClear, isNavigationPositionClear, resolveGroundMovement, terrainGroundPose, terrainMillimetres, type NavigationWorld, type TerrainOccupancyProof } from '../src/navigation.js';
const digest = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex');
function world(obstructions: unknown[] = [], slope = 0): NavigationWorld {
  const axis = [-2000, 0, 2000];
  const geometry = readHeightfieldGeometry({ profile: 'exulanica.heightfield-geometry/v1', component_id: 'terrain:navigation', frame: 'region-local-east-up-south-mm', east_mm: axis, south_mm: axis, height_mm: axis.flatMap(() => axis.map(x => 2000 + x * slope)), diagonal: 'a-c-b,b-c-d', provenance: { kind: 'authored', source_sha256: 'a'.repeat(64), generator_id: 'fixture:navigation', generator_version: 1, input_sha256: 'b'.repeat(64) } }, digest);
  const contact = readHeightfieldContact({ profile: 'exulanica.heightfield-contact/v1', component_id: geometry.data.component_id, geometry_sha256: geometry.sha256, policy: HEIGHTFIELD_PERSON_POLICY, obstructions }, geometry, digest);
  return { terrain: { contact, entryMm: [-1000, 0], source: { worldId: 'world:terrain', receiptSha256: 'c'.repeat(64) }, occupancy: { status: 'verified', worldId: 'world:terrain', versionId: '11111111-1111-1111-1111-111111111111', receiptSha256: 'c'.repeat(64), geometrySha256: geometry.sha256, contactSha256: contact.sha256, authoredStateSha256: 'd'.repeat(64) } },
    surface: { sample: () => { throw Error('terrain must never sample a fallback floor'); } }, eyeHeight: 1.62, cameraRadius: .34, centre: atlasVec3(0, 0, 0), fieldRadius: 4, recoveryRadius: 6, maximumSlopeDegrees: 1, maximumStepHeight: .001, surfaceSampleSpacing: 1000, obstacles: [], regions: [], traces: [] };
}
function changedProof(w: NavigationWorld, occupancy: TerrainOccupancyProof): NavigationWorld { return { ...w, terrain: { ...w.terrain!, occupancy } }; }

describe('exact terrain navigation dispatch', () => {
  it('uses exact binary64 half-down millimetre quantization, including signed ties', () => {
    expect(terrainMillimetres(.0625)).toBe(62);
    expect(terrainMillimetres(-.0625)).toBe(-62);
    expect(terrainMillimetres(.06250000000000001)).toBe(63);
    expect(terrainMillimetres(-.06250000000000001)).toBe(-63);
    expect(terrainMillimetres(.06249999999999999)).toBe(62);
    expect(terrainMillimetres(Number.MIN_VALUE)).toBe(0);
    for (const value of [NaN, Infinity, 1000]) expect(() => terrainMillimetres(value)).toThrow();
  });
  it('ascends and returns using whole sweeps and carries exact source/version/pose pins', () => {
    const w = world([], .25), entry = terrainGroundPose(w, [-1000, 0])!;
    const up = resolveGroundMovement(w, { current: entry.position, desired: atlasVec3(.5002, 999, 0), lastSafe: entry.position, terrainState: entry.state, lastSafeTerrain: entry.state });
    expect(up.position).toEqual(atlasVec3(.5, 2.125 + w.eyeHeight, 0));
    expect(up.terrainState?.positionMm).toEqual([500, 0]);
    expect(up.terrainState).toMatchObject({ worldId: 'world:terrain', versionId: '11111111-1111-1111-1111-111111111111', authoredStateSha256: 'd'.repeat(64) });
    expect(up.terrainResult?.status).toBe('clear');
    const down = resolveGroundMovement(w, { current: up.position, desired: entry.position, lastSafe: up.position, terrainState: up.terrainState!, lastSafeTerrain: up.terrainState! });
    expect(down.position).toEqual(entry.position);
    expect(down.terrainState).toEqual(entry.state);
  });
  it('refuses a middle obstruction between clear endpoints without relocating accepted state', () => {
    const w = world([{ kind: 'aabb', obstruction_id: 'solid:midway', bounds_mm: [-10, 2500, -10, 10, 2600, 10] }]);
    const from = terrainGroundPose(w, [-700, -700])!, to = terrainGroundPose(w, [700, 700])!;
    const before = JSON.stringify(from);
    const result = resolveGroundMovement(w, { current: from.position, desired: to.position, lastSafe: from.position, terrainState: from.state, lastSafeTerrain: from.state });
    expect(result.terrainFailure).toBe('obstructed');
    expect(result.position).toBe(from.position);
    expect(result.terrainState).toBe(from.state);
    expect(result.lastSafeTerrain).toBe(from.state);
    expect(JSON.stringify(from)).toBe(before);
    expect(isNavigationPathClear(w, from.position, to.position)).toBe(false);
    expect(isNavigationGroundPathContinuous(w, from.position, to.position)).toBe(false);
  });
  it('keeps the previous accepted pose on domain, segment and invalid-pose refusal', () => {
    const w = world(), entry = terrainGroundPose(w, [-1000, 0])!;
    for (const [desired, reason] of [[atlasVec3(1.7, 0, 0), 'segment_limit'], [atlasVec3(-1.7, 0, 0), 'outside_domain'], [atlasVec3(NaN, 0, 0), 'invalid_pose']] as const) {
      const result = resolveGroundMovement(w, { current: entry.position, desired, lastSafe: entry.position, terrainState: entry.state });
      expect(result.terrainFailure).toBe(reason); expect(result.position).toBe(entry.position);
    }
    expect(resolveGroundMovement(w, { current: entry.position, desired: entry.position, lastSafe: entry.position }).terrainFailure).toBe('invalid_pose');
  });
  it('never relabels stale source, contact, version or authored state as a new accepted pose', () => {
    const w = world(), entry = terrainGroundPose(w, [-1000, 0])!;
    for (const change of [{ geometrySha256: 'e'.repeat(64) }, { contactSha256: 'e'.repeat(64) }, { authoredStateSha256: 'e'.repeat(64) }, { receiptSha256: 'e'.repeat(64) }, { versionId: '22222222-2222-2222-2222-222222222222' }, { positionMm: [0, 0] as const }]) {
      const stale = { ...entry.state, ...change };
      expect(terrainGroundPose(w, [-1000, 0], stale)).toBeNull();
      const result = resolveGroundMovement(w, { current: entry.position, desired: atlasVec3(0, 0, 0), lastSafe: entry.position, terrainState: stale });
      expect(result.terrainFailure).toBe('stale_source'); expect(result.terrainState).toBe(stale); expect(result.position).toBe(entry.position);
    }
  });
  it('keeps source-only or mismatched occupancy unavailable and never borrows approximate blockers', () => {
    const w = world(), entry = terrainGroundPose(w, [-1000, 0])!;
    const verified = w.terrain!.occupancy; if (verified.status !== 'verified') throw Error('fixture proof');
    for (const unknown of [changedProof(w, { status: 'unavailable' }), changedProof(w, { ...verified, worldId: 'another-world' }), changedProof(w, { ...verified, contactSha256: 'f'.repeat(64) }), { ...w, obstacles: [{ id: 'unbound', centre: atlasVec3(0, 0, 0), radius: 1 }] }]) {
      expect(terrainGroundPose(unknown, [-1000, 0])).toBeNull();
      const result = resolveGroundMovement(unknown, { current: entry.position, desired: atlasVec3(0, 0, 0), lastSafe: entry.position, terrainState: entry.state });
      expect(result.terrainFailure).toBe('unbound_occupancy'); expect(result.position).toBe(entry.position);
      expect(isNavigationPositionClear(unknown, entry.position)).toBe(false);
    }
    expect(isNavigationPositionClear(w, entry.position)).toBe(true);
    expect(isNavigationPathClear(w, entry.position, terrainGroundPose(w, [0, 0])!.position)).toBe(true);
  });
});
