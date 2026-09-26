/**
 * Who decides for a saved world's people, mounted beside its inhabitants: the server's models read,
 * kept current as the drawn minute moves, and the owner's choice sent and read back.
 *
 * It reads once per simulated minute the page draws, never more often, and never while a read is
 * already out: a minute that moves during a read is read after it. A choice is recorded by the
 * server and then read back, so the section only ever says what the server holds.
 */

import { ApiError } from '@exulanica/graph-client';
import type { Credentials } from '../config.js';
import { SocietyModelsClient, type ModelRef, type SocietyModels } from '../society-models-api.js';
import {
  buildSocietyModels,
  choiceRefusalWords,
  choiceWords,
  decisionWordsFor,
  recordedWords,
  type ChoosablePerson,
} from '../ui/society-models.js';

export interface MountedSocietyModels {
  readonly root: HTMLElement;
  /**
   * Read again when `tick` is not the minute last read, or always with `force`. A null tick is a
   * world nobody lives in, where there is nobody to choose for and nothing is read.
   */
  refresh(tick: number | null, people: readonly ChoosablePerson[], force?: boolean): Promise<void>;
  /** A person's lines for the inspector: who decides for them, and their latest decision. */
  personDetails(subjectId: string): readonly (readonly [string, string])[];
  dispose(): void;
}

export function mountSocietyModels(options: {
  readonly credentials: Credentials;
  readonly world: { readonly worldId: string; readonly versionId: string };
  readonly client?: SocietyModelsClient;
  /** Called after each read, so an open inspector can say what changed. */
  readonly onRead?: () => void;
}): MountedSocietyModels {
  const abort = new AbortController();
  const client = options.client
    ?? new SocietyModelsClient({ ...options.credentials, signal: abort.signal, worldId: options.world.worldId });
  let view: SocietyModels | null = null;
  let people: readonly ChoosablePerson[] = [];
  let busy = false;
  /** What the last choice came to, and why the last read failed, each until the next. */
  let message = '';
  let failure = '';
  let readTick: number | null | undefined;
  let wanted: number | null = null;
  let reading: Promise<void> | null = null;
  let again = false;
  let disposed = false;
  /** How many reads have begun, and the number of the latest begun that has ended. */
  let begun = 0;
  let ended = 0;

  const section = buildSocietyModels({ onChoose: (chosen, model) => void choose(chosen, model) });
  const render = () => section.render({ view, people, busy, message: [message, failure].filter(Boolean).join(' ') });

  async function read(tick: number | null): Promise<void> {
    readTick = tick;
    const number = ++begun;
    try {
      view = await client.read(options.world.versionId);
      failure = '';
    } catch (error) {
      if (disposed) return;
      failure = `Who decides for them could not be read. ${error instanceof Error ? error.message : ''}`.trim();
    } finally {
      ended = Math.max(ended, number);
    }
    if (disposed) return;
    render();
    options.onRead?.();
  }

  /** Resolves once a read begun after this call has ended, or at once where nothing is read. */
  async function readAfterNow(): Promise<void> {
    const since = begun;
    while (!disposed && wanted !== null && ended <= since) {
      if (reading === null) await refresh(wanted, people, true);
      else await reading;
    }
  }

  async function refresh(tick: number | null, held: readonly ChoosablePerson[], force = false): Promise<void> {
    if (disposed) return;
    people = held;
    wanted = tick;
    render();
    if (tick === null || (!force && tick === readTick)) return;
    if (reading !== null) { again = true; return; }
    reading = read(tick);
    try { await reading; } finally { reading = null; }
    if (again && !disposed) { again = false; await refresh(wanted, people, true); }
  }

  async function choose(chosen: readonly string[], model: ModelRef | null): Promise<void> {
    if (disposed || busy || chosen.length === 0) return;
    busy = true;
    message = '';
    render();
    let recorded = false;
    try {
      await client.choose(options.world.versionId, chosen, model);
      recorded = true;
    } catch (error) {
      message = error instanceof ApiError
        ? choiceRefusalWords(error.code, error.message)
        : `The choice was not recorded. ${error instanceof Error ? error.message : ''}`.trim();
    } finally {
      busy = false;
    }
    // A read already out began before the choice: the words wait for one begun after it.
    await readAfterNow();
    if (recorded && !disposed) {
      // Said from the read that followed the choice, so it never names a model nobody asks.
      message = recordedWords(view, chosen, model);
      render();
    }
  }

  return {
    root: section.root,
    refresh,
    personDetails(subjectId) {
      if (view === null || !view.takesModelChoices) return [];
      return [
        ['Decided by', choiceWords(view, subjectId)],
        ['Latest decision', decisionWordsFor(view, subjectId) ?? 'None yet.'],
      ];
    },
    dispose() {
      disposed = true;
      abort.abort();
      section.root.remove();
    },
  };
}
