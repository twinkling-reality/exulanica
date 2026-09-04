import { describe, expect, it } from 'vitest';

import { adaptSnapshot } from '../src/index.js';
import type { GraphPayload } from '../src/index.js';
import { GROUP, PAYLOAD } from './graph-payload.js';

describe('the two zeroes that stopped being zeroes', () => {
  /** The payload above, with one pending proposal about Julie. */
  const withProposal: GraphPayload = {
    ...PAYLOAD,
    entities: PAYLOAD.entities.map((row, index) =>
      index === 0 ? { ...row, open_question_count: 1 } : row,
    ),
    proposals: [
      {
        proposal_id: 'p1',
        occurrence_id: 'o2',
        entity_id: 'e1',
        rank: 0,
        outcome: 'surfaced',
        basis: {
          modalities: ['context_cooccurrence', 'context_place'],
          extractor_versions: { context_signals: '1' },
        },
        new_modality: 'context_place',
        suppressed_by_rejection: false,
        support_span_ids: ['s2'],
      },
    ],
  };

  it('marks an entity with a pending question as needs_review, outranking its name', () => {
    // A named person with an open question is precisely what the review queue is for. Losing the
    // `user_asserted` badge while the question stands costs nothing: the provenance triad still
    // shows that a person has spoken about this entity.
    const snapshot = adaptSnapshot(withProposal);
    const julie = snapshot.entities.find((entity) => entity.entityId === 'e1');
    expect(julie?.displayName).toBe('Julie');
    expect(julie?.status).toBe('needs_review');
    expect(julie?.openQuestionCount).toBe(1);
  });

  it('keeps merged_away ahead of needs_review', () => {
    // An alias redirect is not something to review. It is somewhere else to look.
    const merged: GraphPayload = {
      ...withProposal,
      entities: withProposal.entities.map((row) =>
        row.entity_id === 'e2' ? { ...row, open_question_count: 3 } : row,
      ),
    };
    const snapshot = adaptSnapshot(merged);
    expect(snapshot.entities.find((e) => e.entityId === 'e2')?.status).toBe('merged_away');
  });

  it('bands a proposal by how many signals agree, not by its score', () => {
    // Two independent signals agreeing is a countable fact. A band read off an uncalibrated
    // weighted sum would be a guess dressed as a measurement, and no evaluation has run.
    const snapshot = adaptSnapshot(withProposal);
    const proposal = snapshot.matchProposals[0];
    expect(proposal?.basisModalities).toEqual(['context_cooccurrence', 'context_place']);
    expect(proposal?.confidence).toBe('medium');
    expect(proposal?.newModality).toBe('context_place');
  });

  it('names the islands a proposal reaches into, from the occurrences it is about', () => {
    // The option pool unions these with the subject's own islands to say which places a
    // confirmation would touch, so an empty list understates the reach of the question the user
    // is being asked. o2 was taken in c2, which the grouping placed in g1.
    expect(adaptSnapshot(withProposal).matchProposals[0]?.occurrenceIds).toEqual(['o2']);
    expect(adaptSnapshot(withProposal).matchProposals[0]?.islandIds).toEqual(['g1']);
    // Through the caller's own mapping when there is one, rather than read off `scene_groups`,
    // which would be a second answer to which island an occurrence is in.
    const injected = adaptSnapshot(withProposal, (captureId) => `island:${captureId}` as never);
    expect(injected.matchProposals[0]?.islandIds).toEqual(['island:c2']);
  });

  it('leaves an entity with no pending question alone', () => {
    // The guard against the rule widening. Every entity in the base payload has no open
    // question, so nothing here may become needs_review.
    const snapshot = adaptSnapshot(PAYLOAD);
    expect(snapshot.entities.map((entity) => entity.status)).toEqual([
      'user_asserted',
      'merged_away',
    ]);
  });
});

