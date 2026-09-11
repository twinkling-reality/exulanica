/**
 * The server's payload as the read model, with every gap stated.
 *
 * **The adapter is where the honesty lives.** The read model was designed against a fuller system
 * than exists, and this file is the single auditable place where the difference is recorded.
 * Every field the server cannot answer is set to the value that is true and says why at the line
 * that sets it, because a zero that means 'not implemented' and a zero that means 'none' look
 * identical in a user interface and only one of them is true. The four whose reason needs more
 * than a line are gathered in `adaptSnapshot`'s own comment instead.
 *
 * Nothing here knows the transport exists. The wire shapes come from `wire.ts` as types, so a
 * test of this file needs a payload and no server.
 */

import { buildIslands, groupIslands, type IslandOf } from './islands.js';
import type {
  AnchorIdRef,
  AssertionProducer,
  AssertionView,
  EntityIdRef,
  EntityRecord,
  EvidenceHandle,
  GraphSnapshot,
  HistoryEvent,
  IslandIdRef,
  LinkState,
  MatchProposalView,
  OccurrenceRecord,
  ReconstructionSceneRecord,
} from './read-model.js';
import { type AssertionPayload, type GraphPayload, type HistoryPayload, toMs } from './wire.js';

/**
 * Server payload to read model, with every gap stated.
 *
 * Four of the fields the read model asks for and the server cannot answer today: the four whose
 * reason needs more than a line. The others carry theirs at the line that sets them. Each is set
 * to the value that is TRUE rather than the value that looks complete:
 *
 *   - `confidence`: null on every entity and 'low' on every occurrence link. A confirmed link is
 *     a human decision and has no confidence, it has support, which is exactly what the read
 *     model's own comment says. A match proposal DOES carry a band now, and it is a count rather
 *     than a score: how many independent signals agree. A band derived from an uncalibrated
 *     weighted sum would be a guess wearing a band's clothes, and no calibration data exists.
 *   - `citingAnswerCount`: 0, and it means 'no answer is stored anywhere', not "no answer cites
 *     this". The field exists because a tier 3 confirmation must state how many answers lose
 *     their citation. Until answers are stored, a tier 3 confirmation cannot state it, and the
 *     gate refuses tier 3 anyway.
 *   - `anchorIds` on a proposal: the occurrence's own id is used as its anchor. An anchor is a
 *     placed object in the Atlas and the placement is the client's, so this is the identity map
 *     until a layout exists to ask.
 *   - `status`: derived from what the server knows, and the mapping is exact rather than
 *     approximate. A name is only ever written by an active `kind='user'` assertion, so an
 *     entity with one is `user_asserted`. An entity with `merged_into` set is `merged_away`.
 *     Everything else is `inferred_only`: it exists because a detector saw something and no
 *     person has spoken about it. `needs_review` outranks both and means one thing: a proposal
 *     about this entity is pending, from `pending_match_proposal` on the server, which is a
 *     question the user has not answered rather than one that was ever asked. It is the review
 *     queue's only filter, so an entity is in the queue exactly when a question about it is
 *     waiting. It loses to `merged_away`, because an alias redirect is not something to review,
 *     and it beats `user_asserted`, because a named person with an open question is precisely
 *     what the queue is for; the provenance triad still shows that a person has spoken.
 */
