import * as pc from 'playcanvas';
import { type LookBox, VEHICLE_LOOKS_V1 } from './vehicle-looks.js';
import type { TrafficWindow, VehicleSamples } from './types.js';

/**
 * A world's vehicles, drawn from the seconds the traffic route served.
 *
 * Nothing here drives. Each vehicle's front moves along the path the server says it passed during
 * the second being drawn, a fraction of the way by distance, never across that path's corners, and
 * its axles follow the same path behind it: the front axle `frontOverhang` back and the rear axle a
 * `wheelbase` further. The body is drawn from the axles and the class's dimensions, standing on the
 * ground the drawn world has at its plan point. A second whose path is empty holds its pose: a
 * parked vehicle, one stopped on its lane to enter or leave a bay, or one that leaves the bay for
 * the lane, where the server supplies no path and none is invented.
 *
 * The clock is the traffic's shared one: the first window starts the page's copy at the second the
 * server's clock was at (`clockSecond`), and a later window sets it again when the two have drifted
 * apart, so every page shows a world's vehicles in the same places. A vehicle named late at an
 * episode's last second is not drawn moving into the next episode, where it starts at home. When
 * the clock passes the last served second, every vehicle holds it and the count of such frames
 * rises. A vehicle standing where the drawn world has no ground is not drawn.
 *
 * Every body family and colour is resolved through `vehicle-looks.ts`; a key it does not state is
 * an error, never a stand-in.
 */

const MM_PER_METRE = 1000;
const PERMILLE = 1000;
const DEGREES_PER_RADIAN = 180 / Math.PI;
/** Seconds of drift between the page's clock and the served one past which it is set again. */
const CLOCK_DRIFT_SECONDS = 2;
/** Windows kept behind the clock, in seconds, so the second a frame is drawn from is still held. */
const BEHIND_SECONDS = 2;

type Point = readonly [number, number];

export const VEHICLE_LOOKS = VEHICLE_LOOKS_V1;

export class VehicleLookError extends Error {}

/** Where the drawn world's ground is at a plan point, in renderer metres, or null for none. */
export type GroundAt = (xMm: number, yMm: number) => number | null;
/** A plan point in the road records' frame, in the renderer's frame (x east, y up, z south). */
export type ToRenderer = (xMm: number, yMm: number, zMm: number) => readonly [number, number, number];

interface Drawn {
  readonly root: pc.Entity;
}

interface Frame {
  readonly front: Point;
  readonly rear: Point;
  readonly path: readonly Point[];
}

function lateKey(second: number, vehicleId: string): string {
  return `${second}:${vehicleId}`;
}

function points(flat: readonly number[]): Point[] {
  const out: Point[] = [];
  for (let index = 0; index + 1 < flat.length; index += 2) out.push([flat[index]!, flat[index + 1]!]);
  return out;
}

function distance(a: Point, b: Point): number {
  return Math.hypot(b[0] - a[0], b[1] - a[1]);
}

/** The point `along` from the start of a polyline, by distance; its ends outside it. */
export function pointAlong(line: readonly Point[], along: number): Point {
  if (line.length === 0) throw new Error('an empty line has no point');
  if (along <= 0) return line[0]!;
  let left = along;
  for (let index = 1; index < line.length; index += 1) {
    const a = line[index - 1]!;
    const b = line[index]!;
    const piece = distance(a, b);
    if (left <= piece && piece > 0) {
      const share = left / piece;
      return [a[0] + (b[0] - a[0]) * share, a[1] + (b[1] - a[1]) * share];
    }
    left -= piece;
  }
  return line[line.length - 1]!;
}

function lengthOf(line: readonly Point[]): number {
  let total = 0;
  for (let index = 1; index < line.length; index += 1) total += distance(line[index - 1]!, line[index]!);
  return total;
}

/**
 * A vehicle's front and axles a `fraction` of the way through the second whose frame is `to`,
 * having stood at `from`: the front along `to`'s path, the axles behind it along the trail from the
 * rear axle it stood on, through its front, then that path.
 */
