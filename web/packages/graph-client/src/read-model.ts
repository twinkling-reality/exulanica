/**
 * The entity graph READ model.
 *
 * architecture-overview.md 1.1 gives graph-client "entity graph reads and writes, assertion log,
 * evidence resolution". This file is the reads and the assertion log, as the shape the two
 * consumers actually need: companion-runtime builds its option pool from it, world-index renders
 * it. Both of those packages may import graph-client; graph-client may import neither.
 *
 * WHY THESE ENUMS ARE DUPLICATED FROM atlas-core. `ProvenanceClass`, `LinkState` and
 * `ConfidenceBand` also exist in atlas-core/provenance.ts over the same closed sets. That is not
 * an oversight and it must not be "fixed" by importing: graph-client sits UNDER atlas-core
 * (`graph-client-is-the-base` in .dependency-cruiser.cjs), so the arrow can only point the other
 * way, and atlas-core is deliberately self-contained. Both spellings are transcriptions of the
 * same SQL enums in domain-and-evidence-model.md 2.1 and 4.3, which is the single source.
 *
 * WHY IDS ARE PLAIN STRINGS HERE. atlas-core brands its ids. Branding them a second time in this
 * package would create two incompatible nominal types over one value and force a cast at every
 * call site in world-index. A plain alias accepts an atlas-core branded id unchanged, so the
 * seam costs nothing in the direction data actually flows (graph -> presentation).
 */

import type { PersonReviewState, PersonState } from './person-presentation.js';

export type EntityIdRef = string;
export type OccurrenceIdRef = string;
export type IslandIdRef = string;
export type AnchorIdRef = string;
export type AssertionIdRef = string;

/**
 * An evidence handle is OPAQUE (interaction-model.md 3.4): "the interaction layer treats an
 * evidence reference as an opaque handle and never constructs or parses one; it passes it to the
 * evidence resolver and renders what comes back". The real address shape is
 * domain-and-evidence-model.md 1.5 and it lives server-side.
 */
export type EvidenceHandle = string;

/** The four provenance classes (domain-and-evidence-model.md 2.1). Four different things. */
export type AssertionKind = 'capture' | 'inference' | 'user' | 'external';

export type AssertionStatus = 'active' | 'superseded' | 'retracted' | 'disputed' | 'rejected';

/** domain-and-evidence-model.md 4.3. id-2: `auto_provisional` may organize, never assert. */
export type LinkState = 'proposed' | 'auto_provisional' | 'confirmed' | 'rejected' | 'revoked';

/**
 * Qualitative only. epi-4: `raw_score` is never rendered and `calibrated_p` is NULL until a
 * calibration bin has enough observed decisions, so this type deliberately cannot hold a
 * percentage. A percentage implies a frequency guarantee that cannot be made.
 */
export type ConfidenceBand = 'low' | 'medium' | 'high';

/** interaction-model.md 6.1, the Kind facet. A region is an entity too. */
export type EntityKind = 'person' | 'place' | 'object' | 'event' | 'region';

/** interaction-model.md 6.1, the Status facet. */
export type IndexStatus =
  | 'confirmed'
  | 'needs_review'
  | 'inferred_only'
  | 'user_asserted'
  | 'rejected'
  | 'merged_away';

/** The five citation kinds (domain-and-evidence-model.md 1.6). A closed set. */
export type CitationModality =
  | 'still_image'
  | 'frame_region'
  | 'video_time'
  | 'audio_time'
  | 'transcript_text';

/**
 * A normalised region, in parts per million of the unit square (spine-9a).
 *
 * Integers, not floats: `region` is inside `span_digest` and no two JSON writers agree on how to
 * render a float. One ppm of a 6000px-wide photograph is 0.006px.
 */
export interface EvidenceRegion {
  readonly xPpm: number;
  readonly yPpm: number;
  readonly wPpm: number;
  readonly hPpm: number;
}

