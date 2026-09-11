/**
 * Typed handoff for an upstream conversational proposal service.
 *
 * This inbox does not call a model, store conversation text, or translate prose into style data.
 * A future authenticated service supplies the already-structured, provenance-bearing proposal;
 * Atlas still validates it through the local recipe registry and backend preview lifecycle.
 */

import type { UpstreamWorldStyleProposal } from './world-style-api.js';

export type WorldStyleProposalListener = (
  proposal: UpstreamWorldStyleProposal,
) => void | Promise<void>;

export class WorldStyleProposalInbox {
  readonly #listeners = new Set<WorldStyleProposalListener>();

  subscribe(listener: WorldStyleProposalListener): () => void {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  /** True only when an Atlas integration was present to receive the proposal. */
  submit(proposal: UpstreamWorldStyleProposal): boolean {
    if (this.#listeners.size === 0) return false;
    for (const listener of this.#listeners) void listener(proposal);
    return true;
  }
}

export const worldStyleProposalInbox = new WorldStyleProposalInbox();

/**
 * What happened to a proposal after it reached the confirmation surface.
 *
 * The return channel of the inbox above, and it exists for one reason: the Companion has to be
 * able to record what became of something it proposed, and the surface that decides is not the
 * surface that proposed. `composition/appearance.ts` owns Apply and Discard; `composition/
 * companion.ts` owns what is remembered. Neither may import the other, and a shared module they
 * both already depend on is where the seam belongs.
 *
 * **Keyed by origin reference rather than proposal id, deliberately.** A stale base makes the
 * world style client discard its proposal and create a REFINEMENT with a new id, silently and
 * correctly, so a listener keyed on the id it first saw would stop hearing about its own
 * proposal exactly when a second person changed the world underneath it. The origin reference is
 * minted per utterance and survives that recovery, because it describes what was asked rather
 * than which attempt is current.
 */
export type WorldStyleProposalOutcomeKind =
  /** The authority validated it and there is now something to confirm. */
  | 'previewed'
  /** A person confirmed it. The world changed. */
  | 'accepted'
  /** A person threw it away, or the surface replaced it. Nothing changed. */
  | 'discarded'
  /** The authority would not have it. Nothing changed and the reason is in `detail`. */
  | 'refused';

export interface WorldStyleProposalOutcome {
  /** The origin reference the proposal carried. Empty for a proposal that had none. */
  readonly originReference: string;
  readonly kind: WorldStyleProposalOutcomeKind;
  /** What the surface would say about it. The failure's own words when it is a refusal. */
  readonly detail: string;
}

export type WorldStyleProposalOutcomeListener = (
  outcome: WorldStyleProposalOutcome,
) => void | Promise<void>;

export class WorldStyleProposalOutcomes {
  readonly #listeners = new Set<WorldStyleProposalOutcomeListener>();

  subscribe(listener: WorldStyleProposalOutcomeListener): () => void {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  /** True only when something was listening. A proposal nobody proposed has nobody to tell. */
  report(outcome: WorldStyleProposalOutcome): boolean {
    if (this.#listeners.size === 0) return false;
    for (const listener of this.#listeners) void listener(outcome);
    return true;
  }
}

export const worldStyleProposalOutcomes = new WorldStyleProposalOutcomes();
