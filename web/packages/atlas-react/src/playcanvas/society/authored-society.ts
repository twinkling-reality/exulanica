import * as pc from 'playcanvas';
import { FlightFlock } from '../flight/flock.js';
import type { FlightKindLook, FlightWindow } from '../flight/types.js';
import type { NativeCharacterFrame } from '../native-character-runtime.js';
import { createObjectContainerAsset } from '../scene-objects.js';
import { SocietyCrowd, type CrowdCounts, type CrowdSeatingMiss } from './crowd.js';
import type { SeatingLayout } from './seating.js';
import type { CrowdJump, CrowdTiming, OwnedSocietyState } from './types.js';

/**
 * The inhabitants of a saved world, drawn over its authored region.
 *
 * The same crowd the owned district draws, hung from the authored region's own root. That root is
 * the frame the society states every position in, east and south integer millimetres about the
 * region origin at the ground's elevation, and it is the frame the person's objects are placed in,
 * so an inhabitant resting at an object is drawn at that object. Nothing here decides where anybody
 * is: positions and paths come only from the persisted snapshot handed to `setSociety`.
 *
 * Nothing occludes a pick here. A saved world's ground has no buildings, and its placed objects are
 * not solid to this ray; the nearest drawn inhabitant along it is the one selected.
 *
 * The flyers its objects host are drawn here too (`../flight/flock.ts`), from the windows of the
 * saved world's flight handed to `setFlight`, in the same frame; the flock is made with the first
 * window, so a world with no flight draws nothing more than it did.
 */
export class AuthoredRegionSociety {
  readonly root: pc.Entity;
  private readonly crowd: SocietyCrowd;
  private readonly ray = new pc.Ray();
  private readonly box = new pc.BoundingBox();
  private readonly hitPoint = new pc.Vec3();
  private flock: FlightFlock | null = null;
  private readonly flightAssets: { app: pc.AppBase; asset: pc.Asset }[] = [];
  private destroyed = false;

  constructor(device: pc.GraphicsDevice, regionRoot: pc.Entity) {
    this.root = new pc.Entity('authored-region-society');
    regionRoot.addChild(this.root);
    this.crowd = new SocietyCrowd(device, this.root);
  }

  /**
   * Present one canonical snapshot; returns how many inhabitants are drawn. `layout` says how the
   * objects people use are drawn at their places (`./seating.ts`); without one, everyone is drawn
   * where the snapshot puts them, facing the way they walked.
   */
  setSociety(
    state: OwnedSocietyState,
    observer?: readonly [number, number],
    options?: CrowdTiming,
    layout: SeatingLayout | null = null,
  ): number {
    return this.crowd.set(state, observer, options, layout).drawn;
  }

  /** Everyone drawn as everyone else is although their state says what they do, and why. */
  get seatingMisses(): readonly CrowdSeatingMiss[] {
    return this.crowd.seatingMisses;
  }

  /** Whether an inhabitant's rest is drawn on a seat: their place has one the catalog draws it on. */
  inhabitantSeatAtPlace(id: string): boolean {
    return this.crowd.seatAtPlace(id);
  }

  /**
   * Find everyone's place again from the objects drawn now (`SocietyCrowd.setLayout`), as after an
   * object is moved or removed, without waiting for the next state.
   */
  setSeatingLayout(layout: SeatingLayout | null): void {
    this.crowd.setLayout(layout);
  }

  /** Everyone the latest snapshot moved without walking, and why (`SocietyCrowd.jumps`). */
  get societyJumps(): readonly CrowdJump[] {
    return this.crowd.jumps;
  }

  /** Release the population without inventing an authoritative snapshot. */
  clearSociety(): void {
    this.crowd.clear();
  }

  /** Interpolate display only; authoritative endpoints remain the society snapshots. */
  tickSociety(nowMs: number): void {
    this.crowd.update(nowMs);
    this.flock?.update(nowMs);
  }

  /** Present one served window of the saved world's flight; the first starts its page clock. */
  setFlight(window: FlightWindow, nowMs: number): void {
    if (this.destroyed) return;
    (this.flock ??= new FlightFlock(this.root)).setWindow(window, nowMs);
  }

