import * as pc from 'playcanvas';

/**
 * Which of the sun's shadow cascades a thing's shadow is drawn into, by the thing's size.
 *
 * The sun's shadow is drawn in cascades, each covering ground further from the eye at a coarser
 * texel. Every shadow caster is drawn into every cascade it overlaps, so a small thing (a figure's
 * part, a flower, a small plant) is drawn three or four times a frame for a shadow the far cascades
 * cannot show at a size anyone sees. Here such a caster is drawn into the near cascades only, through
 * the engine's own mask for that (`MeshInstance.shadowCascadeMask`): near the eye its shadow is
 * exactly as before; further out, where only the coarse cascades reach, it casts none.
 *
 * Measured on the Canopy garden at three fixed views (14 October 2026, headless Chrome with Metal,
 * 1280x860): shadow draws fell from 406, 498 and 358 to 173, 234 and 125 a frame, and the pictures
 * stayed within a threshold declared before measuring (mean pixel difference at most 1.0 and at most
 * 5,000 pixels over 30 at each view). GPU time was within the noise of that machine either way.
 *
 * PRESENTATION ONLY. Nothing here changes what anything is, where it is, or whether it casts a
 * shadow near the eye. The figures are chosen defaults with their reasons, stated beside each; they
 * are for the render budget catalog to take over when that exists.
 */

export interface CasterReach {
  /** A caster whose largest side is under this many metres... */
  readonly underM: number;
  /** ...is drawn into this many of the nearest cascades and no others. */
  readonly cascades: number;
  readonly reason: string;
}

/** The size rules, smallest first; a caster under none of them is drawn into every cascade. */
export const CASTER_REACH: readonly CasterReach[] = Object.freeze([
  Object.freeze({
    underM: 0.6, cascades: 1,
    reason: 'A part of a figure, a flower or a small plant: its shadow is a few texels in the cascades beyond the nearest, which reach ground far enough off that the shadow is a few pixels on screen; in the nearest cascade it is drawn as before.',
  }),
  Object.freeze({
    underM: 1.5, cascades: 2,
    reason: 'A bench, a shrub, a seated person: its shadow still reads in the two nearest cascades and is lost in the two furthest, where the ground it falls on is tens of metres away and a shadow of a metre is a smudge.',
  }),
]);

/** The engine's mask for "every cascade". */
const ALL = pc.SHADOW_CASCADE_ALL;

/** The cascade mask a caster of `sizeM` takes under `rules`: the nearest cascades it may use, or all. */
export function cascadeMaskFor(sizeM: number, rules: readonly CasterReach[] = CASTER_REACH): number {
  for (const rule of rules) if (sizeM < rule.underM) return (1 << rule.cascades) - 1;
  return ALL;
}

/** A caster's size: the largest side of the engine's own bounds of it, in metres. */
export function casterSize(instance: pc.MeshInstance): number {
  const half = instance.aabb.halfExtents;
  return 2 * Math.max(half.x, half.y, half.z);
}

/**
 * How many shadow casters one frame looks at, at most. The engine keeps each layer's casters in one
 * list (`Layer.shadowCasters`, the list its shadow pass culls); the sweep walks those lists a slice a
 * frame, resuming where it stopped, so its cost a frame is bounded whatever the scene holds: a town of
 * twenty thousand listed casters is looked over in twenty frames, about a third of a second, and a
 * caster that arrives is given its mask within that. Measured before this bound, a whole-scene walk took 0.85 ms at 2,000 render components
 * and 10.9 ms at 10,000 every time it ran.
 */
const CASTERS_PER_FRAME = 1000;

/**
 * How many casters not seen before one frame measures and masks, at most: measuring a caster's
 * bounds the first time is the costly step, so a crowd that arrives at once is taken a few hundred a
 * frame rather than in one long frame.
 */
const NEW_CASTERS_PER_FRAME = 200;

/**
 * Gives every shadow caster its cascade mask once, as it first appears, and puts every mask it
 * narrowed back on dispose. A caster whose mask someone else already narrowed is left as it is.
 */
export class ShadowDetail {
  readonly #given = new WeakMap<pc.MeshInstance, number>();
  /** What this narrowed, held weakly so a caster that is gone is not kept alive. */
  #narrowed: WeakRef<pc.MeshInstance>[] = [];
  /** How many were held after the last time the gone were forgotten. */
  #kept = 0;
  #layer = 0;
  #index = 0;
  #disposed = false;
  readonly #tick = (): void => {
    this.sweep(CASTERS_PER_FRAME);
  };

  constructor(private readonly app: pc.AppBase, private readonly rules: readonly CasterReach[] = CASTER_REACH) {
    app.on('update', this.#tick);
  }

  /** Look at up to `most` casters from where the last sweep stopped. Returns how many it narrowed. */
  sweep(most: number = CASTERS_PER_FRAME, fresh: number = NEW_CASTERS_PER_FRAME): number {
    if (this.#disposed) return 0;
    const layers = this.app.scene.layers.layerList;
    let narrowed = 0;
    let looked = 0;
    let wrapped = 0;
    while (looked < most && layers.length > 0) {
      if (this.#layer >= layers.length) {
        this.#layer = 0;
        // Forget the casters that are gone once the list has doubled since last time; stop once every
        // list has been walked this sweep.
        if (this.#narrowed.length > 2 * this.#kept + 64) {
          this.#narrowed = this.#narrowed.filter((held) => held.deref() !== undefined);
          this.#kept = this.#narrowed.length;
        }
        if ((wrapped += 1) > 1) break;
      }
      const casters = layers[this.#layer]!.shadowCasters;
      if (this.#index >= casters.length) {
        this.#layer += 1;
        this.#index = 0;
        continue;
      }
      const instance = casters[this.#index]!;
      if (!this.#given.has(instance) && instance.castShadow && fresh <= 0) break;
      this.#index += 1;
      looked += 1;
      // A caster that no longer casts is looked at again once it does.
      if (this.#given.has(instance) || !instance.castShadow) continue;
      fresh -= 1;
      const own = instance.shadowCascadeMask;
      this.#given.set(instance, own);
      if (own !== ALL) continue;
      const mask = cascadeMaskFor(casterSize(instance), this.rules);
      if (mask === ALL) continue;
      instance.shadowCascadeMask = mask;
      this.#narrowed.push(new WeakRef(instance));
      narrowed += 1;
    }
    return narrowed;
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.app.off('update', this.#tick);
    for (const held of this.#narrowed) {
      const instance = held.deref();
      const own = instance === undefined ? undefined : this.#given.get(instance);
      if (instance !== undefined && own !== undefined) instance.shadowCascadeMask = own;
    }
    this.#narrowed = [];
  }
}