export function poseBetween(
  from: Frame,
  to: Frame,
  fraction: number,
  dimensions: { readonly frontOverhang: number; readonly wheelbase: number },
): { readonly frontAxle: Point; readonly rearAxle: Point } {
  if (to.path.length < 2) return { frontAxle: from.front, rearAxle: from.rear };
  const path = to.path;
  const travelled = lengthOf(path) * Math.min(1, Math.max(0, fraction));
  const trail: Point[] = [from.rear, ...path];
  const head = distance(from.rear, path[0]!) + travelled;
  return {
    frontAxle: pointAlong(trail, head - dimensions.frontOverhang),
    rearAxle: pointAlong(trail, head - dimensions.frontOverhang - dimensions.wheelbase),
  };
}

export class TrafficLayer {
  readonly root: pc.Entity;
  private readonly drawn = new Map<string, Drawn>();
  private readonly windows = new Map<number, { window: TrafficWindow; rows: Map<string, VehicleSamples>; late: Set<string> }>();
  private readonly materials = new Map<string, pc.StandardMaterial>();
  private inputSha256: string | null = null;
  private stepMs = 0;
  private startMs: number | null = null;
  private startSecond = 0;
  private heldSecond: number | null = null;
  private starvedFrames = 0;
  private hiddenCount = 0;
  private movingCount = 0;
  private destroyed = false;
  private readonly yaw = new pc.Quat();
  private readonly yAxis = new pc.Vec3(0, 1, 0);

  constructor(
    parent: pc.Entity,
    private readonly groundAt: GroundAt,
    private readonly toRenderer: ToRenderer,
  ) {
    this.root = new pc.Entity('traffic');
    parent.addChild(this.root);
  }

  /**
   * Hand in a served window. The first starts the page's clock at its `clockSecond` at `nowMs`; a
   * window of another traffic (a new input digest) replaces everything held.
   */
  setWindow(window: TrafficWindow, nowMs: number): void {
    if (this.destroyed) return;
    for (const row of window.vehicles) {
      // Resolve every key before anything is drawn: an unknown one is refused, not stood in for.
      this.bodyBoxes(row.bodyFamily);
      this.colourOf(row.colour);
    }
    if (this.inputSha256 !== window.inputSha256) {
      this.clear();
      this.inputSha256 = window.inputSha256;
      this.stepMs = window.stepMs;
      this.startMs = nowMs;
      this.startSecond = window.clockSecond;
    } else {
      const page = this.secondAt(nowMs);
      if (page !== null && Math.abs(page - window.clockSecond) > CLOCK_DRIFT_SECONDS) {
        this.startMs = nowMs;
        this.startSecond = window.clockSecond;
      }
    }
    this.windows.set(window.fromSecond, {
      window,
      rows: new Map(window.vehicles.map((row) => [row.vehicleId, row])),
      late: new Set(window.lateHome.map((late) => lateKey(late.second, late.vehicleId))),
    });
  }

  /** The first second no window held covers, where the next request starts. */
  get nextSecond(): number | null {
    if (this.windows.size === 0) return null;
    let end = -1;
    for (const { window } of this.windows.values()) end = Math.max(end, window.fromSecond + window.seconds);
    return end;
  }

  /** The page clock's second at `nowMs`, fractional, or null before the first window. */
  secondAt(nowMs: number): number | null {
    if (this.startMs === null || this.stepMs <= 0) return null;
    return this.startSecond + Math.max(0, nowMs - this.startMs) / this.stepMs;
  }

  /** Frames drawn at a second no served window reached yet. */
  get starved(): number {
    return this.starvedFrames;
  }

  /** Vehicles drawn at the last update, and those held but not drawn for want of ground. */
  get drawnCount(): number {
    let shown = 0;
    for (const drawn of this.drawn.values()) if (drawn.root.enabled) shown += 1;
    return shown;
  }

