import type * as pc from 'playcanvas';
import type { NativeCharacterFrame } from '../native-character-runtime.js';
import { sampleMotionPath } from '../society-presentation.js';
import { FarFigures } from './far-figures.js';
import { NEAR_INHABITANT_BUDGET } from '../character/budget.js';
import { CharacterHost } from '../character/host.js';
import { inhabitantRenderable } from '../character/inhabitant.js';
import type { CharacterPose } from '../character/renderable.js';
import { postureSeatMetres, type FarAppearance } from '../character/far.js';
import { POSTURE_BLEND_SECONDS } from '../character/person.js';
import { placeDrawing, seatApproach, type PlaceDrawing, type SeatingLayout, type SeatingMiss } from './seating.js';
import { facingRule, type FacingRule } from './activity-facing.js';
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
 * their speed. A v2 person whose newly read minute adds nothing to walk finishes what is left at no
 * slower than their own walking pace (`FarFigures.walkSpeedOf`): spreading a walk to the next minute
 * keeps it continuous into that minute's walk, and with none to continue into, a remainder spread
 * again each minute would shrink without ever ending, and they would never arrive to do anything. Anything else, a path that starts somewhere the person was not, minutes this crowd
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
 * Everyone walks on the ground plane. A recorded point is a plan point and the height each
 * walker is drawn at is 0, which is the ground a tile bake draws; a person who states the height
 * of the surface they stand on is refused rather than drawn under it. When a place's stated
 * heights are wired through to a person, that refusal is what says the ground-plane zeros here
 * and in the far figures must be read from the person instead of written.
 *
 * A person using a placed object is drawn as its kind says, from the seating layout handed with
 * the snapshot (`./seating.ts`): once their recorded path is walked, and while their state names
 * the action they are at, under way or just completed, they face as that activity's rule says
 * (`./activity-facing.ts`), and where the place has a seat and the catalog draws their activity
 * under way on one, they sit on it. Sitting down is one timeline: they walk at their own pace from
 * the place to where they stand before the seat (`seatApproach`), in front of it or beside it, then
 * turn and lower onto it over the posture's own blend, pelvis on the seat and, in full, feet planted
 * on the ground; getting up runs the same timeline backward before they walk on. The move is
 * presentation: their position, and every answer about where they are, stays the recorded place.
 * Moved without walking (a named jump), they drop the seat at once rather than glide from it.
 * Anyone whose place cannot be found is drawn by the rule above, and the reason is named
 * (`seatingMisses`). A layout handed later (`setLayout`) finds everyone's place again, so a seat
 * that is moved or taken away is got up from without waiting for the next state.
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
  /** How the object this person's action uses is drawn at their place, or null for none. */
  place: PlaceDrawing | null;
  /**
   * How the action the person is at faces (`ACTIVITY_FACING`), under way or just completed, or
   * null for none or an activity with no rule.
   */
  readonly facingRule: FacingRule | null;
  /** The partner the state names for the activity, or null. */
  readonly partnerId: string | null;
  /** The target their action names, under way or just completed, or null. */
  readonly target: string | null;
  /** Their recorded position, millimetres, which their place is found from. */
  readonly recordedMm: readonly [number, number];
  /** Their walk to a seat and onto it, or null when they are nowhere near sitting. */
  settle: Settle | null;
  /** How far onto their seat they are drawn, from 0 standing to 1 seated. */
  seatBlend: number;
  /** Whether they are drawn in the seat posture: lowering onto the seat or sitting on it. */
  onSeat: boolean;
  /** Where they are drawn this frame: east, height of the root, south. */
  drawn: readonly [number, number, number];
}

/**
 * Sitting down as one path: the place, where the person stands before the seat, and the seat, in
 * plan metres, walked at their own pace to the second point and lowered onto the seat over the
 * posture's blend. `progress` is metres along it; getting up walks it back to 0.
 */
interface Settle {
  readonly path: readonly [Point, Point, Point];
  /** Metres from the place to where they stand before the seat, and from there onto it. */
  readonly toFront: number;
  readonly ontoSeat: number;
  /** Height of the root on the seat. */
  readonly lift: number;
  /** Facing on the seat. */
  readonly facing: number;
  /** Which object's which place the seat belongs to. */
  readonly key: string;
  /** Metres per second they walk the first part at. */
  readonly walkSpeed: number;
  progress: number;
}

