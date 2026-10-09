import * as pc from 'playcanvas';
import { FlightFlock } from '../flight/flock.js';
import type { FlightKindLook, FlightWindow } from '../flight/types.js';
import type { NativeCharacterFrame } from '../native-character-runtime.js';
import { createObjectContainerAsset } from '../scene-objects.js';
import { SocietyCrowd, type CrowdCounts, type CrowdFigures, type CrowdSeatingMiss } from './crowd.js';
import type { SeatingLayout } from './seating.js';
import type { CrowdJump, CrowdTiming, OwnedSocietyState } from './types.js';

/**
 * The inhabitants of a saved world, drawn over the region they live in.
 *
 * The same crowd the owned district draws, hung from the region's own root: the starter's authored
 * region, or the island of a world made from photographs (`./region-society.ts`). That root is the
 * frame the society states every position in, east and south integer millimetres about the region
 * origin at its floor, and it is the frame the person's objects are placed in, so an inhabitant
 * resting at an object is drawn at that object. A made world's island is turned and placed by the
 * page's layout, and the render origin follows the visitor, so every point that comes in from the
 * visitor's world (where they stand, the ray they pick along) is carried into the root's own frame
 * through its world transform and the render origin the frame loop last handed over. Nothing here
 * decides where anybody is: positions and paths come only from the persisted snapshot handed to
 * `setSociety`.
 *
 * Nothing occludes a pick here. A saved world's ground has no buildings, and its placed objects are
 * not solid to this ray; the nearest drawn inhabitant along it is the one selected.
 *
 * The flyers its objects host are drawn here too (`../flight/flock.ts`), from the windows of the
 * saved world's flight handed to `setFlight`, in the same frame; the flock is made with the first
 * window, so a world with no flight draws nothing more than it did.
 */
/**
 * A point of the visitor's world (render space plus the render origin) in `root`'s own frame:
 * moved into render space, then carried through the inverse of the root's world transform, which
 * holds its region's placement and turn. `fromWorld` is left holding that inverse, so a direction
 * can be carried by the same turn.
 */
export function visitorPointInRoot(
  root: pc.GraphNode,
  renderOrigin: { readonly x: number; readonly y: number; readonly z: number },
  point: readonly [number, number, number],
  fromWorld: pc.Mat4 = new pc.Mat4(),
  out: pc.Vec3 = new pc.Vec3(),
): pc.Vec3 {
  fromWorld.copy(root.getWorldTransform()).invert();
  out.set(point[0] - renderOrigin.x, point[1] - renderOrigin.y, point[2] - renderOrigin.z);
  return fromWorld.transformPoint(out, out);
}

/**
 * Where a ray of the visitor's world comes down to `root`'s ground (its own level plane, where its
 * people's feet are drawn), as a point of that frame in whole millimetres, as a society's state and
 * a person's walk name one; null where the ray never comes down to it.
 */
export function visitorRayOnRootGround(
  root: pc.GraphNode,
  renderOrigin: { readonly x: number; readonly y: number; readonly z: number },
  origin: readonly [number, number, number],
  direction: readonly [number, number, number],
): { readonly xMm: number; readonly zMm: number } | null {
  const fromWorld = new pc.Mat4();
  const from = visitorPointInRoot(root, renderOrigin, origin, fromWorld);
  const along = fromWorld.transformVector(new pc.Vec3(direction[0], direction[1], direction[2]), new pc.Vec3());
  if (!(along.y < 0) || from.y <= 0) return null;
  const t = -from.y / along.y;
  // Whole millimetres, never a negative zero (adding zero makes -0 plain 0).
  const mm = (metres: number): number => Math.round(metres * 1000) + 0;
  return { xMm: mm(from.x + t * along.x), zMm: mm(from.z + t * along.z) };
}

