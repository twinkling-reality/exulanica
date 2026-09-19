import type { ConsequenceTier } from '@exulanica/graph-client';

/**
 * CONSEQUENCE TIERS (interaction-model.md 5.3), as an enforced policy table rather than four
 * paragraphs of prose that each confirmation surface reimplements slightly differently.
 *
 * "Different consequences warrant different confirmation weight. Naming a person is not merging
 * two people, and merging is not deleting."
 *
 * The tier itself is DERIVED in graph-client (`deriveTier`), not declared here, so an operation
 * cannot be mislabelled tier 1 to skip the blast radius preview. This file answers the next
 * question: given a tier, what is the confirmation surface obliged to do, and where is the
 * operation allowed to be offered at all.
 */

export type ConfirmationSurface = 'dialogue' | 'world_index';

export type ConfirmationControls =
  /** Tier 0: no proposal, no record. */
  | 'none'
  /** Tier 1: a single Save, commits immediately, short undo toast. No typing. */
  | 'single_save'
  /** Tier 2: two distinct controls, cancel and confirm, confirm enabled after a delay. */
  | 'cancel_and_confirm'
  /** Tier 3: typed confirmation of the entity's display name. */
  | 'typed_name';

export interface TierPolicy {
  readonly tier: ConsequenceTier;
  readonly controls: ConfirmationControls;
  /** Tier 0 is "focus, emphasis, camera movement, opening the index": no proposal, no record. */
  readonly producesProposal: boolean;
  /** "A stated blast radius in counts: how many anchors, in which regions." */
  readonly requiresBlastRadius: boolean;
  /** "A live preview in the Atlas behind the panel", via the manifest preview slot (7.2). */
  readonly requiresLivePreview: boolean;
  /**
   * "the confirm control deliberately not under the cursor's resting position and enabled after
   * a short delay, to defeat double-click carry-through from the option that opened the panel".
   *
   * The document says "a short delay" and does not give a number. 600 ms is a DECISION, chosen
   * to sit above a double-click interval (typically 500 ms) and below the point where a
   * deliberate user notices a dead control. It is here, once, so tuning it is one edit.
   */
  readonly confirmEnabledAfterMs: number;
  readonly requiresTypedDisplayName: boolean;
  /**
   * Tier 3 only: "an explicit statement, rendered EVERY SINGLE TIME, that original media is not
   * deleted by this action". The retention guarantee is restated at the exact moment the user is
   * most likely to doubt it.
   */
  readonly requiresMediaRetentionStatement: boolean;
  /** Tier 3 only: "how many existing answers cite this entity and will lose their citation." */
  readonly requiresCitationLossCount: boolean;
  readonly undoToast: boolean;
  /**
   * Where the operation may be OFFERED. Tier 3: "Never offered as a dialogue option and never
   * offered by Companion initiative. Reachable only from the World Index entity detail view."
   */
  readonly offerableFrom: readonly ConfirmationSurface[];
  /** 5.5: spontaneous initiative is "never for a tier 3 operation". */
  readonly offerableByInitiative: boolean;
  /**
   * 6.3: "Batch operations are permitted for tier 1 only. Prohibited at tier 2 and above,
   * because a blast radius cannot be previewed meaningfully for a set."
   */
  readonly batchable: boolean;
  /** Tier 3 is out of the MVP cut. The rule stands regardless (5.3). */
  readonly inMvp: boolean;
}

export const CONFIRM_DELAY_MS = 600;

const POLICIES: Readonly<Record<ConsequenceTier, TierPolicy>> = Object.freeze({
  0: Object.freeze({
    tier: 0,
    controls: 'none',
    producesProposal: false,
    requiresBlastRadius: false,
    requiresLivePreview: false,
    confirmEnabledAfterMs: 0,
    requiresTypedDisplayName: false,
    requiresMediaRetentionStatement: false,
    requiresCitationLossCount: false,
    undoToast: false,
    offerableFrom: Object.freeze<ConfirmationSurface[]>(['dialogue', 'world_index']),
    offerableByInitiative: true,
    batchable: true,
    inMvp: true,
  }),
  1: Object.freeze({
    tier: 1,
    controls: 'single_save',
    producesProposal: true,
    requiresBlastRadius: false,
    requiresLivePreview: false,
    confirmEnabledAfterMs: 0,
    requiresTypedDisplayName: false,
    requiresMediaRetentionStatement: false,
    requiresCitationLossCount: false,
    undoToast: true,
    offerableFrom: Object.freeze<ConfirmationSurface[]>(['dialogue', 'world_index']),
    offerableByInitiative: true,
    batchable: true,
    inMvp: true,
  }),
  2: Object.freeze({
    tier: 2,
    controls: 'cancel_and_confirm',
    producesProposal: true,
    requiresBlastRadius: true,
    requiresLivePreview: true,
    confirmEnabledAfterMs: CONFIRM_DELAY_MS,
    requiresTypedDisplayName: false,
    requiresMediaRetentionStatement: false,
    requiresCitationLossCount: false,
    undoToast: false,
    offerableFrom: Object.freeze<ConfirmationSurface[]>(['dialogue', 'world_index']),
    offerableByInitiative: true,
    batchable: false,
    inMvp: true,
  }),
  3: Object.freeze({
    tier: 3,
    controls: 'typed_name',
    producesProposal: true,
    requiresBlastRadius: true,
    requiresLivePreview: false,
    confirmEnabledAfterMs: CONFIRM_DELAY_MS,
    requiresTypedDisplayName: true,
    requiresMediaRetentionStatement: true,
    requiresCitationLossCount: true,
    undoToast: false,
    // The whole point of the tier. Not reachable from the dialogue panel, in any phrasing.
    offerableFrom: Object.freeze<ConfirmationSurface[]>(['world_index']),
    offerableByInitiative: false,
    batchable: false,
    inMvp: false,
  }),
} as const);

