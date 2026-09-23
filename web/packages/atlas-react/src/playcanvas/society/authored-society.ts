import * as pc from 'playcanvas';
import type { NativeCharacterFrame } from '../native-character-runtime.js';
import { SocietyCrowd, type CrowdCounts } from './crowd.js';
import type { OwnedSocietyState } from './types.js';

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
 */
export class AuthoredRegionSociety {
  readonly root: pc.Entity;
  private readonly crowd: SocietyCrowd;
  private readonly ray = new pc.Ray();
  private readonly box = new pc.BoundingBox();
  private readonly hitPoint = new pc.Vec3();
  private destroyed = false;

  constructor(device: pc.GraphicsDevice, regionRoot: pc.Entity) {
    this.root = new pc.Entity('authored-region-society');
    regionRoot.addChild(this.root);
    this.crowd = new SocietyCrowd(device, this.root);
  }

  /** Present one canonical snapshot; returns how many inhabitants are drawn. */
  setSociety(
    state: OwnedSocietyState,
    observer?: readonly [number, number],
    options?: { readonly intervalMs?: number },
  ): number {
    return this.crowd.set(state, observer, options).drawn;
  }

  /** Release the population without inventing an authoritative snapshot. */
  clearSociety(): void {
    this.crowd.clear();
  }

  /** Interpolate display only; authoritative endpoints remain the society snapshots. */
  tickSociety(nowMs: number): void {
    this.crowd.update(nowMs);
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
    return this.crowd.animating;
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
    this.root.destroy();
  }
}
