import type {
  AnchorIdRef,
  EntityIdRef,
  EntityRecord,
  EvidenceHandle,
  GraphSnapshot,
  IslandIdRef,
  MatchProposalView,
} from '@exulanica/graph-client';
import { hasActiveAssertion, isNeverSame, occurrencesOf } from '@exulanica/graph-client';
import type { ProposalDraft } from './draft.js';
import { draftOperation, makeDraft } from './draft.js';
import type { IdFactory } from './ids.js';
import type { Intent } from './intent.js';
import { assertOfferable } from './tiers.js';
import type { ChoiceSet, OptionKind, TurnOption } from './turn.js';

/**
 * THE ADAPTIVE OPTION POOL (interaction-model.md 4.4).
 *
 * "Each turn is produced by a policy over the entity graph snapshot plus the conversation
 * transcript, in four stages:
 *
 *   1. Select an intent from a small closed set, by priority.          -> intent.ts
 *   2. Build a candidate option pool FROM THE GRAPH.                   -> buildPool, here
 *   3. Prune with hard deterministic rules BEFORE ANY MODEL SEES IT.   -> prune, here
 *   4. Only the phrasing is model-generated."                          -> phrasing.ts
 *
 * And the boundary the whole package exists to hold:
 *
 *   "THE MODEL WRITES WORDS, THE CODE WRITES CONSEQUENCES. A model that hallucinates a sentence
 *   produces an awkward question. A model that could author a proposed update could silently
 *   merge two people. The latter is unacceptable, so the model is never in that path."
 *
 * Because the pool is derived from CURRENT state, options genuinely differ turn to turn. That is
 * not a nicety: it is the difference between a dialogue tree and a form. Nothing here holds a
 * fixed list of buttons.
 */

/** The predicate vocabulary this package writes. `name_is` allows only `user` (epi-3). */
export const PREDICATES = Object.freeze({
  nameIs: 'name_is',
  nameScopeIs: 'name_scope_is',
  relationIs: 'relation_is',
  sameEntityAs: 'same_entity_as',
  notThisClass: 'not_this_class',
  uncertain: 'uncertain',
});

export interface PoolContext {
  readonly snapshot: GraphSnapshot;
  readonly nowMs: number;
  readonly ids: IdFactory;
  readonly subject: EntityRecord;
}

/** Every anchor and island the subject currently occupies. Drives blast radius and tier. */
export interface SubjectFootprint {
  readonly anchorIds: readonly AnchorIdRef[];
  readonly islandIds: readonly IslandIdRef[];
  readonly evidence: readonly EvidenceHandle[];
}

export function subjectFootprint(
  snapshot: GraphSnapshot,
  entityId: EntityIdRef,
): SubjectFootprint {
  const anchorIds: AnchorIdRef[] = [];
  const islands = new Set<IslandIdRef>();
  const evidence: EvidenceHandle[] = [];
  for (const o of occurrencesOf(snapshot, entityId)) {
    anchorIds.push(o.anchorId);
    islands.add(o.islandId);
    for (const e of o.evidence) evidence.push(e);
  }
  return Object.freeze({
    anchorIds: Object.freeze(anchorIds),
    islandIds: Object.freeze([...islands]),
    evidence: Object.freeze(evidence),
  });
}

// ---------------------------------------------------------------------------------------------
// Stage 1 support: which intents this entity can currently carry.
// ---------------------------------------------------------------------------------------------

/** The top-ranked live candidate link for this entity, or null. */
export function topMatchProposal(
  snapshot: GraphSnapshot,
  entityId: EntityIdRef,
): MatchProposalView | null {
  const rank = { high: 0, medium: 1, low: 2 } as const;
  const live = snapshot.matchProposals.filter((m) => m.entityId === entityId);
  if (live.length === 0) return null;
  const sorted = [...live].sort((a, b) => {
    const byConfidence = rank[a.confidence] - rank[b.confidence];
    if (byConfidence !== 0) return byConfidence;
    return a.matchId < b.matchId ? -1 : a.matchId > b.matchId ? 1 : 0;
  });
  return sorted[0] ?? null;
}

