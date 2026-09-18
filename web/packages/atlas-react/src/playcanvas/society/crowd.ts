import type * as pc from 'playcanvas';
import type { NativeCharacterFrame } from '../native-character-runtime.js';
import { sampleMotionPath } from '../society-presentation.js';
import { FarFigures } from './far-figures.js';
import { abstractInhabitantRenderable } from './near-character.js';
import { NEAR_CHARACTER_BUDGET } from '../character/budget.js';
import { CharacterHost } from '../character/host.js';
import type { CrowdRenderable, CrowdRenderableFactory, OwnedSocietyState } from './types.js';

/**
 * The whole synthetic population, drawn by distance.
 *
 * The population is canonical state and is never truncated here. Every outdoor inhabitant is
 * placed along its own recorded motion path; the nearest are full characters and everyone
 * else is a simple far figure of the same person. People inside premises are counted, not drawn,
 * because interiors are not rendered. Two people standing on the same point are both drawn
 * there: where a society puts people is the simulation's occupancy rule, not the renderer's.
 *
 * Motion follows the recorded path only. A v4 inhabitant walks from the start of the tick at its
 * own recorded speed and stops where the path ends; an older snapshot without a speed is eased
 * along its path over the whole interval. No position is invented between path points.
 *
 * Everyone is drawn on the ground plane. A recorded point is a plan point and the height each
 * walker is drawn at is 0, which is the ground a tile bake draws; a person who states the height
 * of the surface they stand on is refused rather than drawn under it. When a place's stated
 * heights are wired through to a person, that refusal is what says the ground-plane zeros here
 * and in the far figures must be read from the person instead of written.
 *
 * Detail by distance applies to time as well as shape. Every drawn inhabitant is placed at its
 * recorded point every frame, but a full character's limbs are solved and skinned on the CPU, so
 * only the nearest few are posed every frame; the rest are posed every second or third frame and
 * carried to their recorded point in between. A selected inhabitant is posed every frame.
 */
