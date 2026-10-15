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
 * A thing an edit moved, placed or brought back stands where its version now puts it, not where the
 * society's minute last saw it, while the minute drawn has not taken that edit in: where the society
 * read states the newest edit its minute took in (`authored_edit_seq`) and the record its newest
 * edit (`editSeq`), by those, also after a reload; otherwise while the minutes drawn still show it
 * as it was before an edit made on this page. A paused world shows an edit at once, and a minute
 * that took the edit in draws it again. An editor may draw a
 * see-through copy of a placed thing where it would go (`setGhost`), tinted where the world refused
 * that spot.
 *
 * Picking meets each figure's pick volume; the nearest wins. The picked thing wears a ring. While a
 * person plays a being (Play this one), that being wears a steady ring at its feet as the society
 * draws it, and the ground where its next walk goes wears another, both in the world-mark person
 * colour on a dark edge in the person ink.
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

/** Whether two placed transforms stand a thing in the same place, turned the same way. */
const sameTransform = (a: PlacedThingRecord['transform'], b: PlacedThingRecord['transform']): boolean =>
  a.xMm === b.xMm && a.yMm === b.yMm && a.zMm === b.zMm && a.yawMicroradians === b.yawMicroradians;

/** Who holds a thing and in which socket, or null for a thing on the ground. */
const holderOf = (thing: HeldThing): string | null => (thing.held_by == null ? null : `${thing.held_by}|${thing.socket ?? ''}`);
import type { BodyMotion } from './body-motion.js';
import type { ThingCrowdFigures } from './crowd-figures.js';
import type { Grip, LookDrawing } from './documents.js';
import type { InstancedContainer } from './dispatch.js';
import { ThingFigureMaker, refusalOf } from './figure-maker.js';
import { PresenceFigure, facingOfYaw, type ThingFigure } from './figures.js';
import type { Named, ThingLibrary } from './library.js';
import { PickRing, rayMeets, ringRadius } from './ring.js';

/**
 * The kind a placed thing names: a shipped kind by key, version and digest, or a kind its workspace
 * keeps by its document's digest alone (a creature drafted from a person's words).
 */
export type PlacedKind =
  | { readonly source?: 'shipped'; readonly kind: string; readonly version: number; readonly sha256: string }
  | { readonly source: 'workspace'; readonly sha256: string };

/** A saved source-bound horizontal support claim. */
export interface PlacedThingSupportReference {
  readonly profile: 'exulanica.support-reference/v1';
  readonly worldId: string;
  readonly sourceSnapshotId: string;
  readonly receiptSha256: string;
  readonly networkSha256: string;
  readonly regionId: string;
  readonly surfaceId: string;
}

