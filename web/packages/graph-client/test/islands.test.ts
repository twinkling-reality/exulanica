import { describe, expect, it } from 'vitest';

import { adaptSnapshot } from '../src/index.js';
import type { GraphPayload } from '../src/index.js';
import { GROUP, PAYLOAD, WITH_UNGROUPED } from './graph-payload.js';

/**
 * ADR-0005's open question, now answered by measurement rather than left open.
 *
 * The corpus is 80 photographs across five visits, which cluster into five scene groups. One
 * island per capture is 80 islands and `solveLayout` refuses more than five. One island per
 * group is five. These tests pin the default that follows, and pin that it is still only a
 * default: the whole point of keeping the function injectable was that this stays an argument.
 */
describe('what an island is, decided by the client', () => {
  it('puts the captures of one scene group in one island', () => {
    const snapshot = adaptSnapshot(PAYLOAD);
    expect(snapshot.occurrences[0]!.islandId).toBe('g1');
    expect(snapshot.occurrences[1]!.islandId).toBe('g1');
    expect(snapshot.islands).toHaveLength(1);
    expect(snapshot.islands[0]!.captureIds).toEqual(['c1', 'c2']);
  });

  it('leaves a capture the grouping did not place standing on its own', () => {
    const snapshot = adaptSnapshot(WITH_UNGROUPED);
    expect(snapshot.occurrences[2]!.islandId).toBe('c3');
    expect(snapshot.islands.map((i) => i.islandId)).toEqual(['c3', 'g1']);
  });

  it('orders islands by when their photographs were taken, which is the layout ordering key', () => {
    const snapshot = adaptSnapshot(WITH_UNGROUPED);
    expect(snapshot.islands[0]!.firstCapturedAtMs).toBeLessThan(
      snapshot.islands[1]!.firstCapturedAtMs!,
    );
  });

  it('carries the spread only for a group whose members actually had a fix', () => {
    expect(adaptSnapshot(PAYLOAD).islands[0]!.spreadMetres).toBe(14);
    const unpositioned: GraphPayload = {
      ...PAYLOAD,
      scene_groups: [{ ...GROUP, positioned_member_count: 0, radius_m: null }],
    };
    // Null rather than zero. A group clustered on time alone has no measured radius, and zero
    // would read as "every photograph was taken from the same spot".
    expect(adaptSnapshot(unpositioned).islands[0]!.spreadMetres).toBeNull();
  });

  it('still lets the caller decide, which is what the injection point was kept for', () => {
    const snapshot = adaptSnapshot(PAYLOAD, (captureId) => `island:${captureId}` as never);
    expect(snapshot.occurrences.map((o) => o.islandId)).toEqual(['island:c1', 'island:c2']);
  });

  it('gives an injected function islands that match the occurrences it placed', () => {
    // The symptom this is about, not tidiness: an occurrence sitting in an island no record
    // covers is an anchor rendered in a region that does not exist, and a record listing a
    // capture that went somewhere else is a region claiming a photograph it does not hold. A
    // function that splits the one scene group is the case that produces both.
    const snapshot = adaptSnapshot(PAYLOAD, (captureId) => `island:${captureId}` as never);
    const covered = new Set(snapshot.islands.map((island) => island.islandId));
    expect(snapshot.occurrences.filter((o) => !covered.has(o.islandId))).toEqual([]);
    expect(snapshot.islands.map((island) => [island.islandId, island.captureIds])).toEqual([
      ['island:c1', ['c1']],
      ['island:c2', ['c2']],
    ]);
  });

  it('covers an island an entity names even when its occurrence row is absent', () => {
    // Entity island ids drive four surfaces. Leaving one without an IslandRecord makes all four
    // point at a region the snapshot itself says does not exist. The entity has no per-capture
    // clock, so the honest record exists and remains undated.
    const entityOnly: GraphPayload = {
      ...PAYLOAD,
      entities: [
        { ...PAYLOAD.entities[0]!, capture_ids: ['c1', 'c2', 'c3'] },
        PAYLOAD.entities[1]!,
      ],
    };
    const snapshot = adaptSnapshot(entityOnly);
    expect(snapshot.entities[0]!.islandIds).toEqual(['g1', 'c3']);
    expect(snapshot.islands.find((island) => island.islandId === 'c3')).toEqual({
      islandId: 'c3',
      captureIds: ['c3'],
      firstCapturedAtMs: null,
      lastCapturedAtMs: null,
      positionedCaptureCount: 0,
      spreadMetres: null,
      rung: null,
      rungCaptureCount: 0,
      recordedSceneRung: null,
      displayedRung: 4,
      displayReasons: [],
      renderingSubstrate: 'source_photographs',
      reconstructionSceneId: null,
    });
  });

  it('drops a split group\'s measurements rather than copying them into both pieces', () => {
    const islands = adaptSnapshot(PAYLOAD, (captureId) => `island:${captureId}` as never).islands;
    // The group measured a 14 metre spread over two positioned captures and earned rung 2. All
    // three are aggregates over the pair, and nothing measured either half of it.
    expect(islands[0]!.spreadMetres).toBeNull();
    expect(islands[0]!.positionedCaptureCount).toBe(0);
    expect(islands[0]!.rung).toBeNull();
    expect(islands[0]!.rungCaptureCount).toBe(0);
    // The times are the piece's own occurrences rather than the group's window. c2's only
    // occurrence has no usable clock, and the group's 11:00 is not an answer for it.
    expect(islands[1]!.firstCapturedAtMs).toBeNull();
  });

  it('carries them for an island that IS the group, which is every island the default makes', () => {
    // The guard against the rule above eating the ordinary case.
    const island = adaptSnapshot(PAYLOAD).islands[0]!;
    expect(island.captureIds).toEqual(['c1', 'c2']);
    expect(island.spreadMetres).toBe(14);
    expect(island.positionedCaptureCount).toBe(2);
    expect(island.rung).toBe(2);
    expect(island.rungCaptureCount).toBe(2);
    expect(island.firstCapturedAtMs).toBe(Date.parse('2026-03-04T10:00:00+00:00'));
  });
});