describe('the snapshot adapter states what the server cannot answer', () => {
  const snapshot = adaptSnapshot(PAYLOAD, (captureId) => `island:${captureId}` as never);

  it('maps a named entity to user_asserted, because a name is a thing somebody said', () => {
    const julie = snapshot.entities[0]!;
    expect(julie.status).toBe('user_asserted');
    expect(julie.displayName).toBe('Julie');
    expect(julie.assertions[0]!.predicateKey).toBe('name_is');
    expect(julie.assertions[0]!.producedBy).toEqual({ by: 'user', statedAtMs: expect.any(Number) });
  });

  it('maps a merged entity to merged_away and keeps the redirect', () => {
    const merged = snapshot.entities[1]!;
    expect(merged.status).toBe('merged_away');
    expect(merged.mergedInto).toBe('e1');
  });

  it('carries the state version so a proposal can expire against it', () => {
    expect(snapshot.stateVersion).toBe(7);
  });

  it('leaves an unlinked occurrence as proposed rather than inventing a link', () => {
    expect(snapshot.occurrences[1]!.entityId).toBeNull();
    expect(snapshot.occurrences[1]!.linkState).toBe('proposed');
    expect(snapshot.occurrences[1]!.capturedAtMs).toBeNull();
  });

  it('asks the caller what an island is rather than deciding', () => {
    expect(snapshot.entities[0]!.islandIds).toEqual(['island:c1', 'island:c2']);
    expect(snapshot.occurrences[0]!.islandId).toBe('island:c1');
  });

  it('reports citingAnswerCount as zero because no answer is stored anywhere', () => {
    // Documented in adaptSnapshot. Asserted so the day answers ARE stored, this fails and
    // somebody has to decide rather than shipping a zero that has stopped being true.
    expect(snapshot.entities[0]!.citingAnswerCount).toBe(0);
  });
});

describe('a receipt-backed reconstruction scene remains distinct from its island', () => {
  const scene = {
    scene_id: 'scene-1',
    member_digest: '1'.repeat(64),
    pose_receipt_sha256: '2'.repeat(64),
    placement_receipt_sha256: '3'.repeat(64),
    gate_digest: '4'.repeat(64),
    recorded_rung: 3,
    recorded_reasons: ['Rung 2 withheld: no measured corridor receipt is available.'],
    displayed_rung: 3 as const,
    display_reasons: ['Rung 2 withheld: no measured corridor receipt is available.'],
    member_count: 2,
    registered_member_count: 1,
    receipt_state: 'available' as const,
    placement_state: 'available' as const,
    rendering_substrate: 'posed_point_maps' as const,
    members: [
      {
        capture_id: 'c1',
        ordinal: 0,
        registered: true,
        exclusion_reason: null,
        placement: {
          artifact_id: 'artifact-1',
          content_sha256: '5'.repeat(64),
          container: 'opm/2',
          scene_from_opm_row_major: [
            1, 0, 0, 2,
            0, 1, 0, 0,
            0, 0, 1, -3,
            0, 0, 0, 1,
          ],
          local_units_to_scene_units: 1,
          scale_status: 'unvalidated-identity' as const,
          state: 'available' as const,
          reference: {
            href: '/geometry/artifact-1',
            authorization: 'workspace-bearer' as const,
            content_sha256: '5'.repeat(64),
            byte_size: 120,
          },
        },
      },
      {
        capture_id: 'c2',
        ordinal: 1,
        registered: false,
        exclusion_reason: 'pose-not-registered',
        placement: null,
      },
    ],
  };

  it('carries recorded rung, displayed rung, reasons, substrate and exact transforms separately', () => {
    const snapshot = adaptSnapshot({ ...PAYLOAD, reconstruction_scenes: [scene] });
    expect(snapshot.reconstructionScenes).toHaveLength(1);
    expect(snapshot.reconstructionScenes![0]).toMatchObject({
      sceneId: 'scene-1',
      islandId: 'g1',
      recordedRung: 3,
      displayedRung: 3,
      renderingSubstrate: 'posed_point_maps',
    });
    expect(snapshot.reconstructionScenes![0]!.members[0]!.placement)
      .toMatchObject({ artifactId: 'artifact-1', localUnitsToSceneUnits: 1 });
    expect(snapshot.islands[0]).toMatchObject({
      recordedSceneRung: 3,
      displayedRung: 3,
      renderingSubstrate: 'posed_point_maps',
      reconstructionSceneId: 'scene-1',
    });
  });

  it('does not place one scene into either region when a custom island policy splits its members', () => {
    const snapshot = adaptSnapshot(
      { ...PAYLOAD, reconstruction_scenes: [scene] },
      (captureId) => `island:${captureId}` as never,
    );
    expect(snapshot.reconstructionScenes![0]!.islandId).toBeNull();
    expect(snapshot.islands.every((island) => island.reconstructionSceneId === null)).toBe(true);
  });

  it('builds one scene-backed island when reconstruction is the only durable grouping', () => {
    const snapshot = adaptSnapshot({
      ...PAYLOAD,
      entities: [],
      occurrences: [],
      proposals: [],
      scene_groups: [],
      reconstruction_scenes: [scene],
    });

    expect(snapshot.islands).toEqual([
      expect.objectContaining({
        islandId: 'scene-1',
        captureIds: ['c1', 'c2'],
        reconstructionSceneId: 'scene-1',
      }),
    ]);
    expect(snapshot.reconstructionScenes![0]!.islandId).toBe('scene-1');
  });
});

