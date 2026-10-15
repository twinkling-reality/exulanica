import type {
  AtlasVec3,
  GroundMovementResolution,
  NavigationWorld,
  SpatialClassification,
  SupportState,
  TerrainState,
} from '@exulanica/atlas-core';
import { atlasVec3, forwardFromYawPitch, isNavigationPositionClear, resolveGroundMovement, SupportNavigationError, terrainGroundPose, terrainMillimetres } from '@exulanica/atlas-core';

/**
 * First-person controls: pointer-lock mouse-look plus WASD, and a reticle at fixed screen centre.
 *
 * THE ONE FACT THAT SHAPES THIS FILE. Pointer Lock 2.0 states that while locked,
 * `clientX`/`clientY` and `screenX`/`screenY` "must hold constant values as if the pointer did not
 * move at all once pointer lock was entered", while `movementX`/`movementY` have no limit.
 * https://w3c.github.io/pointerlock/
 *
 * So there is no cursor to hover with and targeting is reticle-based, at screen centre, always.
 * This module therefore never reads a cursor position and never exposes one. It publishes a yaw
 * and a pitch, and the focus solver turns those into a forward vector. Any future code that wants
 * to hover a world object with the mouse is unimplementable and should be rejected here.
 *
 * THE SECOND FACT. The same specification requires that "a default unlock gesture must always be
 * available that will exit pointer lock", recommends Escape, and exits lock when the window loses
 * focus; re-locking after a user-initiated unlock needs a fresh engagement gesture.
 * https://developer.mozilla.org/en-US/docs/Web/API/Pointer_Lock_API
 *
 * So this renderer control never binds Escape, never calls `requestPointerLock` outside a real
 * user gesture, and never auto-relocks. It observes `pointerlockchange` and follows. Once the lock
 * is already absent, a separate converse-mode surface may use Escape for its ordinary dismissal.
 * The two input modes in the interaction model, `traverse` and `converse`, are therefore a READ of
 * the browser's lock state rather than a state this module owns.
 *
 * BEFORE LOOKING AROUND. While the lock is absent the pointer is an ordinary cursor, and a plain
 * click on the world (pressed and released within CLICK_SLOP_PX and CLICK_MS) is handed to the
 * application as that screen point (`onPointerPick`), which picks what is under it and says whether
 * it took the click. A click it does not take, and any press that drags or is held, enters camera
 * look exactly as a press always has. Nothing hovers, and once the lock is held, targeting is the
 * reticle's alone.
 *
 * NO JUMP VERB. The space bar is Interact. That is a product decision, not an omission.
 *
 * FLYING (F). A person may leave the ground to look around: the camera, never anyone in the world,
 * moves where it looks, through walls, held within the world's reach and above the ground. While
 * flying, Space rises and C descends (Space does not interact then; E and Enter still do), Shift
 * doubles the speed, and the scroll wheel sets it. F again lands on the open ground below.
 */

/** How far a press may move, in CSS pixels, and still be a click rather than a drag to look. */
export const CLICK_SLOP_PX = 4;
/** How long a press may last, in milliseconds, and still be a click. */
export const CLICK_MS = 300;

export type InputMode = 'traverse' | 'converse';

export interface ControlsConfig {
  readonly sensitivity: number;
  readonly moveSpeed: number;
  readonly sprintMultiplier: number;
  /** Critically damped acceleration ramp, in seconds to reach most of the target velocity. */
  readonly accelTime: number;
  readonly eyeHeight: number;
}

export const DEFAULT_CONTROLS: ControlsConfig = Object.freeze({
  sensitivity: 0.0022,
  moveSpeed: 9,
  sprintMultiplier: 2.6,
  accelTime: 0.12,
  eyeHeight: 1.62,
});

/**
 * Flying speeds, metres a second. A first flight crosses a garden in a few seconds; the scroll wheel
 * steps it by a quarter each notch, down to a slow drift for looking closely and up to crossing a
 * town's kilometres quickly; Shift doubles whatever it is.
 */
export const FLY_SPEED = Object.freeze({ start: 12, least: 2, most: 150, step: 1.25, sprint: 2 });
/** How high flying may go above the world's ground, metres: a town seen whole, not the sky. */
export const FLY_CEILING_M = 600;
/** How far above the ground below a flying eye always stays, metres: never under the ground. */
export const FLY_FLOOR_M = 0.3;
/** Where landing looks for open ground around the spot below, metres from it, nearest first. */
const LANDING_RINGS_M = [0, 1, 2, 4, 8, 16] as const;

/** A small epsilon short of straight up and straight down: the user must be able to look at threads. */
const PITCH_LIMIT = Math.PI / 2 - 0.01;

export interface CameraState {
  terrain?: TerrainState;
  support?: SupportState;
  x: number;
  y: number;
  z: number;
  yaw: number;
  pitch: number;
}