/**
 * Which questions this entity could answer, in no particular order. Priority is intent.ts's job.
 *
 * `acknowledge` is deliberately absent: it is the fallback the generator uses when NOTHING is
 * applicable anywhere, not a thing an entity offers.
 */
export function applicableIntents(
  snapshot: GraphSnapshot,
  entity: EntityRecord,
): readonly Intent[] {
  const intents: Intent[] = [];
  if (entity.status === 'merged_away' || entity.status === 'rejected') return intents;

  // A region is an entity too (6.1), but "what is this region called" is not the identity
  // question the Companion is for, and asking it would turn the Atlas into a naming chore.
  if (entity.displayName === null && entity.kind !== 'region' && entity.occurrenceCount > 0) {
    intents.push('resolve_identity');
  }
  if (topMatchProposal(snapshot, entity.entityId) !== null) {
    intents.push('confirm_continuity');
  }
  if (entity.displayName !== null) {
    const scopeUnset = !hasActiveAssertion(entity, PREDICATES.nameScopeIs);
    const spansIslands = entity.islandIds.length > 1;
    if ((scopeUnset && spansIslands) || entity.relations.length === 0) {
      intents.push('enrich_relation');
    }
  }
  if (entity.contradictions.length > 0) intents.push('disambiguate_claim');
  return intents;
}

// ---------------------------------------------------------------------------------------------
// Stage 2: build the candidate pool from the graph.
// ---------------------------------------------------------------------------------------------

/**
 * A candidate option before pruning.
 *
 * `tier` is absent on purpose: it is read off the draft, and a draft's tier is derived from what
 * it touches. There is no field here for a caller to write a tier into.
 */
interface OptionSpec {
  readonly key: string;
  readonly kind: OptionKind;
  readonly textKey: string;
  readonly draft: ProposalDraft | null;
  /** Entities the option acts on. Any deleted one drops the option entirely. */
  readonly targets: readonly EntityIdRef[];
  /** Set when the option would assert two entities are the same. Checked against `never_same`. */
  readonly sameAsPair: readonly [EntityIdRef, EntityIdRef] | null;
  readonly suppressedByRejection: boolean;
}

const spec = (s: Partial<OptionSpec> & Pick<OptionSpec, 'key' | 'kind' | 'textKey'>): OptionSpec =>
  Object.freeze({
    draft: null,
    targets: Object.freeze([]),
    sameAsPair: null,
    suppressedByRejection: false,
    ...s,
  });

export interface RawPool {
  readonly mode: ChoiceSet['mode'];
  readonly specs: readonly OptionSpec[];
  /**
   * The message key for the Companion's utterance on this turn.
   *
   * It belongs to the pool rather than to the intent because one intent can ask two genuinely
   * different questions: `enrich_relation` asks about name scope when the entity has just
   * started spanning islands, and about relationships otherwise. Deriving the utterance from the
   * intent alone would put the wrong sentence above the right buttons.
   */
  readonly utteranceKey: string;
}

function resolveIdentityPool(ctx: PoolContext): RawPool {
  const foot = subjectFootprint(ctx.snapshot, ctx.subject.entityId);
  return {
    // "Single select when the answers are logically exclusive" - these three are.
    mode: 'single',
    utteranceKey: 'utterance.resolveIdentity',
    specs: [
      // No draft: this focuses the free-text affordance. The name arrives as an utterance, is
      // parsed into a draft, and goes through the identical confirmation flow (4.3).
      spec({ key: 'giveName', kind: 'suggested_reply', textKey: 'option.giveName' }),
      spec({
        key: 'alreadyNamed',
        kind: 'suggested_reply',
        textKey: 'option.someoneIAlreadyNamed',
      }),
      spec({
        key: 'notThisKind',
        kind: 'exclusive',
        textKey: `option.notA.${ctx.subject.kind}`,
        targets: [ctx.subject.entityId],
        draft: makeDraft({
          draftId: ctx.ids('draft'),
          origin: 'user_choice',
          rawUtterance: '',
          subjectEntityId: ctx.subject.entityId,
          operations: [
            draftOperation('reject_inference', foot.anchorIds, foot.islandIds, {
              predicateKey: PREDICATES.notThisClass,
              rejectedClass: ctx.subject.kind,
            }),
          ],
          provenanceSummaryKey: 'provenance.userRejectedDetectionClass',
          captureEvidence: foot.evidence,
        }),
      }),
    ],
  };
}