  get hidden(): number {
    return this.hiddenCount;
  }

  /** Whether a vehicle drawn at the last update was moving: its second's path is not empty. */
  get animating(): boolean {
    return this.movingCount > 0;
  }

  /** Every vehicle where the page's clock puts it. `Number.MAX_SAFE_INTEGER` is reduced motion. */
  update(nowMs: number): void {
    if (this.destroyed || this.startMs === null) return;
    if (nowMs === Number.MAX_SAFE_INTEGER) {
      if (this.heldSecond !== null) this.poseAt(this.heldSecond, 0);
      return;
    }
    const at = this.secondAt(nowMs);
    if (at === null) return;
    const last = (this.nextSecond ?? 0) - 1;
    let second = at;
    if (second > last) {
      this.starvedFrames += 1;
      second = last;
    }
    this.forget(Math.floor(second) - BEHIND_SECONDS);
    const whole = Math.floor(second);
    this.heldSecond = whole;
    this.poseAt(whole, second - whole);
  }

  clear(): void {
    for (const drawn of this.drawn.values()) drawn.root.destroy();
    this.drawn.clear();
    this.windows.clear();
    this.inputSha256 = null;
    this.startMs = null;
    this.heldSecond = null;
  }

  destroy(): void {
    if (this.destroyed) return;
    this.clear();
    for (const material of this.materials.values()) material.destroy();
    this.materials.clear();
    this.destroyed = true;
    this.root.destroy();
  }

  private forget(before: number): void {
    for (const [from, { window }] of this.windows) {
      if (from + window.seconds <= before) this.windows.delete(from);
    }
  }

  private late(vehicleId: string, second: number): boolean {
    for (const { late } of this.windows.values()) if (late.has(lateKey(second, vehicleId))) return true;
    return false;
  }

  private frame(vehicleId: string, second: number): Frame | null {
    for (const { window, rows } of this.windows.values()) {
      const index = second - window.fromSecond;
      if (index < 0 || index >= window.seconds) continue;
      const row = rows.get(vehicleId);
      if (row === undefined) return null;
      return {
        front: [row.frontAxleMm[2 * index]!, row.frontAxleMm[2 * index + 1]!],
        rear: [row.rearAxleMm[2 * index]!, row.rearAxleMm[2 * index + 1]!],
        path: points(row.motionPathMm[index] ?? []),
      };
    }
    return null;
  }

  private poseAt(whole: number, fraction: number): void {
    const seen = new Set<string>();
    let hidden = 0;
    let moving = 0;
    for (const { window } of this.windows.values()) {
      if (whole < window.fromSecond || whole >= window.fromSecond + window.seconds) continue;
      for (const row of window.vehicles) {
        seen.add(row.vehicleId);
        const from = this.frame(row.vehicleId, whole);
        if (from === null) continue;
        const next = this.late(row.vehicleId, whole) ? null : this.frame(row.vehicleId, whole + 1);
        if (next !== null && next.path.length > 1) moving += 1;
        const pose = next === null
          ? { frontAxle: from.front, rearAxle: from.rear }
          : poseBetween(from, next, fraction, row.dimensionsMm);
        if (!this.place(row, pose.frontAxle, pose.rearAxle)) hidden += 1;
      }
    }
    this.hiddenCount = hidden;
    this.movingCount = moving;
    for (const [id, drawn] of this.drawn) {
      if (!seen.has(id)) {
        drawn.root.destroy();
        this.drawn.delete(id);
      }
    }
  }