/**
 * What carries the pose from one frame to the next.
 *
 * `ground` stands it on the navigation world's surface: every move is resolved against that surface
 * and its field, and the eye sits at eye height above it. `altitude` keeps the height a view gave
 * it, as an overview from above does: movement pans across the world at that height and no surface
 * resolves it. A view states its hold when it is set (`setView`); nothing infers one from a height.
 * `fly` is a person flying (F): the camera moves where it looks, through anything, held within the
 * world's reach and above its ground.
 */
export type CameraHold = 'ground' | 'altitude' | 'fly';

export interface PlanarMovement {
  readonly x: number;
  readonly z: number;
}

/**
 * How far from the field's centre a view held at altitude may pan: as far as the field's recovery
 * envelope, or as far as the view was set if that is farther. It can cross the whole field and
 * return to where it was framed from, and it cannot drift away from the world it is looking at.
 */
function altitudeReachFrom(world: NavigationWorld, pose: CameraState): number {
  return Math.max(world.recoveryRadius, Math.hypot(pose.x - world.centre.x, pose.z - world.centre.z));
}

/** Convert normalized keyboard intent into the horizontal camera basis. */
export function cameraRelativeMovement(
  right: number,
  forward: number,
  yaw: number,
): PlanarMovement {
  const length = Math.hypot(right, forward);
  if (!Number.isFinite(length) || length === 0 || !Number.isFinite(yaw)) {
    return Object.freeze({ x: 0, z: 0 });
  }
  const normalizedRight = right / Math.max(1, length);
  const normalizedForward = forward / Math.max(1, length);
  const sine = Math.sin(yaw);
  const cosine = Math.cos(yaw);
  return Object.freeze({
    x: normalizedForward * -sine + normalizedRight * cosine,
    z: normalizedForward * -cosine - normalizedRight * sine,
  });
}

export class FirstPersonControls {
  readonly state: CameraState;

  private readonly canvas: HTMLCanvasElement;
  private readonly config: ControlsConfig;
  private sensitivityMultiplier = 1;
  private enabled = true;
  private conversationActive = false;
  private readonly keys = new Set<string>();
  private vx = 0;
  private vz = 0;
  private intent: PlanarMovement = Object.freeze({ x: 0, z: 0 });
  private locked = false;
  private lastSafe: AtlasVec3 | null = null;
  private lastSafeSupport: SupportState | undefined;
  private lastSafeTerrain: TerrainState | undefined;
  /** Only the never-accepted original entry may wait for an asynchronous source attachment. */
  private pendingTerrainEntry: {readonly x: number; readonly y: number; readonly z: number;
    readonly worldId: string; readonly receiptSha256: string; readonly geometrySha256: string; readonly contactSha256: string} | null = null;
  private navigationWorld: NavigationWorld | null;
  private cameraHold: CameraHold;
  /** How far from the field's centre a view held at altitude may pan; see `altitudeReachFrom`. */
  private altitudeReach = 0;
  private spatial: SpatialClassification | null = null;
  private recoveryReason: GroundMovementResolution['recoveryReason'] = null;
  private disposers: Array<() => void> = [];
  private vy = 0;
  /** The flying speed the scroll wheel has set, metres a second; kept for the session. */
  private flySpeed: number = FLY_SPEED.start;
  /** Fired when flying starts or stops, however it stops (F, a view set, travel). */
  onFlyChange: ((flying: boolean) => void) | null = null;

  /** Fired when the browser's lock state changes. The application follows; it never drives. */
  onModeChange: ((mode: InputMode) => void) | null = null;
  /** Interact. E is the visible world binding; Space and Enter remain keyboard alternatives. */
  onInteract: (() => void) | null = null;
  /** Summon or dismiss Companion. Bound to X and right click. */
  onSummon: (() => void) | null = null;
  /**
   * A plain click on the world while not looking around, at its screen point: true when the
   * application picked something there and took the click, so no camera look starts. Null keeps
   * every press for camera look.
   */
  onPointerPick: ((clientX: number, clientY: number) => boolean) | null = null;
  /** A left press that may still be a click, while the lock is absent. */
  private press: { readonly x: number; readonly y: number; readonly at: number } | null = null;
  private walkAssist:'off'|'walk'|'run'='off';
  setWalkAssist(mode:'off'|'walk'|'run'):void {this.walkAssist=mode;}

  onCameraToggle: (() => void) | null = null;

