import * as pc from 'playcanvas';
import type {
  FlightKindLook,
  FlightPartFactory,
  FlightSamples,
  FlightState,
  FlightWindow,
} from './types.js';

/**
 * A saved world's flyers, drawn from the steps the flight route served.
 *
 * Nothing here steers. Each flyer stands where its served steps put it, interpolated between two
 * consecutive steps along the straight segment the server checked, and faces the way its served
 * velocity points. Bank comes from the served turning acceleration, pitch from the served climb,
 * and the wings beat while a step says the flyer flaps, glide level while it does not, and fold
 * along the body while it perches. When the page's clock passes the last served step, every
 * flyer holds that step and the count of such frames rises, rather than anything being guessed.
 *
 * The clock is the page's own: the first window handed in starts it at that window's first step.
 * Windows the clock has passed are let go as new ones arrive. Under reduced motion every flyer
 * stands still at the step the clock had reached when the latest window arrived, as the crowd
 * shows each person where a minute left them. The flock asks for frames only while some flyer is
 * off its perch at the clock's step.
 */

const MM_PER_METRE = 1000;
/** Standard gravity in millimetres a second squared: a bank's angle is atan(turning / gravity). */
const GRAVITY_MM_S2 = 9807;
const DEGREES_PER_RADIAN = 180 / Math.PI;
const MRAD_PER_RADIAN = 1000;
/** How far a beating wing swings above and below level, in degrees. */
const BEAT_DEGREES = 50;
/** How far a gliding wing is raised above level, in degrees: a shallow V, as a gliding bird holds. */
const GLIDE_DEGREES = 8;
/** How far a perching flyer's wings are swept back along its body, in degrees. */
const FOLD_DEGREES = 80;
/** The steepest nose-up or nose-down a flyer is drawn at, in degrees. */
const PITCH_LIMIT_DEGREES = 60;
/** Below this horizontal speed, in millimetres a second, a flyer keeps the heading it had. */
const HEADING_SPEED_MM_S = 50;
/** Windows kept behind the clock, in steps, so the step a frame interpolates from is still held. */
const BEHIND_STEPS = 2;

interface Drawn {
  readonly root: pc.Entity;
  readonly body: pc.Entity;
  readonly right: pc.Entity;
  readonly left: pc.Entity;
  readonly look: FlightKindLook;
  headingDegrees: number;
  wingPhase: number;
}

interface Sample {
  readonly position: [number, number, number];
  readonly velocity: [number, number, number];
  readonly turn: number;
  readonly state: FlightState;
  readonly flap: boolean;
}

const yAxis = new pc.Vec3(0, 1, 0);
const xAxis = new pc.Vec3(1, 0, 0);
const zAxis = new pc.Vec3(0, 0, 1);
/** Half a turn about the vertical: the left wing is the right one turned so. */
const HALF_TURN = new pc.Quat().setFromAxisAngle(yAxis, 180);

export class FlightFlock {
  readonly root: pc.Entity;
  private readonly kinds = new Map<string, { look: FlightKindLook; parts: FlightPartFactory }>();
  private readonly drawn = new Map<string, Drawn>();
  /** Each held window by its first step, with its flyers' rows by identity. */
  private readonly windows = new Map<number, { window: FlightWindow; rows: Map<string, FlightSamples> }>();
  private inputSha256: string | null = null;
  private stepMs = 0;
  private groundMm = 0;
  private startMs: number | null = null;
  private startStep = 0;
  private lastNowMs: number | null = null;
  /** The step every flyer is posed at under reduced motion: the clock's when a window arrived. */
  private heldStep: number | null = null;
  private reduced = false;
  private starvedFrames = 0;
  private destroyed = false;
  private readonly yaw = new pc.Quat();
  private readonly pitch = new pc.Quat();
  private readonly roll = new pc.Quat();
  private readonly turned = new pc.Quat();
  private readonly wingTurn = new pc.Quat();
  private readonly mirrored = new pc.Quat();

  constructor(parent: pc.Entity, private readonly clock: () => number = () => performance.now()) {
    this.root = new pc.Entity('flight-flock');
    parent.addChild(this.root);
  }

  /** How a kind is drawn, and the factory that builds its parts. Flyers of it appear once set. */
  setKind(look: FlightKindLook, parts: FlightPartFactory): void {
    this.kinds.set(look.key, { look, parts });
  }

  hasKind(key: string): boolean {
    return this.kinds.has(key);
  }

