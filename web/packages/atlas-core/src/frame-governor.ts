/**
 * The frame governor: whether this computer draws a world's frames in time, read from the frames
 * themselves, and which quality level of the render budget it should draw at.
 *
 * NEVER FROM GUESSED HARDWARE. A GPU's name, a core count or a memory size is wrong often enough
 * to be useless and reads more about a visitor than drawing needs. The page hands this every frame
 * it begins; this keeps the display's interval, counts the frames that come late, and judges each
 * window of frames. Where the browser offers graphics timer queries, their figures only confirm
 * that the graphics are the cause before the drawing steps down: a society or a script holding the
 * main thread makes late frames too, and drawing lighter would not help them.
 *
 * Stepping is OFF by default (`mode: 'off'`): the governor judges every window and holds level 0,
 * so a page can record what it would do without changing what anyone sees. The figures in
 * `FRAME_GOVERNOR_RULES` are starting values with their reasons, for a measurement on ordinary
 * laptops to settle.
 *
 * Pure: no DOM, no renderer, no clock of its own. Times are the page's own milliseconds.
 */

export interface FrameGovernorRules {
  /** Frames are not judged for this long after a world loads or its look changes, ms. */
  readonly settleMs: number;
  /** An interval longer than this is a pause (a hidden or background tab), not a frame, ms. */
  readonly gapMs: number;
  /** How many judged frames the display's interval is read from. */
  readonly displayFrames: number;
  /** The longest display interval believed, ms. */
  readonly slowestDisplayMs: number;
  /** A frame is late when its interval is more than this many display intervals. */
  readonly lateFactor: number;
  /** One judged window, ms of frames. */
  readonly windowMs: number;
  /** The fewest judged frames a window needs for a verdict. */
  readonly windowFramesLeast: number;
  /** A window is weak when more than this share of its frames are late. */
  readonly weakShare: number;
  /** Graphics are the cause when their median time is above this share of the display interval. */
  readonly graphicsBoundShare: number;
  /** Graphics have room when their median time is under this share of the display interval. */
  readonly roomShare: number;
  /** How long graphics must have room before the drawing steps up one level, ms. */
  readonly stepUpAfterMs: number;
  /** The least time between two steps, ms. */
  readonly stepEveryMs: number;
}

export const FRAME_GOVERNOR_RULES: FrameGovernorRules = Object.freeze({
  // Building shaders and uploading textures make late frames on every computer.
  settleMs: 3000,
  // Browsers stop drawing a hidden tab; a quarter of a second is no frame anyone waited for.
  gapMs: 250,
  // About a second of frames at 60 Hz.
  displayFrames: 60,
  // A computer that draws every frame slowly gives steady long intervals, which would read as a slow
  // display; no display in use for a world refreshes under 60 Hz, so a longer interval is late.
  slowestDisplayMs: 1000 / 60,
  // Half a display interval late: one frame shown twice.
  lateFactor: 1.5,
  windowMs: 5000,
  windowFramesLeast: 30,
  // One frame in five shown twice is visible as stutter while walking.
  weakShare: 0.2,
  graphicsBoundShare: 0.7,
  roomShare: 0.4,
  stepUpAfterMs: 30_000,
  stepEveryMs: 10_000,
});

/** One frame the page began. */
export interface FrameSample {
  /** When the frame began, ms on the page's clock. */
  readonly atMs: number;
  /** The frame's graphics time from timer queries, ms, or null where the browser offers none. */
  readonly graphicsMs: number | null;
  /** Whether the page was hidden. */
  readonly hidden: boolean;
  /** Whether the scene was drawn this frame (a page drawing on demand skips still frames). */
  readonly drawing: boolean;
}

/** What one judged window found. */
export type FrameVerdict =
  /** Frames came in time. */
  | 'steady'
  /** Frames came late and the graphics are the cause, or nothing says otherwise. */
  | 'weak'
  /** Frames came late but the graphics had room: something else holds the main thread. */
  | 'busy';

export interface FrameWindow {
  readonly verdict: FrameVerdict;
  readonly frames: number;
  readonly lateShare: number;
  /** Median graphics time of the window, ms, or null without timer queries. */
  readonly graphicsMs: number | null;
}

export interface FrameGovernorState {
  /** The level to draw at: 0 is full quality. */
  readonly level: number;
  /** The level the governor would draw at with stepping on. */
  readonly advised: number;
  readonly displayMs: number | null;
  readonly lastWindow: FrameWindow | null;
  /** Stepping stopped for this session: drawing lighter did not help. */
  readonly stopped: boolean;
}

export interface FrameGovernorOptions {
  /** The highest level the render budget states. With 0 there is nowhere to step. */
  readonly mostLevel: number;
  /** 'off' judges and holds level 0; 'automatic' draws at the level it advises. */
  readonly mode?: 'off' | 'automatic';
  readonly rules?: FrameGovernorRules;
}

const median = (values: readonly number[]): number => {
  const ordered = [...values].sort((a, b) => a - b);
  const middle = ordered.length >> 1;
  return ordered.length % 2 === 1 ? ordered[middle]! : (ordered[middle - 1]! + ordered[middle]!) / 2;
};