export function adaptSnapshot(
  payload: GraphPayload,
  islandOf?: IslandOf,
): GraphSnapshot {
  const toIsland = islandOf ?? groupIslands(payload);
  const entities: readonly EntityRecord[] = payload.entities.map(
    (row): EntityRecord => ({
      entityId: row.entity_id as EntityIdRef,
      kind: row.entity_class as EntityRecord['kind'],
      displayName: row.display_name,
      status: entityStatus(row.merged_into, row.display_name, row.open_question_count),
      occurrenceCount: row.occurrence_count,
      // The islands this entity was seen in, each named ONCE. Sixteen captures of one visit are
      // one island, and the length of this array is read as an island count by four surfaces:
      // whether the Companion asks which places a name covers, whether the option pool offers
      // that choice at all, the cross-island reach term the review queue is ordered by, and the
      // island count a delete confirmation states out loud. None of them de-duplicates first, so
      // a capture list mapped straight through told all four that a person photographed three
      // times in one kitchen had been seen in three places.
      islandIds: [...new Set(row.capture_ids.map(toIsland))],
      firstSeenMs: toMs(row.first_seen),
      lastSeenMs: toMs(row.last_seen),
      confidence: null,
      openQuestionCount: row.open_question_count,
      citingAnswerCount: 0,
      assertions: row.assertions.map(adaptAssertion),
      // Empty because nothing writes a relation predicate yet, not because relations are ignored.
      // The vocabulary seeds no predicate whose object is another entity.
      relations: [],
      // Empty because nothing writes a dispute yet. The read model carries the field because 5.4
      // requires a contradicting inference to be recorded and surfaced, never applied.
      contradictions: [],
      history: row.history.map((event) =>
        adaptHistory(event, payload.state_version),
      ),
      mergedInto: (row.merged_into as EntityIdRef | null) ?? null,
    }),
  );

  const occurrences: readonly OccurrenceRecord[] = payload.occurrences.map(
    (row): OccurrenceRecord => ({
      occurrenceId: row.occurrence_id as OccurrenceRecord['occurrenceId'],
      captureId: row.capture_id,
      anchorId: row.occurrence_id as AnchorIdRef,
      islandId: toIsland(row.capture_id),
      kind: row.occurrence_class as OccurrenceRecord['kind'],
      entityId: (row.entity_id as EntityIdRef | null) ?? null,
      linkState: (row.link_state ?? 'proposed') as LinkState,
      confidence: 'low',
      evidence: [row.primary_span_id as EvidenceHandle],
      capturedAtMs: toMs(row.captured_at),
    }),
  );

  // Where each occurrence ended up, so a proposal can name the regions it touches. The same
  // mapping the occurrence records above went through, because two answers to "which island is
  // this occurrence in" is one answer too many.
  const islandByOccurrence = new Map<string, IslandIdRef>(
    payload.occurrences.map((row) => [row.occurrence_id, toIsland(row.capture_id)]),
  );

  const matchProposals: readonly MatchProposalView[] = payload.proposals.map(
    (row): MatchProposalView => {
      const island = islandByOccurrence.get(row.occurrence_id);
      return {
        matchId: row.proposal_id,
        entityId: row.entity_id as EntityIdRef,
        // Null because the server proposes an OCCURRENCE against an entity: there is no second
        // entity in the row to name. Null is what the read model already spells "the entity, and
        // the bare occurrences it might match", so this is a fact about the proposal rather than
        // a gap in it, and the option pool reads it and targets the subject entity alone.
        candidateEntityId: null,
        occurrenceIds: [row.occurrence_id as OccurrenceRecord['occurrenceId']],
        anchorIds: [row.occurrence_id as AnchorIdRef],
        // The regions this proposal reaches into, from the occurrences it names. The join is in
        // the payload, so it is computed rather than left empty: the option pool unions these
        // with the subject's own islands to say which places a confirmation would touch, and an
        // empty list there understates the reach of the decision the user is being asked for.
        // Empty only when the payload carries no occurrence for the id, which would be an
        // island invented out of nothing.
        islandIds: island === undefined ? [] : [island],
        // A COUNT, not a score. "Two independent signals agree" is a countable fact about the
        // basis; a band read off an uncalibrated weighted sum would be a guess dressed as a
        // measurement, and there is no calibration data because no evaluation has run.
        confidence: bandFromModalityCount(readModalities(row.basis).length),
        basisModalities: readModalities(row.basis),
        evidence: row.support_span_ids as readonly EvidenceHandle[],
        suppressedByRejection: row.suppressed_by_rejection,
        // What this proposal carries that the user has not already refused for the pair, computed
        // by the producer that knows. Null when nothing about the pair was refused before, which
        // is the ordinary case rather than a missing value.
        newModality: row.new_modality,
      };
    },
  );

  const reconstructionScenes: readonly ReconstructionSceneRecord[] =
    payload.reconstruction_scenes.map((row) => {
      const islandIds = new Set(row.members.map((member) => toIsland(member.capture_id)));
      return {
      sceneId: row.scene_id,
      trainedGeometry: row.trained_geometry == null ? null : {
        artifactId: row.trained_geometry.artifact_id,
        contentSha256: row.trained_geometry.content_sha256,
        container: row.trained_geometry.container,
        sceneFromAssetRowMajor: row.trained_geometry.scene_from_asset_row_major,
        bounds: row.trained_geometry.bounds,
        state: row.trained_geometry.state,
        reference: row.trained_geometry.reference === null ? null : {
          href: row.trained_geometry.reference.href,
          authorization: row.trained_geometry.reference.authorization,
          contentSha256: row.trained_geometry.reference.content_sha256,
          byteSize: row.trained_geometry.reference.byte_size,
        },
        ...(row.trained_geometry.quality === undefined ? {} : { quality: {
          heldoutViews: row.trained_geometry.quality.heldout_views,
          psnr: row.trained_geometry.quality.psnr,
          ssim: row.trained_geometry.quality.ssim,
          lpips: row.trained_geometry.quality.lpips,
          coverageFraction: row.trained_geometry.quality.coverage_fraction,
          floatersFraction: row.trained_geometry.quality.floaters_fraction,
          iterationsCompleted: row.trained_geometry.quality.iterations_completed,
          durationSeconds: row.trained_geometry.quality.duration_seconds,
          usdCost: row.trained_geometry.quality.usd_cost,
          gpu: row.trained_geometry.quality.gpu,
        } }),
      },
        // An absent field is an older payload that predates the generated tier, and it maps to an
        // empty list rather than to a claim: either way nothing is drawn, and the field's name is
        // what a caller must read before anything can be.
        generatedGeometry: (row.generated_geometry ?? []).map((entry) => ({
          artifactId: entry.artifact_id,
          receiptSha256: entry.receipt_sha256,
          tier: entry.tier,
          state: entry.state,
          stateReason: entry.state_reason,
          model: entry.model === null ? null : {
            provider: entry.model.provider,
            modelId: entry.model.model_id,
            modelVersion: entry.model.model_version,
          },
          promptSha256: entry.prompt_sha256,
          conditioning: entry.conditioning,
          worldReadBundleSha256: entry.world_read_bundle_sha256,
          container: entry.container,
          contentSha256: entry.content_sha256,
          byteSize: entry.byte_size,
          seam: entry.seam,
        })),
        islandId: islandIds.size === 1 ? [...islandIds][0]! : null,
        memberDigest: row.member_digest,
        poseReceiptSha256: row.pose_receipt_sha256,
        placementReceiptSha256: row.placement_receipt_sha256,
        gateDigest: row.gate_digest,
        recordedRung: asRung(row.recorded_rung),
        recordedReasons: row.recorded_reasons,
        displayedRung: row.displayed_rung,
        displayReasons: row.display_reasons,
        memberCount: row.member_count,
        registeredMemberCount: row.registered_member_count,
        receiptState: row.receipt_state,
        placementState: row.placement_state,
        renderingSubstrate: row.rendering_substrate,
        hiddenPersonCount: row.hidden_person_count ?? 0,
        maskedMemberCount: row.masked_member_count ?? 0,
        members: row.members.map((member) => ({
          captureId: member.capture_id,
          ordinal: member.ordinal,
          registered: member.registered,
          recoveredCamera: member.recovered_camera == null ? null : {
            sceneFromCameraRowMajor: member.recovered_camera.scene_from_camera_row_major,
            calibration: member.recovered_camera.calibration,
            projection: member.recovered_camera.projection,
          },
          exclusionReason: member.exclusion_reason,
          // Carried, not dropped. This mapping is the only path between what the server sends
          // and what a draw site can see, and for a while it silently discarded both of these:
          // the fields were declared on the wire, resolved by the server and thrown away here,
          // so every consent decision stopped at the parser.
          personRegions: (member.person_regions ?? []).map((person) => ({
            regionId: person.region_id,
            state: person.state,
            silhouettePpm: person.silhouette_ppm,
            displayName: person.display_name,
            subjectId: person.subject_id,
          })),
          // Absent reads as unscreened, which draws nothing. An older server that does not send
          // this field must not thereby be treated as having screened the photograph.
          personReviewState: member.person_review_state ?? 'unscreened',
          unposedPointMap: member.unposed_point_map == null
            ? null
            : {
                artifactId: member.unposed_point_map.artifact_id,
                contentSha256: member.unposed_point_map.content_sha256,
                container: member.unposed_point_map.container,
                state: member.unposed_point_map.state,
                reference: member.unposed_point_map.reference === null
                  ? null
                  : {
                      href: member.unposed_point_map.reference.href,
                      authorization: member.unposed_point_map.reference.authorization,
                      contentSha256: member.unposed_point_map.reference.content_sha256,
                      byteSize: member.unposed_point_map.reference.byte_size,
                    },
                photograph: member.unposed_point_map.photograph == null
                  ? null
                  : {
                      href: member.unposed_point_map.photograph.href,
                      authorization: member.unposed_point_map.photograph.authorization,
                      contentSha256: member.unposed_point_map.photograph.content_sha256,
                      byteSize: member.unposed_point_map.photograph.byte_size,
                    },
              },
          placement: member.placement === null
            ? null
            : {
                artifactId: member.placement.artifact_id,
                contentSha256: member.placement.content_sha256,
                container: member.placement.container,
                sceneFromOpmRowMajor: member.placement.scene_from_opm_row_major,
                localUnitsToSceneUnits: member.placement.local_units_to_scene_units,
                scaleStatus: member.placement.scale_status,
                state: member.placement.state,
                reference: member.placement.reference === null
                  ? null
                  : {
                      href: member.placement.reference.href,
                      authorization: member.placement.reference.authorization,
                      contentSha256: member.placement.reference.content_sha256,
                      byteSize: member.placement.reference.byte_size,
                    },
              },
        })),
      };
    });

  return {
    stateVersion: payload.state_version,
    entities,
    occurrences,
    islands: buildIslands(payload, toIsland),
    reconstructionScenes,
    matchProposals,
    neverSame: payload.never_same.map(
      ([a, b]) => [a as EntityIdRef, b as EntityIdRef] as const,
    ),
    deletedEntityIds: payload.deleted_entity_ids as readonly EntityIdRef[],
  };
}