/**
 * A rung and the count beside it are one statement, and they stand or fall together.
 *
 * `rung: null` and `rung: 4` are different facts, per the read model's own comment: null means
 * nothing here has been through reconstruction, and 4 means reconstruction ran and found too
 * little to place. The count beside the rung says how much of the region is behind it, so a
 * count reported next to no rung is a measurement behind a claim that was not made.
 */
describe('what an exact reconstruction set does to regions', () => {
  const member = (captureId: string, ordinal: number) => ({
    capture_id: captureId, ordinal, registered: true, exclusion_reason: null, placement: null,
  });
  const scene = (sceneId: string, captureIds: readonly string[], substrate: 'posed_point_maps' | 'gaussian_splats' = 'posed_point_maps') => ({
    scene_id: sceneId, member_digest: '1'.repeat(64), pose_receipt_sha256: '2'.repeat(64),
    placement_receipt_sha256: '3'.repeat(64), gate_digest: '4'.repeat(64), recorded_rung: 3,
    recorded_reasons: [], displayed_rung: 3 as const, display_reasons: [], member_count: captureIds.length,
    registered_member_count: captureIds.length, receipt_state: 'available' as const,
    placement_state: 'available' as const, rendering_substrate: substrate,
    members: captureIds.map((captureId, ordinal) => member(captureId, ordinal)),
  });

  it('joins the ungrouped members of an exact set to the one group its other members share', () => {
    const snapshot = adaptSnapshot({ ...PAYLOAD, reconstruction_scenes: [scene('exact', ['c1', 'c2', 'c9', 'c10'])] });
    expect(snapshot.islands.map((island) => island.islandId)).toEqual(['g1']);
    expect(snapshot.islands[0]!.captureIds).toEqual(['c1', 'c2', 'c9', 'c10']);
    expect(snapshot.islands[0]!.reconstructionSceneId).toBe('exact');
    expect(snapshot.reconstructionScenes![0]!.islandId).toBe('g1');
    // The group's own aggregates describe 2 photographs, not 4, so the region does not claim them.
    expect(snapshot.islands[0]!.spreadMetres).toBeNull();
  });

  it('keeps a set that spans two measured groups split rather than overriding the grouping', () => {
    const second = { ...GROUP, group_id: 'g2', capture_ids: ['c3'] };
    const snapshot = adaptSnapshot({ ...PAYLOAD, scene_groups: [GROUP, second],
      reconstruction_scenes: [scene('spanning', ['c1', 'c3', 'c9'])] });
    expect(snapshot.reconstructionScenes![0]!.islandId).toBeNull();
    expect(snapshot.islands.map((island) => island.islandId).sort()).toEqual(['c9', 'g1', 'g2']);
  });

  it('displays the most complete scene of a region and leaves the overlapping smaller one recorded', () => {
    const snapshot = adaptSnapshot({ ...PAYLOAD, reconstruction_scenes: [
      scene('group-scene', ['c1', 'c2'], 'gaussian_splats'), scene('exact', ['c1', 'c2', 'c9']),
    ] });
    expect(snapshot.islands).toHaveLength(1);
    expect(snapshot.islands[0]!.reconstructionSceneId).toBe('exact');
    expect(snapshot.reconstructionScenes!.map((item) => [item.sceneId, item.islandId]))
      .toEqual([['group-scene', 'g1'], ['exact', 'g1']]);
    // Equal coverage prefers trained geometry, then the stable scene identity order.
    const tied = adaptSnapshot({ ...PAYLOAD, reconstruction_scenes: [
      scene('b-maps', ['c1', 'c2']), scene('a-maps', ['c1', 'c2']), scene('z-trained', ['c1', 'c2'], 'gaussian_splats'),
    ] });
    expect(tied.islands[0]!.reconstructionSceneId).toBe('z-trained');
    expect(tied.islands[0]!.renderingSubstrate).toBe('gaussian_splats');
  });
});

