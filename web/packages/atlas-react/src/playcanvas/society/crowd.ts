import type * as pc from 'playcanvas';
import type { NativeCharacterFrame } from '../native-character-runtime.js';
import { sampleMotionPath } from '../society-presentation.js';
import { FarFigures } from './far-figures.js';
import { NEAR_INHABITANT_BUDGET } from '../character/budget.js';
import { CharacterHost } from '../character/host.js';
import { inhabitantRenderable } from '../character/inhabitant.js';
import type { CharacterPose } from '../character/renderable.js';
import type { FarAppearance } from '../character/far.js';
import type {
  CrowdJump,
  CrowdJumpReason,
  CrowdRenderable,
  CrowdRenderableFactory,
  CrowdTiming,
  OwnedSocietyState,
  SocietyInhabitantSnapshot,
} from './types.js';

/**
 * The whole synthetic population, drawn by distance.
 *
 * The population is canonical state and is never truncated here. Every outdoor inhabitant is
 * placed along its own recorded motion path; the nearest are full catalog people and everyone
 * else is the far form of the same person's look. People inside premises are counted, not drawn,
 * because interiors are not rendered. Two people standing on the same point are both drawn
 * there: where a society puts people is the simulation's occupancy rule, not the renderer's.
 *
 * Motion follows the recorded path only. A v4 inhabitant records its own walking speed
 * (`walk_speed_mm_per_tick`) and walks at it, one tick's worth per interval, stopping where the
 * recorded path ends. A v2 state records only a bound, how far anybody may walk in a tick
 * (`movement_budget_mm_per_tick`), and a person's recorded path is usually much shorter: walking
 * it at the bound would cover it in a fraction of the interval and stand for the rest, a burst.
 * So a v2 person walks what they have still to walk evenly over the interval and the caller's
 * start lag, when the next tick's path is expected, never faster than `CATCH_UP_SPEED_LIMIT` times
 * the bound's own pace. Each later snapshot's path is appended to what the person has still to walk
 * when it starts where that ends, so a person walking through several minutes never stops between
 * them; a v4 person behind catches up along the recorded path at most `CATCH_UP_SPEED_LIMIT` times
 * their speed. Anything else, a path that starts somewhere the person was not, minutes this crowd
 * never saw, or more waiting than can be caught up, moves the person without walking, and every
 * such move is a named jump (`jumps`) rather than a silent one. An older snapshot without a pace is
 * eased along its path over the whole interval. No position is invented between path points.
 * Everyone faces the way their recorded path last took them and keeps that facing when they
 * stop, in either form, so a person first drawn in full after arriving, or again after a spell
 * in the far form, faces as their far figure did.
 *
 * What a person is doing comes from the state too, never from how they move: an inhabitant whose
 * state names an active action (`action.kind` with `status` active) is handed that activity once
 * the path recorded for the tick has been walked, so a person asked to rest walks there and then
 * sits. How an activity is drawn is the character catalog's decision.
 *
 * Everyone is drawn on the ground plane. A recorded point is a plan point and the height each
 * walker is drawn at is 0, which is the ground a tile bake draws; a person who states the height
 * of the surface they stand on is refused rather than drawn under it. When a place's stated
 * heights are wired through to a person, that refusal is what says the ground-plane zeros here
 * and in the far figures must be read from the person instead of written.
 *
 * Detail by distance applies to time as well as shape. Every drawn inhabitant is placed at its
 * recorded point every frame, but only the nearest few full characters are posed every frame;
 * the rest are posed every second or third frame and carried to their recorded point in between.
 * A selected inhabitant is posed every frame.
 */
export interface CrowdOptions {
  /** Full characters at most; the inhabitants' share of the measured budget is the ceiling. */
  readonly nearLimit?: number;
  /** Full characters only within this many metres of the observer. */
  readonly nearRadius?: number;
  /** Far figures only within this many metres of the observer. */
  readonly farRadius?: number;
  /** Who draws a person in full; the catalog person unless a caller supplies another. */
  readonly factory?: CrowdRenderableFactory;
  /** Frames between poses for the full character at this nearness rank (0 is nearest). */
  readonly poseInterval?: PoseInterval;
}

