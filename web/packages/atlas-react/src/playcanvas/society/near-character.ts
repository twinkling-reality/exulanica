import type * as pc from 'playcanvas';
import { PlayerAvatar } from '../player-avatar.js';
import { abstractCharacter, syntheticCharacterStyle } from '../character-shape.js';
import type { CrowdPose, CrowdRenderable, CrowdRenderableFactory, InhabitantIdentity } from './types.js';

/**
 * The abstract figure as a crowd's full-detail person, for a caller that asks for it by name.
 *
 * A crowd draws catalog people unless it is given this factory. Keyed only by synthetic identity,
 * it never reads simulation state, and it has no seated posture: it draws every activity standing.
 */
class AbstractInhabitant implements CrowdRenderable {
  private readonly avatar: PlayerAvatar;
  private last: readonly [number, number] | null = null;
  private visible = true;

  constructor(device: pc.GraphicsDevice, parent: pc.Entity, identity: InhabitantIdentity) {
    const subject = {
      kind: 'synthetic-inhabitant' as const,
      societyId: identity.societyId,
      branchId: identity.branchId,
      inhabitantId: identity.inhabitantId,
    };
    this.avatar = new PlayerAvatar(device, parent, {
      name: `synthetic:${identity.inhabitantId}`,
      detail: 'mid',
      representation: abstractCharacter(subject, 'mid', syntheticCharacterStyle(identity.inhabitantId)),
    });
  }

  get root(): pc.Entity { return this.avatar.root; }
  get subject() { return this.avatar.representation.subject; }
  get representation() { return this.avatar.representation; }
  get standingHeight(): number { return this.avatar.body.heightMm / 1000; }
  get facing(): number { return this.avatar.facing; }
  get residentBytes(): number { return this.avatar.residentBytes; }
  get textureResidentBytes(): number { return this.avatar.textureResidentBytes; }

  /**
   * Solve and skin a new pose. The step is measured from the last posed point, so a pose that
   * follows several `follow` frames advances the gait by the whole distance walked since.
   */
  pose(pose: CrowdPose): void {
    const [x, , z] = pose.position;
    const previous = pose.discontinuity || this.last === null ? [x, z] : this.last;
    this.last = [x, z];
    this.avatar.update(
      { x, y: this.standingHeight * 0.89, z, yaw: 0, pitch: 0 },
      x - previous[0]!,
      z - previous[1]!,
      pose.deltaSeconds,
      this.visible,
      pose.reducedMotion ?? false,
      pose.position[1],
    );
  }

  /** Move the last skinned pose to the updated ground contact; posing is where the CPU cost is. */
  follow(position: readonly [number, number, number]): void {
    if (!this.visible) return;
    this.avatar.root.setLocalPosition(position[0], position[1], position[2]);
  }

  setVisible(visible: boolean): void {
    this.visible = visible;
    if (!visible) this.avatar.root.enabled = false;
  }

  destroy(): void { this.avatar.destroy(); }
}

export const abstractInhabitantRenderable: CrowdRenderableFactory = (device, parent, identity) =>
  new AbstractInhabitant(device, parent, identity);