describe('what a rung says, and what the count beside it says', () => {
  const withRung = (rung: number | null, count: number): GraphPayload => ({
    ...PAYLOAD,
    scene_groups: [{ ...GROUP, rung, rung_capture_count: count }],
  });

  it('takes the capture count to zero for a rung this client cannot name', () => {
    // Rung 7 is a server this client does not understand. It reports no rung, and therefore
    // reports nothing behind the rung either: "no rung, from two captures" is two facts where
    // the client has one.
    const island = adaptSnapshot(withRung(7, 2)).islands[0]!;
    expect(island.rung).toBeNull();
    expect(island.rungCaptureCount).toBe(0);
  });

  it('takes the capture count to zero for a group nothing reconstructed', () => {
    // The same rule for the ordinary null, and it is what the branch for a region no group
    // speaks for already answers, so a grouped region and a loose photograph say the same thing
    // the same way. This pairing is the client's rule rather than a payload seen on the wire:
    // today's server takes the rung and the count off one list (`max(earned)` beside
    // `len(earned)` in scene_groups.py), so a null rung reaches it with a count of zero already.
    const island = adaptSnapshot(withRung(null, 5)).islands[0]!;
    expect(island.rung).toBeNull();
    expect(island.rungCaptureCount).toBe(0);
  });

  it('carries rung 4 and its count through, because running and finding nothing is a fact', () => {
    // The guard against the rule above eating the honest rung 4. Reconstruction ran over sixteen
    // captures and placed none of them, and that is a thing the interface has to be able to say.
    const island = adaptSnapshot(withRung(4, 16)).islands[0]!;
    expect(island.rung).toBe(4);
    expect(island.rungCaptureCount).toBe(16);
  });
});