export type PoseInterval = (rank: number) => number;

export interface CrowdCounts {
  readonly population: number;
  readonly outdoors: number;
  readonly indoors: number;
  readonly near: number;
  readonly far: number;
  readonly drawn: number;
}

type Point = readonly [number, number];

interface Walker {
  readonly id: string;
  /** What this person has still to walk, from where they were drawn when it was last extended. */
  readonly route: readonly Point[];
  readonly lengths: readonly number[];
  readonly total: number;
  /** Metres of `route` walked so far. */
  walked: number;
  /** Metres one tick allows, as the state records it, or null when it records no pace. */
  readonly budget: number | null;
  /**
   * For a v2 person, metres per millisecond: what they have still to walk spread evenly until the
   * next tick is expected. Null for a v4 person, who walks at their own recorded speed.
   */
  readonly rate: number | null;
  /** When a person standing still starts the walk just read, in the caller's clock. */
  readonly startsAtMs: number;
  readonly indoors: boolean;
  /** The activity the state says this person is performing, or null when it names none. */
  readonly activity: string | null;
  position: readonly [number, number];
  facing: number;
  /** Whether the path recorded for this tick has been walked to its end. */
  arrived: boolean;
}

/**
 * The inhabitants' share of the measured budget: everyone drawn in full counts, and the player's
 * own body holds its place whenever it is on screen (`PLAYER_NEAR_PLACES`).
 */
const NEAR_LIMIT = NEAR_INHABITANT_BUDGET;
const REFRESH_METRES = 4;
const DEFAULT_INTERVAL_MS = 1_850;
/** Two recorded points this close are one point: the state's unit is the millimetre. */
const SAME_POINT_METRES = 0.001;
/**
 * The fastest a person behind their recorded walk is drawn, as a multiple of their own pace. Half
 * again a walking pace still reads as walking briskly; beyond it a recorded walk would read as
 * running, which no state says anybody does.
 */
const CATCH_UP_SPEED_LIMIT = 1.5;
/**
 * The most recorded walking that may wait for a person, in ticks: the tick being walked and the one
 * just read. More would keep them walking in the past for longer than a tick, so they are carried
 * forward along their own path to the last tick's walk instead, as a named jump.
 */
const BEHIND_LIMIT_TICKS = 2;
/**
 * The nearest 4 are posed every frame, the next 8 every second frame and the rest every third.
 * Measured in the development preview at 1440x900: an abstract figure's pose costs about 0.53 ms of
 * main-thread time, almost all of it CPU skinning, and a catalog person's about 2.6 microseconds,
 * because the engine animates and skins every drawn person whether or not it was posed
 * (test/character-evidence/follow-saving-2026-09-17.log.txt). The cadence is what makes the abstract
 * figure affordable and costs a catalog person nothing it would notice.
 */
const POSE_INTERVAL: PoseInterval = (rank) => (rank < 4 ? 1 : rank < 12 ? 2 : 3);

interface PoseSlot {
  rank: number;
  pendingSeconds: number;
}

function polyline(path: readonly Point[]): { lengths: number[]; total: number } {
  const lengths = path.slice(1).map((p, i) => Math.hypot(p[0] - path[i]![0], p[1] - path[i]![1]));
  return { lengths, total: lengths.reduce((a, b) => a + b, 0) };
}

const apart = (a: Point, b: Point): number => Math.hypot(a[0] - b[0], a[1] - b[1]);

/** The part of a walker's route not yet walked, starting where it is drawn. */
function remainder(walker: Walker): Point[] {
  const rest: Point[] = [walker.position];
  let covered = 0;
  for (let i = 0; i < walker.lengths.length; i += 1) {
    covered += walker.lengths[i]!;
    if (covered > walker.walked) rest.push(walker.route[i + 1]!);
  }
  return rest;
}