/** What the resolver hands back for a handle. The UI renders this and never parses the handle. */
export interface ResolvedEvidence {
  readonly handle: EvidenceHandle;
  readonly modality: CitationModality;
  /** Opaque storage key for the original media. Opening a citation opens THIS. */
  readonly sourceKey: string;
  /**
   * Wall clock, from a `clock_anchor` row, never smuggled into the media axis (1.5). Null when
   * the capture carries no usable clock, which is a real and common state.
   */
  readonly capturedAtMs: number | null;
  readonly capturedAtUncertaintyMs: number | null;
  readonly region: EvidenceRegion | null;
}

export interface EvidenceResolver {
  resolve(handles: readonly EvidenceHandle[]): Promise<readonly ResolvedEvidence[]>;
}

/**
 * What produced an assertion. This is the "and what produced it" half of the provenance panel,
 * and it is a discriminated union rather than a string because the four provenance classes carry
 * genuinely different obligations: an inference must name its run, an external lookup must carry
 * url + retrieved_at + snapshot hash (epi-2), a user assertion must name a human.
 */
export type AssertionProducer =
  | { readonly by: 'capture'; readonly mediaKey: string }
  | { readonly by: 'pipeline'; readonly runId: string; readonly modelRef: string }
  | { readonly by: 'user'; readonly statedAtMs: number }
  | {
      readonly by: 'external';
      readonly url: string;
      readonly retrievedAtMs: number;
      readonly snapshotHash: string;
    };

export interface AssertionView {
  readonly assertionId: AssertionIdRef;
  readonly kind: AssertionKind;
  /** 'name_is', 'person_present', 'relation_is', ... `name_is` allows only `user` (epi-3). */
  readonly predicateKey: string;
  readonly status: AssertionStatus;
  /** Typed by the predicate's value schema. Opaque to the presentation layer. */
  readonly objectValue: unknown;
  readonly supportEvidence: readonly EvidenceHandle[];
  readonly producedBy: AssertionProducer;
  /** Null for `capture` and `user`, which do not have confidence: they have support. */
  readonly confidence: ConfidenceBand | null;
  readonly assertedAtMs: number;
  readonly supersedes: AssertionIdRef | null;
}

export interface RelationView {
  readonly predicateKey: string;
  readonly objectEntityId: EntityIdRef;
  readonly kind: AssertionKind;
  readonly supportEvidence: readonly EvidenceHandle[];
}

/**
 * 5.4: "a system inference that contradicts a user assertion is recorded as a contradiction and
 * surfaced as a question, NEVER APPLIED". The contradiction is therefore read-model state that
 * the Companion turns into a `disambiguate_claim` intent and the index shows as needs-review.
 */
export interface ContradictionView {
  readonly contradictionId: string;
  readonly userAssertionId: AssertionIdRef;
  readonly otherAssertionId: AssertionIdRef;
  readonly predicateKey: string;
  readonly openedAtMs: number;
}

export type HistoryEventType =
  | 'entity_created'
  | 'link_confirmed'
  | 'link_rejected'
  | 'link_revoked'
  | 'entities_merged'
  | 'entity_split'
  | 'event_undone'
  | 'assertion_committed';

/**
 * One row of the immutable assertion log (5.4), rendered as History in the entity detail view.
 * "Nothing is ever silently rewritten."
 */
export interface HistoryEvent {
  readonly eventId: string;
  readonly type: HistoryEventType;
  readonly actor: 'user' | 'system';
  readonly atMs: number;
  readonly stateVersion: number;
  /** 5.1: the verbatim raw utterance, retained and never paraphrased away. */
  readonly rawUtterance: string | null;
  readonly summaryKey: string;
  readonly undoes: string | null;
}

/**
 * An entity as the index and the Companion see it.
 *
 * `displayName` is null when nobody has named it. id-1: the occurrence is anonymous and the
 * entity holds the name; id-6: names come solely from the account holder's own annotation, so a
 * null here is the normal state and not a missing value to be filled in by a model.
 */
export interface EntityRecord {
  readonly entityId: EntityIdRef;
  readonly kind: EntityKind;
  readonly displayName: string | null;
  readonly status: IndexStatus;

  readonly occurrenceCount: number;
  readonly islandIds: readonly IslandIdRef[];
  readonly firstSeenMs: number | null;
  readonly lastSeenMs: number | null;

