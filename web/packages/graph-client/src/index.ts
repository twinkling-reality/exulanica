/**
 * @exulanica/graph-client
 *
 * Entity graph reads, the assertion log and evidence resolution. This package sits UNDER
 * everything: it may not import atlas-core, atlas-react, companion-runtime or world-index
 * (architecture-overview.md 1.1), and `.dependency-cruiser.cjs` enforces that.
 *
 * Mutations live behind a second entry point, `@exulanica/graph-client/mutations`, so that
 * "atlas-react forbids graph mutations" is a path a lint rule can name rather than a habit.
 *
 * The transport is real, and four files divide the work of speaking to it. `wire.ts` says what
 * the server sent, in the server's own words. `snapshot.ts` turns that into the read model and is
 * the single place where the difference between what the read model asks for and what the server
 * can answer is written down. `islands.ts` says what an island is, which is the client's decision
 * and not the server's. `client.ts` says which routes exist. The read model did not have to
 * change to make the transport real, which is what the boundary was for.
 *
 * What this file names is the package's vocabulary, not its contents. It is a curated list rather
 * than four `export *` lines because of what it leaves out: the thirteen helpers those files are
 * built from stay inside the package. How a confidence band is derived from a modality count is a
 * decision inside one file, and putting it in the workspace namespace would invite a second
 * caller and turn it into a shared rule nobody owns. The exports map exposes only `.` and
 * `./mutations`, so a deep import of one of those files does not resolve at all.
 */

export type { GraphPayload } from './wire.js';

// The presentation rule for people in a photograph. Exported because three separate draw sites
// need it -- world veils, the reconstruction inspector, and the citation image in the detail
// pane -- and a rule copied into three call sites is a rule that gets corrected in two of them.
export type {
  PersonRegionView,
  PersonReviewState,
  PersonState,
} from './person-presentation.js';
export {
  drawsName,
  drawsPixels,
  drawsSilhouette,
  hiddenRegions,
  mayDrawPhotograph,
  personPresenceSentence,
} from './person-presentation.js';

export type { IslandOf } from './islands.js';

export type { GraphLoadState, GraphSource, TerminalGraphLoadState } from './source.js';
export { loadGraph } from './source.js';

export { adaptSnapshot } from './snapshot.js';

export type { ClientOptions } from './client.js';
export { ExulanicaClient } from './client.js';

export type { ApiProblem, TransportOptions } from './transport.js';
export { ApiError, Transport, toApiError } from './transport.js';

export type {
  ConsequenceTier,
  ProposalOperation,
  ProposalOrigin,
  UpdateProposal,
} from './proposal.js';
export { TIER_2_ANCHOR_THRESHOLD, deriveTier, maxTierOf } from './proposal.js';

export type {
  AnchorIdRef,
  AssertionIdRef,
  AssertionKind,
  AssertionProducer,
  AssertionStatus,
  AssertionView,
  CitationModality,
  ConfidenceBand,
  ContradictionView,
  EntityIdRef,
  EntityKind,
  EntityRecord,
  EvidenceHandle,
  EvidenceRegion,
  EvidenceResolver,
  GraphSnapshot,
  HistoryEvent,
  HistoryEventType,
  IndexStatus,
  IslandIdRef,
  IslandRecord,
  TrainedGeometryRecord,
  TrainingQualityRecord,
  LinkState,
  MatchProposalView,
  OccurrenceIdRef,
  OccurrenceKind,
  OccurrenceRecord,
  ReconstructionPointMapRecord,
  RecoveredCameraCalibration,
  RecoveredCameraRecord,
  ReconstructionRungRef,
  ReconstructionSceneMemberRecord,
  ReconstructionSceneRecord,
  RelationView,
  RenderingSubstrate,
  ResolvedEvidence,
} from './read-model.js';
export {
  entityById,
  hasActiveAssertion,
  isNeverSame,
  knowledgeSources,
  occurrencesOf,
  openQuestionCount,
} from './read-model.js';