  /**
   * Hand in a served window. The first starts the page's clock at `nowMs`; a window of another
   * flight (a new input digest) replaces everything held, clock included.
   */
  setWindow(window: FlightWindow, nowMs: number): void {
    if (this.destroyed) return;
    if (this.inputSha256 !== window.inputSha256) {
      this.clear();
      this.inputSha256 = window.inputSha256;
      this.stepMs = window.stepMs;
      this.groundMm = window.groundMm;
      this.startMs = nowMs;
      this.startStep = window.fromStep;
    }
    this.windows.set(window.fromStep, {
      window,
      rows: new Map(window.flyers.map((row) => [row.flyerId, row])),
    });
    const at = this.stepAt(nowMs);
    if (at === null) return;
    const step = Math.floor(Math.min(at, (this.nextStep ?? 0) - 1));
    this.heldStep = step;
    this.forget(step - BEHIND_STEPS);
  }

  /** The first step no window held covers, where the next request for this flight starts. */
  get nextStep(): number | null {
    if (this.windows.size === 0) return null;
    let end = -1;
    for (const { window } of this.windows.values()) end = Math.max(end, window.fromStep + window.steps);
    return end;
  }

  /** The page clock's step at `nowMs`, fractional, or null before the first window. */
  stepAt(nowMs: number): number | null {
    if (this.startMs === null || this.stepMs <= 0) return null;
    return this.startStep + Math.max(0, nowMs - this.startMs) / this.stepMs;
  }

  /** How many served windows are held: those the clock has not yet passed. */
  get heldWindows(): number {
    return this.windows.size;
  }

  /** Frames drawn at a step no served window reached yet: each held the last served step. */
  get starved(): number {
    return this.starvedFrames;
  }

  /** Whether a frame drawn now would move anything: some flyer is off its perch at the clock's step. */
  get animating(): boolean {
    if (this.reduced || this.destroyed || this.drawn.size === 0) return false;
    const at = this.stepAt(this.clock());
    if (at === null || at > (this.nextStep ?? 0) - 1) return false;
    const whole = Math.floor(at);
    for (const { window } of this.windows.values()) {
      for (const step of [whole, whole + 1]) {
        const index = step - window.fromStep;
        if (index < 0 || index >= window.steps) continue;
        if (window.flyers.some((row) => window.states[row.state[index]!] !== 'perching')) return true;
      }
    }
    return false;
  }

  get drawnFlyerIds(): readonly string[] {
    return [...this.drawn.keys()];
  }

  /**
   * Every flyer where the page's clock puts it. `Number.MAX_SAFE_INTEGER` is reduced motion: every
   * flyer stands at the held step, its wings still.
   */
  update(nowMs: number): void {
    if (this.destroyed || this.startMs === null) return;
    if (nowMs === Number.MAX_SAFE_INTEGER) {
      this.reduced = true;
      if (this.heldStep !== null) this.poseAt(this.heldStep, 0, 0);
      return;
    }
    this.reduced = false;
    const elapsed = this.lastNowMs === null ? 0 : Math.max(0, nowMs - this.lastNowMs);
    this.lastNowMs = nowMs;
    const at = this.stepAt(nowMs);
    if (at === null) return;
    const last = (this.nextStep ?? 0) - 1;
    let step = at;
    if (step > last) {
      this.starvedFrames += 1;
      step = last;
    }
    this.forget(Math.floor(step) - BEHIND_STEPS);
    const whole = Math.floor(step);
    this.heldStep = whole;
    this.poseAt(whole, step - whole, elapsed);
  }

  /** Every held flyer at a served step, a fraction of the way to the next; the rest let go. */
  private poseAt(whole: number, fraction: number, elapsed: number): void {
    const seen = new Set<string>();
    for (const { window } of this.windows.values()) {
      if (whole < window.fromStep || whole >= window.fromStep + window.steps) continue;
      for (const samples of window.flyers) {
        seen.add(samples.flyerId);
        const from = this.sample(samples.flyerId, whole);
        const to = this.sample(samples.flyerId, whole + 1) ?? from;
        if (from === null || to === null) continue;
        this.pose(samples, from, to, fraction, elapsed);
      }
    }
    for (const [id, drawn] of this.drawn) {
      if (!seen.has(id)) {
        drawn.root.destroy();
        this.drawn.delete(id);
      }
    }
  }

  /** Release every flyer and window; the next window starts the clock again. */
  clear(): void {
    for (const drawn of this.drawn.values()) drawn.root.destroy();
    this.drawn.clear();
    this.windows.clear();
    this.inputSha256 = null;
    this.startMs = null;
    this.lastNowMs = null;
    this.heldStep = null;
  }

  destroy(): void {
    if (this.destroyed) return;
    this.clear();
    this.destroyed = true;
    this.root.destroy();
  }

  private forget(before: number): void {
    for (const [from, { window }] of this.windows) {
      if (from + window.steps <= before) this.windows.delete(from);
    }
  }

