import type {
  EntityIdRef,
  EntityRecord,
  EvidenceHandle,
  GraphSnapshot,
  UpdateProposal,
} from '@exulanica/graph-client';
import type { CommitResult, ProposalGate } from '@exulanica/graph-client/mutations';
import type { ConfirmationSummary } from './confirmation.js';
import { buildConfirmation } from './confirmation.js';
import type { DraftOperation, ProposalDraft } from './draft.js';
import { finalizeDraft, makeDraft } from './draft.js';
import { escapeDraft } from './escapes.js';
import type { IdFactory } from './ids.js';
import { sequentialIds } from './ids.js';
import type {
  CompanionMemory,
  PersistedAnswer,
  PersistedMemory,
  TranscriptEntry,
} from './memory.js';
import {
  EMPTY_MEMORY,
  memoryFromPersisted,
  recordAsked,
  recordEscape,
  recordTranscript,
  standingAnswers,
} from './memory.js';
import { generateTurn } from './generator.js';
import { subjectFootprint } from './pool.js';
import { draftFromParse, parseUtterance } from './parse.js';
import type { ConfirmationAcknowledgement, ConfirmationSurface } from './tiers.js';
import { assertMultiSelectable, unmetRequirements } from './tiers.js';
import type { Turn } from './turn.js';
import { findOption } from './turn.js';

/**
 * THE SESSION: turn -> selection -> draft -> staged proposal -> confirmation -> commit.
 *
 * The invariant this class exists to make unavoidable (interaction-model.md 5.1):
 *
 *   "NO FREE-TEXT ANSWER AND NO CHOICE EVER MUTATES THE GRAPH DIRECTLY. Every path, including a
 *   single click on 'Yes, the same person', produces an update proposal, which is rendered, and
 *   only an explicit confirmation commits it."
 *
 * There is therefore exactly one method on this class that can reach the graph (`commit`), it
 * takes a proposal id that must already be in the gate's pending set, and it refuses when the
 * tier's confirmation requirements are unmet. Behind it sits graph-client's `ProposalGate`,
 * which refuses again on its own terms. Two independent checks, because the guarantee is worth
 * more than the duplication.
 *
 * `adoptPersistedMemory` is the one method added since, and it is worth saying what it is not.
 * Durable memory is what the person has already told this Companion to leave alone; it decides
 * which questions may be ASKED and it never decides what may be written. It reaches `#memory`
 * and nothing else, and there is no path from a stored answer to a `ProposalDraft` anywhere in
 * this package.
 */

export type SelectionOutcome =
  /** The choice carried no consequence (tier 0). The conversation moved on. */
  | { readonly kind: 'advanced'; readonly turn: Turn }
  /** A proposal is staged and rendered. Nothing has been written. */
  | {
      readonly kind: 'awaiting_confirmation';
      readonly proposal: UpdateProposal;
      readonly confirmation: ConfirmationSummary;
    }
  /** The selection was not permitted. `reasonKey` is renderable. */
  | { readonly kind: 'refused'; readonly reasonKey: string };

export class ConfirmationRefusedError extends Error {
  constructor(
    message: string,
    readonly unmet: readonly string[],
  ) {
    super(message);
    this.name = 'ConfirmationRefusedError';
  }
}

interface PendingConfirmation {
  readonly proposal: UpdateProposal;
  readonly confirmation: ConfirmationSummary;
  readonly entity: EntityRecord | null;
}

export interface CompanionSessionOptions {
  readonly snapshot: GraphSnapshot;
  readonly gate: ProposalGate;
  readonly ids?: IdFactory;
  readonly memory?: CompanionMemory;
  /**
   * Durable memory to open with, and the instant to fold it against.
   *
   * One field carrying both rather than two fields beside each other, because a `PersistedMemory`
   * with no instant is not a thing that can be folded: `memoryFromPersisted` decides which
   * cooldowns are still in force, and the caller's clock is the only honest source for that.
   * Pairing them here makes the missing half a type error instead of a silently wrong window.
   *
   * Optional because a session is often opened before its memory has arrived. The app's
   * composition root builds the engine while `GET /graph` is the only thing it has waited for,
   * and hands the durable memory over later through `adoptPersistedMemory`.
   */
  readonly persisted?: { readonly memory: PersistedMemory; readonly nowMs: number };
  /** Which mount point this session's confirmations render in. Tier 3 is refused in `dialogue`. */
  readonly surface?: ConfirmationSurface;
  readonly anchorForEvidence?: ReadonlyMap<EvidenceHandle, string>;
}