/**
 * Confirm continuity. 4.4 stage 2 names this pool exactly:
 * "{same person, different people, show me both moments} plus the escapes."
 */
function confirmContinuityPool(ctx: PoolContext, match: MatchProposalView): RawPool {
  const foot = subjectFootprint(ctx.snapshot, ctx.subject.entityId);
  const anchorIds = [...new Set([...foot.anchorIds, ...match.anchorIds])];
  const islandIds = [...new Set([...foot.islandIds, ...match.islandIds])];
  const other = match.candidateEntityId;

  return {
    // Logically exclusive, AND the "same person" option spans islands, which makes it tier 2.
    // Either condition alone forces single-select (4.3).
    mode: 'single',
    utteranceKey: 'utterance.confirmContinuity',
    specs: [
      spec({
        key: 'samePerson',
        kind: 'exclusive',
        textKey: 'option.yesSamePerson',
        targets: other === null ? [ctx.subject.entityId] : [ctx.subject.entityId, other],
        sameAsPair: other === null ? null : [ctx.subject.entityId, other],
        suppressedByRejection: match.suppressedByRejection,
        draft: makeDraft({
          draftId: ctx.ids('draft'),
          origin: 'user_choice',
          rawUtterance: '',
          subjectEntityId: ctx.subject.entityId,
          operations: [
            draftOperation('relate', anchorIds, islandIds, {
              predicateKey: PREDICATES.sameEntityAs,
              matchId: match.matchId,
              candidateEntityId: other,
              basisModalities: match.basisModalities,
            }),
          ],
          provenanceSummaryKey: 'provenance.userConfirmedContinuity',
          captureEvidence: match.evidence,
        }),
      }),
      spec({
        key: 'differentPeople',
        kind: 'exclusive',
        textKey: 'option.noDifferentPeople',
        targets: other === null ? [ctx.subject.entityId] : [ctx.subject.entityId, other],
        draft: makeDraft({
          draftId: ctx.ids('draft'),
          origin: 'user_choice',
          rawUtterance: '',
          subjectEntityId: ctx.subject.entityId,
          operations: [
            // A rejection is deliberately trivial to record (id-5: "the user will do this often
            // and it must never feel expensive"). It touches no anchors, so it is tier 1.
            draftOperation('reject_inference', [], [], {
              matchId: match.matchId,
              basisModalities: match.basisModalities,
            }),
          ],
          provenanceSummaryKey: 'provenance.userRejectedContinuity',
          captureEvidence: match.evidence,
        }),
      }),
      // Tier 0: "focus, emphasis, camera movement, opening the index. No proposal, no record."
      spec({ key: 'showBothMoments', kind: 'suggested_reply', textKey: 'option.showBothMoments' }),
    ],
  };
}

/**
 * The name-scope question. This is turn T3 of the worked example in 4.4:
 * "She now links four captures across two regions. Use that as her display name everywhere?"
 *
 * It is reachable only BECAUSE the previous answer changed the graph, which is the entire point
 * of the worked example: the pool is derived from current state, so a new question becomes
 * askable that was not askable a turn ago.
 */
