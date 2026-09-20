/**
 * Watching an intake form, in the surface that has a credential and something to watch.
 *
 * **Why here and not on the landing page.** The formation stream is per intake batch and every
 * request to it carries an account cookie or bearer token. A signed-out visitor has neither: no
 * batch of their own and no credential. The public landing page therefore shows no formation
 * state. This is the surface where an upload is a real thing that happened, so this is where its
 * stream belongs.
 *
 * **Nothing here decides what a stage means.** The contract, the reducer, the labels and the
 * visual mapping all live in `@exulanica/formation`, which knows nothing about this application.
 * This module chooses which batch to watch and hands the events on.
 *
 * **The batch is found, not assumed.** There is no upload endpoint yet, so an intake starts from
 * the command line and this asks the API what there is to watch. That is a smaller lie than a
 * hard-coded id and a smaller one than a fabricated batch: the list is what the workspace
 * actually contains, and an empty list renders as "nothing is forming" rather than as a spinner.
 */

import type { FormationState, StageEvent, StreamState } from '@exulanica/formation';
import {
  HttpFormationEventSource,
  initialFormationState,
  reduceFormation,
  withStreamState,
} from '@exulanica/formation';

export interface BatchSummary {
  readonly batchId: string;
  readonly label: string | null;
  readonly declaredSize: number | null;
  readonly status: string;
  readonly startedAt: string;
  readonly endedAt: string | null;
}

interface BatchPayload {
  readonly batch_id: string;
  readonly label: string | null;
  readonly declared_size: number | null;
  readonly status: string;
  readonly started_at: string;
  readonly ended_at: string | null;
}

export interface FormationWatchOptions {
  readonly baseUrl: string;
  readonly token: string;
}

/** What there is to watch, newest first. */
export async function listBatches(options: FormationWatchOptions): Promise<BatchSummary[]> {
  const headers: Record<string, string> = {};
  // An explicit empty bearer prevents the API from falling back to its HttpOnly account cookie.
  if (options.token) headers['authorization'] = `Bearer ${options.token}`;
  const response = await fetch(`${options.baseUrl}/formation`, {
    headers,
    credentials: 'include',
  });
  if (!response.ok) return [];
  const rows = (await response.json()) as BatchPayload[];
  return rows.map((row) => ({
    batchId: row.batch_id,
    label: row.label,
    declaredSize: row.declared_size,
    status: row.status,
    startedAt: row.started_at,
    endedAt: row.ended_at,
  }));
}

/**
 * Subscribe to one batch and report the reduced state on every change.
 *
 * The reducer is the one from the shared package and the state is threaded through it rather than
 * being patched here. Two things follow that are worth stating: nothing advances between events,
 * so a pipeline that goes quiet leaves the display exactly where it was; and a reconnect resumes
 * from the id the reducer last accepted rather than from the last frame that happened to arrive.
 */
export function watchBatch(
  options: FormationWatchOptions,
  batchId: string,
  onState: (state: FormationState) => void,
): () => void {
  const source = new HttpFormationEventSource({
    baseUrl: options.baseUrl,
    token: options.token,
    // The browser's own fetch, handed in rather than reached for, which is what lets the
    // transport be tested with a function that returns bytes.
    fetch: globalThis.fetch.bind(globalThis) as never,
  });

  let state = initialFormationState(batchId);
  onState(state);

  return source.subscribe(
    batchId,
    null,
    (event: StageEvent) => {
      state = reduceFormation(state, event);
      onState(state);
    },
    (stream: StreamState) => {
      state = withStreamState(state, stream);
      onState(state);
    },
  );
}
