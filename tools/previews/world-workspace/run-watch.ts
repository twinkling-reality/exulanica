// A world's run while it is open (r09, R-RUN-BUILD-SHEET section 2): the world screen's top pill
// carries it in place of the people line (who decides, the time left, the spending and Stop), and says
// why it ended for a while once it ends; the live dot on the chips of characters whose model decides. It reads the world's running state every 2.5 s only
// while a run is open, and once when asked otherwise. The pops over characters who said or chose
// something come from contextual-world.ts's read while the world plays (T2), on the same cadence. Starting and stopping are
// entity-execution.mjs's startRun and stopRun; the words are run-words.mjs's.
// The app's modules are named by their paths, which the preview serves as /src/… (one module each) and the tests load.
import { SocietyControlClient, type SocietyPlaybackControl } from '../../../web/packages/app/src/society-control-api.ts';
import type { SocietyModels } from '../../../web/packages/app/src/society-models-api.ts';
import { openRun, startRun, stopRun } from './entity-execution.mjs';
import { defaultRunLimits, endedNote, pillRunLine } from './run-words.mjs';

/** Where a run shows: the world screen's top pill (world-corners.ts `run` and `runEnded`). */
export interface RunPill {
  run(state: { readonly line: string; readonly onStop: () => void } | null): void;
  runEnded(words: string): void;
}

/** A character as the words call them (character-words.mjs `called`): how a sentence opens and names them within it. */
export interface CalledAs { readonly start: string; readonly within: string }

/** How often an open run is read, in milliseconds, and what was said while the world plays (T2). */
export const WATCH_MS = 2500;

export interface RunWatch {
  /** The latest read of the world's running state, or null before the first. */
  readonly control: SocietyPlaybackControl | null;
  /** The open run, or null. */
  readonly run: ReturnType<typeof openRun>;
  /** The limits Run would open with now, for the characters whose choice is a model. */
  limits(models: SocietyModels | null): ReturnType<typeof defaultRunLimits>;
  /** Reads the running state now (after a start, a stop or a page opening). */
  refresh(): Promise<void>;
  /** Reads the running state now and answers the limits Run would open with under it, for a page that shows them. */
  refreshed(models: SocietyModels | null): Promise<ReturnType<typeof defaultRunLimits>>;
  /**
   * Opens a run for `subjectId`'s world with the limits shown; answers null when it opened, or the
   * refusal code. The same request id is reused until a start succeeds.
   */
  start(options: { readonly subjectId: string; readonly expectedModel: { readonly provider: string; readonly modelId: string }; readonly shown: ReturnType<typeof defaultRunLimits>;
    readonly modelsClient: unknown; readonly refresh: () => Promise<unknown> }): Promise<string | null>;
  /** Stops the open run; the note says why it ended. Answers null, or the refusal code. */
  stop(): Promise<string | null>;
  dispose(): void;
}

export function mountRunWatch({ pill, askers, free = () => false, entry, credentials, isCurrent, readOnly, onChange }: {
  readonly pill: RunPill;
  /** The characters whose choice is a model, as the page calls them now, for the pill's "who decides". */
  readonly askers: () => readonly CalledAs[];
  /**
   * Whether every model those characters have is on this computer, or null before the page has read them: the pill then
   * says no money figure (A2).
   */
  readonly free?: () => boolean | null;
  readonly entry: { readonly worldId: string; readonly authoredVersionId: string };
  readonly credentials: Record<string, unknown>;
  readonly isCurrent: () => boolean;
  readonly readOnly: boolean;
  readonly onChange: (watch: RunWatch) => void;
}): RunWatch {
  const controlClient = new SocietyControlClient({ ...credentials, worldId: entry.worldId } as ConstructorParameters<typeof SocietyControlClient>[0]);
  let control: SocietyPlaybackControl | null = null, live = true, timer = 0, requestId: string | null = null;
  let shown = false, stopping = false;
  const watch: RunWatch = {
    get control() { return control; },
    get run() { return openRun(control); },
    limits(models) {
      return defaultRunLimits(control?.hostPlayback?.intervalMs ?? control?.tickIntervalMs ?? 60_000, models?.choices.filter(choice => choice.model).length ?? 0);
    },
    async refresh() { await read(); },
    async refreshed(models) { await read(); return watch.limits(models); },
    async start({ subjectId, expectedModel, shown, modelsClient, refresh }) {
      if (readOnly) return 'forbidden';
      requestId ||= crypto.randomUUID();
      try {
        control = await startRun({ modelsClient, controlClient, entry, subjectId, expectedModel, current: () => live && isCurrent(), refresh, requestId,
          limitsFor: (fresh: SocietyPlaybackControl, models: SocietyModels) => {
            // The start's own read is the world's running state now: kept, so the limits a refused start shows next
            // are the ones a second press asks under (the page may have opened before the world had people).
            control = fresh;
            const limits = defaultRunLimits(fresh.hostPlayback?.intervalMs ?? fresh.tickIntervalMs, models.choices.filter(choice => choice.model).length);
            if (JSON.stringify(limits) !== JSON.stringify(shown)) throw Object.assign(Error('limits changed'), { code: 'stale_society_state' });
            return limits;
          } });
        requestId = null;
        draw(); schedule(); onChange(watch);
        return null;
      } catch (error) {
        return (error as { code?: string }).code ?? 'unknown';
      }
    },
    async stop() {
      if (readOnly || stopping) return null;
      stopping = true;
      try {
        const before = openRun(control);
        control = await stopRun({ controlClient, entry, current: () => live && isCurrent() });
        ended(before);
        draw(); onChange(watch);
        return null;
      } catch (error) {
        return (error as { code?: string }).code ?? 'unknown';
      } finally { stopping = false; }
    },
    dispose() { live = false; clearTimeout(timer); clearInterval(tick); if (shown) pill.run(null); shown = false; },
  };
  // The pill's time left counts down between reads.
  const tick = window.setInterval(() => { if (live && shown) draw(); }, 1000);
  /** The note after a run, once, with the server's sentence for why it ended. */
  function ended(before: ReturnType<typeof openRun>) {
    if (!before || openRun(control)) return;
    const closed = control?.livingSession;
    if (closed && closed.sessionId === before.sessionId && closed.state === 'closed') pill.runEnded(endedNote(closed));
  }
  function draw() {
    const run = openRun(control);
    if (!run) { if (shown) pill.run(null); shown = false; return; }
    shown = true;
    pill.run({ line: pillRunLine(run, Date.now(), askers(), free()), onStop: () => { void watch.stop(); } });
  }
  async function read() {
    const before = openRun(control);
    try {
      const fresh = await controlClient.read(entry.authoredVersionId);
      if (!live || fresh.versionId !== entry.authoredVersionId) return;
      control = fresh;
    } catch { return; }
    ended(before);
    draw(); onChange(watch); schedule();
  }
  function schedule() {
    clearTimeout(timer);
    if (!live || !openRun(control)) return;
    timer = window.setTimeout(() => { if (!document.hidden) void read(); else schedule(); }, WATCH_MS);
  }
  return watch;
}