  /**
   * Draw a flying kind from its reviewed body and wing, given as verified container bytes; its
   * flyers appear from the next frame.
   */
  async setFlightKind(
    app: pc.AppBase,
    look: FlightKindLook,
    body: { readonly assetKey: string; readonly bytes: ArrayBuffer },
    wing: { readonly assetKey: string; readonly bytes: ArrayBuffer },
  ): Promise<void> {
    const assets = await Promise.all([
      createObjectContainerAsset(app, body.assetKey, body.bytes),
      createObjectContainerAsset(app, wing.assetKey, wing.bytes),
    ]);
    for (const asset of assets) this.flightAssets.push({ app, asset });
    if (this.destroyed) {
      this.releaseFlightAssets();
      return;
    }
    const [bodyAsset, wingAsset] = assets;
    (this.flock ??= new FlightFlock(this.root)).setKind(look, {
      body: () => (bodyAsset!.resource as pc.ContainerResource).instantiateRenderEntity({}),
      wing: () => (wingAsset!.resource as pc.ContainerResource).instantiateRenderEntity({}),
    });
  }

  hasFlightKind(key: string): boolean {
    return this.flock?.hasKind(key) ?? false;
  }

  /** The step the next window of this flight starts at, or null before the first window. */
  get flightNextStep(): number | null {
    return this.flock?.nextStep ?? null;
  }

  /** The flight's page clock, as a fractional step, or null before the first window. */
  flightStepAt(nowMs: number): number | null {
    return this.flock?.stepAt(nowMs) ?? null;
  }

  /** Frames drawn past the last served step, each holding it (`FlightFlock.starved`). */
  get flightStarvedFrames(): number {
    return this.flock?.starved ?? 0;
  }

  get drawnFlyerIds(): readonly string[] {
    return this.flock?.drawnFlyerIds ?? [];
  }

  /** Release every flyer and window of the flight; kinds stay loaded for the next one. */
  clearFlight(): void {
    this.flock?.clear();
  }

  private releaseFlightAssets(): void {
    for (const { app, asset } of this.flightAssets.splice(0)) {
      asset.unload();
      app.assets.remove(asset);
    }
  }

  /** Re-choose who is near, from the observer's world position. */
  refreshNearby(observer: readonly [number, number]): void {
    const origin = this.root.getPosition();
    this.crowd.refresh([observer[0] - origin.x, observer[1] - origin.z]);
  }

  get societyCounts(): CrowdCounts {
    return this.crowd.counts;
  }

  get societyAnimating(): boolean {
    return this.crowd.animating || (this.flock?.animating ?? false);
  }

  get drawnInhabitantCount(): number {
    return this.crowd.counts.drawn;
  }

  /** Every drawn inhabitant, full characters first, then far figures by distance. */
  get visibleInhabitantIds(): readonly string[] {
    return this.crowd.drawnIds;
  }

  /** Selecting an inhabitant keeps it a full character; it never moves anyone. */
  revealInhabitant(id: string): void {
    this.crowd.select(id);
  }

  coincidentInhabitants(id: string): readonly string[] {
    return this.crowd.sharing(id);
  }

  inhabitantRepresentation(id: string) {
    return this.crowd.representation(id);
  }

  inhabitantDetail(id: string): 'near' | 'far' | 'indoors' | 'not-drawn' {
    return this.crowd.detailOf(id);
  }

  nativeCharacterFrames(deltaSeconds: number, reducedMotion: boolean): readonly NativeCharacterFrame[] {
    return this.crowd.nativeFrames(deltaSeconds, reducedMotion);
  }

  get characterTextureBytes(): number {
    return this.crowd.textureResidentBytes;
  }

  get geometryResidentBytes(): number {
    return this.crowd.residentBytes;
  }

  /** The nearest drawn inhabitant along a world-space ray, or null. */
  pickInhabitant(
    origin: readonly [number, number, number],
    direction: readonly [number, number, number],
  ): string | null {
    // The crowd reports boxes in this root's frame. The root only ever translates, so the ray is
    // carried into it by subtracting where the root is.
    const at = this.root.getPosition();
    this.ray.origin.set(origin[0] - at.x, origin[1] - at.y, origin[2] - at.z);
    this.ray.direction.set(direction[0], direction[1], direction[2]);
    const length = this.ray.direction.length();
    if (!(length > 0)) return null;
    this.ray.direction.mulScalar(1 / length);
    return this.crowd.pick(Number.POSITIVE_INFINITY, (minimum, maximum) => {
      this.box.setMinMax(
        new pc.Vec3(minimum[0], minimum[1], minimum[2]),
        new pc.Vec3(maximum[0], maximum[1], maximum[2]),
      );
      return this.box.intersectsRay(this.ray, this.hitPoint)
        ? this.hitPoint.distance(this.ray.origin)
        : null;
    });
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.crowd.destroy();
    this.flock?.destroy();
    this.flock = null;
    this.releaseFlightAssets();
    this.root.destroy();
  }
}
