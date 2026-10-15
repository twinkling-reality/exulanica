// A world's run while it is open (DESIGN's frame 09): the Running strip at the top centre with its
// time left, its spending and Stop; the note with why it ended and what it spent; the pops over
// characters whose model acted; the live dot on their chips. It reads the world's running state
// every 2.5 s only while a run is open, and once when asked otherwise. Starting and stopping are
// entity-execution.mjs's startRun and stopRun; the words are run-words.mjs's.
import { SocietyControlClient, type SocietyPlaybackControl } from '/src/society-control-api.ts';
import type { SocietyModels } from '/src/society-models-api.ts';
import { openRun, startRun, stopRun } from './entity-execution.mjs';
import { defaultRunLimits, endedNote, stripWords } from './run-words.mjs';
import { runStrip, type RunStrip } from './world-ui-character.ts';
import type { Notes } from './world-ui.ts';

/** How often an open run is read, in milliseconds. */
const WATCH_MS = 2500;

/** One thing a character's model did in a run, for its pop: a line said, or an action chosen. */
export interface RunAct {
  readonly subjectId: string;
  readonly words: string;
  readonly said: boolean;
}

export interface RunWatch {
  /** The latest read of the world's running state, or null before the first. */
  readonly control: SocietyPlaybackControl | null;
  /** The open run, or null. */
  readonly run: ReturnType<typeof openRun>;
  /** The limits Run would open with now, for the characters whose choice is a model. */
  limits(models: SocietyModels | null): ReturnType<typeof defaultRunLimits>;
  /** Reads the running state now (after a start, a stop or a page opening). */
  refresh(): Promise<void>;
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

export function mountRunWatch({ host, notes, entry, credentials, isCurrent, readOnly, acts, onAct, onChange }: {
  readonly host: HTMLElement;
  readonly notes: Notes;
  readonly entry: { readonly worldId: string; readonly authoredVersionId: string };
  readonly credentials: Record<string, unknown>;
  readonly isCurrent: () => boolean;
  readonly readOnly: boolean;
  /** Reads what models did in minutes after `fromTick`: the said lines and applied choices. */
  readonly acts: (fromTick: number) => Promise<readonly RunAct[]>;
  /** Called for each thing a model did, newest last, while a run is open. */
  readonly onAct: (act: RunAct) => void;
  readonly onChange: (watch: RunWatch) => void;
}): RunWatch {
  const controlClient = new SocietyControlClient({ ...credentials, worldId: entry.worldId } as ConstructorParameters<typeof SocietyControlClient>[0]);
  let control: SocietyPlaybackControl | null = null, live = true, timer = 0, requestId: string | null = null;
  let strip: RunStrip | null = null, seenTick: number | null = null, stopping = false;
  const watch: RunWatch = {
    get control() { return control; },
    get run() { return openRun(control); },
    limits(models) {
      return defaultRunLimits(control?.hostPlayback?.intervalMs ?? control?.tickIntervalMs ?? 60_000, models?.choices.filter(choice => choice.model).length ?? 0);
    },
    async refresh() { await read(); },
    async start({ subjectId, expectedModel, shown, modelsClient, refresh }) {
      if (readOnly) return 'forbidden';
      requestId ||= crypto.randomUUID();
      try {
        control = await startRun({ modelsClient, controlClient, entry, subjectId, expectedModel, current: () => live && isCurrent(), refresh, requestId,
          limitsFor: (fresh: SocietyPlaybackControl, models: SocietyModels) => {
            const limits = defaultRunLimits(fresh.hostPlayback?.intervalMs ?? fresh.tickIntervalMs, models.choices.filter(choice => choice.model).length);
            if (JSON.stringify(limits) !== JSON.stringify(shown)) throw Object.assign(Error('limits changed'), { code: 'stale_society_state' });
            return limits;
          } });
        requestId = null;
        seenTick = control?.currentTick ?? null;
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
    dispose() { live = false; clearTimeout(timer); clearInterval(tick); strip?.remove(); strip = null; },
  };
  // The strip's time left counts down between reads.
  const tick = window.setInterval(() => { if (live && strip) draw(); }, 1000);
  /** The note after a run, once, with the server's sentence for why it ended. */
  function ended(before: ReturnType<typeof openRun>) {
    if (!before || openRun(control)) return;
    const closed = control?.livingSession;
    if (closed && closed.sessionId === before.sessionId && closed.state === 'closed') notes.show(endedNote(closed), { ms: 8000 });
  }
  function draw() {
    const run = openRun(control);
    if (!run) { strip?.remove(); strip = null; return; }
    if (!strip) { strip = runStrip({ onStop: () => { void watch.stop(); } }); host.append(strip.root); }
    strip.set(stripWords(run, Date.now()));
  }
  async function read() {
    const before = openRun(control);
    try {
      const fresh = await controlClient.read(entry.authoredVersionId);
      if (!live || fresh.versionId !== entry.authoredVersionId) return;
      control = fresh;
    } catch { return; }
    ended(before);
    const run = openRun(control);
    if (run && seenTick !== null && control.currentTick > seenTick) {
      const from = seenTick + 1;
      seenTick = control.currentTick;
      void acts(from).then(list => { if (live) for (const act of list) onAct(act); }, () => {});
    } else if (run && seenTick === null) seenTick = control.currentTick;
    if (!run) seenTick = null;
    draw(); onChange(watch); schedule();
  }
  function schedule() {
    clearTimeout(timer);
    if (!live || !openRun(control)) return;
    timer = window.setTimeout(() => { if (!document.hidden) void read(); else schedule(); }, WATCH_MS);
  }
  return watch;
}
