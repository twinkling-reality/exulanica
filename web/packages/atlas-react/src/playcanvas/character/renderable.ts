/**
 * A person as the world draws it: a far form always, and a rigged near form when asked for and
 * available. The subject never moves on its own; `pose` receives resolved ground positions.
 */
import * as pc from 'playcanvas';
import type { CharacterSubject } from '@exulanica/atlas-core';
import type { CharacterHost } from './host.js';
import { activityPosture, catalogFamily, type CatalogFamily } from './catalog.js';
import { describeLook, type CharacterDetail, type CharacterLook, type CharacterRenderableDescription } from './look.js';
import { CharacterPerson } from './person.js';
import { FarPerson, farAppearance, type FarAppearance } from './far.js';

export interface CharacterPose {
  /** Ground contact point in metres, in the parent entity's space. */
  readonly position: readonly [number, number, number];
  /** Facing in radians about +Y, -Z forward. Omit to face the direction of travel. */
  readonly yaw?: number;
  readonly deltaSeconds: number;
  readonly reducedMotion?: boolean;
  /** A relocation: nothing is animated across it. */
  readonly discontinuity?: boolean;
  /**
   * What the person is doing where they stand, as the simulation states it: the kind of an action
   * under way, such as `rest`, or null for none. The catalog decides how an activity is drawn; an
   * activity it declares no posture for is drawn standing. Never inferred from motion.
   */
  readonly activity?: string | null;
}

export type CharacterRenderableStatus = 'pending' | 'ready' | 'unavailable';

export interface CharacterRenderable {
  readonly root: pc.Entity;
  readonly subject: CharacterSubject;
  readonly look: CharacterLook;
  readonly lookSha256: string;
  readonly detail: CharacterDetail;
  readonly status: CharacterRenderableStatus;
  readonly standingHeight: number;
  readonly facing: number;
  pose(pose: CharacterPose): void;
  /**
   * Carry the body to a new ground contact without solving a new pose.
   *
   * The clips keep playing, so the figure still moves; what is skipped is the per-frame solving:
   * speed and heading, the gait, the foot contact lock. A caller that carries between poses must
   * add up the time it skipped and hand it to the next `pose`, which then reads speed over the
   * whole gap rather than over one frame.
   *
   * Measured 2026-09-17: a pose costs 2.6 microseconds of this work per person, a carry at most 0.1.
   * That saving is 1.5 per cent of what a drawn person costs a frame, because the engine animates
   * and skins every drawn person whether or not it was posed
   * (test/character-evidence/follow-saving-2026-09-17.log.txt).
   */
  follow(position: readonly [number, number, number]): void;
  setDetail(detail: CharacterDetail): void;
  setVisible(visible: boolean): void;
  destroy(): void;
}

/** Tag on every renderable root, so older display paths leave these subjects alone. */
export const CHARACTER_RENDERABLE_TAG = 'character-renderable';

/** The root's name: who it draws, in the form the abstract figure's roots use. */
function rootName(subject: CharacterSubject): string {
  switch (subject.kind) {
    case 'player': return `player:${subject.playerId}`;
    case 'synthetic-inhabitant': return `synthetic:${subject.inhabitantId}`;
    case 'scene-person': return `scene-person:${subject.sceneId}:${subject.personRegionId}`;
    default: {
      const unknown: never = subject;
      throw new TypeError(`No character root name for ${JSON.stringify(unknown)}`);
    }
  }
}
const TURN_SECONDS = 0.14;
const MOVING_METRES_PER_SECOND = 0.05;

function wrap(angle: number): number {
  return Math.atan2(Math.sin(angle), Math.cos(angle));
}

export class LayeredCharacterRenderable implements CharacterRenderable {
  readonly root: pc.Entity;
  readonly lookSha256: string;
  private readonly far: FarPerson;
  private near: CharacterPerson | null = null;
  private request: AbortController | null = null;
  private wanted: CharacterDetail;
  private shown: CharacterDetail = 'far';
  private failure: string | null = null;
  private previous: readonly [number, number, number] | null = null;
  private heading: number | null = null;
  private speed = 0;
  private turnRate = 0;
  private visible = true;
  private disposed = false;
  private readonly unsubscribe: () => void;
  private readonly nearDescription: CharacterRenderableDescription;
  private readonly farDescription: CharacterRenderableDescription;
  private readonly family: CatalogFamily;
  private posture: string | null = null;

  constructor(
    private readonly host: CharacterHost,
    parent: pc.Entity,
    readonly subject: CharacterSubject,
    readonly look: CharacterLook,
    detail: CharacterDetail,
  ) {
    this.nearDescription = describeLook(host.catalog, look, 'near');
    this.farDescription = describeLook(host.catalog, look, 'far');
    this.family = catalogFamily(host.catalog, look.familyId);
    this.lookSha256 = this.nearDescription.lookSha256;
    this.root = new pc.Entity(rootName(subject), host.app);
    this.root.tags.add(CHARACTER_RENDERABLE_TAG);
    parent.addChild(this.root);
    this.far = new FarPerson(host.app, farAppearance(host.catalog, look));
    this.root.addChild(this.far.root);
    this.wanted = detail;
    this.unsubscribe = host.onLoader(() => this.ensureNear());
    this.ensureNear();
  }

  get detail(): CharacterDetail {
    return this.wanted;
  }

  get status(): CharacterRenderableStatus {
    if (this.wanted === 'far') return 'ready';
    if (this.shown === 'near') return 'ready';
    return this.failure ? 'unavailable' : 'pending';
  }

  get failureReason(): string | null {
    return this.failure;
  }

  get standingHeight(): number {
    return this.nearDescription.heightMillimetres / 1000;
  }