  /** One flyer's served step, from whichever held window covers it, or null. */
  private sample(flyerId: string, step: number): Sample | null {
    for (const { window, rows } of this.windows.values()) {
      const index = step - window.fromStep;
      if (index < 0 || index >= window.steps) continue;
      const row = rows.get(flyerId);
      if (row === undefined) return null;
      const p = row.positionMm;
      const v = row.velocityMmS;
      return {
        position: [p[3 * index]!, p[3 * index + 1]!, p[3 * index + 2]!],
        velocity: [v[3 * index]!, v[3 * index + 1]!, v[3 * index + 2]!],
        turn: row.turnMmS2[index]!,
        state: window.states[row.state[index]!]!,
        flap: row.flap[index] === 1,
      };
    }
    return null;
  }

  private drawnFor(samples: FlightSamples): Drawn | null {
    const existing = this.drawn.get(samples.flyerId);
    if (existing !== undefined) return existing;
    const kind = this.kinds.get(samples.kind);
    if (kind === undefined) return null;
    const root = new pc.Entity(`flyer:${samples.flyerId}`);
    const body = kind.parts.body();
    const right = kind.parts.wing();
    const left = kind.parts.wing();
    // The catalog's part frame is across, front, up; the entity's is across, up, back (-z front).
    const [across, front, up] = kind.look.wingHingeMm;
    right.setLocalPosition(across / MM_PER_METRE, up / MM_PER_METRE, -front / MM_PER_METRE);
    left.setLocalPosition(-across / MM_PER_METRE, up / MM_PER_METRE, -front / MM_PER_METRE);
    root.addChild(body);
    root.addChild(right);
    root.addChild(left);
    this.root.addChild(root);
    const drawn: Drawn = { root, body, right, left, look: kind.look, headingDegrees: 0, wingPhase: 0 };
    this.drawn.set(samples.flyerId, drawn);
    return drawn;
  }

  private pose(samples: FlightSamples, from: Sample, to: Sample, fraction: number, elapsedMs: number): void {
    const drawn = this.drawnFor(samples);
    if (drawn === null) return;
    const mix = (a: number, b: number) => a + (b - a) * fraction;
    drawn.root.setLocalPosition(
      mix(from.position[0], to.position[0]) / MM_PER_METRE,
      (mix(from.position[1], to.position[1]) - this.groundMm) / MM_PER_METRE,
      mix(from.position[2], to.position[2]) / MM_PER_METRE,
    );
    const vx = mix(from.velocity[0], to.velocity[0]);
    const vy = mix(from.velocity[1], to.velocity[1]);
    const vz = mix(from.velocity[2], to.velocity[2]);
    const level = Math.hypot(vx, vz);
    if (level > HEADING_SPEED_MM_S) drawn.headingDegrees = Math.atan2(-vx, -vz) * DEGREES_PER_RADIAN;
    const hovering = from.state === 'taking_off' || from.state === 'landing' || from.state === 'perching';
    const pitch = hovering ? 0 : Math.max(
      -PITCH_LIMIT_DEGREES,
      Math.min(PITCH_LIMIT_DEGREES, Math.atan2(vy, level) * DEGREES_PER_RADIAN),
    );
    const limit = drawn.look.maxBankMrad / MRAD_PER_RADIAN;
    const turn = mix(from.turn, to.turn);
    const bank = Math.max(-limit, Math.min(limit, Math.atan2(turn, GRAVITY_MM_S2))) * DEGREES_PER_RADIAN;
    this.yaw.setFromAxisAngle(yAxis, drawn.headingDegrees);
    this.pitch.setFromAxisAngle(xAxis, pitch);
    this.roll.setFromAxisAngle(zAxis, bank);
    this.turned.mul2(this.yaw, this.pitch).mul(this.roll);
    drawn.root.setLocalRotation(this.turned);
    this.wings(drawn, from, elapsedMs);
  }

  private wings(drawn: Drawn, sample: Sample, elapsedMs: number): void {
    // The left wing is the right one turned half a turn about the vertical, so each wing's own
    // turn is applied first, about its own axes, and the left wing's half turn after it.
    if (sample.state === 'perching') {
      this.wingTurn.setFromAxisAngle(yAxis, -FOLD_DEGREES);
      drawn.right.setLocalRotation(this.wingTurn);
      this.wingTurn.setFromAxisAngle(yAxis, FOLD_DEGREES);
      drawn.left.setLocalRotation(this.mirrored.mul2(HALF_TURN, this.wingTurn));
      drawn.wingPhase = 0;
      return;
    }
    let angle = GLIDE_DEGREES;
    if (sample.flap) {
      drawn.wingPhase = (drawn.wingPhase + elapsedMs / Math.max(1, drawn.look.flapCycleMs)) % 1;
      angle = BEAT_DEGREES * Math.sin(2 * Math.PI * drawn.wingPhase);
    }
    // Raising a wing is a turn about its own forward axis, the same angle on both sides.
    this.wingTurn.setFromAxisAngle(zAxis, angle);
    drawn.right.setLocalRotation(this.wingTurn);
    drawn.left.setLocalRotation(this.mirrored.mul2(HALF_TURN, this.wingTurn));
  }
}