  /** Qualitative, and meaningful only while the entity is inference-backed. */
  readonly confidence: ConfidenceBand | null;
  /** Drives the ambient counter and the review queue. Never rendered as "N of M". */
  readonly openQuestionCount: number;
  /**
   * How many stored answers cite this entity.
   *
   * interaction-model.md 5.3 requires a tier 3 confirmation to state "a named consequence: HOW
   * MANY EXISTING ANSWERS CITE THIS ENTITY AND WILL LOSE THEIR CITATION". A confirmation cannot
   * state a number the read model does not carry, so it is carried.
   */
  readonly citingAnswerCount: number;

  readonly assertions: readonly AssertionView[];
  readonly relations: readonly RelationView[];
  readonly contradictions: readonly ContradictionView[];
  readonly history: readonly HistoryEvent[];

  /** Merge leaves alias redirects so old permalinks resolve (id-7). */
  readonly mergedInto: EntityIdRef | null;
}

/**
 * A ranked candidate link, from the promotion path in domain-and-evidence-model.md 3.2:
 * "candidate generation: ANN over entity exemplars, plus hard constraints -> match_proposal
 * rows, ranked -> gate".
 *
 * id-6: THE SYSTEM NEVER PROPOSES A REAL-WORLD IDENTITY. It proposes only "the same person as in
 * these other captures". That is why this type carries entity ids and evidence and no name.
 */
export interface MatchProposalView {
  readonly matchId: string;
  /** The entity the user has already seen, and the entity (or bare occurrences) it might match. */
  readonly entityId: EntityIdRef;
  readonly candidateEntityId: EntityIdRef | null;
  readonly occurrenceIds: readonly OccurrenceIdRef[];
  readonly anchorIds: readonly AnchorIdRef[];
  readonly islandIds: readonly IslandIdRef[];
  readonly confidence: ConfidenceBand;
  /**
   * Which modalities were used, from the closed set in id-4:
   * `{face, voice, gait, context_place, context_cooccurrence, user_text}`. The photograph corpus
   * uses face, context_place and context_cooccurrence; voice and gait have no source material.
   */
  readonly basisModalities: readonly string[];
  /**
   * id-4, the re-proposal rule: a proposal is suppressed when an unrevoked rejection matches and
   * the new basis is a SUBSET of the rejected basis. Resolved server-side, because it needs the
   * rejection table; the client only needs to know not to offer it as if it were fresh.
   */
  readonly suppressedByRejection: boolean;
  /** Set when the proposal resurfaced with a materially new modality. id-4 requires it be said. */
  readonly newModality: string | null;
  readonly evidence: readonly EvidenceHandle[];
}

/**
 * What kind of thing a detection is (`occurrence_class`).
 *
 * Carried on the record rather than derived, because the renderer decides between a presence
 * marker and world geometry from it: interaction-model.md is explicit that people are citations
 * rather than reconstructions, and a person rendered as geometry would be a person baked into a
 * scene. `voice` and `conversation` exist in the schema and have no source material in a
 * photograph corpus; they are in this union because the column can hold them, and a consumer
 * that cannot draw one should say so rather than fall through to the wrong shape.
 */
export type OccurrenceKind =
  | 'person'
  | 'voice'
  | 'place'
  | 'object'
  | 'conversation'
  | 'event';

/** A detection made addressable. Anonymous by construction: no name field exists here. */
export interface OccurrenceRecord {
  readonly occurrenceId: OccurrenceIdRef;
  /** Original capture membership, retained so a recovered camera can resolve existing evidence. */
  readonly captureId?: string;
  readonly anchorId: AnchorIdRef;
  readonly islandId: IslandIdRef;
  readonly kind: OccurrenceKind;
  readonly entityId: EntityIdRef | null;
  readonly linkState: LinkState;
  readonly confidence: ConfidenceBand;
  readonly evidence: readonly EvidenceHandle[];
  readonly capturedAtMs: number | null;
}

