/**
 * @exulanica/companion-runtime
 *
 * Turn generation, option pool construction, proposal drafting, escape handling and the
 * initiative gate. Forbidden: renderer, React, DOM (architecture-overview.md 1.1).
 *
 * The DOM ban is enforced by `lib: ["ES2022"]` in this package's tsconfig; the renderer and React
 * bans by `.dependency-cruiser.cjs`. The package stays runnable headless in a test, because the
 * option pool is the thing most worth testing and a canvas would make that expensive.
 *
 * THE SAFETY BOUNDARY THIS PACKAGE EXISTS TO HOLD (interaction-model.md 4.4): the model writes
 * words, the code writes consequences. The id, kind, consequence tier and proposed update of
 * every option are constructed by deterministic code. Only the phrasing is model-generated, and
 * `phrasing.ts` is the entire surface over which a model may touch a turn.
 *
 * Reading order, if you are new to this package:
 *   tiers.ts       what each consequence weighs, and where it may be offered
 *   turn.ts        the turn and option shapes, and the choice-mode rules
 *   pool.ts        stages 2 and 3: build from the graph, prune deterministically
 *   generator.ts   stage 1 and assembly
 *   session.ts     the single write path
 */

export type { ConfirmationControls, ConfirmationSurface, TierPolicy, ConfirmationAcknowledgement } from './tiers.js';
export {
  CONFIRM_DELAY_MS,
  TierPolicyError,
  assertBatchable,
  assertMultiSelectable,
  assertOfferable,
  tierPolicy,
  unmetRequirements,
} from './tiers.js';

export type { IdFactory } from './ids.js';
export { sequentialIds } from './ids.js';

export type { DraftOp, DraftOperation, DraftInput, ProposalDraft } from './draft.js';
export { affectedAnchors, affectedIslands, draftOperation, finalizeDraft, makeDraft } from './draft.js';

export type { Intent } from './intent.js';
export { INTENT_PRIORITY, intentRank } from './intent.js';

export type {
  ChoiceMode,
  ChoiceSet,
  EscapeKind,
  OptionKind,
  Turn,
  TurnOption,
} from './turn.js';
export { TurnValidationError, allOptions, findOption, validateTurn } from './turn.js';

export { ESCAPE_ORDER, escapeDraft, escapeOption, escapeOptions } from './escapes.js';

export type {
  AbstentionCode,
  AnswerOrigin,
  CompanionMemory,
  EscapeRecord,
  PersistedAnswer,
  PersistedCitation,
  PersistedEscape,
  PersistedMemory,
  QuestionKey,
  SuppressionReason,
  TranscriptEntry,
} from './memory.js';
export {
  DAY_MS,
  EMPTY_MEMORY,
  EMPTY_PERSISTED_MEMORY,
  NOT_SURE_COOLDOWN_MS,
  SKIP_COOLDOWN_MS,
  hardSuppression,
  latestAnswer,
  memoryFromPersisted,
  priorityPenalty,
  questionKey,
  recordAsked,
  recordEscape,
  recordSpontaneousSpeech,
  recordTranscript,
  standingAnswers,
} from './memory.js';

export type { RankedEntity } from './value.js';
export { VALUE_WEIGHTS, entityValue, rankByValue } from './value.js';

export type {
  AmbientAnchorState,
  InitiativeContext,
  InitiativeDecision,
  InitiativeOffer,
  InitiativeRefusal,
  InitiativeRefused,
  InitiativeSetting,
  OpenQuestionIndicator,
} from './initiative.js';
export {
  BASE_INITIATIVE_COOLDOWN_MS,
  HOUR_MS,
  MAX_SPEECH_PER_HOUR,
  MAX_SPEECH_PER_SESSION,
  OFFER_DISSOLVE_MS,
  SESSION_WARMUP_MS,
  SPONTANEOUS_INITIATIVE_IN_MVP,
  ambientAnchorState,
  mayInitiate,
  openQuestionIndicator,
} from './initiative.js';

export type { PoolContext, RawPool, SubjectFootprint } from './pool.js';
export { PREDICATES, applicableIntents, buildPool, prune, subjectFootprint, topMatchProposal } from './pool.js';

export type { PhrasingRequest, PhrasingRequestOption, PhrasingResponse } from './phrasing.js';
export { PhrasingError, applyPhrasing, phrasingRequest } from './phrasing.js';

export type { ParseDraftContext, UtteranceParse } from './parse.js';
export { draftFromParse, parseUtterance } from './parse.js';

export type {
  BandId,
  BandRow,
  BlastRadius,
  ConfirmationBand,
  ConfirmationInput,
  ConfirmationSummary,
  EvidenceChip,
  ExternalBlock,
  ProvenancePanel,
} from './confirmation.js';
export { BAND_ORDER, buildConfirmation, buildProvenancePanel } from './confirmation.js';

export type { GenerateInput, QuestionCandidate } from './generator.js';
export { MAX_TURN_EVIDENCE, generateTurn, rankQuestions, selectQuestion } from './generator.js';

export type { CompanionSessionOptions, SelectionOutcome } from './session.js';
export { CompanionSession, ConfirmationRefusedError } from './session.js';

export {
  JULIE_T2,
  JULIE_T3,
  MOCK_ISLANDS,
  MOCK_MATCHES,
  MOCK_NOW_MS,
  SNAPSHOT_T1,
  SNAPSHOT_T2,
  SNAPSHOT_T3,
  withMatchProposals,
} from './mock.js';