/** Facing in radians about +Y with -Z forward, the renderable's convention; held when not moving. */
function heading(a: readonly [number, number], b: readonly [number, number], held: number): number {
  const dx = b[0] - a[0], dz = b[1] - a[1];
  return Math.hypot(dx, dz) < 1e-6 ? held : Math.atan2(-dx, -dz);
}

/** The activity a snapshot states for a person: the kind of an action that is under way. */
function stateActivity(person: SocietyInhabitantSnapshot): string | null {
  return person.action?.status === 'active' ? person.action.kind : null;
}

export class SocietyCrowd {
  private readonly factory: CrowdRenderableFactory;
  private readonly nearLimit: number;
  private readonly nearRadius: number;
  private readonly farRadius: number;
  private readonly far: FarFigures;
  private readonly near = new Map<string, CrowdRenderable>();
  private walkers = new Map<string, Walker>();
  private state: OwnedSocietyState | null = null;
  private scope = '';
  private tick = -1;
  private startedAtMs = 0;
  private intervalMs = DEFAULT_INTERVAL_MS;
  private startLagMs = 0;
  /** Whether anybody still has recorded walking to present. */
  private moving = false;
  private lastFrameMs = 0;
  /** Up to when every paced walker has been walked, in the caller's clock. */
  private lastWalkMs = 0;
  private jumpsRead: readonly CrowdJump[] = [];
  private observer: readonly [number, number] | null = null;
  private selectedId: string | null = null;
  /** The native runtime's own flag, read once per frame by `nativeFrames`. */
  private discontinuity = true;
  /** Renderables whose next pose must not be read as motion from wherever they were. */
  private readonly fresh = new Set<string>();
  private farIds: string[] = [];
  private readonly poseInterval: PoseInterval;
  /** Nearness rank and unposed time of each full character. */
  private readonly slots = new Map<string, PoseSlot>();
  private frame = 0;

  constructor(
    private readonly device: pc.GraphicsDevice,
    private readonly root: pc.Entity,
    options: CrowdOptions = {},
  ) {
    this.factory = options.factory ?? inhabitantRenderable;
    this.nearLimit = Math.max(0, Math.min(NEAR_LIMIT, options.nearLimit ?? NEAR_LIMIT));
    this.nearRadius = options.nearRadius ?? 60;
    this.farRadius = options.farRadius ?? 700;
    this.poseInterval = options.poseInterval ?? POSE_INTERVAL;
    this.far = new FarFigures(device, root);
  }