/**
 * One island, as the layout needs it, with what it was made of.
 *
 * An island is a PRESENTATION unit and this record says so by carrying nothing that could be
 * mistaken for an answer. `spreadMetres` is how far apart the member captures with a fix were,
 * which is a fact about the photographs; it is not the island's size in the Atlas, because an
 * island's atlas position and radius carry no real-world meaning at all (interaction-model.md
 * 1.2, risk R-48).
 *
 * `positionedCaptureCount` is separate from `captureIds.length` on purpose. A group clustered on
 * time alone, because none of its members had a fix, is a weaker claim about being one place
 * than a group where every member agreed on a position, and an interface that showed the two
 * identically would be flattening that.
 */
/**
 * A rung on the reconstruction ladder, as a closed set.
 *
 * Duplicated from atlas-core's `ReconstructionRung` for the same reason `ConfidenceBand` and
 * `LinkState` are: graph-client sits UNDER atlas-core and the arrow can only point the other way.
 * Both are transcriptions of the four rungs in product-specification.md section 5.
 */
export type ReconstructionRungRef = 1 | 2 | 3 | 4;

export type RenderingSubstrate = 'posed_point_maps' | 'gaussian_splats' | 'source_photographs';

export interface TrainedGeometryRecord {
  readonly artifactId: string;
  readonly contentSha256: string;
  readonly container: 'sog/1';
  readonly sceneFromAssetRowMajor: readonly number[];
  readonly bounds: { readonly min: readonly number[]; readonly max: readonly number[] };
  readonly state: 'available' | 'bytes_missing' | 'invalid';
  readonly reference: {
    readonly href: string;
    readonly authorization: 'workspace-bearer';
    readonly contentSha256: string;
    readonly byteSize: number;
  } | null;
  /**
   * Appearance-held-out measurements with pose conditioning, as the trainer's quality receipt
   * recorded them. A number beside the rung, never a rung or a physical-scale claim.
   */
  readonly quality?: TrainingQualityRecord;
}

export interface TrainingQualityRecord {
  readonly heldoutViews: number;
  readonly psnr: number;
  readonly ssim: number;
  readonly lpips: number;
  readonly coverageFraction: number;
  readonly floatersFraction: number;
  readonly iterationsCompleted: number;
  readonly durationSeconds: number;
  readonly usdCost: number;
  readonly gpu: string;
}

export interface ReconstructionPointMapRecord {
  readonly artifactId: string;
  readonly contentSha256: string;
  readonly container: string | null;
  readonly sceneFromOpmRowMajor: readonly number[];
  readonly localUnitsToSceneUnits: number;
  readonly scaleStatus: 'colmap-correspondence-fit';
  readonly state: 'available' | 'bytes_missing';
  readonly reference: {
    readonly href: string;
    readonly authorization: 'workspace-bearer';
    readonly contentSha256: string;
    readonly byteSize: number;
  } | null;
}

export interface RecoveredCameraCalibration {
  readonly model: string;
  readonly width: number;
  readonly height: number;
  readonly fx: number;
  readonly fy: number;
  readonly cx: number;
  readonly cy: number;
  readonly parameters: readonly number[];
}

export interface RecoveredCameraRecord {
  readonly sceneFromCameraRowMajor: readonly number[];
  readonly calibration: RecoveredCameraCalibration;
  readonly projection: 'pinhole' | 'pinhole-approximation';
}

/** One person in one photograph: an outline and a state, never pixels. */
export interface PersonRegionRecord {
  readonly regionId: string;
  readonly state: PersonState;
  readonly silhouettePpm: readonly (readonly number[])[];
  readonly displayName: string | null;
  readonly subjectId: string | null;
}

export interface ReconstructionSceneMemberRecord {
  readonly captureId: string;
  readonly ordinal: number;
  readonly registered: boolean;
  readonly recoveredCamera?: RecoveredCameraRecord | null;
  readonly placement: ReconstructionPointMapRecord | null;
  readonly exclusionReason: string | null;
  readonly personRegions: readonly PersonRegionRecord[];
  /**
   * Whether anybody has screened this photograph for people.
   *
   * Not the same fact as an empty `personRegions`. An absent or unrecognised value must be read
   * as `unscreened`, which draws no pixels: the two look identical in an empty array and are
   * opposite answers.
   */
  readonly personReviewState: PersonReviewState;
}