describe('a timestamp the client cannot read', () => {
  it('becomes null rather than NaN, because NaN goes on to be rendered as a date', () => {
    // `wire.ts` says of `toMs` that it is "never NaN", and this is that sentence. A NaN travels
    // through every arithmetic comparison the layout solver and the timeline make without
    // throwing, and comes out the far end as an Invalid Date beside a photograph. A null has to
    // be handled by whoever received it.
    const unreadable: GraphPayload = {
      ...PAYLOAD,
      entities: [{ ...PAYLOAD.entities[0]!, first_seen: 'the fourth of March', last_seen: null }],
    };
    expect(adaptSnapshot(unreadable).entities[0]!.firstSeenMs).toBeNull();
  });
});

/**
 * How many islands an entity was seen in, which is a count four surfaces act on.
 *
 * `entity.islandIds.length` decides whether the Companion asks which places a name covers
 * (companion-runtime `confirmation.ts`), whether the option pool offers that choice at all
 * (`pool.ts`), the cross-island reach term the review queue is ordered by (`value.ts`) and the
 * island count a delete confirmation states out loud (world-index `proposals.ts`). None of them
 * de-duplicates first, so this adapter has to.
 */
describe('an entity is counted once per island, not once per capture', () => {
  /** Three photographs of one person in one kitchen. One island, seen three times. */
  const threeInOneGroup: GraphPayload = {
    ...PAYLOAD,
    entities: [
      { ...PAYLOAD.entities[0]!, occurrence_count: 3, capture_ids: ['c1', 'c2', 'c3'] },
    ],
    scene_groups: [{ ...GROUP, capture_ids: ['c1', 'c2', 'c3'] }],
  };

  it('reports one island for three captures of one scene group', () => {
    expect(adaptSnapshot(threeInOneGroup).entities[0]!.islandIds).toEqual(['g1']);
  });

  it('still reports both islands for an entity that genuinely spans two', () => {
    // The guard against the de-duplication collapsing islands that really do differ. An entity
    // seen in the kitchen and at the harbour must keep reading as two places, or the reach term
    // stops firing for exactly the entities it was written for.
    const twoGroups: GraphPayload = {
      ...threeInOneGroup,
      scene_groups: [
        { ...GROUP, capture_ids: ['c1', 'c2'] },
        {
          ...GROUP,
          group_id: 'g2',
          ordinal: 1,
          capture_ids: ['c3'],
          member_count: 1,
          positioned_member_count: 1,
        },
      ],
    };
    expect(adaptSnapshot(twoGroups).entities[0]!.islandIds).toEqual(['g1', 'g2']);
  });
});
