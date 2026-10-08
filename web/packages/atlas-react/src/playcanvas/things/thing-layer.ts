/**
 * The things a world's version places, drawn by their looks where the version puts them.
 *
 * A placed thing names its kind by key, version and digest and stands at a region-local transform
 * (the authored objects' frame: east, up, south, millimetres; a yaw that turns its front). This
 * layer reads each kind and the look it wears (the kind's first look until a look is chosen for it)
 * from the host's thing library, makes the one figure its look kind draws (`./dispatch.ts`) and
 * stands it there. Nothing here moves a thing: a placed thing stands where its version says, and a
 * thing that acts in a society is drawn by the society's crowd from the society's state instead.
 *
 * A thing that cannot be drawn (a region this world does not draw, a document the library does not
 * hold, a look kind this page does not draw, a container that does not read) is drawn as nothing,
 * and its reason is kept by name in `misses`, never stood in for.
 *
 * Picking meets each figure's pick volume; the nearest wins. The picked thing wears a ring.
 */

import * as pc from 'playcanvas';
import type { OwnedSocietyState, SocietyThingSnapshot } from '../society/types.js';

/**
 * A society's thing as the drawing reads it: from THINGS 3b a held thing also names its holder's
 * socket (`socket`, set exactly while `held_by` is), and its `position_mm` is null while it is held.
 */
type HeldThing = SocietyThingSnapshot & { readonly socket?: string | null };

/** A society thing's key here: the author's id for a placed thing, else its society id. */
const thingKey = (thing: { readonly id: string; readonly placed_id: string | null }): string => thing.placed_id ?? `carried:${thing.id}`;

/** Who holds a thing and in which socket, or null for a thing on the ground. */
const holderOf = (thing: HeldThing): string | null => (thing.held_by == null ? null : `${thing.held_by}|${thing.socket ?? ''}`);
import type { ThingCrowdFigures } from './crowd-figures.js';
import type { Grip, LookDrawing } from './documents.js';
import type { InstancedContainer } from './dispatch.js';
import { ThingFigureMaker, refusalOf } from './figure-maker.js';
import { PresenceFigure, facingOfYaw, type ThingFigure } from './figures.js';
import type { Named, ThingLibrary } from './library.js';
import { PickRing, rayMeets, ringRadius } from './ring.js';

/** A placed thing as the version document lists it, in this page's words. */
export interface PlacedThingRecord {
  readonly thingId: string;
  readonly kind: { readonly kind: string; readonly version: number; readonly sha256: string };
  readonly regionId: string;
  readonly transform: {
    readonly xMm: number;
    readonly yMm: number;
    readonly zMm: number;
    readonly yawMicroradians: number;
    readonly scaleMilli: number;
  };
  readonly removed: boolean;
}

/**
 * What a pick names, every id the drawing knows: the version document's (`placedId`), the society
 * state's thing id (`thingId`) and the society person id (`subjectId`); at least one is set.
 */
export interface ThingPick {
  readonly placedId: string | null;
  readonly thingId: string | null;
  readonly subjectId: string | null;
}

export interface ThingMiss {
  readonly placedId: string;
  readonly reason: string;
  readonly detail: string;
}

export interface DrawnThing {
  readonly placedId: string;
  readonly lookKind: string;
  readonly look: string;
}

export interface ThingLayerOptions {
  readonly app: pc.AppBase;
  readonly camera: pc.Entity;
  readonly library: ThingLibrary;
  /** The entity a region's things stand in, or null where this world does not draw that region. */
  readonly regionRoot: (regionId: string) => pc.Entity | null;
  /** The shell's signal colour, `#rrggbb`, for the ring under a picked thing. */
  readonly ringColour: string;
  /** Ask the page for another frame: things move between the page's own redraws. */
  readonly invalidate?: () => void;
  /** Whether the person asked for reduced motion, read every frame. */
  readonly reducedMotion?: () => boolean;
  /**
   * Make one figure's instance of a look's container. Left out, the container is fetched from the
   * library, held to its digest, loaded once a digest by the engine's glTF reader and instantiated.
   */
  readonly instantiate?: (look: LookDrawing) => Promise<InstancedContainer>;
}

interface Entry {
  record: PlacedThingRecord;
  /** What the figure was made from: the kind, the look and the region; another means a new figure. */
  key: string;
  figure: ThingFigure | null;
  look: string | null;
  /** Raised each time the entry is rebuilt, so a stale load is dropped. */
  generation: number;
  /** How it is held, for a holdable object, once made. */
  grip: Grip | null;
  /** The entity it stands in when nobody holds it. */
  parent: pc.Entity | null;
  /** Who holds it now and in which socket, while a society's state says one does. */
  heldBy: { readonly subjectId: string; readonly socket: string } | null;
}