/** One receipt-backed reconstruction scene, distinct from a presentation island or scene group. */
export interface ReconstructionSceneRecord {
  readonly sceneId: string;
  /** Null when a caller's custom island policy split the immutable member set. */
  readonly islandId: IslandIdRef | null;
  readonly memberDigest: string;
  readonly poseReceiptSha256: string | null;
  readonly placementReceiptSha256: string | null;
  readonly gateDigest: string | null;
  readonly recordedRung: ReconstructionRungRef | null;
  readonly recordedReasons: readonly string[];
  readonly displayedRung: ReconstructionRungRef;
  readonly displayReasons: readonly string[];
  readonly memberCount: number;
  readonly registeredMemberCount: number;
  readonly receiptState: 'available' | 'missing' | 'invalid';
  readonly placementState: 'available' | 'partial' | 'bytes_missing' | 'unavailable' | 'invalid';
  readonly renderingSubstrate: RenderingSubstrate;
  /** Counted by the server, so a client that failed to load regions cannot report zero. */
  readonly hiddenPersonCount: number;
  readonly maskedMemberCount: number;
  readonly members: readonly ReconstructionSceneMemberRecord[];
  readonly trainedGeometry?: TrainedGeometryRecord | null;
  /**
   * What a world model imagined for this scene. Never merged into `trainedGeometry`.
   *
   * Empty means nothing was generated. A surface here was produced by a model and observed by no
   * camera: it supports no claim, satisfies no gate, and carries no rung.
   */
  readonly generatedGeometry: readonly GeneratedGeometryRecord[];
}

/** One generation, with everything needed to say what made it and what it was shown. */
export interface GeneratedGeometryRecord {
  readonly artifactId: string;
  readonly receiptSha256: string | null;
  readonly tier: 'generated';
  /** `invalid` means the generation exists but its receipt did not verify. Never drawn. */
  readonly state: 'available' | 'invalid';
  readonly stateReason: string | null;
  readonly model: {
    readonly provider: string;
    readonly modelId: string;
    readonly modelVersion: string;
  } | null;
  readonly promptSha256: string | null;
  readonly conditioning: readonly { readonly role: string; readonly sha256: string }[];
  readonly worldReadBundleSha256: string | null;
  readonly container: string | null;
  readonly contentSha256: string | null;
  readonly byteSize: number | null;
  /** Where the record stops, in words. Shown beside the surface, never omitted. */
  readonly seam: string | null;
}

export interface IslandRecord {
  readonly islandId: IslandIdRef;
  readonly captureIds: readonly string[];
  readonly firstCapturedAtMs: number | null;
  readonly lastCapturedAtMs: number | null;
  readonly positionedCaptureCount: number;
  /** Null when nothing in the group had a position. Not zero: zero is a real spread. */
  readonly spreadMetres: number | null;
  /**
   * The rung this region earned, WORST FIRST across its captures, or null.
   *
   * Null means nothing here has been through reconstruction at all, which is a different fact
   * from rung 4 and must not be shown as one: rung 4 means reconstruction ran and there was too
   * little to place. product-specification.md 5.1 requires the rung be displayed rather than
   * smoothed over, and a client cannot display what it does not carry.
   */
  readonly rung: ReconstructionRungRef | null;
  /**
   * How many of the region's captures stand behind the rung above. A rung from two of sixteen is
   * a weaker claim than one from all sixteen, and an interface showing them alike flattens that.
   *
   * Zero whenever `rung` is null, which is not always the number of captures the server counted:
   * the rung and the count are one statement and they stand or fall together, so a count beside
   * no rung would be a measurement standing behind a claim that was never made.
   */
  readonly rungCaptureCount: number;
  /** The scene gate's immutable result, separate from what this client can draw. */
  readonly recordedSceneRung?: ReconstructionRungRef | null;
  /** The honest presentation rung after receipt and byte availability are applied. */
  readonly displayedRung?: ReconstructionRungRef;
  readonly displayReasons?: readonly string[];
  readonly renderingSubstrate?: RenderingSubstrate;
  readonly reconstructionSceneId?: string | null;
}