  /** Accept one canonical snapshot and start presenting its recorded motion. */
  set(
    state: OwnedSocietyState,
    observer?: readonly [number, number],
    options: CrowdTiming = {},
  ): CrowdCounts {
    const scope = `${state.society_id ?? 'preview'}:${state.branch_id ?? ''}`;
    if (scope !== this.scope) this.releaseNear();
    const continuing = scope === this.scope && this.state !== null;
    const consecutive = continuing && state.tick === this.tick + 1;
    const later = continuing && state.tick > this.tick;
    const unreadTicks = later ? state.tick - this.tick - 1 : 0;
    const nowMs = options.nowMs ?? performance.now();
    // Everyone is walked up to now first, so what is appended joins where they are drawn.
    if (continuing) this.place(nowMs, 0, false, false);
    // A person without a pace starts again from wherever the snapshot says; a paced person's
    // own jumps say when they do.
    if (!consecutive) {
      for (const [id, walker] of this.walkers) {
        if (walker.budget !== null && continuing) continue;
        this.discontinuity = true;
        if (this.near.has(id)) this.fresh.add(id);
      }
      if (!continuing) this.discontinuity = true;
    }
    this.scope = scope;
    this.tick = state.tick;
    this.state = state;
    if (observer) this.observer = observer;
    this.intervalMs = Math.max(1, options.intervalMs ?? DEFAULT_INTERVAL_MS);
    this.startLagMs = Math.max(0, options.startLagMs ?? 0);
    this.startedAtMs = nowMs;
    this.lastFrameMs = nowMs;
    this.lastWalkMs = nowMs;
    // Whether this snapshot records paths is read from the snapshot: every engine that reads its
    // input writes each person's path, and a legacy state carries none, so no profile is listed here.
    const pathful = state.inhabitants.every((person) => Array.isArray(person.motion_path_mm));
    const walkers = new Map<string, Walker>();
    const jumps: CrowdJump[] = [];
    for (const person of state.inhabitants) {
      if (person.synthetic !== true) continue;
      if (person.support_z_mm !== undefined && person.support_z_mm !== null) {
        throw new Error(
          `inhabitant ${person.id} stands on a surface at ${person.support_z_mm} mm and this crowd draws every walker on the ground plane`,
        );
      }
      const end = [person.position_mm[0] / 1000, person.position_mm[1] / 1000] as const;
      const recorded = person.motion_path_mm?.map(([x, z]) => [x / 1000, z / 1000] as const);
      const previous = continuing ? this.walkers.get(person.id) : undefined;
      const pace = person.walk_speed_mm_per_tick ?? state.movement_budget_mm_per_tick;
      const budget = pace === undefined ? null : pace / 1000;
      // A recorded speed is walked at; a recorded bound is only a bound (see the class comment).
      const spread = budget !== null && person.walk_speed_mm_per_tick === undefined;
      let route: readonly Point[];
      let walked = 0;
      let startsAtMs = nowMs;
      const jump = (reason: CrowdJumpReason, metres: number) => {
        if (metres <= SAME_POINT_METRES) return;
        jumps.push({ inhabitantId: person.id, reason, tick: state.tick, unreadTicks, metres });
        if (this.near.has(person.id)) this.fresh.add(person.id);
        this.discontinuity = true;
      };
      if (budget === null) {
        // Snapshots without a pace, without a supported path, or out of sequence, jump to the
        // recorded position.
        route = pathful && consecutive && recorded?.length ? recorded : [end];
      } else if (previous === undefined) {
        // Never drawn before: the person appears where the state says they are.
        route = [end];
      } else if (!later) {
        route = [end];
        jump('not-newer', apart(previous.position, end));
      } else if (!pathful || !recorded?.length) {
        route = [end];
        jump('no-recorded-path', apart(previous.position, end));
      } else if (apart(recorded[0]!, previous.route[previous.route.length - 1]!) <= SAME_POINT_METRES) {
        route = [...remainder(previous), ...recorded.slice(1)];
        const standing = previous.walked >= previous.total;
        // A spread walk already lasts until the next tick is expected, so it starts at once.
        startsAtMs = standing && !spread ? nowMs + this.startLagMs : spread ? nowMs : previous.startsAtMs;
      } else {
        route = recorded;
        startsAtMs = spread ? nowMs : nowMs + this.startLagMs;
        jump(consecutive ? 'path-starts-elsewhere' : 'minutes-not-read', apart(previous.position, recorded[0]!));
      }
      const { lengths, total } = polyline(route);
      if (budget !== null && total - walked > budget * BEHIND_LIMIT_TICKS) {
        const skipped = total - walked - budget;
        walked += skipped;
        jump('too-far-behind', skipped);
      }
      const walker: Walker = {
        id: person.id,
        route,
        lengths,
        total,
        walked,
        budget,
        rate: spread
          ? Math.min((total - walked) / (this.intervalMs + this.startLagMs), (CATCH_UP_SPEED_LIMIT * budget!) / this.intervalMs)
          : null,
        startsAtMs,
        indoors: person.indoors === true,
        activity: stateActivity(person),
        position: sampleMotionPath(route, total === 0 ? 1 : walked / total),
        facing: previous?.facing ?? 0,
        arrived: walked >= total,
      };
      walkers.set(person.id, walker);
    }
    this.walkers = walkers;
    this.jumpsRead = jumps;
    if (this.selectedId && !walkers.has(this.selectedId)) this.selectedId = null;
    this.assignDetail();
    this.place(nowMs, 1 / 60, false);
    return this.counts;
  }