function nameScopePool(ctx: PoolContext): RawPool {
  const foot = subjectFootprint(ctx.snapshot, ctx.subject.entityId);
  const scopeDraft = (scope: 'everywhere' | 'private'): ProposalDraft =>
    makeDraft({
      draftId: ctx.ids('draft'),
      origin: 'user_choice',
      rawUtterance: '',
      subjectEntityId: ctx.subject.entityId,
      operations: [
        draftOperation('name', foot.anchorIds, foot.islandIds, {
          predicateKey: PREDICATES.nameScopeIs,
          scope,
          displayName: ctx.subject.displayName,
        }),
      ],
      provenanceSummaryKey: 'provenance.userSetNameScope',
      captureEvidence: foot.evidence,
    });

  return {
    mode: 'single',
    utteranceKey: 'utterance.nameScope',
    specs: [
      spec({
        key: 'useEverywhere',
        kind: 'exclusive',
        textKey: 'option.useNameEverywhere',
        targets: [ctx.subject.entityId],
        draft: scopeDraft('everywhere'),
      }),
      spec({ key: 'differentName', kind: 'suggested_reply', textKey: 'option.useADifferentName' }),
      spec({
        key: 'keepPrivate',
        kind: 'exclusive',
        textKey: 'option.keepNamePrivate',
        targets: [ctx.subject.entityId],
        draft: scopeDraft('private'),
      }),
    ],
  };
}

/** Relationship gathering. The one genuinely multi-select pool: "multi select for attribute gathering". */
const RELATION_VALUES: readonly string[] = Object.freeze([
  'family',
  'friend',
  'colleague',
  'partner',
  'met_through_someone',
]);

function relationPool(ctx: PoolContext): RawPool {
  return {
    mode: 'multi',
    utteranceKey: 'utterance.relation',
    specs: RELATION_VALUES.map((value) =>
      spec({
        key: `relation.${value}`,
        kind: 'multi_select',
        textKey: `option.relation.${value}`,
        targets: [ctx.subject.entityId],
        draft: makeDraft({
          draftId: ctx.ids('draft'),
          origin: 'user_choice',
          rawUtterance: '',
          subjectEntityId: ctx.subject.entityId,
          // A relation is a claim about the entity, not about any anchor, so it touches no
          // anchors and stays tier 1 - which is what makes it legal in a multi-select set.
          operations: [
            draftOperation('relate', [], [], {
              predicateKey: PREDICATES.relationIs,
              value,
            }),
          ],
          provenanceSummaryKey: 'provenance.userStatedRelation',
        }),
      }),
    ),
  };
}

/**
 * A contradiction (5.4). "A system inference that contradicts a user assertion is recorded as a
 * contradiction and surfaced as a question, NEVER APPLIED."
 */
function disambiguatePool(ctx: PoolContext): RawPool {
  const contradiction = ctx.subject.contradictions[0];
  /* c8 ignore next */
  if (contradiction === undefined) return { mode: 'single', specs: [], utteranceKey: 'utterance.acknowledge' };
  return {
    mode: 'single',
    utteranceKey: 'utterance.disambiguate',
    specs: [
      spec({
        key: 'keepMine',
        kind: 'exclusive',
        textKey: 'option.keepWhatIToldYou',
        targets: [ctx.subject.entityId],
        draft: makeDraft({
          draftId: ctx.ids('draft'),
          origin: 'user_choice',
          rawUtterance: '',
          subjectEntityId: ctx.subject.entityId,
          operations: [
            draftOperation('reject_inference', [], [], {
              contradictionId: contradiction.contradictionId,
              rejects: contradiction.otherAssertionId,
            }),
          ],
          provenanceSummaryKey: 'provenance.userKeptTheirOwnAssertion',
        }),
      }),
      spec({
        key: 'acceptOther',
        kind: 'exclusive',
        textKey: 'option.acceptTheOtherReading',
        targets: [ctx.subject.entityId],
        draft: makeDraft({
          draftId: ctx.ids('draft'),
          origin: 'user_choice',
          rawUtterance: '',
          subjectEntityId: ctx.subject.entityId,
          operations: [
            draftOperation('note', [], [], {
              contradictionId: contradiction.contradictionId,
              supersedes: contradiction.userAssertionId,
            }),
          ],
          provenanceSummaryKey: 'provenance.userSupersededTheirOwnAssertion',
        }),
      }),
      spec({ key: 'showEvidence', kind: 'suggested_reply', textKey: 'option.showMeTheEvidence' }),
    ],
  };
}