export class FrameGovernor {
  readonly #rules: FrameGovernorRules;
  readonly #mostLevel: number;
  readonly #mode: 'off' | 'automatic';
  #settledAt = Number.NEGATIVE_INFINITY;
  #lastAt: number | null = null;
  #display: number[] = [];
  #displayMs: number | null = null;
  #windowStart: number | null = null;
  #intervals: number[] = [];
  #graphics: number[] = [];
  #advised = 0;
  #lastStepAt = Number.NEGATIVE_INFINITY;
  #roomSince: number | null = null;
  /** A step down taken without timer evidence, waiting for the next window to show it helped. */
  #unconfirmedStep = false;
  #stopped = false;
  #lastWindow: FrameWindow | null = null;

  constructor(options: FrameGovernorOptions) {
    if (!Number.isInteger(options.mostLevel) || options.mostLevel < 0) throw new TypeError('frame governor: mostLevel must be a whole number from 0');
    this.#mostLevel = options.mostLevel;
    this.#mode = options.mode ?? 'off';
    this.#rules = options.rules ?? FRAME_GOVERNOR_RULES;
  }

  /** A world loaded or its look changed: frames are not judged until they settle. */
  restart(atMs: number): void {
    this.#settledAt = atMs + this.#rules.settleMs;
    this.#lastAt = null;
    this.#windowStart = null;
    this.#intervals = [];
    this.#graphics = [];
    this.#roomSince = null;
  }

  /** Hand the governor one frame; returns the level to draw at. */
  observe(sample: FrameSample): number {
    const previous = this.#lastAt;
    this.#lastAt = sample.hidden || !sample.drawing ? null : sample.atMs;
    if (previous === null || sample.hidden || !sample.drawing || sample.atMs < this.#settledAt) return this.level;
    const interval = sample.atMs - previous;
    if (!(interval > 0) || interval > this.#rules.gapMs) return this.level;
    if (this.#displayMs === null) {
      this.#display.push(interval);
      if (this.#display.length < this.#rules.displayFrames) return this.level;
      // The shortest steady interval: the tenth of the shortest, so one quick frame does not set it.
      const ordered = [...this.#display].sort((a, b) => a - b);
      this.#displayMs = Math.min(ordered[Math.floor(ordered.length / 10)]!, this.#rules.slowestDisplayMs);
    }
    this.#windowStart ??= sample.atMs;
    this.#intervals.push(interval);
    if (sample.graphicsMs !== null) this.#graphics.push(sample.graphicsMs);
    if (sample.atMs - this.#windowStart >= this.#rules.windowMs) this.#judge(sample.atMs);
    return this.level;
  }

  get level(): number {
    return this.#mode === 'automatic' ? this.#advised : 0;
  }

  state(): FrameGovernorState {
    return Object.freeze({ level: this.level, advised: this.#advised, displayMs: this.#displayMs, lastWindow: this.#lastWindow, stopped: this.#stopped });
  }

  #judge(atMs: number): void {
    const displayMs = this.#displayMs!;
    const frames = this.#intervals.length;
    const late = this.#intervals.filter((interval) => interval > this.#rules.lateFactor * displayMs).length;
    // Timer figures count only when most frames carry one.
    const graphicsMs = this.#graphics.length * 2 > frames ? median(this.#graphics) : null;
    this.#windowStart = null;
    this.#intervals = [];
    this.#graphics = [];
    if (frames < this.#rules.windowFramesLeast) return;
    const lateShare = late / frames;
    const weak = lateShare > this.#rules.weakShare;
    const verdict: FrameVerdict = !weak ? 'steady'
      : graphicsMs !== null && graphicsMs <= this.#rules.graphicsBoundShare * displayMs ? 'busy' : 'weak';
    this.#lastWindow = Object.freeze({ verdict, frames, lateShare, graphicsMs });
    if (this.#stopped) return;
    if (this.#unconfirmedStep) {
      // The step down taken without timer evidence: kept if it helped, undone for good if not.
      this.#unconfirmedStep = false;
      if (verdict !== 'steady') {
        this.#step(-1, atMs);
        this.#stopped = true;
        return;
      }
    }
    if (verdict === 'weak' && this.#advised < this.#mostLevel && atMs - this.#lastStepAt >= this.#rules.stepEveryMs) {
      this.#step(1, atMs);
      this.#unconfirmedStep = graphicsMs === null;
      this.#roomSince = null;
      return;
    }
    const room = verdict === 'steady' && graphicsMs !== null && graphicsMs < this.#rules.roomShare * displayMs;
    if (!room) {
      this.#roomSince = null;
      return;
    }
    this.#roomSince ??= atMs;
    if (this.#advised > 0 && atMs - this.#roomSince >= this.#rules.stepUpAfterMs && atMs - this.#lastStepAt >= this.#rules.stepEveryMs) {
      this.#step(-1, atMs);
      this.#roomSince = null;
    }
  }

  #step(by: 1 | -1, atMs: number): void {
    this.#advised = Math.min(this.#mostLevel, Math.max(0, this.#advised + by));
    this.#lastStepAt = atMs;
  }
}