/** A placed thing as the version document lists it, in this page's words. */
export interface PlacedThingRecord {
  readonly thingId: string;
  readonly kind: PlacedKind;
  readonly regionId: string;
  readonly transform: {
    readonly xMm: number;
    readonly yMm: number;
    readonly zMm: number;
    readonly yawMicroradians: number;
    readonly scaleMilli: number;
  };
  readonly removed: boolean;
  readonly support?: PlacedThingSupportReference;
  /** The version's newest edit naming this thing, where the version's edit log was read. */
  readonly editSeq?: number;
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

/**
 * Where an editor would put a placed thing: its placed id, a pose of its region in the frame of a
 * record's transform, and whether the world refused that spot.
 */
export interface ThingGhost {
  readonly placedId: string;
  readonly xMm: number;
  readonly yMm: number;
  readonly zMm: number;
  readonly yawMicroradians: number;
  readonly refused: boolean;
}

/**
 * A ghost's own light, the in-world design's see-through copy (WORKSPACE-DESIGN-v2 5.15): white
 * where it may stand, the design's refused coral (#ff8f7e) where the world refused the spot. It is
 * drawn unlit, so it reads the same on paving, grass and water, by day and by night.
 */
const GHOST_LIGHT = new pc.Color(1, 1, 1);
const REFUSED_LIGHT = new pc.Color(1, 0x8f / 255, 0x7e / 255);
/**
 * How much of a ghost is drawn: a dither, as a fading representation is, so it never sorts against
 * the world; a refused copy a little more, so its tint reads.
 */
const GHOST_OPACITY = 0.3;
const REFUSED_OPACITY = 0.4;

/** Make `material` a ghost's: unlit, no maps or vertex colours, its light its colour, dithered. */
function asGhost(material: pc.StandardMaterial, refused: boolean): pc.StandardMaterial {
  // A light copy, not the thing's own surface: no maps or vertex colours, its colour its light.
  material.useLighting = false;
  material.diffuse = pc.Color.BLACK;
  material.diffuseMap = null;
  material.diffuseVertexColor = false;
  material.emissive = refused ? REFUSED_LIGHT : GHOST_LIGHT;
  material.emissiveMap = null;
  material.emissiveVertexColor = false;
  material.opacity = refused ? REFUSED_OPACITY : GHOST_OPACITY;
  material.opacityDither = pc.DITHER_IGNNOISE;
  material.opacityShadowDither = pc.DITHER_IGNNOISE;
  material.update();
  return material;
}

/**
 * A made part's copy where it would stand: the base's centre in the region's frame (millimetres
 * east, up and south), its box as its drawing states it (width along its front, depth, height,
 * millimetres) and its quarter turns, and whether the world refused the spot.
 */
export interface BoxGhost {
  readonly regionId: string;
  readonly xMm: number;
  readonly yMm: number;
  readonly zMm: number;
  readonly sizeMm: readonly [number, number, number];
  readonly quarterTurns: number;
  readonly refused: boolean;
}
/** How thin a copy of a part that lies flat (a pond, a field) is drawn, millimetres. */
const FLAT_GHOST_MM = 50;

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
  /** Source-region root only while this exact supported placement has current admitted availability. */
  readonly supportRoot?: (thing: PlacedThingRecord) => pc.Entity | null;
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
  /** The world-mark person colour, `#rrggbb`, for Play this one's rings; the pick ring's when left out. */
  readonly personColour?: string;
  /** The world-mark person ink, `#rrggbb`, the dark edge Play this one's rings stand on so they read on pale ground; none when left out. */
  readonly personEdge?: string;
  /** The society drawn now, which Play this one's rings stand in, or null while none is. */
  readonly society?: () => DrawnSociety | null;
  /** The table a drafted body's stated chains are posed by (`./body-motion.ts`); at rest when left out. */
  readonly bodyMotion?: BodyMotion;
}

/** Where the society's people stand as its crowd draws them (`AuthoredSociety`). */
export interface DrawnSociety {
  /** The crowd's root: the society's own frame, the state's `position_mm` over 1,000. */
  readonly root: pc.Entity;
  /** Where a person's feet are drawn now, in world space, into `out`; false when not drawn outdoors. */
  groundOf(id: string, out: pc.Vec3): boolean;
  /**
   * The land's height under a point of the society's own frame (east, south, metres) for a site on
   * land; none where its ground is the root's own plane.
   */
  readonly groundHeightAt?: ((east: number, south: number) => number) | undefined;
}

/** A point of the society's own frame, millimetres, as the state and a person's walk name one. */
export interface SocietyPoint {
  readonly xMm: number;
  readonly zMm: number;
}

