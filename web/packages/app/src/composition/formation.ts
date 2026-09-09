/**
 * What there is to watch forming, and the subscription that watches it.
 *
 * There is no upload endpoint yet, so an intake starts from the command line and this asks the
 * API rather than assuming: an empty list renders as nothing forming, which is a true statement,
 * and a fabricated batch would not be.
 *
 * The panel is built at one point in a mount and the watch starts at another, after the shell's
 * children have been replaced. `begin()` is that second point, kept as its own call so the
 * ordering is stated rather than implied by where a constructor happens to sit.
 */

import { listBatches, watchBatch, type BatchSummary, type FormationWatchOptions } from '../formation.js';
import { buildFormation, type FormationPanel } from '../ui/formation.js';
import type { SessionState } from './session-state.js';

export interface MountedFormation {
  readonly root: HTMLElement;
  readonly panel: FormationPanel;
  /** Render the empty state and start watching. Called after the shell has been replaced. */
  begin(): void;
  dispose(): void;
}

/**
 * Stop the previous mount's subscription.
 *
 * Also runs on the empty-world path, where no new panel is built: a stream left open would keep
 * pushing states at a panel whose DOM has been replaced.
 */
export function disposeFormationWatch(state: SessionState): void {
  state.stopWatching?.();
  state.stopWatching = null;
}

export function mountFormation(deps: {
  readonly state: SessionState;
  readonly credentials: FormationWatchOptions;
}): MountedFormation {
  const { state } = deps;
  const panel = buildFormation();

  return {
    root: panel.root,
    panel,
    begin: () => {
      panel.render(null, null);
      disposeFormationWatch(state);
      void listBatches(deps.credentials).then((batches) => {
        const watching = mostRecentlyStarted(batches);
        if (watching === undefined) return;
        state.stopWatching = watchBatch(deps.credentials, watching.batchId, (batchState) => {
          panel.render(batchState, watching.label);
        });
      });
    },
    dispose: () => disposeFormationWatch(state),
  };
}

/**
 * The batch to watch, or none.
 *
 * The most recently started one, running or not. A finished batch replays its history and ends,
 * which is the same code path a live subscriber takes, so somebody who opens the page after an
 * ingest finished reads what happened rather than finding nothing and concluding it was lost.
 */
function mostRecentlyStarted(batches: readonly BatchSummary[]): BatchSummary | undefined {
  return [...batches].sort((a, b) => b.startedAt.localeCompare(a.startedAt))[0];
}