  constructor(
    canvas: HTMLCanvasElement,
    start: CameraState,
    config = DEFAULT_CONTROLS,
    navigationWorld: NavigationWorld | null = null,
    options: { readonly hold?: CameraHold } = {},
  ) {
    this.canvas = canvas;
    this.config = config;
    this.navigationWorld = navigationWorld;
    this.state = { ...start };
    this.cameraHold = options.hold ?? 'ground';
    if (navigationWorld?.terrain === undefined && navigationWorld?.support !== undefined) {
      this.state.support = start.support ?? navigationWorld.support.entry;
      this.lastSafeSupport = this.state.support;
    }
    let initialGround: { readonly height: number } | null | undefined;
    try {
      if (navigationWorld?.terrain !== undefined) {
        const point = [terrainMillimetres(start.x), terrainMillimetres(start.z)] as const;
        const entry = navigationWorld.terrain.entryMm;
        const mayInitialize = start.terrain !== undefined || (point[0] === entry[0] && point[1] === entry[1]);
        const accepted = mayInitialize ? terrainGroundPose(navigationWorld, point, start.terrain) : null;
        if (accepted !== null && start.x === accepted.position.x && start.z === accepted.position.z
            && Number.isFinite(start.y) && Math.abs(start.y - accepted.position.y) <= .001) {
          this.state.terrain = accepted.state;
          this.lastSafeTerrain = accepted.state;
          initialGround = { height: accepted.position.y - navigationWorld.eyeHeight };
        } else {
          initialGround = null;
          if (start.terrain === undefined && mayInitialize && navigationWorld.terrain.occupancy.status !== 'verified'
              && [start.x, start.y, start.z].every(Number.isFinite)) {
            this.pendingTerrainEntry = {x: start.x, y: start.y, z: start.z,
              worldId: navigationWorld.terrain.source.worldId, receiptSha256: navigationWorld.terrain.source.receiptSha256,
              geometrySha256: navigationWorld.terrain.contact.geometry.sha256, contactSha256: navigationWorld.terrain.contact.sha256};
          }
        }
      } else initialGround = navigationWorld?.support === undefined ? navigationWorld?.surface.sample(start.x, start.z)
        : { height: navigationWorld.support.at(this.state.support!, [start.x * 1000, start.z * 1000]) / 1000 };
    } catch (error) {
      if (navigationWorld?.terrain !== undefined && error instanceof RangeError) initialGround = null;
      else if (!(error instanceof SupportNavigationError) || this.cameraHold === 'ground') throw error;
      initialGround = null;
    }
    if (navigationWorld?.terrain !== undefined) {
      if (this.lastSafeTerrain !== undefined) this.canvas.dataset['navigationTerrain'] = JSON.stringify(this.lastSafeTerrain);
      this.disposers.push(() => { delete this.canvas.dataset['navigationTerrain']; delete this.canvas.dataset['navigationTerrainFailure']; });
    }
    if (this.state.support !== undefined) {
      this.canvas.dataset['navigationSupport'] = JSON.stringify(this.state.support);
      this.disposers.push(() => { delete this.canvas.dataset['navigationSupport']; });
    }
    if (navigationWorld !== null && initialGround != null) {
      const grounded = initialGround.height + navigationWorld.eyeHeight;
      /*
       * Ground the start pose only when it is meant to be one.
       *
       * `flatNavigationSurface` samples everywhere and never returns null, so grounding every
       * start pose silently teleports the deliberate aerial poses too: an overview at y = 95
       * lands at roughly 0.3 with its downward pitch intact, aimed at the dirt. Recovery still
       * seeds from the grounded point either way.
       */
      if (this.cameraHold === 'ground') this.state.y = grounded;
      this.lastSafe = atlasVec3(this.state.x, grounded, this.state.z);
    }
    if (navigationWorld !== null && this.cameraHold === 'altitude') {
      this.altitudeReach = altitudeReachFrom(navigationWorld, this.state);
    }
    const previousTabIndex = canvas.getAttribute('tabindex');
    canvas.tabIndex = 0;
    this.disposers.push(() => { if (previousTabIndex === null) canvas.removeAttribute('tabindex'); else canvas.setAttribute('tabindex', previousTabIndex); });

    const on = <K extends keyof DocumentEventMap>(
      target: Document | HTMLElement | Window,
      type: K | string,
      handler: (e: never) => void,
      opts?: AddEventListenerOptions,
    ): void => {
      target.addEventListener(type, handler as EventListener, opts);
      this.disposers.push(() => target.removeEventListener(type, handler as EventListener));
    };

    on(document, 'pointerlockchange', () => {
      this.locked = document.pointerLockElement === this.canvas;
      if (!this.locked) {
        this.keys.clear();
        this.vx = 0;
        this.vy = 0;
        this.vz = 0;
        this.intent = Object.freeze({ x: 0, z: 0 });
      }
      this.onModeChange?.(this.locked ? 'traverse' : 'converse');
    });

    on(document, 'mousemove', (e: MouseEvent) => {
      if (!this.locked) return;
      // movementX/movementY only. clientX/clientY are frozen by the specification.
      if (!this.enabled) return;
      this.state.yaw -= e.movementX * this.config.sensitivity * this.sensitivityMultiplier;
      this.state.pitch -= e.movementY * this.config.sensitivity * this.sensitivityMultiplier;
      this.state.pitch = Math.max(-PITCH_LIMIT, Math.min(PITCH_LIMIT, this.state.pitch));
    });

    // A real user gesture, which is the only thing that may request the lock. Some embedded
    // browsers refuse pointer lock; focused keyboard navigation still works.
    const lock = (): void => { void this.canvas.requestPointerLock()?.catch(() => undefined); };
    on(canvas, 'mousedown', (e: MouseEvent) => {
      if (!this.locked) {
        if (!this.enabled || this.conversationActive) return;
        // A press made while a person types in a field is never a pick: it only leaves the field.
        const active = document.activeElement;
        const typing = active instanceof HTMLElement
          && (active.isContentEditable || active.closest('input, textarea, select') !== null);
        this.canvas.focus();
        // A left press may be a click on something; it looks around once it drags, lasts or misses.
        if (e.button === 0 && this.onPointerPick !== null && !typing) {
          this.press = { x: e.clientX, y: e.clientY, at: Date.now() };
          return;
        }
        lock();
        return;
      }
      // A left click belongs exclusively to entering/maintaining camera look. Treating the same
      // gesture as Interact opened a memory surface when the person was only trying to look.
      if (e.button === 2) this.onSummon?.();
    });
    on(document, 'mousemove', (e: MouseEvent) => {
      const press = this.press;
      if (press === null || Math.hypot(e.clientX - press.x, e.clientY - press.y) <= CLICK_SLOP_PX) return;
      this.press = null;
      lock();
    });
    on(document, 'mouseup', (e: MouseEvent) => {
      const press = this.press;
      if (press === null) return;
      this.press = null;
      const click = Date.now() - press.at <= CLICK_MS
        && Math.hypot(e.clientX - press.x, e.clientY - press.y) <= CLICK_SLOP_PX;
      if (click && this.onPointerPick?.(e.clientX, e.clientY) === true) return;
      lock();
    });
    on(canvas, 'contextmenu', (e: Event) => e.preventDefault());

    on(window, 'keydown', (e: KeyboardEvent) => {
      // While this renderer may own movement, Escape belongs to the browser's unlock gesture.
      // Converse-mode UI can handle it only after pointer lock has already been released.
      if (e.code === 'Escape') {this.walkAssist='off';return;}
      const target = e.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable || target.closest('input, textarea, select, button, summary') !== null)
      ) {
        return;
      }
      if (!this.enabled) return;
      if (e.code === 'KeyF' && !e.repeat && !this.conversationActive) { e.preventDefault(); this.toggleFly(); return; }
      // While flying C descends; on the ground it is the camera toggle, as before.
      if (e.code === 'KeyC' && !e.repeat && this.cameraHold !== 'fly') { e.preventDefault(); this.onCameraToggle?.(); return; }
      if(['KeyW','KeyA','KeyS','KeyD'].includes(e.code))this.walkAssist='off';
      this.keys.add(e.code);
      if (document.activeElement === this.canvas && (e.code.startsWith('Arrow') || ['KeyW','KeyA','KeyS','KeyD'].includes(e.code))) e.preventDefault();
      if ((this.locked || document.activeElement === this.canvas) && (e.code === 'Space' || e.code === 'KeyE' || e.code === 'Enter')) {
        e.preventDefault();
        // Flying, Space rises: it interacts on the ground only.
        if (!(e.code === 'Space' && this.cameraHold === 'fly')) this.onInteract?.();
      }
      if (e.code === 'KeyX' && !e.repeat) {
        e.preventDefault();
        this.onSummon?.();
      }
    });
    // Flying, the wheel sets the speed; on the ground it does nothing here.
    on(canvas, 'wheel', (e: WheelEvent) => {
      if (this.cameraHold !== 'fly' || !this.enabled || e.deltaY === 0) return;
      e.preventDefault();
      this.setFlySpeed(this.flySpeed * (e.deltaY < 0 ? FLY_SPEED.step : 1 / FLY_SPEED.step));
    }, { passive: false });
    on(document, 'focusin', (event: FocusEvent) => {
      if(event.target instanceof HTMLElement && event.target.closest('input,textarea,select,[contenteditable]'))this.walkAssist='off';
      if (event.target instanceof HTMLElement && event.target.closest('input, textarea, select, button, summary, [contenteditable]')) {
        this.keys.clear(); this.vx = 0; this.vz = 0;
        this.intent = Object.freeze({ x: 0, z: 0 });
      }
    });
    on(window, 'keyup', (e: KeyboardEvent) => this.keys.delete(e.code));
    on(window, 'blur', () => {
      this.walkAssist='off';
      this.keys.clear();
      this.vx = 0;
      this.vz = 0;
      this.intent = Object.freeze({ x: 0, z: 0 });
    });
  }

  get mode(): InputMode {
    return this.locked ? 'traverse' : 'converse';
  }

  get hold(): CameraHold {
    return this.cameraHold;
  }

  /**
   * Put the camera at a view and hold it there the way the view names.
   *
   * A ground view is stood on the surface at once, so its first frame is already the one it keeps,
   * and becomes the safe point recovery returns to when it is on the field. An altitude view keeps
   * its height and pans from there.
   */
  setView(pose: CameraState, hold: CameraHold): void {
    const wasFlying = this.cameraHold === 'fly';
    this.setViewHeld(pose, hold);
    if (wasFlying !== (this.cameraHold === 'fly')) this.onFlyChange?.(this.cameraHold === 'fly');
  }

  private setViewHeld(pose: CameraState, hold: CameraHold): void {
    const terrainWorld = this.navigationWorld?.terrain === undefined ? null : this.navigationWorld;
    if (terrainWorld !== null && hold === 'ground') {
      if (pose.terrain === undefined) return;
      try {
        const accepted = terrainGroundPose(terrainWorld, [terrainMillimetres(pose.x), terrainMillimetres(pose.z)], pose.terrain);
        if (accepted === null || pose.x !== accepted.position.x || pose.z !== accepted.position.z
            || !Number.isFinite(pose.y) || Math.abs(pose.y - accepted.position.y) > .001) return;
        this.state.terrain = accepted.state;
        this.lastSafeTerrain = accepted.state;
      } catch (error) { if (!(error instanceof RangeError)) throw error; return; }
    }
    const supported = terrainWorld === null ? this.navigationWorld?.support : undefined;
    if (supported !== undefined && hold === 'ground') {
      const state = pose.support ?? supported.entry;
      try {
        const height = supported.at(state, [pose.x * 1000, pose.z * 1000]) / 1000 + this.navigationWorld!.eyeHeight;
        if (!Number.isFinite(pose.y) || Math.abs(pose.y - height) > .001) return;
        this.state.support = state;
        this.lastSafeSupport = state;
      } catch (error) { if (!(error instanceof SupportNavigationError)) throw error; return; }
    }
    const { support: _viewSupport, terrain: _viewTerrain, ...visualPose } = pose;
    Object.assign(this.state, (supported !== undefined || terrainWorld !== null) && hold !== 'ground' ? visualPose : pose);
    this.vx = 0;
    this.vy = 0;
    this.vz = 0;
    this.intent = Object.freeze({ x: 0, z: 0 });
    this.cameraHold = hold;
    const world = this.navigationWorld;
    if (world === null) return;
    if (hold !== 'ground') {
      this.altitudeReach = altitudeReachFrom(world, pose);
      return;
    }
    if (terrainWorld !== null) {
      this.lastSafe = atlasVec3(this.state.x, this.state.y, this.state.z);
      this.canvas.dataset['navigationTerrain'] = JSON.stringify(this.state.terrain);
      return;
    }
    const ground = world.support === undefined ? world.surface.sample(pose.x, pose.z)
      : { height: world.support.at(this.state.support!, [pose.x * 1000, pose.z * 1000]) / 1000 };
    if (ground == null) return;
    this.state.y = ground.height + world.eyeHeight;
    if (Math.hypot(pose.x - world.centre.x, pose.z - world.centre.z) <= world.fieldRadius) {
      this.lastSafe = atlasVec3(pose.x, this.state.y, pose.z);
    }
  }

  /**
   * The walking world replaced while the world stays open (a made part moved or removed, a basin
   * graded again): on the ground, the person stands on the new ground where they are, or on the
   * nearest clear ground around them as landing finds it; held at altitude or flying, the view keeps
   * its height and its reach is read again. Only a world walked on its surface is replaced so: a
   * world of terrain or of supports keeps the walking world it opened with.
   */
  replaceNavigation(next: NavigationWorld): void {
    const now = this.navigationWorld;
    if (now === null || now.terrain !== undefined || now.support !== undefined || next.terrain !== undefined || next.support !== undefined) {
      throw new Error('Only a world walked on its surface takes a new walking world while it is open.');
    }
    this.navigationWorld = next;
    // Where the person last stood stays the place to go back to only while it is still open ground.
    if (this.lastSafe !== null && !isNavigationPositionClear(next, this.lastSafe)) this.lastSafe = null;
    if (this.cameraHold === 'ground') this.standOnOpenGround();
    else this.altitudeReach = altitudeReachFrom(next, this.state);
  }

  /**
   * Stand on the ground again from wherever the pose is, as travel does: its transition ends on
   * the surface, and the frames after it are walked.
   */
  holdGround(): void {
    if (this.cameraHold === 'fly') {
      this.land();
      return;
    }
    if (this.navigationWorld?.terrain !== undefined && this.cameraHold === 'altitude') {
      const held = this.lastSafeTerrain;
      const accepted = held === undefined ? null : terrainGroundPose(this.navigationWorld, held.positionMm, held);
      // Returning from an overview restores the held accepted contact, never a new sampled floor.
      if (accepted === null) return;
      this.state.x = accepted.position.x; this.state.y = accepted.position.y; this.state.z = accepted.position.z;
      this.state.terrain = accepted.state;
    }
    this.cameraHold = 'ground';
  }

  /** Whether the person is flying (F). */
  get flying(): boolean {
    return this.cameraHold === 'fly';
  }

  /** The flying speed the scroll wheel has set, metres a second. */
  get flyingSpeed(): number {
    return this.flySpeed;
  }

  /** Set the flying speed, held within `FLY_SPEED`'s least and most. */
  setFlySpeed(metresPerSecond: number): void {
    if (!Number.isFinite(metresPerSecond)) return;
    this.flySpeed = Math.min(FLY_SPEED.most, Math.max(FLY_SPEED.least, metresPerSecond));
  }

  /** Take off from where the camera is, or land if flying. */
  toggleFly(): void {
    if (this.cameraHold === 'fly') {
      this.land();
      return;
    }
    this.lastSafe ??= atlasVec3(this.state.x, this.state.y, this.state.z);
    this.cameraHold = 'fly';
    if (this.navigationWorld !== null) this.altitudeReach = altitudeReachFrom(this.navigationWorld, this.state);
    this.walkAssist = 'off';
    this.vy = 0;
    this.onFlyChange?.(true);
  }

  /**
   * Land from flying: on the open ground below, or the nearest open ground within a few metres of
   * it, or else back where the person last stood. A world whose ground is an admitted terrain or a
   * support network lands where the person took off, since a new stand there needs its own contact.
   */
  private land(): void {
    this.standOnOpenGround();
    this.onFlyChange?.(false);
  }

  /**
   * Stand on the open ground below, or the nearest open ground within a few metres of it, or else
   * back where the person last stood, still: landing's search, which says nothing about flying.
   */
  private standOnOpenGround(): void {
    const world = this.navigationWorld;
    const { yaw, pitch } = this.state;
    const back = (): void => {
      const safe = this.lastSafe;
      if (world?.terrain !== undefined) {
        this.cameraHold = 'altitude';
        this.holdGround();
        return;
      }
      if (safe === null || world === null) {
        this.cameraHold = 'ground';
        return;
      }
      this.setViewHeld({ ...this.state, x: safe.x, y: safe.y, z: safe.z, yaw, pitch }, 'ground');
    };
    if (world === null || world.terrain !== undefined || world.support !== undefined) {
      back();
    } else {
      let landed = false;
      for (const ring of LANDING_RINGS_M) {
        for (let k = 0; k < (ring === 0 ? 1 : 8) && !landed; k += 1) {
          const angle = (k * Math.PI) / 4;
          const x = this.state.x + ring * Math.cos(angle), z = this.state.z + ring * Math.sin(angle);
          const ground = world.surface.sample(x, z);
          if (ground == null) continue;
          const at = atlasVec3(x, ground.height + world.eyeHeight, z);
          if (!isNavigationPositionClear(world, at)) continue;
          this.setViewHeld({ ...this.state, x, y: at.y, z, yaw, pitch }, 'ground');
          this.lastSafe = at;
          landed = true;
        }
        if (landed) break;
      }
      if (!landed) back();
    }
    this.vx = 0;
    this.vy = 0;
    this.vz = 0;
  }

  get movementSpeed(): number {
    return Math.hypot(this.vx, this.vz);
  }

  /** Camera-relative heading requested this frame, before collision and acceleration. */
  get movementHeading(): number | null {
    return Math.hypot(this.intent.x, this.intent.z) > 0.0001
      ? Math.atan2(-this.intent.x, -this.intent.z)
      : null;
  }

  get spatialClassification(): SpatialClassification | null {
    return this.spatial;
  }

  /** One-shot recovery event for contextual UI. Reading it consumes it. */
  consumeRecoveryReason(): GroundMovementResolution['recoveryReason'] {
    const reason = this.recoveryReason;
    this.recoveryReason = null;
    return reason;
  }

  setSensitivityMultiplier(multiplier: number): void {
    if (!Number.isFinite(multiplier)) return;
    this.sensitivityMultiplier = Math.max(0.5, Math.min(2, multiplier));
  }

  /** Map is a camera presentation, so ground movement pauses without changing input mode. */
  setEnabled(enabled: boolean): void {
    if(!enabled)this.walkAssist='off';
    this.enabled = enabled;
    if (!enabled) {
      this.keys.clear();
      this.vx = 0;
      this.vz = 0;
      this.intent = Object.freeze({ x: 0, z: 0 });
    }
  }

  /**
   * Answering keeps a free cursor and blocks pointer recapture, but walking remains available.
   * Camera look stays fixed until the person clicks the world again after dismissing the turn.
   */
  setConversationActive(active: boolean): void {
    this.conversationActive = active;
    this.keys.clear();
    this.vx = 0;
    this.vz = 0;
    this.intent = Object.freeze({ x: 0, z: 0 });
    if (active && this.locked && document.pointerLockElement === this.canvas) {
      document.exitPointerLock();
    }
  }

  private acceptPendingTerrainEntry(): void {
    const pending = this.pendingTerrainEntry, world = this.navigationWorld;
    if (pending === null || world?.terrain === undefined) return;
    const source = world.terrain;
    if (this.cameraHold !== 'ground' || this.state.terrain !== undefined || this.lastSafeTerrain !== undefined
        || this.state.x !== pending.x || this.state.y !== pending.y || this.state.z !== pending.z
        || source.source.worldId !== pending.worldId || source.source.receiptSha256 !== pending.receiptSha256
        || source.contact.geometry.sha256 !== pending.geometrySha256 || source.contact.sha256 !== pending.contactSha256) {
      this.pendingTerrainEntry = null; return;
    }
    if (source.occupancy.status !== 'verified') return;
    // One current, complete authorization attempt. A failed or later revoked pose is never retried here.
    this.pendingTerrainEntry = null;
    const accepted = terrainGroundPose(world, source.entryMm);
    if (accepted === null || accepted.position.x !== pending.x || accepted.position.z !== pending.z
        || Math.abs(accepted.position.y - pending.y) > .001) return;
    this.state.terrain = accepted.state; this.lastSafeTerrain = accepted.state;
    this.state.y = accepted.position.y; this.lastSafe = accepted.position;
  }

  /** Advance by `dt` seconds. System surfaces never share ownership with locomotion. */
  update(dt: number): void {
    if (!this.enabled || !Number.isFinite(dt) || dt <= 0) return;
    this.acceptPendingTerrainEntry();
    dt = Math.min(dt, .05);
    let ix = 0;
    let iz = 0;
    if (!this.conversationActive && (this.locked || document.activeElement === this.canvas)) {
      const turn = 1.35 * dt;
      if (this.keys.has('ArrowLeft')) this.state.yaw += turn;
      if (this.keys.has('ArrowRight')) this.state.yaw -= turn;
      if (this.keys.has('ArrowUp')) this.state.pitch = Math.min(PITCH_LIMIT, this.state.pitch + turn);
      if (this.keys.has('ArrowDown')) this.state.pitch = Math.max(-PITCH_LIMIT, this.state.pitch - turn);
      if (this.keys.has('KeyW')) iz += 1;
      if (this.keys.has('KeyS')) iz -= 1;
      if (this.keys.has('KeyA')) ix -= 1;
      if (this.keys.has('KeyD')) ix += 1;
    }
    if(this.walkAssist!=='off')iz=1;
    if (this.cameraHold === 'fly') {
      this.fly(dt, ix, iz);
      return;
    }
    const sprint = this.walkAssist==='run' || this.keys.has('ShiftLeft') || this.keys.has('ShiftRight');
    const speed = this.config.moveSpeed * (sprint ? this.config.sprintMultiplier : 1);
    const intent = cameraRelativeMovement(ix, iz, this.state.yaw);
    this.intent = intent;

    // Critically damped ramp. An instant velocity step reads as a teleport and is a comfort cost.
    const k = 1 - Math.exp(-dt / Math.max(this.config.accelTime, 1e-4));
    this.vx += (intent.x * speed - this.vx) * k;
    this.vz += (intent.z * speed - this.vz) * k;

    const current = atlasVec3(this.state.x, this.state.y, this.state.z);
    const desired = atlasVec3(
      this.state.x + this.vx * dt,
      this.state.y,
      this.state.z + this.vz * dt,
    );
    if (this.navigationWorld === null || this.cameraHold === 'altitude') {
      // A view held at altitude pans at the height it was given. No surface resolves it, because
      // nothing it passes over is where anyone stands; only its distance from the field is held.
      const world = this.navigationWorld;
      const dx = desired.x - (world?.centre.x ?? 0);
      const dz = desired.z - (world?.centre.z ?? 0);
      const distance = Math.hypot(dx, dz);
      const scale = world !== null && distance > this.altitudeReach ? this.altitudeReach / distance : 1;
      this.state.x = (world?.centre.x ?? 0) + dx * scale;
      this.state.z = (world?.centre.z ?? 0) + dz * scale;
      return;
    }
    const resolution = resolveGroundMovement(this.navigationWorld, {
      current,
      desired,
      lastSafe: this.lastSafe,
      ...(this.state.terrain === undefined ? {} : { terrainState: this.state.terrain }),
      ...(this.lastSafeTerrain === undefined ? {} : { lastSafeTerrain: this.lastSafeTerrain }),
      ...(this.state.support === undefined ? {} : { supportState: this.state.support }),
      ...(this.lastSafeSupport === undefined ? {} : { lastSafeSupport: this.lastSafeSupport }),
    });
    this.state.x = resolution.position.x;
    this.state.y = resolution.position.y;
    this.state.z = resolution.position.z;
    this.lastSafe = resolution.lastSafe;
    if (resolution.terrainState !== undefined) this.state.terrain = resolution.terrainState;
    if (resolution.lastSafeTerrain !== undefined) this.lastSafeTerrain = resolution.lastSafeTerrain;
    if (resolution.terrainState !== undefined) this.canvas.dataset['navigationTerrain'] = JSON.stringify(resolution.terrainState);
    if (resolution.terrainFailure === undefined) delete this.canvas.dataset['navigationTerrainFailure'];
    else this.canvas.dataset['navigationTerrainFailure'] = resolution.terrainFailure;
    if (resolution.supportState !== undefined) this.state.support = resolution.supportState;
    if (resolution.lastSafeSupport !== undefined) this.lastSafeSupport = resolution.lastSafeSupport;
    if (this.state.support !== undefined) this.canvas.dataset['navigationSupport'] = JSON.stringify(this.state.support);
    this.spatial = resolution.spatial;
    if (resolution.recovered) this.recoveryReason = resolution.recoveryReason;
  }

  /** Move a flying camera: along the look, sideways, Space up and C down, through anything. */
  private fly(dt: number, ix: number, iz: number): void {
    const steering = !this.conversationActive && (this.locked || document.activeElement === this.canvas);
    const iy = steering ? (this.keys.has('Space') ? 1 : 0) - (this.keys.has('KeyC') ? 1 : 0) : 0;
    const sprint = this.keys.has('ShiftLeft') || this.keys.has('ShiftRight');
    const speed = this.flySpeed * (sprint ? FLY_SPEED.sprint : 1);
    // Forward follows the look, pitch included; sideways stays level; up and down are the world's.
    const look = forwardFromYawPitch(this.state.yaw + Math.PI, this.state.pitch);
    const side = cameraRelativeMovement(ix, 0, this.state.yaw);
    let tx = look.x * iz + side.x, ty = look.y * iz + iy, tz = look.z * iz + side.z;
    const length = Math.hypot(tx, ty, tz);
    if (length > 1) { tx /= length; ty /= length; tz /= length; }
    const k = 1 - Math.exp(-dt / Math.max(this.config.accelTime, 1e-4));
    this.vx += (tx * speed - this.vx) * k;
    this.vy += (ty * speed - this.vy) * k;
    this.vz += (tz * speed - this.vz) * k;
    this.intent = Object.freeze({ x: tx, z: tz });
    let x = this.state.x + this.vx * dt, y = this.state.y + this.vy * dt, z = this.state.z + this.vz * dt;
    const world = this.navigationWorld;
    if (world !== null) {
      const dx = x - world.centre.x, dz = z - world.centre.z;
      const distance = Math.hypot(dx, dz);
      if (distance > this.altitudeReach) {
        x = world.centre.x + (dx * this.altitudeReach) / distance;
        z = world.centre.z + (dz * this.altitudeReach) / distance;
      }
      let ground: { readonly height: number } | null | undefined = null;
      try { ground = world.terrain === undefined ? world.surface.sample(x, z) : null; } catch { ground = null; }
      if (ground != null) y = Math.min(Math.max(y, ground.height + FLY_FLOOR_M), ground.height + FLY_CEILING_M);
      else y = Math.min(y, (this.lastSafe?.y ?? 0) + FLY_CEILING_M);
    }
    this.state.x = x;
    this.state.y = y;
    this.state.z = z;
  }

  /** The reticle direction. Screen centre, always. */
  forward(): AtlasVec3 {
    // atlas-core's convention: yaw 0 looks along +Z in its own basis. The camera's -Z forward is
    // the same ray with the yaw measured from the opposite pole, which is the single negation
    // below rather than a scattered set of sign flips.
    return forwardFromYawPitch(this.state.yaw + Math.PI, this.state.pitch);
  }

  destroy(): void {
    for (const d of this.disposers) d();
    this.disposers = [];
  }
}