export function buildPool(intent: Intent, ctx: PoolContext): RawPool {
  switch (intent) {
    case 'resolve_identity':
      return resolveIdentityPool(ctx);
    case 'confirm_continuity': {
      const match = topMatchProposal(ctx.snapshot, ctx.subject.entityId);
      /* c8 ignore next */
      if (match === null) return { mode: 'single', specs: [], utteranceKey: 'utterance.acknowledge' };
      return confirmContinuityPool(ctx, match);
    }
    case 'enrich_relation': {
      const scopeUnset = !hasActiveAssertion(ctx.subject, PREDICATES.nameScopeIs);
      return scopeUnset && ctx.subject.islandIds.length > 1
        ? nameScopePool(ctx)
        : relationPool(ctx);
    }
    case 'disambiguate_claim':
      return disambiguatePool(ctx);
    case 'acknowledge':
      return { mode: 'single', specs: [], utteranceKey: 'utterance.acknowledge' };
  }
}

// ---------------------------------------------------------------------------------------------
// Stage 3: prune with hard deterministic rules, BEFORE any model sees the pool.
// ---------------------------------------------------------------------------------------------

/**
 * "Never offer an option targeting a deleted entity. Never offer merge for two clusters already
 * asserted distinct. WHERE THE REASON IS INFORMATIVE, MARK THE OPTION UNAVAILABLE WITH A REASON
 * RATHER THAN HIDING IT, following the availability semantics above."
 *
 * The two rules land differently on purpose, and the difference is what "informative" means:
 *
 *   DELETED ENTITY -> dropped. The user deleted it. Showing them a greyed-out row that says "you
 *   deleted this" re-surfaces the thing they removed, which is the opposite of what deletion is
 *   for, and 7.3 reserves `hidden` for exactly this content.
 *
 *   ALREADY DISTINCT, or SUPPRESSED BY A REJECTION -> kept, unavailable, with a reason. Here the
 *   reason IS the information: it tells the user the system remembers their earlier decision,
 *   which is the difference between a system that learned and one that forgot.
 */
export function prune(
  intent: Intent,
  ctx: PoolContext,
  pool: RawPool,
): readonly TurnOption[] {
  const deleted = new Set(ctx.snapshot.deletedEntityIds);
  const options: TurnOption[] = [];

  for (const s of pool.specs) {
    if (s.targets.some((t) => deleted.has(t))) continue;

    let available = true;
    let reason: string | null = null;

    if (s.sameAsPair !== null && isNeverSame(ctx.snapshot, s.sameAsPair[0], s.sameAsPair[1])) {
      available = false;
      reason = 'unavailable.alreadyAssertedDistinct';
    } else if (s.suppressedByRejection) {
      available = false;
      reason = 'unavailable.rejectedOnTheSameEvidence';
    }

    const tier = s.draft?.maxTier ?? 0;
    // Tier 3 may never reach the dialogue surface, in any phrasing (5.3). Throws, not filters:
    // a tier 3 option in a dialogue pool is a bug in the builder, not a runtime condition.
    //
    // IT CANNOT REFUSE ANYTHING TODAY, and that is a fact about this file rather than about the
    // guard. `assertOfferable(_, 'dialogue')` refuses tier 3 only, tiers 0 to 2 all being
    // offerable from here; `deriveTier` returns 3 only for a `delete`; and every
    // `draftOperation` built below is `name`, `note`, `reject_inference` or `relate`. So it
    // becomes live the day a spec here builds a delete, which is exactly the day it is wanted.
    // Measured 2026-09-19: deleting this line left all 2846 tests in `web/` passing, and
    // replacing it with an unconditional throw failed 29, so the line runs constantly and has
    // never had anything to refuse.
    assertOfferable(tier, 'dialogue');

    options.push(
      Object.freeze({
        // Deterministic and stable across regenerations of the same question, so a test (and a
        // keyboard shortcut, and a telemetry event) can name an option.
        optionId: `${intent}:${s.key}`,
        kind: s.kind,
        textKey: s.textKey,
        phrasing: null,
        available,
        unavailableReasonKey: reason,
        tier,
        draft: s.draft,
        escape: null,
      }),
    );
  }

  return Object.freeze(options);
}