  /**
   * Advance the presentation only; canonical positions change only through `set`.
   * `Number.MAX_SAFE_INTEGER` means reduced motion: show every recorded end point at once.
   */
  update(nowMs: number): void {
    if (!this.state) return;
    const reduced = nowMs === Number.MAX_SAFE_INTEGER;
    const dt = Math.max(0.001, Math.min(0.05, (nowMs - this.lastFrameMs) / 1000));
    this.lastFrameMs = reduced ? this.lastFrameMs : nowMs;
    this.place(nowMs, dt, reduced);
  }

  /** Re-choose who is near when the observer has moved; the population itself is untouched. */
  refresh(observer: readonly [number, number]): void {
    if (!this.state) return;
    const held = this.observer;
    if (held && Math.hypot(observer[0] - held[0], observer[1] - held[1]) < REFRESH_METRES) return;
    this.observer = observer;
    this.assignDetail();
  }

  clear(): void {
    this.state = null;
    this.walkers.clear();
    this.releaseNear();
    this.far.update([]);
    this.farIds = [];
    this.scope = '';
    this.tick = -1;
    this.moving = false;
    this.jumpsRead = [];
    this.observer = null;
    this.selectedId = null;
    this.discontinuity = true;
  }

  destroy(): void {
    this.clear();
    this.far.destroy();
  }

  /**
   * Whether anybody is still walking. A person without a recorded pace walks for one interval from
   * the snapshot; a paced person walks until the route read so far is walked.
   */
  get animating(): boolean {
    if (this.state === null || !this.moving) return false;
    for (const walker of this.walkers.values()) {
      if (walker.budget !== null && !walker.arrived) return true;
    }
    return performance.now() - this.startedAtMs < this.intervalMs;
  }

  /** Every person the latest snapshot moved without walking, and why; empty when nobody. */
  get jumps(): readonly CrowdJump[] {
    return this.jumpsRead;
  }

  get counts(): CrowdCounts {
    let indoors = 0;
    for (const walker of this.walkers.values()) if (walker.indoors) indoors += 1;
    return {
      population: this.walkers.size,
      outdoors: this.walkers.size - indoors,
      indoors,
      near: this.near.size,
      far: this.farIds.length,
      drawn: this.near.size + this.farIds.length,
    };
  }

  /** Every inhabitant currently drawn, near or far, in stable order. */
  get drawnIds(): readonly string[] {
    return [...this.near.keys(), ...this.farIds];
  }

  detailOf(id: string): 'near' | 'far' | 'indoors' | 'not-drawn' {
    if (this.near.has(id)) return 'near';
    if (this.farIds.includes(id)) return 'far';
    if (this.walkers.get(id)?.indoors) return 'indoors';
    return 'not-drawn';
  }

  positionOf(id: string): readonly [number, number] | null {
    return this.walkers.get(id)?.position ?? null;
  }

  /** What an inhabitant's far figure draws: the far form of that person's own look. */
  farAppearance(id: string): FarAppearance {
    return this.far.appearanceOf(id);
  }

  /** The activity drawn for an inhabitant now: the state's, once its recorded path is walked. */
  activityOf(id: string): string | null {
    const walker = this.walkers.get(id);
    return walker?.arrived ? walker.activity : null;
  }

  /** Inhabitants presented at exactly this inhabitant's point, including itself. */
  sharing(id: string): readonly string[] {
    const held = this.walkers.get(id);
    if (!held || held.indoors) return held ? [id] : [];
    return [...this.walkers.values()]
      .filter((w) => !w.indoors && Math.hypot(w.position[0] - held.position[0], w.position[1] - held.position[1]) < 0.001)
      .map((w) => w.id);
  }

  /** Keep a selected inhabitant as a full character while it is outdoors. */
  select(id: string): void {
    if (!this.walkers.has(id)) return;
    this.selectedId = id;
    this.assignDetail();
  }

  representation(id: string) {
    return this.near.get(id)?.representation ?? null;
  }