/**
 * An inhabitant drawn as everyone else is although their state says what they are doing, and why:
 * a place that was not found (`SeatingMiss`), or an activity with no facing rule.
 */
export interface CrowdSeatingMiss {
  readonly inhabitantId: string;
  readonly reason: SeatingMiss | 'activity-has-no-facing';
}

/**
 * The inhabitants' share of the measured budget: everyone drawn in full counts, and the player's
 * own body holds its place whenever it is on screen (`PLAYER_NEAR_PLACES`).
 */
const NEAR_LIMIT = NEAR_INHABITANT_BUDGET;
const REFRESH_METRES = 4;
const DEFAULT_INTERVAL_MS = 1_850;
const MILLISECONDS_PER_SECOND = 1000;
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

/**
 * The action a person is at: one under way, or one just completed where they still stand, as a
 * visit is completed within the minute its visitor arrives. A blocked action is none.
 */
function stateAction(person: SocietyInhabitantSnapshot): { kind: string; target: string | null } | null {
  const action = person.action;
  if (action?.status !== 'active' && action?.status !== 'completed') return null;
  return { kind: action.kind, target: action.target_id ?? null };
}

/** The partner a person's goal names, for a state whose goals name one. */
function statePartner(person: SocietyInhabitantSnapshot): string | null {
  const goal: object | null | undefined = person.goal;
  if (!goal || !('partner_id' in goal)) return null;
  return typeof goal.partner_id === 'string' ? goal.partner_id : null;
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
  private missesRead: readonly CrowdSeatingMiss[] = [];
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
    layout: SeatingLayout | null = null,
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
    const misses: CrowdSeatingMiss[] = [];
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
      let jumped = false;
      const jump = (reason: CrowdJumpReason, metres: number) => {
        if (metres <= SAME_POINT_METRES) return;
        jumped = true;
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
      // What this minute adds to their walk: nothing for a person staying where they are.
      const adds = recorded && recorded.length > 1 ? polyline(recorded).total : 0;
      if (budget !== null && total - walked > budget * BEHIND_LIMIT_TICKS) {
        const skipped = total - walked - budget;
        walked += skipped;
        jump('too-far-behind', skipped);
      }
      const activity = stateActivity(person);
      const at = stateAction(person);
      const rule = at === null ? null : facingRule(at.kind);
      const target = layout === null ? null : at?.target ?? null;
      const found = target === null ? null : placeDrawing(layout!, target, person.position_mm);
      if (found?.kind === 'miss') misses.push({ inhabitantId: person.id, reason: found.reason });
      if (layout !== null && at !== null && rule === null) {
        misses.push({ inhabitantId: person.id, reason: 'activity-has-no-facing' });
      }
      const position = sampleMotionPath(route, total === 0 ? 1 : walked / total);
      const walker: Walker = {
        id: person.id,
        route,
        lengths,
        total,
        walked,
        budget,
        rate: spread
          ? Math.min(
            Math.max(
              (total - walked) / (this.intervalMs + this.startLagMs),
              adds <= SAME_POINT_METRES ? this.far.walkSpeedOf(person.id) / MILLISECONDS_PER_SECOND : 0,
            ),
            (CATCH_UP_SPEED_LIMIT * budget!) / this.intervalMs,
          )
          : null,
        startsAtMs,
        indoors: person.indoors === true,
        activity,
        position,
        facing: previous?.facing ?? 0,
        arrived: walked >= total,
        place: found?.kind === 'place' ? found.drawing : null,
        facingRule: rule,
        partnerId: statePartner(person),
        target: at?.target ?? null,
        recordedMm: person.position_mm,
        // Moved without walking, they are drawn where they now are, off any seat at once.
        settle: jumped ? null : previous?.settle ?? null,
        seatBlend: jumped ? 0 : previous?.seatBlend ?? 0,
        onSeat: jumped ? false : previous?.onSeat ?? false,
        drawn: jumped || previous === undefined ? [position[0], 0, position[1]] : previous.drawn,
      };
      walkers.set(person.id, walker);
    }
    this.walkers = walkers;
    this.jumpsRead = jumps;
    this.missesRead = misses;
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
    this.missesRead = [];
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

  /**
   * Everyone in the latest snapshot using an object whose place the layout could not find, and
   * why; they are drawn as everyone else is. Empty when nobody, or when no layout was handed.
   */
  get seatingMisses(): readonly CrowdSeatingMiss[] {
    return this.missesRead;
  }

  /** Whether an inhabitant is drawn settling onto, or sitting on, a seat. */
  seatedOn(id: string): boolean {
    const walker = this.walkers.get(id);
    return walker !== undefined && this.wantsSeat(walker);
  }

  /**
   * Whether an inhabitant's activity is drawn on a seat once they reach it: their place has one
   * and the catalog draws the activity on it, whether or not they have arrived.
   */
  seatAtPlace(id: string): boolean {
    const walker = this.walkers.get(id);
    return walker !== undefined && this.seatable(walker);
  }

  /**
   * Find everyone's place again from a layout drawn after the latest state, as when an object is
   * moved or removed: a person whose seat is gone gets up from it now, not at the next minute.
   * Everything else about them stays as the latest state has it.
   */
  setLayout(layout: SeatingLayout | null): void {
    const misses: CrowdSeatingMiss[] = this.missesRead.filter((miss) => miss.reason === 'activity-has-no-facing');
    for (const walker of this.walkers.values()) {
      const found = layout === null || walker.target === null ? null : placeDrawing(layout, walker.target, walker.recordedMm);
      if (found?.kind === 'miss') misses.push({ inhabitantId: walker.id, reason: found.reason });
      walker.place = found?.kind === 'place' ? found.drawing : null;
    }
    this.missesRead = misses;
    this.moving = true;
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
    return walker === undefined ? null : this.drawnActivity(walker);
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
      const [x, y, z] = walker.drawn;
      const height = renderable?.standingHeight ?? this.far.appearanceOf(id).heightMetres;
      const distance = hit([x - 0.34, y, z - 0.34], [x + 0.34, y + height, z + 0.34]);
      if (distance !== null && distance < nearest) {
        nearest = distance;
        selected = id;
      }
    }
    return selected;
  }

  /** Whether a walker's activity is drawn on the seat of their place, arrived or not. */
  private seatable(walker: Walker): boolean {
    if (walker.activity === null || walker.place?.seat == null || walker.indoors) return false;
    if (this.near.has(walker.id) && this.near.get(walker.id)!.drawsSeats !== true) return false;
    return this.far.seatPostureOf(walker.id, walker.activity) !== null;
  }

  /** Whether a walker is to be drawn on a seat: at their place, with a seat the catalog draws on. */
  private wantsSeat(walker: Walker): boolean {
    return walker.arrived && this.seatable(walker);
  }

  /**
   * Turn a walker to face what their place says, and move them one frame along their walk to their
   * seat and onto it, or back off it. Returns whether they are still on the way.
   */
  private settle(walker: Walker, dt: number, reduced: boolean): boolean {
    const wanted = this.wantsSeat(walker);
    const place = walker.place;
    const key = wanted ? `${place!.objectId}:${place!.placeIndex}` : null;
    if (wanted && walker.settle === null) {
      const seat = place!.seat!;
      const posture = this.far.seatPostureOf(walker.id, walker.activity)!;
      const at: Point = [seat.position[0], seat.position[2]];
      const front = seatApproach(at, seat.facing, walker.position);
      walker.settle = {
        path: [walker.position, front, at],
        toFront: apart(walker.position, front),
        ontoSeat: apart(front, at),
        lift: seat.position[1] - postureSeatMetres(this.far.appearanceOf(walker.id), posture),
        facing: seat.facing,
        key: key!,
        walkSpeed: this.far.walkSpeedOf(walker.id),
        progress: 0,
      };
    }
    const settle = walker.settle;
    if (settle === null) {
      walker.drawn = [walker.position[0], 0, walker.position[1]];
      walker.seatBlend = 0;
      walker.onSeat = false;
      if (walker.arrived) walker.facing = this.facingOf(walker);
      return false;
    }
    // A seat that is no longer theirs, or no longer there, is got up from before another is sat on.
    const staying = wanted && settle.key === key;
    const end = settle.toFront + settle.ontoSeat;
    const goal = staying ? end : 0;
    const before = settle.progress;
    if (reduced) settle.progress = goal;
    else {
      let left = dt;
      while (left > 0 && settle.progress !== goal) {
        // The walk to the seat at their own pace; lowering onto it, or rising, over the posture's blend.
        const rising = goal < settle.progress;
        const walking = rising ? settle.progress <= settle.toFront : settle.progress < settle.toFront;
        const speed = walking ? settle.walkSpeed : settle.ontoSeat / POSTURE_BLEND_SECONDS;
        const edge = rising ? (walking ? 0 : settle.toFront) : (walking ? settle.toFront : end);
        const reach = Math.abs(edge - settle.progress);
        if (!(speed > 0)) {
          settle.progress = edge;
          continue;
        }
        const step = Math.min(reach, speed * left);
        settle.progress = step === reach ? edge : settle.progress + (rising ? -step : step);
        left -= step / speed;
      }
    }
    const onto = settle.ontoSeat > 0
      ? Math.min(1, Math.max(0, (settle.progress - settle.toFront) / settle.ontoSeat))
      : (settle.progress >= end ? 1 : 0);
    const [x, z] = sampleMotionPath(settle.path, end > 0 ? settle.progress / end : 1);
    walker.drawn = [x, settle.lift * onto, z];
    walker.seatBlend = onto;
    walker.onSeat = staying && settle.progress >= settle.toFront;
    if (settle.progress > settle.toFront || walker.onSeat) {
      walker.facing = settle.facing;
    } else if (settle.progress !== before) {
      // Walking to where they stand before the seat, or back to their place, they face the way they go.
      walker.facing = goal > before
        ? heading(settle.path[0], settle.path[1], walker.facing)
        : heading(settle.path[1], settle.path[0], walker.facing);
    }
    if (settle.progress <= 0 && !staying) {
      walker.settle = null;
      if (walker.arrived) walker.facing = this.facingOf(walker);
      return false;
    }
    return settle.progress !== goal;
  }

  /** The way a walker standing at the end of their path faces, by their activity's rule. */
  private facingOf(walker: Walker): number {
    if (walker.facingRule === 'place' && walker.place !== null) return walker.place.facing;
    if (walker.facingRule === 'partner' && walker.partnerId !== null) {
      const partner = this.walkers.get(walker.partnerId);
      if (partner !== undefined && !partner.indoors) return heading(walker.position, partner.position, walker.facing);
    }
    return walker.facing;
  }

  /**
   * The activity a walker is drawn doing: the state's once their path is walked, and none while
   * they walk to a seat or back from it, when they are on their feet.
   */
  private drawnActivity(walker: Walker): string | null {
    if (!walker.arrived) return null;
    // Someone whose activity is drawn on a seat is on their feet until they are on it.
    return (walker.settle !== null || this.seatable(walker)) && !walker.onSeat ? null : walker.activity;
  }

  /** Where and how a full character is posed for a walker, apart from its timing. */
  private poseOf(walker: Walker): Omit<CharacterPose, 'deltaSeconds'> {
    const seated = walker.onSeat;
    return {
      position: walker.drawn,
      yaw: walker.facing,
      activity: this.drawnActivity(walker),
      ...(seated ? { seated } : {}),
      ...(walker.drawn[1] !== 0 ? { groundY: 0 } : {}),
    };
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
      renderable.pose({ ...this.poseOf(walker), deltaSeconds: 1 / 60, discontinuity: true });
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
      // Someone getting up from a seat walks on once they are back at their place.
      if (walker.total > 0 && walker.settle === null) {
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
      const settling = this.settle(walker, dt, reduced);
      moving ||= !walker.arrived || settling;
    }
    this.moving = moving;
    if (!draw) return;
    this.frame += 1;
    for (const [id, renderable] of this.near) {
      const walker = this.walkers.get(id)!;
      const slot = this.slots.get(id)!;
      const position = walker.drawn;
      const discontinuity = this.fresh.delete(id);
      renderable.setVisible(!walker.indoors);
      slot.pendingSeconds += dt;
      // Frames, not seconds: a slow frame must not make more posing due. The gait advances by
      // the distance walked since the last pose, so a longer gap costs update rate, not stride.
      const interval = id === this.selectedId ? 1 : Math.max(1, Math.floor(this.poseInterval(slot.rank)));
      // Someone above the ground has their feet planted afresh on every frame the clip moves them.
      const due = discontinuity || !renderable.follow || interval === 1 || position[1] !== 0 ||
        (this.frame + slot.rank) % interval === 0;
      if (due) {
        renderable.pose({ ...this.poseOf(walker), deltaSeconds: slot.pendingSeconds, reducedMotion: reduced, discontinuity });
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
          x: walker.drawn[0],
          y: walker.drawn[1],
          z: walker.drawn[2],
          facing: walker.facing,
          activity: this.drawnActivity(walker),
          seated: walker.onSeat,
        };
      }),
      dt,
      reduced,
    );
  }
}