const ANIMATED_LOOK_KINDS: ReadonlySet<string> = new Set(['rigid_on_bones', 'skinned', 'light', 'catalog_person']);

export class ThingLayer {
  private readonly entries = new Map<string, Entry>();
  private readonly missed = new Map<string, ThingMiss>();
  private readonly lookChoices = new Map<string, Named>();
  private readonly ring: PickRing;
  /** Makes every figure of this page from the library, a container once a digest. */
  readonly maker: ThingFigureMaker;
  private picked: string | null = null;
  private destroyed = false;
  private readonly onUpdate = (dt: number) => this.step(dt);

  constructor(private readonly options: ThingLayerOptions) {
    this.ring = new PickRing(options.app.graphicsDevice, options.ringColour);
    this.maker = new ThingFigureMaker({
      app: options.app,
      library: options.library,
      ...(options.instantiate ? { instantiate: options.instantiate } : {}),
    });
    // After the engine's animation step, so a rigged look's arm is posed over its clip.
    options.app.on('update', this.onUpdate);
  }

  /** Stand the version's things: draw new ones, move moved ones, take away removed ones. */
  async setPlaced(things: readonly PlacedThingRecord[]): Promise<void> {
    if (this.destroyed) return;
    const wanted = new Map(things.filter((thing) => !thing.removed).map((thing) => [thing.thingId, thing]));
    for (const [id, entry] of this.entries) {
      if (!wanted.has(id)) this.drop(id, entry);
    }
    const loads: Promise<void>[] = [];
    for (const [id, record] of wanted) {
      const key = this.keyOf(record);
      const entry = this.entries.get(id);
      if (entry !== undefined && entry.key === key) {
        // Moved or turned: stood where the version now says at once, not at the next frame.
        entry.record = record;
        this.poseOne(entry, 0);
        continue;
      }
      if (entry !== undefined) this.drop(id, entry);
      const fresh: Entry = {
        record, key, figure: null, look: null, generation: (entry?.generation ?? 0) + 1,
        grip: null, parent: null, heldBy: null,
      };
      this.entries.set(id, fresh);
      loads.push(this.build(id, fresh));
    }
    await Promise.all(loads);
    this.options.invalidate?.();
  }

  /** Draw a placed thing in another look, or its kind's first with null. Nothing else changes. */
  async setLook(placedId: string, look: Named | null): Promise<void> {
    if (look === null) this.lookChoices.delete(placedId);
    else this.lookChoices.set(placedId, look);
    const entry = this.entries.get(placedId);
    if (entry === undefined) return;
    await this.setPlaced([...[...this.entries.values()].map((one) => one.record)]);
  }

  /** Every thing drawn now, with the look it wears. */
  get drawn(): readonly DrawnThing[] {
    return [...this.entries].flatMap(([placedId, entry]) =>
      entry.figure === null ? [] : [{ placedId, lookKind: entry.figure.lookKind, look: entry.look ?? '' }]);
  }

  /** Every placed thing drawn as nothing, and why. */
  get misses(): readonly ThingMiss[] {
    return [...this.missed.values()];
  }

  /** The figure drawing a placed thing, or null. */
  figureOf(placedId: string): ThingFigure | null {
    return this.entries.get(placedId)?.figure ?? null;
  }

  /** Whether anything drawn moves on its own (breathes, drifts, plays a clip). */
  get animating(): boolean {
    if (this.options.reducedMotion?.() === true) return false;
    if (this.society !== null) return true;
    for (const entry of this.entries.values()) if (entry.figure !== null && ANIMATED_LOOK_KINDS.has(entry.figure.lookKind)) return true;
    return this.picked !== null;
  }

  /** The nearest drawn thing a world ray meets, and how far along it, or null. */
  pick(origin: readonly [number, number, number], direction: readonly [number, number, number]): { readonly pick: ThingPick; readonly distance: number } | null {
    const from = new pc.Vec3(origin[0], origin[1], origin[2]);
    const along = new pc.Vec3(direction[0], direction[1], direction[2]).normalize();
    let best: { pick: ThingPick; distance: number } | null = null;
    for (const [placedId, entry] of this.entries) {
      const figure = entry.figure;
      if (figure === null || figure.pickVolume === null || !figure.root.enabled) continue;
      const distance = rayMeets(figure.root, figure.pickVolume, from, along);
      if (distance === null) continue;
      // The picked thing wins a tie with anything standing in the same place.
      if (best === null || distance < best.distance || (distance === best.distance && placedId === this.picked)) {
        best = { pick: Object.freeze({ placedId, thingId: null, subjectId: null }), distance };
      }
    }
    return best;
  }