  get facing(): number {
    return this.heading ?? 0;
  }

  get description(): CharacterRenderableDescription {
    return this.shown === 'near' ? this.nearDescription : this.farDescription;
  }

  get resolvedSpeed(): number {
    return this.speed;
  }

  /** What this person's far form draws. */
  get farAppearance(): FarAppearance {
    return this.far.appearance;
  }

  /** The posture drawn for the activity last stated, or null for standing and moving. */
  get drawnPosture(): string | null {
    return this.posture;
  }

  get drawnForm(): CharacterDetail | 'hidden' {
    return this.visible && this.root.enabled ? this.shown : 'hidden';
  }

  private ensureNear(): void {
    if (this.disposed || this.wanted !== 'near' || this.near || this.request || this.failure || !this.host.hasLoader) return;
    const request = new AbortController();
    this.request = request;
    CharacterPerson.create(this.host, this.nearDescription, request.signal).then(
      (person) => {
        if (this.disposed || request.signal.aborted || this.wanted !== 'near') {
          person.destroy();
          return;
        }
        this.near = person;
        this.root.addChild(person.root);
        this.show('near');
      },
      (error: unknown) => {
        if (request.signal.aborted || this.disposed) return;
        // The far form stays as the explicit simple form; nothing is fabricated.
        this.failure = error instanceof Error ? error.message : String(error);
      },
    ).finally(() => {
      if (this.request === request) this.request = null;
    });
  }

  private show(form: CharacterDetail): void {
    this.shown = form;
    this.far.root.enabled = form === 'far';
    if (this.near) this.near.setVisible(form === 'near' && this.visible);
  }

  follow(position: readonly [number, number, number]): void {
    if (this.disposed) return;
    const [x, y, z] = position;
    if (![x, y, z].every(Number.isFinite)) throw new TypeError('Character pose must be finite');
    // `previous` stays where the last pose left it, so the next pose reads the travel of the whole
    // gap against the time the caller accumulated, and the gait keeps matching the ground.
    this.root.setLocalPosition(x, y, z);
  }

  setDetail(detail: CharacterDetail): void {
    if (this.disposed || detail === this.wanted) return;
    this.wanted = detail;
    if (detail === 'far') {
      this.request?.abort();
      this.request = null;
      this.near?.destroy();
      this.near = null;
      this.failure = null;
      this.show('far');
    } else {
      this.ensureNear();
    }
  }

  setVisible(visible: boolean): void {
    this.visible = visible;
    this.root.enabled = visible;
    this.near?.setVisible(visible && this.shown === 'near');
    if (!visible) this.previous = null;
  }

  pose(pose: CharacterPose): void {
    if (this.disposed) return;
    const [x, y, z] = pose.position;
    if (![x, y, z].every(Number.isFinite)) throw new TypeError('Character pose must be finite');
    const dt = Math.max(0, pose.deltaSeconds);
    const discontinuity = pose.discontinuity === true || this.previous === null;
    let speed = 0;
    let travel: number | null = null;
    if (!discontinuity && dt > 0) {
      const dx = x - this.previous![0], dz = z - this.previous![2];
      speed = Math.hypot(dx, dz) / dt;
      if (speed > MOVING_METRES_PER_SECOND) travel = Math.atan2(-dx, -dz);
    }
    this.previous = [x, y, z];
    const target = pose.yaw ?? travel ?? this.heading ?? 0;
    const before = this.heading ?? target;
    let heading = before;
    if (discontinuity || pose.reducedMotion) heading = target;
    else heading = wrap(before + wrap(target - before) * (1 - Math.exp(-dt / TURN_SECONDS)));
    this.turnRate = dt > 0 && !discontinuity ? wrap(heading - before) / dt : 0;
    this.heading = heading;
    this.speed = discontinuity ? 0 : speed;
    this.root.setLocalPosition(x, y, z);
    this.root.setLocalEulerAngles(0, (heading * 180) / Math.PI, 0);
    const reduced = pose.reducedMotion === true;
    this.posture = activityPosture(this.family, pose.activity);
    this.far.setPosture(this.posture);
    this.far.update(this.speed, dt, reduced);
    this.near?.update({ speed: this.speed, turnRate: this.turnRate, deltaSeconds: dt, reducedMotion: reduced, discontinuity, posture: this.posture });
  }

  // Members the district runtime reads from its display avatars. They keep that code unchanged.
  get body(): { readonly heightMm: number } {
    return { heightMm: this.nearDescription.heightMillimetres };
  }

  get representation(): { readonly subject: CharacterSubject; readonly representationId: string; readonly availability: 'available' } {
    return { subject: this.subject, representationId: `look:${this.lookSha256}`, availability: 'available' };
  }

  get residentBytes(): number {
    return 0;
  }

  get textureResidentBytes(): number {
    return 0;
  }

  /** Legacy avatar update: a resolved ground point plus this step's displacement. */
  update(
    state: { readonly x: number; readonly z: number },
    dx: number,
    dz: number,
    dt: number,
    visible: boolean,
    reduced: boolean,
    groundY = 0,
    headingYaw: number | null = null,
  ): void {
    if (visible !== this.visible) this.setVisible(visible);
    if (!visible) return;
    // This call passes the displacement that led here; rebuild the previous point from it.
    if (this.previous === null && (dx !== 0 || dz !== 0)) this.previous = [state.x - dx, groundY, state.z - dz];
    this.pose({
      position: [state.x, groundY, state.z],
      ...(headingYaw === null ? {} : { yaw: headingYaw }),
      deltaSeconds: dt,
      reducedMotion: reduced,
    });
  }

  destroy(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.unsubscribe();
    this.request?.abort();
    this.near?.destroy();
    this.far.destroy();
    this.root.destroy();
  }
}