function asRung(value: number | null): 1 | 2 | 3 | 4 | null {
  return value === 1 || value === 2 || value === 3 || value === 4 ? value : null;
}

/** The modalities a proposal was built from, from its recorded basis. Never invented. */
function readModalities(
  basis: Readonly<Record<string, unknown>>,
): readonly string[] {
  const declared = basis['modalities'];
  return Array.isArray(declared)
    ? declared.filter((m): m is string => typeof m === 'string')
    : [];
}

/**
 * The band a proposal is shown under, from how many independent signals corroborate it.
 *
 * Deliberately not derived from the score. `score` is `raw_score` in the epistemic sense: never
 * rendered, never a threshold that decides a factual claim, and produced by weights that no
 * evaluation has validated. How many signals agree is a fact that can be counted, and counting
 * is the strongest honest statement available until there is calibration data.
 */
function bandFromModalityCount(count: number): 'low' | 'medium' | 'high' {
  if (count >= 3) return 'high';
  if (count === 2) return 'medium';
  return 'low';
}

/**
 * How a stored entity presents in the index's Status facet.
 *
 * `user_asserted` rather than `confirmed` for a named entity, and the distinction is the
 * product's: a name is a thing a person said, and `confirmed` in this vocabulary is about a link
 * having been agreed rather than about an entity having been named.
 */
