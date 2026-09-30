import * as pc from 'playcanvas';
import type { GroundAt, SignalGroupSamples, ToRenderer, TrafficWindow } from './types.js';

/**
 * A world's traffic signals, drawn from the codes the traffic route served for each second.
 *
 * Traffic owns where a head stands and what it shows (`exulanica.traffic-signal-presentation/v1`):
 * a vehicle group's heads stand at the stop lines of the lanes it releases, a pedestrian group's at
 * both ends of each crosswalk it releases, and each second a group shows the indication its code
 * names, the one the simulation's vehicles obeyed that second. This draws a post at each point with
 * a lamp lit in that indication's colour; what a head looks like is stated below as data. A point
 * where the drawn world has no ground is not drawn.
 */

export interface SignalLooks {
  readonly profile: string;
  readonly reason: string;
  readonly post: { readonly height_mm: number; readonly width_mm: number; readonly colour: string; readonly reason: string };
  readonly lamp: { readonly height_mm: number; readonly width_mm: number; readonly reason: string };
  readonly colours: Readonly<Record<string, string>>;
}

export const SIGNAL_LOOKS_V1: SignalLooks = {
  profile: 'exulanica.signal-looks/v1',
  reason: 'How the page draws a traffic signal head: a post at the point the traffic names, topped by one lamp lit in the colour of what its group shows that second. Presentation only; the simulation reads none of it.',
  post: {
    height_mm: 2400,
    width_mm: 120,
    colour: '#2b2f33',
    reason: 'A post tall enough to read above a parked car from a walker\'s eye, dark so the lamp carries the meaning.',
  },
  lamp: {
    height_mm: 450,
    width_mm: 300,
    reason: 'One lamp box a head, large enough to read its colour at a street\'s length; one lamp, since the record states one indication a group.',
  },
  colours: {
    green: '#2fbf5b',
    amber: '#f2a516',
    red: '#d6352b',
    walk: '#f4f4ef',
    clearance: '#f2a516',
    dont_walk: '#d6352b',
  },
};

const MM_PER_METRE = 1000;

interface Head {
  readonly root: pc.Entity;
  readonly lamp: pc.Entity;
}

export class SignalLookError extends Error {}

export class SignalLights {
  readonly root: pc.Entity;
  private readonly windows = new Map<number, TrafficWindow>();
  private readonly heads = new Map<string, Head>();
  private readonly materials = new Map<string, pc.StandardMaterial>();
  private litCount = 0;

  constructor(
    parent: pc.Entity,
    private readonly groundAt: GroundAt,
    private readonly toRenderer: ToRenderer,
    private readonly looks: SignalLooks = SIGNAL_LOOKS_V1,
  ) {
    this.root = new pc.Entity('traffic-signals');
    parent.addChild(this.root);
  }

  /** Hand in a served window; every indication it names is resolved before anything is drawn. */
  setWindow(window: TrafficWindow): void {
    for (const indication of [...window.vehicleIndications, ...window.pedestrianIndications]) this.colourOf(indication);
    this.windows.set(window.fromSecond, window);
  }

  /** Heads lit at the last update. */
  get lit(): number {
    return this.litCount;
  }

  /** Every head lit as its group shows at `second`; windows ending before `forgetBefore` go. */
  show(second: number, forgetBefore: number): void {
    for (const [from, window] of this.windows) if (from + window.seconds <= forgetBefore) this.windows.delete(from);
    let lit = 0;
    for (const window of this.windows.values()) {
      const index = second - window.fromSecond;
      if (index < 0 || index >= window.seconds) continue;
      for (const signal of window.signals) {
        for (const group of signal.groups) {
          const code = group.codes[index]!;
          const names = group.kind === 'vehicle' ? window.vehicleIndications : window.pedestrianIndications;
          const material = this.materialFor(this.colourOf(names[code]!));
          lit += this.light(signal.signalId, group, material);
        }
      }
      break;
    }
    this.litCount = lit;
  }

  clear(): void {
    for (const head of this.heads.values()) head.root.destroy();
    this.heads.clear();
    this.windows.clear();
    this.litCount = 0;
  }

  destroy(): void {
    this.clear();
    for (const material of this.materials.values()) material.destroy();
    this.materials.clear();
    this.root.destroy();
  }

  /** Light each of a group's heads; how many stand on ground. */
  private light(signalId: string, group: SignalGroupSamples, material: pc.StandardMaterial): number {
    let lit = 0;
    for (let index = 0; index + 1 < group.pointsMm.length; index += 2) {
      const x = group.pointsMm[index]!;
      const y = group.pointsMm[index + 1]!;
      const key = `${signalId}:${group.group}:${x}:${y}`;
      const ground = this.groundAt(x, y);
      const head = this.headFor(key, x, y, ground);
      head.root.enabled = ground !== null;
      if (ground === null) continue;
      head.lamp.render!.material = material;
      lit += 1;
    }
    return lit;
  }

  private headFor(key: string, x: number, y: number, ground: number | null): Head {
    const existing = this.heads.get(key);
    if (existing !== undefined) return existing;
    const { post, lamp } = this.looks;
    const root = new pc.Entity(`signal-head:${key}`);
    const [rx, , rz] = this.toRenderer(x, y, 0);
    root.setLocalPosition(rx, ground ?? 0, rz);
    const pole = new pc.Entity('post');
    pole.setLocalPosition(0, post.height_mm / 2 / MM_PER_METRE, 0);
    pole.setLocalScale(post.width_mm / MM_PER_METRE, post.height_mm / MM_PER_METRE, post.width_mm / MM_PER_METRE);
    pole.addComponent('render', { type: 'box', material: this.materialFor(post.colour) });
    const light = new pc.Entity('lamp');
    light.setLocalPosition(0, (post.height_mm + lamp.height_mm / 2) / MM_PER_METRE, 0);
    light.setLocalScale(lamp.width_mm / MM_PER_METRE, lamp.height_mm / MM_PER_METRE, lamp.width_mm / MM_PER_METRE);
    light.addComponent('render', { type: 'box', material: this.materialFor(post.colour) });
    root.addChild(pole);
    root.addChild(light);
    this.root.addChild(root);
    const head = { root, lamp: light };
    this.heads.set(key, head);
    return head;
  }

  private colourOf(indication: string): string {
    const found = this.looks.colours[indication];
    if (found === undefined) throw new SignalLookError(`signal-looks states no colour for ${indication}`);
    return found;
  }

  private materialFor(hex: string): pc.StandardMaterial {
    const existing = this.materials.get(hex);
    if (existing !== undefined) return existing;
    const material = new pc.StandardMaterial();
    const value = Number.parseInt(hex.slice(1), 16);
    const colour = new pc.Color(((value >> 16) & 255) / 255, ((value >> 8) & 255) / 255, (value & 255) / 255);
    material.diffuse = colour;
    material.emissive = colour;
    material.update();
    this.materials.set(hex, material);
    return material;
  }
}
