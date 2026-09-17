/**
 * DEVELOPMENT EVALUATION: catalog inhabitants standing and walking beside the player.
 *
 * Nobody here is a member of any society and nothing here decides where a person goes: the
 * figures follow fixed lanes so their bodies, clothing, gait, turns and stops can be looked at in
 * the real world, under its light, from the player's own camera. Every figure comes from
 * `inhabitantRenderable`, the one function the society display calls, so what is seen here is what
 * a living district draws. The app mounts this only on the development preview route.
 */
import * as pc from 'playcanvas';
import { inhabitantRenderable } from './inhabitant.js';
import type { CharacterDetail } from './look.js';
import type { CharacterRenderable } from './renderable.js';

/** The members of an Atlas binding this evaluation reads. */
export interface CrowdEvaluationHost {
  readonly app: pc.AppBase;
  readonly device: pc.GraphicsDevice;
  readonly environmentRoot: pc.Entity;
  readonly controls: { readonly state: { readonly x: number; readonly y: number; readonly z: number; readonly yaw: number } };
  readonly navigationWorld: {
    readonly eyeHeight: number;
    readonly surface: { sample(x: number, z: number): { readonly height: number } | null };
  };
}

export interface CrowdEvaluationOptions {
  /** People in the crowd, 1 to 128. */
  readonly count: number;
  /** How many of the nearest people are drawn as full characters; the rest are distant forms. */
  readonly nearBudget: number;
  /** Walking lanes, each walked by one person at one of the evaluation speeds. */
  readonly walkers?: number;
}

/** Slow walk, walk, brisk walk and run, metres per second. */
export const EVALUATION_SPEEDS = [0.7, 1.25, 1.6, 3.4] as const;
const PAUSE_SECONDS = 1.6;
const LANE_METRES = 9;
const SOCIETY = 'character-evaluation';

interface Figure {
  readonly renderable: CharacterRenderable;
  readonly home: readonly [number, number];
  readonly lane: { readonly from: readonly [number, number]; readonly to: readonly [number, number]; readonly speed: number; readonly phase: number } | null;
}

function laneState(lane: NonNullable<Figure['lane']>, t: number): { x: number; z: number; yaw: number } {
  const walk = LANE_METRES / lane.speed;
  const period = 2 * (walk + PAUSE_SECONDS);
  let u = (t + lane.phase * period) % period;
  const out = u < walk + PAUSE_SECONDS;
  if (!out) u -= walk + PAUSE_SECONDS;
  const [a, b] = out ? [lane.from, lane.to] : [lane.to, lane.from];
  const k = Math.min(1, u / walk);
  const x = a[0] + (b[0] - a[0]) * k, z = a[1] + (b[1] - a[1]) * k;
  const heading = (from: readonly [number, number], to: readonly [number, number]) => Math.atan2(-(to[0] - from[0]), -(to[1] - from[1]));
  // Arrive, stop, then turn in place to face the way back before setting off again.
  const yaw = u < walk + PAUSE_SECONDS * 0.45 ? heading(a, b) : heading(b, a);
  return { x, z, yaw };
}

export class CharacterCrowdEvaluation {
  private readonly figures: Figure[] = [];
  private readonly root: pc.Entity;
  private elapsed = 0;
  private readonly onUpdate: (dt: number) => void;
  private destroyed = false;