  /** Ring the picked thing, or take the ring away with null. */
  setPicked(pick: ThingPick | null): void {
    this.picked = pick?.placedId ?? null;
    const figure = this.picked === null ? null : this.figureOf(this.picked);
    this.ring.place(figure?.root ?? null, ringRadius(figure?.pickVolume ?? null));
    this.options.invalidate?.();
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.options.app.off('update', this.onUpdate);
    this.ring.place(null, 0);
    for (const [id, entry] of this.entries) this.drop(id, entry);
    this.ring.destroy();
    this.maker.destroy();
  }

  private keyOf(record: PlacedThingRecord): string {
    const look = this.lookChoices.get(record.thingId);
    return [record.kind.kind, record.kind.version, record.kind.sha256, record.regionId, look ? `${look.key}/${look.version}/${look.sha256}` : '-'].join('|');
  }

  private drop(id: string, entry: Entry): void {
    if (this.picked === id) this.ring.place(null, 0);
    entry.figure?.destroy();
    entry.figure = null;
    entry.generation += 1;
    this.entries.delete(id);
    this.missed.delete(id);
  }

  private miss(id: string, reason: string, detail: string): void {
    this.missed.set(id, Object.freeze({ placedId: id, reason, detail }));
  }

  private async build(id: string, entry: Entry): Promise<void> {
    const generation = entry.generation;
    const stale = () => this.destroyed || this.entries.get(id) !== entry || entry.generation !== generation;
    const { record } = entry;
    const parent = this.options.regionRoot(record.regionId);
    if (parent === null) {
      this.miss(id, 'region_not_drawn', `This world does not draw the region ${record.regionId}.`);
      return;
    }
    try {
      const made = await this.maker.make(
        parent,
        { name: `thing:${id}`, thingId: id, kind: { key: record.kind.kind, version: record.kind.version, sha256: record.kind.sha256 }, look: this.lookChoices.get(id) ?? null },
        stale,
      );
      if (made === null) return;
      entry.figure = made.figure;
      entry.look = made.look;
      entry.grip = made.kind.grip;
      entry.parent = parent;
      this.missed.delete(id);
      this.poseOne(entry, 0);
      if (this.picked === id) this.ring.place(made.figure.root, ringRadius(made.figure.pickVolume));
    } catch (error) {
      if (stale()) return;
      this.miss(id, refusalOf(error), error instanceof Error ? error.message : String(error));
    }
  }

  /**
   * Draw what a society of things says about the version's things, or the version alone with null.
   * Its beings are its people, drawn by the crowd (`figures`), so their standing figures here are
   * not drawn; each object stands where the state puts it, or is held in its holder's socket, and
   * one the state does not list (carried away) is not drawn. A state from before v7 lists no things
   * and changes nothing here.
   *
   * A thing that changes hands, or is picked up or put down, moves when the people it passes between
   * have walked to where the state ends their walks (`walkEnded`, the crowd's): the later of the two
   * walks for a hand-over, the actor's own for a pick up or put down. Until then it is drawn where it
   * was, in the giver's socket or on the ground; a pair already in reach exchanges at once.
   */
  setSociety(state: OwnedSocietyState | null, figures: ThingCrowdFigures | null, walkEnded: (subjectId: string) => boolean = () => true): void {
    if (state?.things === undefined) {
      this.society = null;
      this.shown.clear();
      this.pending.clear();
    } else {
      const target = new Map(state.things.map((thing) => [thingKey(thing), thing as HeldThing]));
      this.society = { things: target, figures, walkEnded };
      for (const [key, thing] of target) {
        const shown = this.shown.get(key);
        if (shown === undefined || holderOf(shown) === holderOf(thing)) {
          this.shown.set(key, thing);
          this.pending.delete(key);
        } else {
          this.pending.set(key, [...new Set([shown.held_by, thing.held_by].filter((id): id is string => id != null))]);
        }
      }
      for (const key of [...this.shown.keys()]) {
        if (target.has(key)) continue;
        this.shown.delete(key);
        this.pending.delete(key);
      }
      this.settle();
    }
    this.applySociety();
    this.options.invalidate?.();
  }

  private society: {
    readonly things: ReadonlyMap<string, HeldThing>;
    readonly figures: ThingCrowdFigures | null;
    readonly walkEnded: (subjectId: string) => boolean;
  } | null = null;
  /** Each society thing as it is drawn now: the state's, or the last before a move still waiting on a walk. */
  private readonly shown = new Map<string, HeldThing>();
  /** Things whose move waits for these people's walks to end. */
  private readonly pending = new Map<string, readonly string[]>();