export function tierPolicy(tier: ConsequenceTier): TierPolicy {
  const p = POLICIES[tier];
  /* c8 ignore next */
  if (p === undefined) throw new RangeError(`unknown consequence tier: ${String(tier)}`);
  return p;
}

export class TierPolicyError extends Error {
  constructor(
    message: string,
    readonly tier: ConsequenceTier,
  ) {
    super(message);
    this.name = 'TierPolicyError';
  }
}

/**
 * The gate that keeps deletion out of the conversation.
 *
 * 5.3: "The Companion may never propose a deletion, in any phrasing, under any circumstance."
 * That sentence is only true if something throws, so this throws. It is called from TWO places:
 * the option pool builder (`prune`) and turn validation (`validateTurn`).
 *
 * It said three until 2026-09-19, naming proposal drafting and the initiative gate, and neither
 * of those calls it: the initiative gate reads `tierPolicy(...).offerableByInitiative` and
 * drafting derives a tier without consulting a surface at all. So the count was wrong, the two
 * places named were wrong, and the one place that does call it was not named. Counted across
 * every package's `src`, and now pinned by 'states its own call sites' in the tests, because a
 * justification that names a number is a second claim and this one drifted with nothing
 * watching it.
 */
export function assertOfferable(tier: ConsequenceTier, surface: ConfirmationSurface): void {
  const policy = tierPolicy(tier);
  if (!policy.offerableFrom.includes(surface)) {
    throw new TierPolicyError(
      `tier ${tier} operations may not be offered from the ${surface} surface ` +
        `(offerable from: ${policy.offerableFrom.join(', ')})`,
      tier,
    );
  }
}

/**
 * 4.3: "NEVER MIX A DESTRUCTIVE OR TIER 2 OPTION INTO A MULTI-SELECT SET, because a blast-radius
 * preview cannot be rendered for a set."
 */
export function assertMultiSelectable(tier: ConsequenceTier): void {
  if (tier >= 2) {
    throw new TierPolicyError(
      `tier ${tier} may not appear in a multi-select set: a blast radius cannot be previewed ` +
        `for a set, and this is single-select or nothing`,
      tier,
    );
  }
}

/** 6.3: batch operations are tier 1 only. */
export function assertBatchable(tier: ConsequenceTier): void {
  if (!tierPolicy(tier).batchable) {
    throw new TierPolicyError(`tier ${tier} operations may not be batched`, tier);
  }
}

/**
 * What the confirmation surface reports back before it is allowed to commit.
 *
 * This exists so that "tier 2 requires a live preview" is checkable rather than aspirational.
 * The surface says what it actually did; `unmetRequirements` says whether that was enough.
 */
export interface ConfirmationAcknowledgement {
  readonly surface: ConfirmationSurface;
  /** Milliseconds the confirmation has been on screen. Compared to `confirmEnabledAfterMs`. */
  readonly openForMs: number;
  /** True when the blast radius counts were rendered. */
  readonly blastRadiusShown: boolean;
  /** True when a preview manifest was assigned to the preview slot and applied. */
  readonly livePreviewShown: boolean;
  /** What the user typed, for tier 3. */
  readonly typedDisplayName: string | null;
  readonly mediaRetentionStatementShown: boolean;
  readonly citationLossCountShown: boolean;
}

/**
 * The requirement keys a surface failed to meet. Empty means the commit may proceed.
 *
 * Returning keys rather than throwing is deliberate: a half-built confirmation panel should be
 * able to ask "what am I still missing" and render the answer, and the caller that ignores the
 * answer still cannot commit, because `graph-client`'s `ProposalGate` is a second, independent
 * check on the write itself.
 */
export function unmetRequirements(
  tier: ConsequenceTier,
  ack: ConfirmationAcknowledgement,
  expectedDisplayName: string | null,
): readonly string[] {
  const policy = tierPolicy(tier);
  const unmet: string[] = [];

  if (!policy.offerableFrom.includes(ack.surface)) unmet.push('surface.notPermitted');
  if (!policy.inMvp) unmet.push('tier.outOfMvpCut');
  if (policy.requiresBlastRadius && !ack.blastRadiusShown) unmet.push('blastRadius.notShown');
  if (policy.requiresLivePreview && !ack.livePreviewShown) unmet.push('livePreview.notShown');
  if (ack.openForMs < policy.confirmEnabledAfterMs) unmet.push('confirm.tooSoon');
  if (policy.requiresTypedDisplayName) {
    if (expectedDisplayName === null || ack.typedDisplayName !== expectedDisplayName) {
      unmet.push('typedName.mismatch');
    }
  }
  if (policy.requiresMediaRetentionStatement && !ack.mediaRetentionStatementShown) {
    unmet.push('mediaRetention.notStated');
  }
  if (policy.requiresCitationLossCount && !ack.citationLossCountShown) {
    unmet.push('citationLoss.notStated');
  }
  return unmet;
}
