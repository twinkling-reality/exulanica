/**
 * The Compare view's reads, and its start: a version's comparisons, the chosen one's numbers and
 * verdict, the two runs of the chosen seed and sides, each replayed by the server with no model
 * call, and what starting a comparison would be, then its start.
 *
 * Opening the view reads the list again and opens the newest comparison, its first seed and its
 * first two models, and asks the server what a comparison of this world may be given. A change to
 * what is chosen asks for its plan again; starting one sends it, and the server plays it off the
 * request. While a started comparison of the list is waiting or running, the list and the open
 * comparison are read again every `PROGRESS_READ_MS`. A response that arrives after a newer choice
 * was made is dropped, so the view never shows two choices mixed. Nothing here asks a model.
 */

import { ApiError, type TransportOptions } from '@exulanica/graph-client';
import {
  SocietyComparisonClient,
  type ComparisonListing,
  type ComparisonResult,
  type ComparisonSelection,
  type RunReplay,
  type SocietyComparisonReadPort,
  type SocietyComparisonStartPort,
  type StartRequest,
} from '../society-comparison-api.js';
import { createModalFocus } from '../ui/modal-focus.js';
import {
  buildSocietyComparisonView,
  defaultSides,
  type ComparisonDay,
} from '../ui/society-comparison.js';
import { buildComparisonStartForm, inProgress, refusalWords } from '../ui/society-comparison-start.js';

/**
 * How often a list with a started comparison still to finish is read again. A run takes from about
 * a second (the routine's and waiting's, which ask nobody) to minutes (a model asked at every
 * choice point, each minute's asks ending by the decision contract's deadline), so every four
 * seconds shows each finished run within a few seconds, for one small read.
 */
export const PROGRESS_READ_MS = 4000;

export interface SocietyComparisonMountOptions {
  /** The open world and version the comparisons belong to. */
  readonly getWorldId: () => string | null;
  readonly getVersionId: () => string | null;
  readonly credentials?: TransportOptions;
  /**
   * A client of the reads, and of the plan and the start where it offers them; left out, one is
   * made over `credentials` for the open world.
   */
  readonly client?: SocietyComparisonReadPort & Partial<SocietyComparisonStartPort>;
  /** A fresh id for a comparison's start; left out, the browser's own. */
  readonly newId?: () => string;
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
  /** The seed and sides drawn now. */
  let shownDay: ComparisonDay | null = null;
  let listed: readonly ComparisonListing[] = [];
  let planning = 0;
  let progress: ReturnType<typeof setTimeout> | null = null;
  const client = (): SocietyComparisonReadPort & Partial<SocietyComparisonStartPort> => {
    if (options.client !== undefined) return options.client;
    if (options.credentials === undefined) throw new Error('The Compare view reads with the page\'s credentials');
    return new SocietyComparisonClient({ ...options.credentials, worldId: options.getWorldId() });
  };
  const current = (token: number): boolean => !disposed && token === generation;

  const loadDay = async (versionId: string, result: ComparisonResult, day: ComparisonDay): Promise<void> => {
    const token = ++generation;
    shownDay = day;
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
    void plan(versionId, null);
    try {
      const listings = await client().list(versionId);
      if (!current(token)) return;
      listed = listings;
      const newest = listings[0]?.comparisonId ?? null;
      view.showList(listings, newest);
      followProgress(listings);
      if (newest !== null) await openComparison(versionId, newest);
    } catch (error) {
      if (current(token)) view.status('list', 'The comparisons could not be read', failure(error));
    }
  };

  const plan = async (versionId: string, selection: ComparisonSelection | null): Promise<void> => {
    const port = client();
    if (port.plan === undefined) return;
    const token = ++planning;
    try {
      const offered = await port.plan(versionId, selection);
      if (!disposed && token === planning) form.showPlan(offered);
    } catch (error) {
      if (!disposed && token === planning) form.status('refused', failure(error));
    }
  };

  const followProgress = (listings: readonly ComparisonListing[]): void => {
    if (progress !== null) clearTimeout(progress);
    progress = null;
    if (!visible || disposed || !listings.some(inProgress)) return;
    progress = setTimeout(() => {
      progress = null;
      void readProgress();
    }, PROGRESS_READ_MS);
  };

  /** The list and the open comparison read again, keeping what the person has open. */
  const readProgress = async (): Promise<void> => {
    const versionId = options.getVersionId();
    if (versionId === null || !visible || disposed) return;
    try {
      const listings = await client().list(versionId);
      if (!visible || disposed) return;
      listed = listings;
      const open = opened?.result.comparisonId ?? null;
      view.showList(listings, open);
      const openListing = listings.find((listing) => listing.comparisonId === open);
      if (opened !== null && openListing !== undefined && (inProgress(openListing) || opened.result.start?.state !== openListing.start?.state)) {
        const before = opened.result;
        const result = await client().read(versionId, before.comparisonId);
        if (!visible || disposed || opened?.result.comparisonId !== result.comparisonId) return;
        opened = { versionId, result };
        const day = shownDay ?? { seedDigest: result.seeds[0]?.seedDigest ?? '', ...defaultSides(result) };
        const statuses = (held: ComparisonResult) => {
          const seed = held.seeds.find((found) => found.seedDigest === day.seedDigest);
          return `${seed?.runs[day.left]?.status}:${seed?.runs[day.right]?.status}`;
        };
        // The two runs drawn are replayed again only once either of them has finished since.
        if (statuses(before) !== statuses(result)) await loadDay(versionId, result, day);
        else view.showResult(result, day);
      }
      if (!listings.some(inProgress)) void plan(versionId, null);
      followProgress(listings);
    } catch {
      followProgress(listed);
    }
  };

  const startComparison = async (request: StartRequest): Promise<void> => {
    const versionId = options.getVersionId();
    const port = client();
    if (versionId === null || port.start === undefined) return;
    form.status('starting', 'Starting the comparison…');
    try {
      const [started] = await port.start(versionId, request);
      if (disposed) return;
      form.status('starting', 'Started. The server runs it now; its progress is in the list below.');
      const listings = await client().list(versionId);
      if (disposed) return;
      listed = listings;
      view.showList(listings, started?.comparisonId ?? null);
      if (started !== undefined) await openComparison(versionId, started.comparisonId);
      void plan(versionId, null);
      followProgress(listings);
    } catch (error) {
      if (disposed) return;
      form.status('refused', error instanceof ApiError
        ? refusalWords(error.code, error.message.slice(error.code.length + 2))
        : failure(error));
    }
  };

  const form = buildComparisonStartForm({
    onSelection: (selection) => {
      const versionId = options.getVersionId();
      if (versionId !== null) void plan(versionId, selection);
    },
    onStart: (request) => { void startComparison(request); },
    newId: options.newId ?? (() => crypto.randomUUID()),
  });

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
  view.startSlot.append(form.root);
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
      else {
        generation += 1;
        if (progress !== null) clearTimeout(progress);
        progress = null;
      }
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      visible = false;
      if (progress !== null) clearTimeout(progress);
      view.dispose();
    },
  };
}