  /** Move each waiting thing whose people have all walked to where the state ends their walks. */
  private settle(): void {
    const society = this.society;
    if (society === null) return;
    for (const [key, parties] of this.pending) {
      if (!parties.every((id) => society.walkEnded(id))) continue;
      this.shown.set(key, society.things.get(key)!);
      this.pending.delete(key);
    }
  }
  /** The people who held something at the last look, so a hand emptied is told so. */
  private holdersSeen = new Set<string>();

  /** Stand, hold or hide each placed thing as the society's state says; every frame, as holders appear. */
  private applySociety(): void {
    // Each person's figure learns which of its sockets hold something, so it carries them.
    const society = this.society;
    if (society?.figures != null) {
      const holding = new Map<string, Set<string>>();
      for (const thing of this.shown.values()) {
        if (thing.held_by == null || thing.socket == null) continue;
        let sockets = holding.get(thing.held_by);
        if (sockets === undefined) holding.set(thing.held_by, sockets = new Set());
        sockets.add(thing.socket);
      }
      for (const subjectId of new Set([...holding.keys(), ...this.holdersSeen])) {
        society.figures.renderableOf(subjectId)?.setHolding(holding.get(subjectId) ?? new Set());
      }
      this.holdersSeen = new Set(holding.keys());
    }
    for (const entry of this.entries.values()) {
      const figure = entry.figure;
      if (figure === null) continue;
      const society = this.society;
      const thing = society === null ? undefined : this.shown.get(entry.record.thingId);
      const holder = thing?.held_by == null || thing.socket == null ? null : { subjectId: thing.held_by, socket: thing.socket };
      const holderFigure = holder === null ? null : society?.figures?.figureOf(holder.subjectId) ?? null;
      const holding = holder !== null && holderFigure?.hold !== undefined && entry.grip !== null;
      // Out of a hand it no longer is in: back where it stands.
      if (entry.heldBy !== null && (!holding || entry.heldBy.subjectId !== holder!.subjectId || entry.heldBy.socket !== holder!.socket)) {
        const was = society?.figures?.figureOf(entry.heldBy.subjectId);
        was?.release?.(entry.heldBy.socket);
        if (figure.root.parent !== entry.parent && entry.parent !== null) {
          figure.root.parent?.removeChild(figure.root);
          entry.parent.addChild(figure.root);
        }
        entry.heldBy = null;
      }
      if (society === null) {
        figure.setVisible(true);
        continue;
      }
      // Not among the state's things: a being (the crowd draws it as one of the society's people)
      // or an object carried away.
      if (thing === undefined) {
        figure.setVisible(false);
        continue;
      }
      if (holder !== null) {
        if (holding && entry.heldBy === null) {
          holderFigure!.hold!(holder.socket, figure.root, entry.grip!);
          entry.heldBy = holder;
        }
        // Held by someone not drawn now, or whose look holds nothing: not drawn either.
        figure.setVisible(holding);
        continue;
      }
      figure.setVisible(true);
    }
  }

  private step(dt: number): void {
    if (this.destroyed) return;
    const reduced = this.options.reducedMotion?.() === true;
    if (this.society !== null) {
      this.settle();
      this.applySociety();
    }
    for (const entry of this.entries.values()) this.poseOne(entry, dt, reduced);
    const camera = this.options.camera.getPosition();
    for (const entry of this.entries.values()) {
      if (entry.figure instanceof PresenceFigure) entry.figure.face(camera);
      entry.figure?.afterAnimation?.();
    }
    // The society's things the crowd draws: rigged arms over their clips, glows to the camera.
    this.society?.figures?.afterAnimation(camera);
    this.ring.step(dt, reduced);
    if (this.animating) this.options.invalidate?.();
  }

  private poseOne(entry: Entry, dt: number, reducedMotion = false): void {
    const figure = entry.figure;
    // A held thing is placed by its holder's pose.
    if (figure === null || entry.heldBy !== null) return;
    const t = entry.record.transform;
    // Where a society runs, an object stands at the state's plan point, turned by the state's yaw.
    const thing = this.society === null ? undefined : this.shown.get(entry.record.thingId);
    figure.pose({
      position: thing?.position_mm == null
        ? [t.xMm / 1000, t.yMm / 1000, t.zMm / 1000]
        : [thing.position_mm[0] / 1000, (thing.height_mm ?? 0) / 1000, thing.position_mm[1] / 1000],
      facing: facingOfYaw(thing?.yaw_microradians ?? t.yawMicroradians),
      deltaSeconds: dt,
      ...(reducedMotion ? { reducedMotion: true } : {}),
    });
  }
}