export interface CrowdOptions {
  /** Full characters at most; the measured character budget (NEAR_CHARACTER_BUDGET) is the ceiling. */
  readonly nearLimit?: number;
  /** Full characters only within this many metres of the observer. */
  readonly nearRadius?: number;
  /** Far figures only within this many metres of the observer. */
  readonly farRadius?: number;
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

interface Walker {
  readonly id: string;
  readonly path: readonly (readonly [number, number])[];
  readonly lengths: readonly number[];
  readonly total: number;
  /** Metres per interval, or null when the snapshot records no speed. */
  readonly speed: number | null;
  readonly indoors: boolean;
  position: readonly [number, number];
  facing: number;
}

/** The measured ceiling on people drawn in full at once, the player's own body included. */
const NEAR_LIMIT = NEAR_CHARACTER_BUDGET;
const REFRESH_METRES = 4;
const DEFAULT_INTERVAL_MS = 1_850;
/**
 * The nearest 4 are posed every frame, the next 8 every second frame and the rest every third:
 * 12 poses a frame instead of 24. Measured in the preview at 1440x900, one abstract character's
 * pose costs about 0.53 ms of main-thread time, almost all of it CPU skinning, so posing all 24
 * every frame left the main thread busy for nearly the whole 16.7 ms frame.
 */
const POSE_INTERVAL: PoseInterval = (rank) => (rank < 4 ? 1 : rank < 12 ? 2 : 3);

interface PoseSlot {
  rank: number;
  pendingSeconds: number;
}

function polyline(path: readonly (readonly [number, number])[]): { lengths: number[]; total: number } {
  const lengths = path.slice(1).map((p, i) => Math.hypot(p[0] - path[i]![0], p[1] - path[i]![1]));
  return { lengths, total: lengths.reduce((a, b) => a + b, 0) };
}

function heading(a: readonly [number, number], b: readonly [number, number], held: number): number {
  const dx = b[0] - a[0], dz = b[1] - a[1];
  return Math.hypot(dx, dz) < 1e-6 ? held : Math.atan2(dx, dz);
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
  private moving = false;
  private lastFrameMs = 0;
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
    this.factory = options.factory ?? abstractInhabitantRenderable;
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
    options: { readonly intervalMs?: number; readonly nowMs?: number } = {},
  ): CrowdCounts {
    const scope = `${state.society_id ?? 'preview'}:${state.branch_id ?? ''}`;
    if (scope !== this.scope) this.releaseNear();
    const consecutive = scope === this.scope && state.tick === this.tick + 1;
    if (!consecutive) {
      this.discontinuity = true;
      for (const id of this.near.keys()) this.fresh.add(id);
    }
    this.scope = scope;
    this.tick = state.tick;
    this.state = state;
    if (observer) this.observer = observer;
    this.intervalMs = Math.max(1, options.intervalMs ?? DEFAULT_INTERVAL_MS);
    this.startedAtMs = options.nowMs ?? performance.now();
    this.lastFrameMs = this.startedAtMs;
    const pathful = state.profile === 'exulanica-society/v2' || state.profile === 'exulanica-society/v4';
    const walkers = new Map<string, Walker>();
    let moving = false;
    for (const person of state.inhabitants) {
      if (person.synthetic !== true) continue;
      if (person.support_z_mm !== undefined && person.support_z_mm !== null) {
        throw new Error(
          `inhabitant ${person.id} stands on a surface at ${person.support_z_mm} mm and this crowd draws every walker on the ground plane`,
        );
      }
      const end = [person.position_mm[0] / 1000, person.position_mm[1] / 1000] as const;
      const recorded = person.motion_path_mm?.map(([x, z]) => [x / 1000, z / 1000] as const);
      // Snapshots without a supported path, or out of sequence, jump to the recorded position.
      const path = pathful && consecutive && recorded?.length ? recorded : [end];
      const { lengths, total } = polyline(path);
      const previous = this.walkers.get(person.id);
      const walker: Walker = {
        id: person.id,
        path,
        lengths,
        total,
        speed: person.walk_speed_mm_per_tick === undefined ? null : person.walk_speed_mm_per_tick / 1000,
        indoors: person.indoors === true,
        position: path[0]!,
        facing: previous?.facing ?? 0,
      };
      moving ||= total > 0;
      walkers.set(person.id, walker);
    }
    this.walkers = walkers;
    this.moving = moving;
    if (this.selectedId && !walkers.has(this.selectedId)) this.selectedId = null;
    this.assignDetail();
    this.place(this.startedAtMs, 1 / 60, false);
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
    this.observer = null;
    this.selectedId = null;
    this.discontinuity = true;
  }

  destroy(): void {
    this.clear();
    this.far.destroy();
  }

  get animating(): boolean {
    return this.state !== null && this.moving && performance.now() - this.startedAtMs < this.intervalMs;
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
    let bytes = 0;
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
      const height = renderable?.standingHeight ?? 1.8;
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
      renderable.pose({
        position: [walker.position[0], 0, walker.position[1]],
        deltaSeconds: 1 / 60,
        discontinuity: true,
      });
      this.near.set(id, renderable);
      this.discontinuity = true;
    }
    this.farIds = ranked.filter(({ w, d }) => !nearIds.has(w.id) && d <= this.farRadius).map(({ w }) => w.id);
  }

  private place(nowMs: number, dt: number, reduced: boolean): void {
    const elapsed = reduced ? Number.POSITIVE_INFINITY : Math.max(0, nowMs - this.startedAtMs);
    const fraction = Math.min(1, elapsed / this.intervalMs);
    const eased = fraction * fraction * (3 - 2 * fraction);
    for (const walker of this.walkers.values()) {
      let position = walker.path[walker.path.length - 1]!;
      if (walker.total > 0 && Number.isFinite(elapsed)) {
        const travelled = walker.speed === null ? eased : Math.min(1, (fraction * walker.speed) / walker.total);
        position = sampleMotionPath(walker.path, travelled);
      }
      walker.facing = heading(walker.position, position, walker.facing);
      walker.position = position;
    }
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
        renderable.pose({ position, deltaSeconds: slot.pendingSeconds, reducedMotion: reduced, discontinuity });
        slot.pendingSeconds = 0;
      } else {
        renderable.follow!(position);
      }
    }
    this.far.update(
      this.farIds.map((id) => {
        const walker = this.walkers.get(id)!;
        return { id, x: walker.position[0], z: walker.position[1], facing: walker.facing };
      }),
    );
  }
}