  /** Stand one vehicle's body on its axles; false when the drawn world has no ground there. */
  private place(row: VehicleSamples, frontAxle: Point, rearAxle: Point): boolean {
    const dimensions = row.dimensionsMm;
    let hx = frontAxle[0] - rearAxle[0];
    let hy = frontAxle[1] - rearAxle[1];
    const run = Math.hypot(hx, hy);
    if (run === 0) {
      this.hide(row.vehicleId);
      return false;
    }
    hx /= run;
    hy /= run;
    // The bumpers, from the axles along the heading; the body's centre is half way between them.
    const frontX = frontAxle[0] + hx * dimensions.frontOverhang;
    const frontY = frontAxle[1] + hy * dimensions.frontOverhang;
    const rearX = rearAxle[0] - hx * dimensions.rearOverhang;
    const rearY = rearAxle[1] - hy * dimensions.rearOverhang;
    const centreX = (frontX + rearX) / 2;
    const centreY = (frontY + rearY) / 2;
    const ground = this.groundAt(centreX, centreY);
    if (ground === null) {
      this.hide(row.vehicleId);
      return false;
    }
    const drawn = this.drawnFor(row);
    const [x, , z] = this.toRenderer(centreX, centreY, 0);
    drawn.root.enabled = true;
    drawn.root.setLocalPosition(x, ground, z);
    // Yaw 0 faces north, forward (-sin yaw, 0, -cos yaw): a heading (hx, hy) is atan2(-hx, hy).
    this.yaw.setFromAxisAngle(this.yAxis, Math.atan2(-hx, hy) * DEGREES_PER_RADIAN);
    drawn.root.setLocalRotation(this.yaw);
    return true;
  }

  /** A vehicle not drawn this frame keeps its parts, disabled, if it has any. */
  private hide(vehicleId: string): void {
    const drawn = this.drawn.get(vehicleId);
    if (drawn !== undefined) drawn.root.enabled = false;
  }

  private drawnFor(row: VehicleSamples): Drawn {
    const existing = this.drawn.get(row.vehicleId);
    if (existing !== undefined) return existing;
    const root = new pc.Entity(`vehicle:${row.vehicleId}`);
    const { length, width, height } = row.dimensionsMm;
    for (const box of this.bodyBoxes(row.bodyFamily)) {
      const part = new pc.Entity(box.role);
      const [a0, a1] = box.along_permille;
      const [u0, u1] = box.up_permille;
      const along = ((a0 + a1) / 2 / PERMILLE - 0.5) * length;
      part.setLocalPosition(0, ((u0 + u1) / 2 / PERMILLE) * height / MM_PER_METRE, -along / MM_PER_METRE);
      part.setLocalScale(
        (box.across_permille / PERMILLE) * width / MM_PER_METRE,
        ((u1 - u0) / PERMILLE) * height / MM_PER_METRE,
        ((a1 - a0) / PERMILLE) * length / MM_PER_METRE,
      );
      part.addComponent('render', { type: 'box', material: this.materialFor(box.role, row.colour) });
      root.addChild(part);
    }
    this.root.addChild(root);
    const drawn = { root };
    this.drawn.set(row.vehicleId, drawn);
    return drawn;
  }

  private bodyBoxes(family: string): readonly LookBox[] {
    const found = VEHICLE_LOOKS.body_families[family];
    if (found === undefined) throw new VehicleLookError(`vehicle-looks states no body family ${family}`);
    return found.boxes;
  }

  private colourOf(key: string): string {
    const found = VEHICLE_LOOKS.colours[key];
    if (found === undefined) throw new VehicleLookError(`vehicle-looks states no colour ${key}`);
    return found;
  }

  private materialFor(role: string, colour: string): pc.StandardMaterial {
    const stated = VEHICLE_LOOKS.roles[role];
    if (stated === undefined) throw new VehicleLookError(`vehicle-looks states no role ${role}`);
    const hex = stated.colour === 'vehicle' ? this.colourOf(colour) : stated.colour;
    const existing = this.materials.get(hex);
    if (existing !== undefined) return existing;
    const material = new pc.StandardMaterial();
    const value = Number.parseInt(hex.slice(1), 16);
    material.diffuse = new pc.Color(((value >> 16) & 255) / 255, ((value >> 8) & 255) / 255, (value & 255) / 255);
    material.update();
    this.materials.set(hex, material);
    return material;
  }
}