/**
 * An immutable read snapshot at one graph state version.
 *
 * Turn generation and index rendering both run against a snapshot rather than against a live
 * connection, because both must be reproducible in a test with no transport, and because
 * `stateVersion` is what expires an update proposal (5.1).
 */
export interface GraphSnapshot {
  readonly stateVersion: number;
  readonly entities: readonly EntityRecord[];
  readonly occurrences: readonly OccurrenceRecord[];
  /**
   * The islands the caller's `islandOf` produced, in layout order.
   *
   * Derived by the adapter rather than returned by the server, because what an island IS remains
   * the client's decision. Present on the snapshot so the layout solver and the index can agree
   * on one set rather than each deriving its own from the occurrences.
   */
  readonly islands: readonly IslandRecord[];
  /** Present on API snapshots. Optional only for old, hand-built local test snapshots. */
  readonly reconstructionScenes?: readonly ReconstructionSceneRecord[];
  /** Ranked candidate links awaiting a user decision. Drives the confirm-continuity intent. */
  readonly matchProposals: readonly MatchProposalView[];
  /**
   * `never_same(A, B)` constraints written by a previous split (3.2, 3.4). Unordered pairs.
   * The option pool refuses to offer a merge across one of these, with a stated reason.
   */
  readonly neverSame: readonly (readonly [EntityIdRef, EntityIdRef])[];
  /**
   * Entities the user deleted. Kept as ids rather than dropped rows because 4.4 stage 3 says
   * "never offer an option targeting a deleted entity", and a client that has simply forgotten
   * an entity cannot check that.
   */
  readonly deletedEntityIds: readonly EntityIdRef[];
}

/** Is this pair already asserted distinct? Order-independent, per `never_same`. */
export function isNeverSame(
  snapshot: GraphSnapshot,
  a: EntityIdRef,
  b: EntityIdRef,
): boolean {
  return snapshot.neverSame.some(
    ([x, y]) => (x === a && y === b) || (x === b && y === a),
  );
}

/** Whether the entity carries an active assertion for a predicate. */
export function hasActiveAssertion(entity: EntityRecord, predicateKey: string): boolean {
  return entity.assertions.some((a) => a.status === 'active' && a.predicateKey === predicateKey);
}

export function entityById(snapshot: GraphSnapshot): ReadonlyMap<EntityIdRef, EntityRecord> {
  const map = new Map<EntityIdRef, EntityRecord>();
  for (const e of snapshot.entities) map.set(e.entityId, e);
  return map;
}

export function occurrencesOf(
  snapshot: GraphSnapshot,
  entityId: EntityIdRef,
): readonly OccurrenceRecord[] {
  return snapshot.occurrences.filter((o) => o.entityId === entityId);
}

/**
 * Which of the four provenance classes actually back this entity.
 *
 * interaction-model.md 6.1: the "source of knowledge" facet deliberately reuses the same
 * vocabulary as the confirmation panel, so "what do you actually know about this" is answered
 * identically in every surface. Derived, never stored, so it cannot go stale.
 */
export function knowledgeSources(entity: EntityRecord): readonly AssertionKind[] {
  const seen = new Set<AssertionKind>();
  for (const a of entity.assertions) {
    if (a.status === 'active') seen.add(a.kind);
  }
  const order: readonly AssertionKind[] = ['user', 'capture', 'inference', 'external'];
  return order.filter((k) => seen.has(k));
}

/**
 * The global open-question count (interaction-model.md 5.5).
 *
 * "One global counter sits in the persistent HUD ('7 open questions'). It never grows a badge,
 * never animates, never pops, never changes colour. It is allowed to read 7 forever. THERE IS NO
 * COMPLETION METRIC ANYWHERE IN THE PRODUCT."
 *
 * This returns a number and nothing else. There is deliberately no total, no percentage and no
 * "resolved so far" here for a caller to render a progress ring out of.
 */
export function openQuestionCount(snapshot: GraphSnapshot): number {
  let n = 0;
  for (const e of snapshot.entities) {
    if (e.status === 'merged_away' || e.status === 'rejected') continue;
    n += e.openQuestionCount;
  }
  return n;
}
