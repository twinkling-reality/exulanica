/**
 * The write path, in full: name a detection, read what that would change, confirm it, re-read.
 *
 * **Every write goes through the confirmation surface**, and the confirmation surface is the only
 * caller of `session.commit`. The chain is: the user types a name, a draft is built by
 * `world-index`, translated into an update proposal, staged on the gate, rendered for reading,
 * and committed only when the user presses confirm. Skipping any link is not possible from here,
 * because `session` exposes `stage` and `commit` separately and the panel is what sits between.
 *
 * The panel is built in this module rather than in the composition root for that reason. It is
 * not a surface that happens to be near the write path; it is the gap between staging and
 * committing, and moving it somewhere else would make the invariant a convention again.
 *
 * **The snapshot is re-read after a write rather than patched.** A local patch would be a second
 * model of the graph maintained by hand, and the first time it disagreed with the server the
 * interface would be confidently wrong. Re-reading costs one request and cannot drift.
 */

import { ApiError, type OccurrenceRecord } from '@exulanica/graph-client';
import type { GraphSnapshot } from '@exulanica/graph-client';
import { confirmationFor, draftEdit } from '@exulanica/world-index';

import { toUpdateProposal } from '../proposal.js';
import type { Session } from '../session.js';
import type { CompanionStage } from '../ui/companion-stage.js';
import { buildConfirm, type ConfirmPanel } from '../ui/confirm.js';
import type { AppEnvironment, SessionState } from './session-state.js';

export interface WritePathDependencies {
  readonly env: AppEnvironment;
  readonly state: SessionState;
  readonly session: Session;
  /** The snapshot this mount is drawn from. A draft is built against it, never against a later one. */
  readonly snapshot: GraphSnapshot;
  /**
   * The presence, read late. The stage is built by `companion.ts`, which needs this panel to
   * render a staged proposal on; one of the two has to be read after the other is built.
   */
  readonly companionStage: () => CompanionStage;
  /** The detail panel holding the name offer. Built by the root after this surface. */
  readonly detailRoot: () => HTMLElement;
  readonly onConfirmVisibilityChange: (visible: boolean) => void;
  /** Re-read and re-mount. The last step of a committed write and the only caller of it. */
  readonly remount: () => Promise<void>;
}

export interface MountedWritePath {
  readonly confirm: ConfirmPanel;
  propose(occurrence: OccurrenceRecord): void;
  commit(proposalId: string): Promise<void>;
  dispose(): void;
}

export function mountWritePath(deps: WritePathDependencies): MountedWritePath {
  const { env, state, session } = deps;

  const confirm = buildConfirm({
    onConfirm: (proposalId) => void commit(proposalId),
    onCancel: (proposalId) => {
      session.discard(proposalId);
      confirm.hide();
    },
    onVisibilityChange: (visible) => deps.onConfirmVisibilityChange(visible),
  });

  function propose(occurrence: OccurrenceRecord): void {
    const form = deps.detailRoot().querySelector<HTMLFormElement>('.name-offer');
    const input = form?.querySelector<HTMLInputElement>('input');
    const displayName = input?.value.trim() ?? '';
    if (displayName.length === 0) return;

    state.issued += 1;
    const issued = state.issued;
    const proposalId = `proposal-${issued}`;
    // Drafted by world-index, not here. The tier, the reversibility and the four bands all come
    // from the one policy table both surfaces obey.
    const draft = draftEdit(
      deps.snapshot,
      syntheticEntityFor(occurrence),
      displayName,
      (kind) => `${kind}-${issued}`,
    );
    const translated = toUpdateProposal(draft, {
      proposalId,
      turnId: `turn-${issued}`,
      stateVersion: session.stateVersion(),
      occurrenceId: occurrence.occurrenceId,
    });
    if (!translated.ok) {
      confirm.reportFailure(translated.reason);
      return;
    }
    session.stage(translated.proposal);
    confirm.show(proposalId, confirmationFor(draft, syntheticEntityFor(occurrence)), displayName);
  }

  async function commit(proposalId: string): Promise<void> {
    if (env.preview) {
      deps.companionStage().setState('uncertain');
      confirm.reportFailure('Preview mode is read-only. No change was sent.');
      return;
    }
    // This state names a real pending write. It begins before the request and ends with its result.
    deps.companionStage().setState('working');
    try {
      await session.commit(proposalId);
    } catch (error) {
      deps.companionStage().setState('uncertain');
      panelFailure(confirm, error);
      return;
    }
    // Only a completed account-holder confirmation earns this state.
    deps.companionStage().setState('settled');
    confirm.hide();
    // Re-read rather than patched. See the module comment.
    state.snapshot = await session.snapshot();
    state.selected = null;
    await deps.remount();
  }

  return { confirm, propose, commit, dispose: () => undefined };
}

function panelFailure(confirm: ConfirmPanel, error: unknown): void {
  confirm.reportFailure(
    error instanceof ApiError
      ? `${error.code}: ${error.message}`
      : error instanceof Error
        ? error.message
        : 'the write was refused',
  );
}

/**
 * The entity a bare occurrence would become.
 *
 * `draftEdit` and `confirmationFor` both take an `EntityRecord`, because both were written for
 * the case where the thing already exists. Naming a detection creates the entity, so there is no
 * record to hand them yet. This builds the one the write is about to produce: no name, no
 * assertions, and the occurrence's own island. Every field is either the truth or empty, and
 * nothing here is written anywhere: it exists to be described in the confirmation panel and is
 * discarded afterwards.
 */
function syntheticEntityFor(occurrence: OccurrenceRecord) {
  return {
    entityId: occurrence.entityId ?? occurrence.occurrenceId,
    kind: occurrence.kind === 'voice' || occurrence.kind === 'conversation'
      ? ('object' as const)
      : (occurrence.kind as 'person' | 'place' | 'object' | 'event'),
    displayName: null,
    status: 'inferred_only' as const,
    occurrenceCount: 1,
    islandIds: [occurrence.islandId],
    firstSeenMs: occurrence.capturedAtMs,
    lastSeenMs: occurrence.capturedAtMs,
    confidence: occurrence.confidence,
    openQuestionCount: 0,
    citingAnswerCount: 0,
    assertions: [],
    relations: [],
    contradictions: [],
    history: [],
    mergedInto: null,
  };
}