export class CompanionSession {
  #snapshot: GraphSnapshot;
  #memory: CompanionMemory;
  #turn: Turn | null = null;
  /**
   * What this person has already been told, newest first, with corrections resolved.
   *
   * Held beside the memory rather than inside it because it is not an input to a turn. Nothing in
   * `generateTurn`, `hardSuppression` or the value function reads an answer: what suppresses a
   * question is an ESCAPE, and mixing the two would put stored prose one field away from the
   * policy that decides what the Companion says next.
   */
  #remembered: readonly PersistedAnswer[] = Object.freeze([]);
  readonly #gate: ProposalGate;
  readonly #ids: IdFactory;
  readonly #surface: ConfirmationSurface;
  readonly #anchorForEvidence: ReadonlyMap<EvidenceHandle, string>;
  readonly #pending = new Map<string, PendingConfirmation>();

  constructor(options: CompanionSessionOptions) {
    this.#snapshot = options.snapshot;
    this.#gate = options.gate;
    this.#ids = options.ids ?? sequentialIds();
    this.#memory = options.memory ?? EMPTY_MEMORY;
    this.#surface = options.surface ?? 'dialogue';
    this.#anchorForEvidence = options.anchorForEvidence ?? new Map<EvidenceHandle, string>();
    if (options.persisted !== undefined) {
      this.adoptPersistedMemory(options.persisted.memory, options.persisted.nowMs);
    }
  }

  get snapshot(): GraphSnapshot {
    return this.#snapshot;
  }

  get memory(): CompanionMemory {
    return this.#memory;
  }

  /** Every answer that still stands, newest first. A correction hides what it corrected. */
  get rememberedAnswers(): readonly PersistedAnswer[] {
    return this.#remembered;
  }

  /** The last thing this person was told, or null. Exposed so a surface can put it back. */
  get lastAnswer(): PersistedAnswer | null {
    return this.#remembered[0] ?? null;
  }