  /**
   * Geometry the drawn crowd is responsible for: the far figures, whatever each full character owns
   * outright, and what the shared character host holds for everyone composed from the catalog.
   * A renderable that draws from shared containers reports no bytes of its own, so adding only the
   * renderables would miss those people entirely, and asking each of them for the shared total
   * would count one container once per person.
   */
  get residentBytes(): number {
    let bytes = this.far.residentBytes;
    for (const renderable of this.near.values()) bytes += renderable.residentBytes ?? 0;
    return bytes + CharacterHost.residentFor(this.device).geometryBytes;
  }

  get textureResidentBytes(): number {
    let bytes = this.far.textureResidentBytes;
    for (const renderable of this.near.values()) bytes += renderable.textureResidentBytes ?? 0;
    return bytes + CharacterHost.residentFor(this.device).textureBytes;
  }

  nativeFrames(deltaSeconds: number, reducedMotion: boolean): readonly NativeCharacterFrame[] {
    const discontinuity = this.discontinuity;
    this.discontinuity = false;
    return [...this.near.values()].map((renderable) => {
      const p = renderable.root.getLocalPosition();
      return {
        subject: renderable.subject,
        parent: this.root,
        fallback: renderable.root,
        visible: renderable.root.enabled,
        position: [p.x, p.y, p.z],
        yaw: renderable.facing,
        deltaSeconds,
        reducedMotion,
        discontinuity,
      };
    });
  }

  /** The nearest drawn inhabitant whose box `hit` meets before `limit`, near or far. */
  pick(
    limit: number,
    hit: (min: readonly [number, number, number], max: readonly [number, number, number]) => number | null,
  ): string | null {
    let nearest = limit;
    let selected: string | null = null;
    // A selected inhabitant wins a tie with anyone standing on the same point.
    const chosen = this.selectedId;
    const order = chosen && this.near.has(chosen)
      ? [chosen, ...this.drawnIds.filter((id) => id !== chosen)]
      : this.drawnIds;
    for (const id of order) {
      const renderable = this.near.get(id);
      if (renderable && (!renderable.root.enabled || renderable.root.tags.has('native-character-hidden'))) continue;
      const walker = this.walkers.get(id);
      if (!walker) continue;
      const [x, z] = walker.position;
      const height = renderable?.standingHeight ?? this.far.appearanceOf(id).heightMetres;
      const distance = hit([x - 0.34, 0, z - 0.34], [x + 0.34, height, z + 0.34]);
      if (distance !== null && distance < nearest) {
        nearest = distance;
        selected = id;
      }
    }
    return selected;
  }

  private releaseNear(): void {
    for (const renderable of this.near.values()) renderable.destroy();
    this.near.clear();
    this.slots.clear();
    this.fresh.clear();
  }

  private assignDetail(): void {
    const observer = this.observer;
    const outdoors = [...this.walkers.values()].filter((w) => !w.indoors);
    const distance = (w: Walker) =>
      observer ? Math.hypot(w.position[0] - observer[0], w.position[1] - observer[1]) : 0;
    const ranked = outdoors
      .map((w) => ({ w, d: distance(w) }))
      .sort((a, b) => a.d - b.d || (a.w.id < b.w.id ? -1 : 1));
    const nearIds = new Set<string>();
    const selected = this.selectedId ? this.walkers.get(this.selectedId) : undefined;
    if (selected && !selected.indoors && this.nearLimit > 0) nearIds.add(selected.id);
    for (const { w, d } of ranked) {
      if (nearIds.size >= this.nearLimit) break;
      if (d <= this.nearRadius) nearIds.add(w.id);
    }
    for (const [id, renderable] of this.near) {
      if (!nearIds.has(id)) {
        renderable.destroy();
        this.near.delete(id);
        this.slots.delete(id);
        this.fresh.delete(id);
      }
    }
    const identity = { societyId: this.state?.society_id ?? 'preview', branchId: this.state?.branch_id ?? 'preview' };
    let rank = 0;
    for (const id of nearIds) {
      const slot = this.slots.get(id);
      if (slot) slot.rank = rank;
      else this.slots.set(id, { rank, pendingSeconds: 0 });
      rank += 1;
      if (this.near.has(id)) continue;
      const renderable = this.factory(this.device, this.root, { ...identity, inhabitantId: id }, 'near');
      const walker = this.walkers.get(id)!;
      // Posed at once, so a new full character is drawn and pickable before the next frame.
      renderable.setVisible(!walker.indoors);
      const pose: CharacterPose = {
        position: [walker.position[0], 0, walker.position[1]],
        yaw: walker.facing,
        deltaSeconds: 1 / 60,
        discontinuity: true,
        activity: walker.arrived ? walker.activity : null,
      };
      renderable.pose(pose);
      this.near.set(id, renderable);
      this.discontinuity = true;
    }
    this.farIds = ranked.filter(({ w, d }) => !nearIds.has(w.id) && d <= this.farRadius).map(({ w }) => w.id);
  }