/** The ring at the feet of the being a person plays, and around where its next walk goes, metres. */
export const PLAYED_RING_RADIUS = 0.45;
/** How far outside a person the played ring stands: its radius less the quarter metre a person is from middle to side. */
const PLAYED_RING_CLEAR = PLAYED_RING_RADIUS - 0.25;
export const DESTINATION_RING_RADIUS = 0.35;

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
  /** The figure holding it: when its holder's figure is another (made again), that one holds it. */
  heldIn: ThingFigure | null;
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
  /** A made part's see-through box copy, and its one material. */
  private boxGhost: { readonly refused: boolean; readonly root: pc.Entity; readonly shape: pc.Entity; readonly material: pc.StandardMaterial } | null = null;
  /** The see-through copy an editor asked for, and what it was made from. */
  private ghost: { readonly placedId: string; readonly refused: boolean; readonly source: ThingFigure; readonly root: pc.Entity; readonly materials: readonly pc.StandardMaterial[] } | null = null;
  /**
   * Things an edit moved, placed or brought back, by placed id, with every spot the edits replaced
   * (east and south, millimetres): where the drawing stood it before the first, and each place its
   * version gave it before a later one. A minute that lists it at one of them has not taken the
   * newest edit in.
   */
  private readonly edited = new Map<string, Array<readonly [number, number]>>();
  /** The newest authored edit the society's minute drawn has taken in, where its read states it. */
  private societyEdit: number | null = null;
  /** Whether the version's things were stood once: later new ones are an edit's. */
  private placedOnce = false;
  /** Play this one: the being played, ringed where its feet are drawn, and where its next walk goes. */
  private readonly playedRing: PickRing;
  private readonly destinationRing: PickRing;
  private readonly playedAt = new pc.Entity('thing-played-at');
  private readonly destinationAt = new pc.Entity('thing-destination-at');
  private played: string | null = null;
  private destination: SocietyPoint | null = null;
  private readonly feet = new pc.Vec3();
  private destroyed = false;
  private readonly onUpdate = (dt: number) => this.step(dt);

  constructor(private readonly options: ThingLayerOptions) {
    this.ring = new PickRing(options.app.graphicsDevice, options.ringColour);
    this.playedRing = new PickRing(options.app.graphicsDevice, options.personColour ?? options.ringColour, options.personEdge);
    this.destinationRing = new PickRing(options.app.graphicsDevice, options.personColour ?? options.ringColour, options.personEdge);
    this.maker = new ThingFigureMaker({
      app: options.app,
      library: options.library,
      ...(options.instantiate ? { instantiate: options.instantiate } : {}),
      ...(options.bodyMotion ? { bodyMotion: options.bodyMotion } : {}),
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
    let moved = false;
    for (const [id, record] of wanted) {
      const key = this.keyOf(record);
      const entry = this.entries.get(id);
      if (entry !== undefined && entry.key === key) {
        // Moved or turned: stood where the version now says at once, not at the next frame.
        if (!sameTransform(entry.record.transform, record.transform)) {
          const replaced = this.edited.get(id) ?? [this.standing(entry)];
          replaced.push([entry.record.transform.xMm, entry.record.transform.zMm]);
          this.edited.set(id, replaced);
          moved = true;
        }
        entry.record = record;
        this.poseOne(entry, 0);
        continue;
      }
      if (entry !== undefined) {
        // Made again (another look, its support read again): an edit's mark stays with it.
        const replaced = this.edited.get(id);
        this.drop(id, entry);
        if (replaced !== undefined) this.edited.set(id, replaced);
      } else if (this.placedOnce) this.edited.set(id, []);
      const fresh: Entry = {
        record, key, figure: null, look: null, generation: (entry?.generation ?? 0) + 1,
        grip: null, parent: null, heldBy: null, heldIn: null,
      };
      this.entries.set(id, fresh);
      loads.push(this.build(id, fresh));
    }
    this.placedOnce = true;
    // Once for all of them: a group of moves (an undo of several) is not walked once per move.
    if (moved) this.applySociety();
    await Promise.all(loads);
    this.options.invalidate?.();
  }

  /**
   * Draw a see-through copy of a placed thing where an editor would put it, tinted where the world
   * refused that spot, or take it away with null. It is never picked and never part of a society.
   */
  setGhost(ghost: ThingGhost | null): void {
    const entry = ghost === null ? undefined : this.entries.get(ghost.placedId);
    const figure = entry?.figure ?? null;
    if (ghost === null || figure === null || entry?.parent == null) {
      this.dropGhost();
      this.options.invalidate?.();
      return;
    }
    if (this.ghost === null || this.ghost.placedId !== ghost.placedId || this.ghost.refused !== ghost.refused || this.ghost.source !== figure) {
      this.dropGhost();
      // The pick ring stands under the picked figure: it is the thing's, not its copy's.
      const ringed = this.ring.entity.parent === figure.root;
      if (ringed) figure.root.removeChild(this.ring.entity);
      const root = figure.root.clone() as pc.Entity;
      if (ringed) figure.root.addChild(this.ring.entity);
      root.name = `thing-ghost:${ghost.placedId}`;
      root.enabled = true;
      const materials: pc.StandardMaterial[] = [];
      for (const render of root.findComponents('render') as pc.RenderComponent[]) {
        // A copy throws no shadow (a second, dithered one, drawn in every cascade); it still receives.
        render.castShadows = false;
        for (const instance of render.meshInstances) {
          // Only a part whose material can fade is drawn: a copy is never solid. A skinned part is
          // posed by its original's bones, so it would stand where the original stands: not drawn.
          if (!(instance.material instanceof pc.StandardMaterial) || instance.skinInstance != null) { instance.visible = false; continue; }
          const material = asGhost(instance.material.clone(), ghost.refused);
          instance.material = material;
          materials.push(material);
        }
      }
      entry.parent.addChild(root);
      this.ghost = { placedId: ghost.placedId, refused: ghost.refused, source: figure, root, materials };
    }
    this.ghost.root.setLocalPosition(ghost.xMm / 1000, ghost.yMm / 1000, ghost.zMm / 1000);
    this.ghost.root.setLocalEulerAngles(0, (ghost.yawMicroradians / 1_000_000) * (180 / Math.PI), 0);
    this.options.invalidate?.();
  }

  /**
   * Draw a see-through box where a made part would stand (a building, a fixture or a pond carried
   * in build mode), in the ghost's own light, coral where the world refused the spot; null takes it
   * away. A made part has no figure in this layer, so its copy is its box, posed as its drawing poses it.
   */
  setBoxGhost(ghost: BoxGhost | null): void {
    const root = ghost === null ? null : this.options.regionRoot(ghost.regionId);
    if (ghost === null || root === null) {
      this.dropBoxGhost();
      this.options.invalidate?.();
      return;
    }
    if (this.boxGhost === null || this.boxGhost.refused !== ghost.refused || this.boxGhost.root.parent !== root) {
      this.dropBoxGhost();
      const entity = new pc.Entity('part-ghost');
      const shape = new pc.Entity('part-ghost:shape');
      const material = asGhost(new pc.StandardMaterial(), ghost.refused);
      shape.addComponent('render', { type: 'box', material, castShadows: false });
      entity.addChild(shape);
      root.addChild(entity);
      this.boxGhost = { refused: ghost.refused, root: entity, shape, material };
    }
    const [width, depth, height] = ghost.sizeMm.map((mm) => Math.max(mm, FLAT_GHOST_MM) / 1000) as [number, number, number];
    this.boxGhost.root.setLocalPosition(ghost.xMm / 1000, ghost.yMm / 1000, ghost.zMm / 1000);
    this.boxGhost.root.setLocalEulerAngles(0, 90 * (ghost.quarterTurns % 4), 0);
    this.boxGhost.shape.setLocalPosition(0, height / 2, 0);
    this.boxGhost.shape.setLocalScale(width, height, depth);
    this.options.invalidate?.();
  }

  private dropBoxGhost(): void {
    if (this.boxGhost === null) return;
    this.boxGhost.root.destroy();
    this.boxGhost.material.destroy();
    this.boxGhost = null;
  }

  private dropGhost(): void {
    if (this.ghost === null) return;
    this.ghost.root.destroy();
    for (const material of this.ghost.materials) material.destroy();
    this.ghost = null;
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
      entry.figure === null || (entry.record.support !== undefined && this.options.supportRoot?.(entry.record) == null) ? [] : [{ placedId, lookKind: entry.figure.lookKind, look: entry.look ?? '' }]);
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
      if (figure === null || figure.pickVolume === null || !figure.root.enabled
          || (entry.record.support !== undefined && this.options.supportRoot?.(entry.record) == null)) continue;
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

  /**
   * Ring the being a person plays at its feet, following its drawn walk, or take the ring away with
   * null. Steady: the ring says whose it is, it does not ask to be looked at.
   */
  setPlayed(subjectId: string | null): void {
    this.played = subjectId;
    this.placePlayed();
    this.options.invalidate?.();
  }

  /** Ring the ground where the played being's next walk goes, a point of the society's own frame, or none with null. */
  setDestination(point: SocietyPoint | null): void {
    this.destination = point;
    this.placeDestination();
    this.options.invalidate?.();
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.options.app.off('update', this.onUpdate);
    this.dropGhost();
    this.dropBoxGhost();
    this.ring.place(null, 0);
    for (const [id, entry] of this.entries) this.drop(id, entry);
    this.ring.destroy();
    this.playedRing.destroy();
    this.destinationRing.destroy();
    this.playedAt.destroy();
    this.destinationAt.destroy();
    this.maker.destroy();
  }

  /** The played being's ring where the society draws its feet now; none while it is not drawn outdoors. */
  private placePlayed(): void {
    const society = this.played === null ? null : this.options.society?.() ?? null;
    if (society === null || !society.groundOf(this.played!, this.feet)) {
      this.playedRing.place(null, 0);
      return;
    }
    if (this.playedAt.parent !== this.options.app.root) {
      this.playedAt.parent?.removeChild(this.playedAt);
      this.options.app.root.addChild(this.playedAt);
    }
    this.playedAt.setPosition(this.feet);
    // Around a body that states its size the ring stands as far outside its flanks as it stands outside a person.
    const body = this.society?.figures?.renderableOf(this.played!)?.footprint ?? null;
    this.playedRing.place(this.playedAt, body === null ? PLAYED_RING_RADIUS : Math.max(PLAYED_RING_RADIUS, body.halfAcross + PLAYED_RING_CLEAR));
  }

  /** The destination's ring on the society's ground, in the crowd's own frame; none without a society. */
  private placeDestination(): void {
    const root = this.destination === null ? null : this.options.society?.()?.root ?? null;
    if (root === null) {
      this.destinationRing.place(null, 0);
      return;
    }
    if (this.destinationAt.parent !== root) {
      this.destinationAt.parent?.removeChild(this.destinationAt);
      root.addChild(this.destinationAt);
    }
    const ground = this.options.society?.()?.groundHeightAt;
    const east = this.destination!.xMm / 1000, south = this.destination!.zMm / 1000;
    this.destinationAt.setLocalPosition(east, ground === undefined ? 0 : ground(east, south), south);
    this.destinationRing.place(this.destinationAt, DESTINATION_RING_RADIUS);
  }

  private keyOf(record: PlacedThingRecord): string {
    const look = this.lookChoices.get(record.thingId);
    const kind = record.kind.source === 'workspace' ? ['workspace', record.kind.sha256] : [record.kind.kind, record.kind.version, record.kind.sha256];
    return [...kind, record.regionId, look ? `${look.key}/${look.version}/${look.sha256}` : '-',
      record.support === undefined ? '-' : JSON.stringify(record.support),
      record.support === undefined || this.options.supportRoot?.(record) != null ? 'admitted' : 'unavailable'].join('|');
  }

  private drop(id: string, entry: Entry): void {
    if (this.picked === id) this.ring.place(null, 0);
    if (this.ghost?.placedId === id) this.dropGhost();
    this.edited.delete(id);
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
    const stale = () => this.destroyed || this.entries.get(id) !== entry || entry.generation !== generation
      || (entry.record.support !== undefined && this.options.supportRoot?.(entry.record) == null);
    const { record } = entry;
    if (record.support !== undefined && this.options.supportRoot?.(record) == null) {
      this.miss(id, 'support_projection_unavailable', 'This saved thing has no current verified support projection.');
      return;
    }
    const parent = record.support === undefined ? this.options.regionRoot(record.regionId) : this.options.supportRoot?.(record) ?? null;
    if (parent === null) {
      this.miss(id, 'region_not_drawn', `This world does not draw the region ${record.regionId}.`);
      return;
    }
    try {
      const made = await this.maker.make(
        parent,
        {
          name: `thing:${id}`,
          thingId: id,
          kind: record.kind.source === 'workspace'
            ? { source: 'workspace', sha256: record.kind.sha256 }
            : { key: record.kind.kind, version: record.kind.version, sha256: record.kind.sha256 },
          look: this.lookChoices.get(id) ?? null,
        },
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
   * one the state does not list (carried away) is not drawn. A thing of a kind its workspace keeps
   * that is none of the state's people lives in no society, so it stands where its version places
   * it. A state from before v7 lists no things and changes nothing here.
   *
   * A thing that changes hands, or is picked up or put down, moves when the people it passes between
   * have walked to where the state ends their walks (`walkEnded`, the crowd's): the later of the two
   * walks for a hand-over, the actor's own for a pick up or put down. Until then it is drawn where it
   * was, in the giver's socket or on the ground; a pair already in reach exchanges at once. What a
   * visitor carries out stays in its hand while the crowd still draws it walking back into its gate
   * (`leaving`, the crowd's), and goes with it.
   */
  setSociety(
    state: OwnedSocietyState | null,
    figures: ThingCrowdFigures | null,
    walkEnded: (subjectId: string) => boolean = () => true,
    leaving: (subjectId: string) => boolean = () => false,
  ): void {
    this.settleEdits(state);
    this.societyEdit = state?.things === undefined ? null : state.authored_edit_seq ?? null;
    if (state?.things === undefined) {
      this.society = null;
      this.shown.clear();
      this.pending.clear();
    } else {
      const target = new Map(state.things.map((thing) => [thingKey(thing), thing as HeldThing]));
      const beings = new Set(state.inhabitants.map((person) => person.placed_id).filter((id): id is string => id != null));
      this.society = { things: target, beings, figures, walkEnded, leaving };
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
        this.pending.delete(key);
        if (!this.goesWithItsHolder(key)) this.shown.delete(key);
      }
      this.settle();
    }
    this.applySociety();
    this.options.invalidate?.();
  }

  /**
   * Let the society draw an edited thing again once a minute has taken the newest edit in: it lists
   * the thing in a hand, at the place its version now gives it, or on the ground anywhere none of
   * the edits replaced. A minute that lists it at a replaced spot, or does not list it, has not: the
   * version's drawing stays. Without a society's things every mark goes, since the version alone is
   * drawn then.
   */
  private settleEdits(state: OwnedSocietyState | null): void {
    if (this.edited.size === 0) return;
    if (state?.things === undefined) {
      this.edited.clear();
      return;
    }
    const listed = new Map(state.things.map((thing) => [thingKey(thing), thing as HeldThing]));
    for (const [id, replaced] of this.edited) {
      const thing = listed.get(id);
      if (thing === undefined) continue;
      const at = thing.held_by == null ? thing.position_mm : null;
      const now = this.entries.get(id)?.record.transform;
      const current = at != null && now !== undefined && at[0] === now.xMm && at[1] === now.zMm;
      if (at != null && !current && replaced.some(([east, south]) => at[0] === east && at[1] === south)) continue;
      this.edited.delete(id);
    }
  }

  /** Whether the thing's newest edit is one the society's minute drawn has not taken in, by the read's word. */
  private unseen(entry: Entry): boolean {
    return this.societyEdit !== null && entry.record.editSeq !== undefined && entry.record.editSeq > this.societyEdit;
  }

  /** Whether an edit is drawn as its version says rather than as the society's minute has it. */
  private editedNow(entry: Entry): boolean {
    return this.edited.has(entry.record.thingId) || this.unseen(entry);
  }

  /** Where the drawing stands a thing now (east and south, millimetres): the society's place, else its version's. */
  private standing(entry: Entry): readonly [number, number] {
    const shown = this.society === null || entry.record.support !== undefined ? undefined : this.shown.get(entry.record.thingId);
    return shown?.position_mm != null
      ? [shown.position_mm[0], shown.position_mm[1]]
      : [entry.record.transform.xMm, entry.record.transform.zMm];
  }

  private society: {
    readonly things: ReadonlyMap<string, HeldThing>;
    /** The placed ids of the state's people: the placed beings the crowd draws. */
    readonly beings: ReadonlySet<string>;
    readonly figures: ThingCrowdFigures | null;
    readonly walkEnded: (subjectId: string) => boolean;
    readonly leaving: (subjectId: string) => boolean;
  } | null = null;

  /** Whether a thing the state no longer lists is in the hand of a visitor still drawn leaving. */
  private goesWithItsHolder(key: string): boolean {
    const holder = this.shown.get(key)?.held_by;
    return holder != null && this.society !== null && this.society.leaving(holder);
  }
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
    // What a visitor carried out goes once the crowd no longer draws it leaving.
    for (const key of this.shown.keys()) {
      if (!society.things.has(key) && !this.goesWithItsHolder(key)) this.shown.delete(key);
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
      if (entry.record.support !== undefined) {
        figure.setVisible(this.options.supportRoot?.(entry.record) != null);
        continue;
      }
      const society = this.society;
      // An object an edit moved, placed or brought back stands as its version says until a later
      // minute lists it; a being is the crowd's to draw.
      const edited = society !== null && this.editedNow(entry) && !society.beings.has(entry.record.thingId);
      const thing = society === null || edited ? undefined : this.shown.get(entry.record.thingId);
      const holder = thing?.held_by == null || thing.socket == null ? null : { subjectId: thing.held_by, socket: thing.socket };
      const holderFigure = holder === null ? null : society?.figures?.figureOf(holder.subjectId) ?? null;
      const holding = holder !== null && holderFigure?.hold !== undefined && entry.grip !== null;
      // Out of a hand it no longer is in, or out of a figure made again since (a changed look's,
      // which let it go): back where it stands until the holder's figure holds it.
      if (entry.heldBy !== null && (!holding || entry.heldIn !== holderFigure
        || entry.heldBy.subjectId !== holder!.subjectId || entry.heldBy.socket !== holder!.socket)) {
        if (entry.heldIn !== null && figure.root.parent === entry.heldIn.root) entry.heldIn.release?.(entry.heldBy.socket);
        if (figure.root.parent !== entry.parent && entry.parent !== null) {
          figure.root.parent?.removeChild(figure.root);
          entry.parent.addChild(figure.root);
        }
        entry.heldBy = null;
        entry.heldIn = null;
      }
      if (society === null) {
        figure.setVisible(true);
        continue;
      }
      // Not among the state's things: a being (the crowd draws it as one of the society's people)
      // or an object carried away. A thing of a kind its workspace keeps that is none of the state's
      // people is in no society, so it stands where its version places it.
      if (thing === undefined) {
        figure.setVisible(edited || (entry.record.kind.source === 'workspace' && !society.beings.has(entry.record.thingId)));
        continue;
      }
      if (holder !== null) {
        if (holding && entry.heldBy === null) {
          holderFigure!.hold!(holder.socket, figure.root, entry.grip!);
          entry.heldBy = holder;
          entry.heldIn = holderFigure;
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
    // Play this one's rings follow the society as it is drawn this frame; they never pulse.
    if (this.played !== null) this.placePlayed();
    if (this.destination !== null) this.placeDestination();
    if (this.animating) this.options.invalidate?.();
  }

  private poseOne(entry: Entry, dt: number, reducedMotion = false): void {
    const figure = entry.figure;
    // A held thing is placed by its holder's pose.
    if (figure === null || entry.heldBy !== null) return;
    if (entry.record.support !== undefined) {
      const available = this.options.supportRoot?.(entry.record) != null;
      figure.setVisible(available);
      if (!available) {
        this.miss(entry.record.thingId, 'support_projection_unavailable', 'This saved thing has no current verified support projection.');
        if (this.picked === entry.record.thingId) this.ring.place(null, 0);
        return;
      }
    }
    const t = entry.record.transform;
    // Where a society runs, an object stands at the state's plan point, turned by the state's yaw.
    const thing = this.society === null || entry.record.support !== undefined
      || (this.editedNow(entry) && !this.society.beings.has(entry.record.thingId))
      ? undefined : this.shown.get(entry.record.thingId);
    // A society's thing stands its height above the ground under it: on land, the land's.
    const ground = thing?.position_mm == null ? undefined : this.options.society?.()?.groundHeightAt;
    figure.pose({
      position: thing?.position_mm == null
        ? [t.xMm / 1000, t.yMm / 1000, t.zMm / 1000]
        : ground === undefined
          ? [thing.position_mm[0] / 1000, (thing.height_mm ?? 0) / 1000, thing.position_mm[1] / 1000]
          : [thing.position_mm[0] / 1000, ground(thing.position_mm[0] / 1000, thing.position_mm[1] / 1000) + (thing.height_mm ?? 0) / 1000, thing.position_mm[1] / 1000],
      facing: facingOfYaw(thing?.yaw_microradians ?? t.yawMicroradians),
      deltaSeconds: dt,
      ...(reducedMotion ? { reducedMotion: true } : {}),
    });
  }
}