  /**
   * Take on durable memory that arrived after the session opened.
   *
   * **THIS IS NOT A WRITE PATH AND CANNOT BECOME ONE.** It touches `#memory` and `#remembered`
   * and nothing else: not `#gate`, not `#pending`, not `#snapshot`. Nothing it stores is read by
   * `#stage`, and no value it accepts is a `ProposalDraft` or reaches one, so the invariant at
   * the top of this file is untouched by it. A method rather than construction only, because the
   * app builds this engine from `GET /graph` in `session.ts` and the memory is a second request
   * that has not landed yet; refusing a method would have meant either blocking the world on the
   * memory read or building the engine twice.
   *
   * **The session's own half of the memory is kept.** The load is asynchronous and can land after
   * a turn has already been delivered, so taking the folded object wholesale would forget what
   * this sitting has already asked and the generator would re-ask it on the next advance. The
   * durable fields come from the fold and the session-scoped fields stay where they were, which
   * is the same line `memoryFromPersisted` draws and the reason it is drawn in one place.
   */
  adoptPersistedMemory(persisted: PersistedMemory, nowMs: number): void {
    const durable = memoryFromPersisted(persisted, nowMs);
    this.#memory = Object.freeze({
      ...durable,
      dismissed: this.#memory.dismissed,
      askedThisSession: this.#memory.askedThisSession,
      spokeAtMs: this.#memory.spokeAtMs,
      transcript: this.#memory.transcript,
      // The larger of the two rather than their product. In the ordinary case this session has
      // taken no escape yet and its multiplier is 1, so the fold's value simply wins; if a Skip
      // HAS been taken here and the same row also came back from the store, multiplying would
      // count one Skip twice and charge the person double for saying one thing once.
      initiativeCooldownMultiplier: Math.max(
        durable.initiativeCooldownMultiplier,
        this.#memory.initiativeCooldownMultiplier,
      ),
    });
    this.#remembered = standingAnswers(persisted);
  }

  get currentTurn(): Turn | null {
    return this.#turn;
  }

  /** Proposals staged and rendered but not committed. Cancelling one restores instantly. */
  get pendingProposalIds(): readonly string[] {
    return [...this.#pending.keys()];
  }

  /**
   * The graph moved underneath us.
   *
   * Not merged into `commit`, because the graph also moves for reasons this session did not
   * cause: another surface committed, a capture finished forming, a background job landed. Any
   * staged proposal computed against the old version is now describing a consequence that is no
   * longer the consequence, so it is dropped rather than silently re-aimed (5.1).
   */
  observeSnapshot(snapshot: GraphSnapshot): void {
    this.#snapshot = snapshot;
    for (const [id, pending] of [...this.#pending]) {
      if (pending.proposal.expiresAtStateVersion < snapshot.stateVersion) {
        this.#pending.delete(id);
        this.#gate.discard(id);
      }
    }
  }

  /** Generate and deliver the next turn. */
  advance(nowMs: number, focusEntityId?: EntityIdRef | null): Turn {
    const turn = generateTurn({
      snapshot: this.#snapshot,
      memory: this.#memory,
      nowMs,
      ids: this.#ids,
      ...(focusEntityId === undefined ? {} : { focusEntityId }),
    });
    // Recorded at DELIVERY, not at generation, so that re-rendering the same turn does not
    // consume the question and skip to the next one.
    this.#memory = recordAsked(this.#memory, turn.intent, turn.subjectEntityId);
    this.#turn = turn;
    return turn;
  }

  #entity(entityId: EntityIdRef | null): EntityRecord | null {
    if (entityId === null) return null;
    return this.#snapshot.entities.find((e) => e.entityId === entityId) ?? null;
  }

  #transcribe(entry: TranscriptEntry): void {
    this.#memory = recordTranscript(this.#memory, entry);
  }

  /** Stage a draft: build its proposal, render its confirmation, write nothing. */
  #stage(draft: ProposalDraft, turn: Turn): SelectionOutcome {
    const entity = this.#entity(draft.subjectEntityId);
    if (entity === null) {
      return { kind: 'refused', reasonKey: 'refused.subjectMissing' };
    }

    const proposal = finalizeDraft(
      draft,
      this.#ids('proposal'),
      turn.turnId,
      this.#snapshot.stateVersion,
    );
    const confirmation = buildConfirmation({
      draft,
      entity,
      surface: this.#surface,
      anchorForEvidence: this.#anchorForEvidence,
    });

    if (!confirmation.permittedHere) {
      return { kind: 'refused', reasonKey: 'refused.tierNotOfferableHere' };
    }

    this.#gate.stage(proposal);
    this.#pending.set(proposal.proposalId, { proposal, confirmation, entity });
    return { kind: 'awaiting_confirmation', proposal, confirmation };
  }

  /**
   * Select one option on the current turn.
   *
   * Escapes are handled here rather than in a separate method because 4.3 puts them in the same
   * option set as everything else, and a surface that had to route them differently would be one
   * refactor away from forgetting to offer them.
   */
  select(optionId: string, nowMs: number): SelectionOutcome {
    const turn = this.#turn;
    if (turn === null) return { kind: 'refused', reasonKey: 'refused.noTurn' };

    const option = findOption(turn, optionId);
    if (option === null) return { kind: 'refused', reasonKey: 'refused.unknownOption' };
    if (!option.available) {
      return { kind: 'refused', reasonKey: option.unavailableReasonKey ?? 'refused.unavailable' };
    }
    if (option.kind === 'multi_select') {
      // Multi mode has an explicit submit. Committing one checkbox on click would be exactly the
      // "renders a fixed form" failure the design is written against.
      return { kind: 'refused', reasonKey: 'refused.useSubmit' };
    }

    this.#transcribe({
      turnId: turn.turnId,
      intent: turn.intent,
      subjectEntityId: turn.subjectEntityId,
      optionId,
      escape: option.escape,
      rawUtterance: null,
      atMs: nowMs,
      stateVersion: this.#snapshot.stateVersion,
    });

    if (option.escape !== null) {
      this.#memory = recordEscape(this.#memory, {
        escape: option.escape,
        intent: turn.intent,
        entityId: turn.subjectEntityId,
        atMs: nowMs,
      });
      const draft = escapeDraft(
        option.escape,
        turn.intent,
        turn.subjectEntityId,
        '',
        this.#ids,
      );
      if (draft === null) return { kind: 'advanced', turn: this.advance(nowMs) };
      return this.#stage(draft, turn);
    }

    if (option.draft === null) {
      // Tier 0: "focus, emphasis, camera movement, opening the index. No proposal, no record."
      return { kind: 'advanced', turn: this.advance(nowMs) };
    }

    return this.#stage(option.draft, turn);
  }

  /**
   * Submit a multi-select set.
   *
   * The selected options are merged into ONE draft, so the user confirms one thing once. Every
   * option in the set is re-checked against `assertMultiSelectable`: the pool already refused to
   * build a tier 2 option into a multi set, and this is the second place that has to be true.
   */
  submit(optionIds: readonly string[], nowMs: number): SelectionOutcome {
    const turn = this.#turn;
    if (turn === null) return { kind: 'refused', reasonKey: 'refused.noTurn' };
    if (turn.choiceSet === null || turn.choiceSet.mode !== 'multi') {
      return { kind: 'refused', reasonKey: 'refused.notAMultiSet' };
    }
    if (optionIds.length === 0) return { kind: 'refused', reasonKey: 'refused.nothingSelected' };

    const operations: DraftOperation[] = [];
    for (const id of optionIds) {
      const option = findOption(turn, id);
      if (option === null) return { kind: 'refused', reasonKey: 'refused.unknownOption' };
      if (!option.available) {
        return { kind: 'refused', reasonKey: option.unavailableReasonKey ?? 'refused.unavailable' };
      }
      assertMultiSelectable(option.tier);
      if (option.draft !== null) operations.push(...option.draft.operations);
    }
    if (operations.length === 0) return { kind: 'advanced', turn: this.advance(nowMs) };

    this.#transcribe({
      turnId: turn.turnId,
      intent: turn.intent,
      subjectEntityId: turn.subjectEntityId,
      optionId: optionIds.join('+'),
      escape: null,
      rawUtterance: null,
      atMs: nowMs,
      stateVersion: this.#snapshot.stateVersion,
    });

    const draft = makeDraft({
      draftId: this.#ids('draft'),
      origin: 'user_choice',
      rawUtterance: '',
      subjectEntityId: turn.subjectEntityId,
      operations,
      provenanceSummaryKey: 'provenance.userSelectedAttributes',
    });
    return this.#stage(draft, turn);
  }

  /**
   * A free-text answer.
   *
   * 4.3: "It is parsed into the same update proposal draft that a choice would produce and goes
   * through the IDENTICAL confirmation flow." Identical means identical: the same `#stage`, the
   * same `buildConfirmation`, the same gate.
   */
  say(text: string, nowMs: number): SelectionOutcome {
    const turn = this.#turn;
    if (turn === null) return { kind: 'refused', reasonKey: 'refused.noTurn' };
    if (turn.subjectEntityId === null) {
      return { kind: 'refused', reasonKey: 'refused.noSubject' };
    }

    this.#transcribe({
      turnId: turn.turnId,
      intent: turn.intent,
      subjectEntityId: turn.subjectEntityId,
      optionId: null,
      escape: null,
      rawUtterance: text,
      atMs: nowMs,
      stateVersion: this.#snapshot.stateVersion,
    });

    const footprint = subjectFootprint(this.#snapshot, turn.subjectEntityId);
    const draft = draftFromParse(parseUtterance(text), {
      ids: this.#ids,
      subjectEntityId: turn.subjectEntityId,
      anchorIds: footprint.anchorIds,
      islandIds: footprint.islandIds,
      captureEvidence: footprint.evidence,
    });
    if (draft === null) return { kind: 'refused', reasonKey: 'refused.couldNotParse' };
    return this.#stage(draft, turn);
  }

  /** Cancel. Nothing was mutated, so there is nothing to roll back (5.3). */
  cancel(proposalId: string): void {
    this.#pending.delete(proposalId);
    this.#gate.discard(proposalId);
  }

  peekConfirmation(proposalId: string): ConfirmationSummary | null {
    return this.#pending.get(proposalId)?.confirmation ?? null;
  }

  /**
   * THE ONLY WRITE PATH.
   *
   * Refuses when the tier's requirements are unmet, listing every one of them, so a surface that
   * forgot the live preview learns which requirement it missed rather than that "commit failed".
   */
  async commit(proposalId: string, ack: ConfirmationAcknowledgement): Promise<CommitResult> {
    const pending = this.#pending.get(proposalId);
    if (pending === undefined) {
      throw new ConfirmationRefusedError(
        `proposal ${proposalId} is not staged in this session`,
        ['proposal.notStaged'],
      );
    }
    const unmet = unmetRequirements(
      pending.proposal.maxTier,
      ack,
      pending.entity?.displayName ?? null,
    );
    if (unmet.length > 0) {
      throw new ConfirmationRefusedError(
        `refusing to commit ${proposalId}: ${unmet.join(', ')}`,
        unmet,
      );
    }
    const result = await this.#gate.commit(proposalId);
    this.#pending.delete(proposalId);
    return result;
  }
}