  private place(nowMs: number, dt: number, reduced: boolean, draw = true): void {
    const elapsed = reduced ? Number.POSITIVE_INFINITY : Math.max(0, nowMs - this.startedAtMs);
    const fraction = Math.min(1, elapsed / this.intervalMs);
    const eased = fraction * fraction * (3 - 2 * fraction);
    const walkedFrom = this.lastWalkMs;
    if (!reduced) this.lastWalkMs = Math.max(this.lastWalkMs, nowMs);
    let moving = false;
    for (const walker of this.walkers.values()) {
      if (walker.total > 0) {
        if (reduced) walker.walked = walker.total;
        else if (walker.budget === null) walker.walked = eased * walker.total;
        else {
          const walking = nowMs - Math.max(walkedFrom, walker.startsAtMs);
          if (walking > 0 && walker.rate !== null) {
            walker.walked = Math.min(walker.total, walker.walked + walker.rate * walking);
          } else if (walking > 0) {
            const pace = walker.budget / this.intervalMs;
            // Behind by more than a tick and the wait for the next, the person walks faster.
            const behindMs = (walker.total - walker.walked) / pace;
            const speed = pace * Math.min(CATCH_UP_SPEED_LIMIT, Math.max(1, behindMs / (this.intervalMs + this.startLagMs)));
            walker.walked = Math.min(walker.total, walker.walked + speed * walking);
          }
        }
      }
      const position = walker.total > 0 ? sampleMotionPath(walker.route, walker.walked / walker.total) : walker.route[0]!;
      walker.facing = heading(walker.position, position, walker.facing);
      walker.position = position;
      walker.arrived = walker.walked >= walker.total;
      moving ||= !walker.arrived;
    }
    this.moving = moving;
    if (!draw) return;
    this.frame += 1;
    for (const [id, renderable] of this.near) {
      const walker = this.walkers.get(id)!;
      const slot = this.slots.get(id)!;
      const position = [walker.position[0], 0, walker.position[1]] as const;
      const discontinuity = this.fresh.delete(id);
      renderable.setVisible(!walker.indoors);
      slot.pendingSeconds += dt;
      // Frames, not seconds: a slow frame must not make more posing due. The gait advances by
      // the distance walked since the last pose, so a longer gap costs update rate, not stride.
      const interval = id === this.selectedId ? 1 : Math.max(1, Math.floor(this.poseInterval(slot.rank)));
      const due = discontinuity || !renderable.follow || interval === 1 || (this.frame + slot.rank) % interval === 0;
      if (due) {
        const pose: CharacterPose = {
          position,
          yaw: walker.facing,
          deltaSeconds: slot.pendingSeconds,
          reducedMotion: reduced,
          discontinuity,
          activity: walker.arrived ? walker.activity : null,
        };
        renderable.pose(pose);
        slot.pendingSeconds = 0;
      } else {
        renderable.follow!(position);
      }
    }
    this.far.update(
      this.farIds.map((id) => {
        const walker = this.walkers.get(id)!;
        return {
          id,
          x: walker.position[0],
          z: walker.position[1],
          facing: walker.facing,
          activity: walker.arrived ? walker.activity : null,
        };
      }),
      dt,
      reduced,
    );
  }
}
