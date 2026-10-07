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
import { createObjectContainerAsset } from '../scene-objects.js';
import type { LookDrawing } from './documents.js';
import { FigureRefused, makeFigure, type InstancedContainer } from './dispatch.js';
import { PresenceFigure, facingOfYaw, type ThingFigure } from './figures.js';
import { LibraryRefused, type Named, type ThingLibrary } from './library.js';
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
}

const ANIMATED_LOOK_KINDS: ReadonlySet<string> = new Set(['rigid_on_bones', 'skinned', 'light', 'catalog_person']);

export class ThingLayer {
  private readonly entries = new Map<string, Entry>();
  private readonly missed = new Map<string, ThingMiss>();
  private readonly assets = new Map<string, Promise<pc.Asset>>();
  private readonly lookChoices = new Map<string, Named>();
  private readonly ring: PickRing;
  private readonly primitive: pc.StandardMaterial;
  private picked: string | null = null;
  private destroyed = false;
  private readonly onUpdate = (dt: number) => this.step(dt);

  constructor(private readonly options: ThingLayerOptions) {
    this.ring = new PickRing(options.app.graphicsDevice, options.ringColour);
    this.primitive = new pc.StandardMaterial();
    this.primitive.name = 'thing:look-role-primitive';
    this.primitive.diffuse = new pc.Color(0.62, 0.6, 0.56);
    this.primitive.useMetalness = true;
    this.primitive.metalness = 0;
    this.primitive.gloss = 0.2;
    this.primitive.update();
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
      const fresh: Entry = { record, key, figure: null, look: null, generation: (entry?.generation ?? 0) + 1 };
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
    this.primitive.destroy();
    for (const held of this.assets.values()) {
      void held.then((asset) => {
        asset.unload();
        this.options.app.assets.remove(asset);
      }, () => undefined);
    }
    this.assets.clear();
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
      const library = this.options.library;
      const kind = await library.kind({ key: record.kind.kind, version: record.kind.version, sha256: record.kind.sha256 });
      const chosen = this.lookChoices.get(id) ?? kind.looks[0] ?? null;
      let look: LookDrawing | null = null;
      if (chosen !== null) look = await library.look(chosen);
      const plan = look === null ? null : (await library.bodyPlans()).get(look.bodyPlan) ?? null;
      const container = look?.container == null ? null : await (this.options.instantiate ?? ((one: LookDrawing) => this.instance(one)))(look);
      if (stale()) {
        container?.model.destroy();
        return;
      }
      const figure = makeFigure({
        parent,
        device: this.options.app.graphicsDevice,
        name: `thing:${id}`,
        thingId: id,
        kind,
        look: look ?? { look: 'none', version: 1, label: 'no look', bodyPlan: kind.bodyPlan, lookKind: 'none', container: null, rig: null, heightMm: null, sampling: 'linear', light: null, role: null },
        plan,
        container,
        primitive: this.primitive,
      });
      entry.figure = figure;
      entry.look = look === null ? 'none' : `${look.look}/v${look.version}`;
      this.missed.delete(id);
      this.poseOne(entry, 0);
      if (this.picked === id) this.ring.place(figure.root, ringRadius(figure.pickVolume));
    } catch (error) {
      if (stale()) return;
      const reason = error instanceof FigureRefused || error instanceof LibraryRefused
        ? error.reason
        : error instanceof Error && 'reason' in error && typeof (error as { reason: unknown }).reason === 'string'
          ? (error as { reason: string }).reason
          : 'look_unreadable';
      this.miss(id, reason, error instanceof Error ? error.message : String(error));
    }
  }

  /** The look's container, loaded once a digest, instantiated for one figure. */
  private async instance(look: LookDrawing): Promise<InstancedContainer> {
    const reference = look.container!;
    let held = this.assets.get(reference.sha256);
    if (held === undefined) {
      held = this.options.library.container(reference).then(async (bytes) => {
        const asset = await createObjectContainerAsset(this.options.app, `thing-look:${reference.sha256.slice(0, 16)}`, bytes);
        if (look.sampling === 'nearest') nearestSampling(asset);
        return asset;
      });
      held.catch(() => this.assets.delete(reference.sha256));
      this.assets.set(reference.sha256, held);
    }
    const asset = await held;
    const resource = asset.resource as pc.ContainerResource & { animations?: pc.Asset[] };
    const model = resource.instantiateRenderEntity({});
    const tracks = new Map<string, pc.AnimTrack>();
    for (const clip of resource.animations ?? []) {
      const track = clip.resource as pc.AnimTrack;
      tracks.set(track.name, track);
    }
    return { model, tracks };
  }

  private step(dt: number): void {
    if (this.destroyed) return;
    const reduced = this.options.reducedMotion?.() === true;
    for (const entry of this.entries.values()) this.poseOne(entry, dt, reduced);
    const camera = this.options.camera.getPosition();
    for (const entry of this.entries.values()) {
      if (entry.figure instanceof PresenceFigure) entry.figure.face(camera);
      entry.figure?.afterAnimation?.();
    }
    this.ring.step(dt, reduced);
    if (this.animating) this.options.invalidate?.();
  }

  private poseOne(entry: Entry, dt: number, reducedMotion = false): void {
    const figure = entry.figure;
    if (figure === null) return;
    const t = entry.record.transform;
    figure.pose({
      position: [t.xMm / 1000, t.yMm / 1000, t.zMm / 1000],
      facing: facingOfYaw(t.yawMicroradians),
      deltaSeconds: dt,
      ...(reducedMotion ? { reducedMotion: true } : {}),
    });
  }
}

/** Draw a pixel-art look's textures as their pixels: nearest filtering, no blur between texels. */
function nearestSampling(asset: pc.Asset): void {
  const resource = asset.resource as pc.ContainerResource & { textures?: pc.Asset[] };
  for (const texture of resource.textures ?? []) {
    const t = texture.resource as pc.Texture | undefined;
    if (t === undefined) continue;
    t.minFilter = pc.FILTER_NEAREST;
    t.magFilter = pc.FILTER_NEAREST;
  }
}