function entityStatus(
  mergedInto: string | null,
  displayName: string | null,
  openQuestionCount: number,
): EntityRecord['status'] {
  if (mergedInto !== null) return 'merged_away';
  if (openQuestionCount > 0) return 'needs_review';
  if (displayName !== null) return 'user_asserted';
  return 'inferred_only';
}

/**
 * One stored claim, with what produced it.
 *
 * `confidence` is null for `capture` and `user` because those do not have confidence, they have
 * support, which is the read model's own wording. An inference could carry a band, and does not
 * yet: the server records the model's qualitative band on the occurrence rather than on the
 * assertion, and inventing one here from a score is exactly the thing epi-4 forbids.
 */
function adaptAssertion(row: AssertionPayload): AssertionView {
  return {
    assertionId: row.assertion_id as AssertionView['assertionId'],
    kind: row.kind as AssertionView['kind'],
    predicateKey: row.predicate_key,
    status: row.status as AssertionView['status'],
    objectValue: row.object_value,
    supportEvidence: row.support_span_ids as readonly EvidenceHandle[],
    producedBy: adaptProducer(row),
    confidence: null,
    assertedAtMs: toMs(row.asserted_at) ?? 0,
    supersedes: (row.supersedes as AssertionView['supersedes']) ?? null,
  };
}

function adaptProducer(row: AssertionPayload): AssertionProducer {
  const by = row.produced_by['by'];
  if (by === 'user') {
    return { by: 'user', statedAtMs: toMs(row.asserted_at) ?? 0 };
  }
  if (by === 'pipeline') {
    return {
      by: 'pipeline',
      runId: String(row.produced_by['run_id'] ?? ''),
      // The model that produced it is on the pipeline event rather than on the assertion, so
      // this is empty rather than guessed. A model ref that named the wrong model would be
      // worse than one that names none.
      modelRef: '',
    };
  }
  if (by === 'external') {
    const source = (row.produced_by['source'] ?? {}) as Record<string, unknown>;
    return {
      by: 'external',
      url: String(source['url'] ?? ''),
      retrievedAtMs: toMs(String(source['retrieved_at'] ?? '')) ?? 0,
      snapshotHash: String(source['snapshot_sha256'] ?? ''),
    };
  }
  return { by: 'capture', mediaKey: row.support_span_ids[0] ?? '' };
}

/**
 * One identity decision, as the entity detail view renders it.
 *
 * `actor` is 'user' for every event this system writes, and that is a fact rather than a
 * simplification: every function that writes an identity event takes an actor and there is no
 * path by which the system writes one on its own. When automatic proposals exist, the event they
 * write will be a `match_proposal` row rather than an identity event, and this will still be
 * true.
 */
function adaptHistory(row: HistoryPayload, stateVersion: number): HistoryEvent {
  return {
    eventId: row.event_id,
    type: row.event_type as HistoryEvent['type'],
    actor: 'user',
    atMs: toMs(row.created_at) ?? 0,
    stateVersion,
    // The verbatim utterance lives on the update proposal that produced the decision, and the
    // identity event records the decision. Null rather than a paraphrase.
    rawUtterance: null,
    summaryKey: `identity.${row.event_type}`,
    undoes: row.undoes,
  };
}