  private constructor(private readonly host: CrowdEvaluationHost, private readonly options: CrowdEvaluationOptions) {
    const { app, environmentRoot } = host;
    this.root = new pc.Entity('character-evaluation-crowd', app);
    environmentRoot.addChild(this.root);
    const s = host.controls.state;
    const forward: readonly [number, number] = [-Math.sin(s.yaw), -Math.cos(s.yaw)];
    const across: readonly [number, number] = [Math.cos(s.yaw), -Math.sin(s.yaw)];
    const count = Math.max(1, Math.min(128, Math.floor(options.count)));
    const walkers = Math.max(0, Math.min(count, options.walkers ?? 4));
    const columns = 5;
    for (let i = 0; i < count; i++) {
      const identity = { societyId: SOCIETY, branchId: 'main', inhabitantId: `evaluation-${String(i).padStart(3, '0')}` };
      const renderable = inhabitantRenderable(host.device, this.root, identity, 'far');
      if (i < walkers) {
        // Lanes run across the view, nearest first, so every gait passes close to the camera.
        const ahead = 3.2 + i * 1.4;
        const centre: readonly [number, number] = [s.x + forward[0] * ahead, s.z + forward[1] * ahead];
        const half = LANE_METRES / 2;
        this.figures.push({
          renderable,
          home: centre,
          lane: {
            from: [centre[0] - across[0] * half, centre[1] - across[1] * half],
            to: [centre[0] + across[0] * half, centre[1] + across[1] * half],
            speed: EVALUATION_SPEEDS[i % EVALUATION_SPEEDS.length]!,
            phase: (i * 0.37) % 1,
          },
        });
      } else {
        const index = i - walkers;
        const row = Math.floor(index / columns), column = (index % columns) - (columns - 1) / 2;
        const ahead = 3.2 + walkers * 1.4 + 1.2 + row * 1.7;
        const stagger = row % 2 === 0 ? 0 : 0.6;
        this.figures.push({
          renderable,
          home: [s.x + forward[0] * ahead + across[0] * (column * 1.25 + stagger), s.z + forward[1] * ahead + across[1] * (column * 1.25 + stagger)],
          lane: null,
        });
      }
    }
    this.onUpdate = (dt: number) => this.update(dt);
    app.on('update', this.onUpdate);
    this.update(0, true);
  }

  static mount(host: CrowdEvaluationHost, options: CrowdEvaluationOptions): CharacterCrowdEvaluation {
    return new CharacterCrowdEvaluation(host, options);
  }

  get renderables(): readonly CharacterRenderable[] {
    return this.figures.map((figure) => figure.renderable);
  }

  /** How many figures are drawn at each detail, and how many near figures are still loading. */
  get counts(): { readonly near: number; readonly far: number; readonly pending: number; readonly unavailable: number } {
    let near = 0, far = 0, pending = 0, unavailable = 0;
    for (const { renderable } of this.figures) {
      if (renderable.detail === 'far') far++;
      else if (renderable.status === 'ready') near++;
      else if (renderable.status === 'pending') pending++;
      else unavailable++;
    }
    return { near, far, pending, unavailable };
  }

  private ground(x: number, z: number): number {
    const s = this.host.controls.state;
    return this.host.navigationWorld.surface.sample(x, z)?.height ?? s.y - this.host.navigationWorld.eyeHeight;
  }

  private update(dt: number, discontinuity = false): void {
    if (this.destroyed) return;
    this.elapsed += dt;
    // Positions are in the environment root's space, which is also where the player stands.
    const s = this.host.controls.state;
    const placed = this.figures.map((figure) => {
      const at = figure.lane ? laneState(figure.lane, this.elapsed) : null;
      const x = at?.x ?? figure.home[0], z = at?.z ?? figure.home[1];
      const yaw = at?.yaw ?? Math.atan2(-(s.x - x), -(s.z - z));
      return { figure, x, z, yaw, distance: Math.hypot(s.x - x, s.z - z) };
    });
    const nearest = [...placed].sort((a, b) => a.distance - b.distance).slice(0, Math.max(0, this.options.nearBudget));
    const near = new Set(nearest.map((entry) => entry.figure));
    for (const { figure, x, z, yaw } of placed) {
      const detail: CharacterDetail = near.has(figure) ? 'near' : 'far';
      if (figure.renderable.detail !== detail) figure.renderable.setDetail(detail);
      figure.renderable.pose({ position: [x, this.ground(x, z), z], yaw, deltaSeconds: dt, discontinuity });
    }
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.host.app.off('update', this.onUpdate);
    for (const { renderable } of this.figures) renderable.destroy();
    this.figures.length = 0;
    this.root.destroy();
  }
}
