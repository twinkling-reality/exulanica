/**
 * The Compare view's reads: a version's comparisons, the chosen one's numbers and verdict, and the
 * two runs of the chosen seed and sides, each replayed by the server with no model call.
 *
 * Opening the view reads the list again and opens the newest comparison, its first seed and its
 * first two models. Every read is one of the three the server offers; a response that arrives
 * after a newer choice was made is dropped, so the view never shows two choices mixed. Nothing
 * here asks a model or writes anything.
 */

import type { TransportOptions } from '@exulanica/graph-client';
import {
  SocietyComparisonClient,
  type ComparisonListing,
  type ComparisonResult,
  type RunReplay,
  type SocietyComparisonReadPort,
} from '../society-comparison-api.js';
import { createModalFocus } from '../ui/modal-focus.js';
import {
  buildSocietyComparisonView,
  defaultSides,
  type ComparisonDay,
} from '../ui/society-comparison.js';

export interface SocietyComparisonMountOptions {
  /** The open world and version the comparisons belong to. */
  readonly getWorldId: () => string | null;
  readonly getVersionId: () => string | null;
  readonly credentials?: TransportOptions;
  /** A client of the three reads; left out, one is made over `credentials` for the open world. */
  readonly client?: SocietyComparisonReadPort;
  readonly onClose: () => void;
}

export interface MountedSocietyComparison {
  readonly root: HTMLElement;
  setVisible(visible: boolean): void;
  dispose(): void;
}

const failure = (error: unknown): string =>
  error instanceof Error && error.message.length > 0 ? error.message : 'The server did not answer.';

export function mountSocietyComparison(options: SocietyComparisonMountOptions): MountedSocietyComparison {
  let generation = 0;
  let visible = false;
  let disposed = false;
  let opened: { versionId: string; result: ComparisonResult } | null = null;
  let listed: readonly ComparisonListing[] = [];
  const client = (): SocietyComparisonReadPort => {
    if (options.client !== undefined) return options.client;
    if (options.credentials === undefined) throw new Error('The Compare view reads with the page\'s credentials');
    return new SocietyComparisonClient({ ...options.credentials, worldId: options.getWorldId() });
  };
  const current = (token: number): boolean => !disposed && token === generation;

  const loadDay = async (versionId: string, result: ComparisonResult, day: ComparisonDay): Promise<void> => {
    const token = ++generation;
    view.showResult(result, day);
    view.status('day', 'Replaying the two runs', 'The server plays each recorded hour again from what it stored.');
    const seed = result.seeds.find((found) => found.seedDigest === day.seedDigest);
    const read = async (arm: string): Promise<RunReplay | null> => {
      const run = seed?.runs[arm];
      if (run === undefined || run.status !== 'completed' || run.runId === null) return null;
      return client().run(versionId, result.comparisonId, run.runId);
    };
    try {
      const [left, right] = await Promise.all([read(day.left), read(day.right)]);
      if (current(token)) view.showDay(left, right);
    } catch (error) {
      if (current(token)) view.status('day', 'These runs could not be replayed', failure(error));
    }
  };

  const openComparison = async (versionId: string, comparisonId: string): Promise<void> => {
    const token = ++generation;
    view.status('result', 'Reading the comparison', 'Scores and the verdict come from the server.');
    try {
      const result = await client().read(versionId, comparisonId);
      if (!current(token)) return;
      opened = { versionId, result };
      const seed = result.seeds[0];
      if (seed === undefined) {
        view.showResult(result, { seedDigest: '', ...defaultSides(result) });
        return;
      }
      await loadDay(versionId, result, { seedDigest: seed.seedDigest, ...defaultSides(result) });
    } catch (error) {
      if (current(token)) view.status('result', 'This comparison could not be read', failure(error));
    }
  };

  const refresh = async (): Promise<void> => {
    const token = ++generation;
    const versionId = options.getVersionId();
    if (versionId === null || options.getWorldId() === null) {
      view.status('list', 'No saved world is open', 'Open a saved world to see the comparisons of its people.');
      return;
    }
    view.status('list', 'Reading comparisons', 'The comparisons recorded for this version of the world.');
    try {
      const listings = await client().list(versionId);
      if (!current(token)) return;
      listed = listings;
      const newest = listings[0]?.comparisonId ?? null;
      view.showList(listings, newest);
      if (newest !== null) await openComparison(versionId, newest);
    } catch (error) {
      if (current(token)) view.status('list', 'The comparisons could not be read', failure(error));
    }
  };

  const view = buildSocietyComparisonView({
    onClose: () => options.onClose(),
    onComparison: (comparisonId) => {
      const versionId = options.getVersionId();
      if (versionId === null) return;
      view.showList(listed, comparisonId);
      void openComparison(versionId, comparisonId);
    },
    onDay: (day) => {
      if (opened !== null) void loadDay(opened.versionId, opened.result, day);
    },
  });
  const focus = createModalFocus(view.root, view.root.querySelector<HTMLButtonElement>('.comparison-close')!);
  view.root.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    options.onClose();
  });

  return {
    root: view.root,
    setVisible(next) {
      if (disposed || next === visible) return;
      visible = next;
      focus.setVisible(next);
      if (next) void refresh();
      else generation += 1;
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      visible = false;
      view.dispose();
    },
  };
}