export class AuthoredRegionSociety {
  readonly root: pc.Entity;
  private readonly crowd: SocietyCrowd;
  private readonly ray = new pc.Ray();
  private readonly box = new pc.BoundingBox();
  private readonly hitPoint = new pc.Vec3();
  private flock: FlightFlock | null = null;
  private readonly flightAssets: { app: pc.AppBase; asset: pc.Asset }[] = [];
  private destroyed = false;
  /** Where render space starts in the visitor's world, as the frame loop last stated it. */
  private renderOrigin: { readonly x: number; readonly y: number; readonly z: number } = { x: 0, y: 0, z: 0 };
  private readonly fromWorld = new pc.Mat4();
  private readonly local = new pc.Vec3();
  private nearbySignature = '';

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
    return this.crowd.set(state, observer === undefined ? undefined : this.localGround(observer), options, layout).drawn;
  }

  /**
   * One frame's steps, from the frame loop: who is near the visitor, the interpolation, and, once
   * a second, the counts on the canvas and a `society-nearby-change` event when who is near
   * changed. `observer` is where the visitor stands in their world; `renderOrigin` is where render
   * space starts in it this frame.
   */
  step(
    canvas: HTMLCanvasElement | null,
    observer: readonly [number, number],
    renderOrigin: { readonly x: number; readonly y: number; readonly z: number },
    dt: number,
    nowMs: number,
    reducedMotion: boolean,
  ): void {
    this.renderOrigin = renderOrigin;
    this.refreshNearby(observer);
    this.tickSociety(reducedMotion ? Number.MAX_SAFE_INTEGER : nowMs);
    if (canvas === null || Math.floor(nowMs / 1000) === Math.floor((nowMs - dt * 1000) / 1000)) return;
    canvas.dataset.societyRendered = String(this.drawnInhabitantCount);
    canvas.dataset.societyNearby = String(this.visibleInhabitantIds.length);
    const signature = this.visibleInhabitantIds.join('|');
    if (signature === this.nearbySignature) return;
    this.nearbySignature = signature;
    canvas.dispatchEvent(new Event('society-nearby-change'));
  }

  /** A point of the visitor's world in this root's frame. */
  private localPoint(x: number, y: number, z: number): pc.Vec3 {
    return visitorPointInRoot(this.root, this.renderOrigin, [x, y, z], this.fromWorld, this.local);
  }

  /** Where the visitor stands, on the ground of this root's frame. */
  private localGround(observer: readonly [number, number]): [number, number] {
    const at = this.localPoint(observer[0], this.root.getPosition().y + this.renderOrigin.y, observer[1]);
    return [at.x, at.z];
  }

  /**
   * Draw the things among the inhabitants by their own looks, or everyone as one of the world's
   * people with null (`SocietyCrowd.setFigures`).
   */
  setFigures(figures: CrowdFigures | null): void {
    this.crowd.setFigures(figures);
  }

  /** Whether a person's drawn walk for the latest state has ended (`SocietyCrowd.walkEnded`). */
  walkEnded(id: string): boolean {
    return this.crowd.walkEnded(id);
  }

  /** The gate each visitor who crossed in came through (`SocietyCrowd.setGates`). */
  setGates(gates: ReadonlyMap<string, readonly [number, number]>): void {
    this.crowd.setGates(gates);
  }

  /** Whether a visitor the state has gone from is still drawn walking into its gate (`SocietyCrowd.isLeaving`). */
  isLeaving(id: string): boolean {
    return this.crowd.isLeaving(id);
  }

  /** Ask the things' figures again, as after the looks chosen for them change (`SocietyCrowd.refreshFigures`). */
  refreshFigures(): void {
    this.crowd.refreshFigures();
  }

  /**
   * Where a mark over an inhabitant hangs, in world space (`SocietyCrowd.anchorOf`), or false when
   * they are not drawn outdoors now. Those in flight are drawn by the flock and hang no mark yet.
   */
  anchorOf(id: string, out: pc.Vec3): boolean {
    return this.crowd.anchorOf(id, out);
  }

  /** Where an inhabitant's feet are drawn, in world space (`SocietyCrowd.groundOf`), or false when not drawn outdoors. */
  groundOf(id: string, out: pc.Vec3): boolean {
    return this.crowd.groundOf(id, out);
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

  /** Re-choose who is near, from the observer's position in their world. */
  refreshNearby(observer: readonly [number, number]): void {
    this.crowd.refresh(this.localGround(observer));
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

  /**
   * The nearest drawn inhabitant along a world-space ray, or null; with `limit`, only one nearer
   * than that many world metres along it (something else the ray meets first stands in front).
   */
  pickInhabitant(
    origin: readonly [number, number, number],
    direction: readonly [number, number, number],
    limit = Number.POSITIVE_INFINITY,
  ): string | null {
    // The crowd reports boxes in this root's frame, so the ray is carried into it: its origin as a
    // point of the visitor's world, its direction by the root's inverse turn.
    this.ray.origin.copy(this.localPoint(origin[0], origin[1], origin[2]));
    this.fromWorld.transformVector(new pc.Vec3(direction[0], direction[1], direction[2]), this.ray.direction);
    const length = this.ray.direction.length();
    if (!(length > 0)) return null;
    this.ray.direction.mulScalar(1 / length);
    // A world distance in this root's frame: the frame's scale along the ray.
    const toLocal = length / Math.hypot(direction[0], direction[1], direction[2]);
    return this.crowd.pick(limit * toLocal, (minimum, maximum) => {
      this.box.setMinMax(
        new pc.Vec3(minimum[0], minimum[1], minimum[2]),
        new pc.Vec3(maximum[0], maximum[1], maximum[2]),
      );
      return this.box.intersectsRay(this.ray, this.hitPoint)
        ? this.hitPoint.distance(this.ray.origin)
        : null;
    });
  }

  /**
   * Where a world-space ray comes down to this society's ground, a point of its own frame in
   * millimetres, or null: the spot a click on open ground names for a person's walk.
   */
  groundPoint(
    origin: readonly [number, number, number],
    direction: readonly [number, number, number],
  ): { readonly xMm: number; readonly zMm: number } | null {
    return visitorRayOnRootGround(this.root, this.renderOrigin, origin, direction);
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
