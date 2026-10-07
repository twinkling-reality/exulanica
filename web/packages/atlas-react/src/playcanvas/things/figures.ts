/**
 * What every drawn thing is to the drawing, whatever its look kind, and the look kinds that draw
 * no rig: a static container, a light, a look role, and no look at all.
 *
 * A figure is posed at a ground contact with a facing and draws what its look says there. It never
 * decides where it is: positions come from the version document (a placed thing) or the society's
 * state (a thing that acts), and a figure only presents them. What it does with presentation alone
 * is named where it does it (a light floats and drifts about its point; a held thing hangs from its
 * socket).
 *
 * Frames: a figure's root is a child of the region's entity, whose frame is the authored objects'
 * (east, up, south, metres). Inside, a look is drawn in its container's glTF frame: +Y up, +Z its
 * front, +X its left. Facing is radians about +Y with -Z forward (the crowd's convention), so a look
 * is turned a half turn inside its root.
 */

import * as pc from 'playcanvas';
import type { Grip, LookKind } from './documents.js';
import { IDENTITY, axisAngle, fromTo, mul, rotate, slerp, type Quat } from './motion.js';
import type { Vec3 } from './skeleton.js';

export interface ThingPose {
  /** Ground contact in the parent's frame, metres. */
  readonly position: readonly [number, number, number];
  /** Radians about +Y, -Z forward. */
  readonly facing: number;
  readonly deltaSeconds: number;
  /** Sockets holding something now, by key. */
  readonly holding?: ReadonlySet<string>;
  /** A socket reaching toward a point of the figure's frame, from 0 (not) to 1 (there). */
  readonly reach?: { readonly socket: string; readonly target: Vec3; readonly amount: number } | null;
  /** Whether the thing is saying a line now. */
  readonly talking?: boolean;
  /** What the state says it is doing where it stands, or null. */
  readonly activity?: string | null;
  readonly reducedMotion?: boolean;
  /** Moved without walking: nothing is animated across it. */
  readonly discontinuity?: boolean;
}

/** Where a pick may meet a figure: a box in the figure's root frame, or a sphere. */
export type PickVolume =
  | { readonly kind: 'box'; readonly min: Vec3; readonly max: Vec3 }
  | { readonly kind: 'sphere'; readonly centre: Vec3; readonly radius: number };

export interface ThingFigure {
  readonly root: pc.Entity;
  readonly lookKind: LookKind;
  /** Metres from the ground contact to the top of the figure, for its mark and its pick volume. */
  readonly standingHeight: number;
  pose(pose: ThingPose): void;
  /** After the engine's animation step, for a look whose clips play there. */
  afterAnimation?(): void;
  /** Hold `entity` (a figure's root, given over) in `socket`, gripped at `grip`. */
  hold?(socket: string, entity: pc.Entity, grip: Grip): void;
  release?(socket: string): pc.Entity | null;
  /** Where the mark and a line's bubble hang, in the world. */
  markAnchor(out: pc.Vec3): pc.Vec3;
  readonly pickVolume: PickVolume | null;
  setVisible(visible: boolean): void;
  destroy(): void;
}

export const quat = (q: Quat): pc.Quat => new pc.Quat(q[0], q[1], q[2], q[3]);

/** A point of a thing's slot frame (millimetres, x across, y front, z up) in glTF metres. */
export const slotToGltf = (x: number, y: number, z: number): Vec3 => [-x / 1000, z / 1000, y / 1000];

/** A holdable axis of the slot frame, in glTF's. */
export const AXIS_GLTF: Readonly<Record<Grip['axis'], Vec3>> = Object.freeze({
  '+x': [-1, 0, 0], '-x': [1, 0, 0], '+y': [0, 0, 1], '-y': [0, 0, -1], '+z': [0, 1, 0], '-z': [0, -1, 0],
});

/** The figure's frame turned to face -Z at facing 0: a half turn about +Y. */
export const HALF_TURN: Quat = axisAngle([0, 1, 0], Math.PI);

/**
 * How a held thing is turned when its socket has no node of its own: by the body, never the wrist.
 * A thing that extends up from the hand (+z) stands up and a little forward, one that hangs (-z)
 * hangs straight down, any other lies forward; offered (a reach from its socket), a thing held up
 * turns to lie forward from the hand.
 */
export function bodyCarry(axis: Grip['axis'], offering: number): Quat {
  if (axis === '-z') return IDENTITY;
  const forward = fromTo(AXIS_GLTF[axis], [0, 0, 1]);
  if (axis !== '+z') return forward;
  return slerp(axisAngle([1, 0, 0], 0.35), forward, Math.max(0, Math.min(1, offering)));
}

/**
 * How a held thing is turned at a socket node: its axis along the node's slot +z (glTF +Y), its
 * grip at the node's origin, so a clip that swings the arm carries it; a thing that hangs hangs
 * straight down from the node whatever the wrist does (presentation only).
 */
export function nodeCarry(axis: Grip['axis'], node: Quat, body: Quat): Quat {
  return axis === '-z' ? body : mul(node, fromTo(AXIS_GLTF[axis], [0, 1, 0]));
}

/** Place a held thing's root so its grip sits at `at` (world) turned by `carry` (world). */
export function placeHeld(entity: pc.Entity, grip: Grip, at: pc.Vec3, carry: Quat): void {
  const g = rotate(carry, slotToGltf(grip.x_mm, grip.y_mm, grip.z_mm));
  entity.setPosition(at.x - g[0], at.y - g[1], at.z - g[2]);
  entity.setRotation(quat(carry));
}

/** A static container's figure: a solid object as placed, its front +Z. */
export class StaticFigure implements ThingFigure {
  readonly root: pc.Entity;
  readonly standingHeight: number;
  readonly pickVolume: PickVolume;

  constructor(
    parent: pc.Entity,
    model: pc.Entity,
    name: string,
    boxMm: { width: number; depth: number; height: number },
    readonly lookKind: 'static' | 'look_role' = 'static',
  ) {
    this.root = new pc.Entity(name);
    this.root.addChild(model);
    parent.addChild(this.root);
    this.standingHeight = boxMm.height / 1000;
    // The kind's box in glTF axes: width across X, depth along Z, height up.
    const hw = boxMm.width / 2000, hd = boxMm.depth / 2000;
    this.pickVolume = { kind: 'box', min: [-hw, 0, -hd], max: [hw, this.standingHeight, hd] };
  }

  /** A placed object's pose: its facing is its authored yaw read as a figure's (see `facingOfYaw`). */
  pose(pose: ThingPose): void {
    this.root.setLocalPosition(pose.position[0], pose.position[1], pose.position[2]);
    this.root.setLocalEulerAngles(0, ((pose.facing - Math.PI) * 180) / Math.PI, 0);
  }

  markAnchor(out: pc.Vec3): pc.Vec3 {
    return out.copy(this.root.getPosition()).add(new pc.Vec3(0, this.standingHeight + 0.25, 0));
  }

  setVisible(visible: boolean): void {
    this.root.enabled = visible;
  }

  destroy(): void {
    this.root.destroy();
  }
}

/**
 * The facing of a thing placed with an authored yaw: the authored objects' rule turns a container's
 * +Z front by the yaw, which is a figure's facing plus a half turn.
 */
export const facingOfYaw = (yawMicroradians: number): number => yawMicroradians / 1_000_000 + Math.PI;

/**
 * A thing with no look: nothing is drawn, and it keeps its place, so its mark, its label and its
 * lines still hang where it is and a person can still find it.
 */
export class NoFigure implements ThingFigure {
  readonly root: pc.Entity;
  readonly lookKind = 'none' as const;
  readonly standingHeight: number;
  readonly pickVolume = null;

  constructor(parent: pc.Entity, name: string, standingHeight: number) {
    this.root = new pc.Entity(name);
    parent.addChild(this.root);
    this.standingHeight = standingHeight;
  }

  pose(pose: ThingPose): void {
    this.root.setLocalPosition(pose.position[0], pose.position[1], pose.position[2]);
  }

  markAnchor(out: pc.Vec3): pc.Vec3 {
    return out.copy(this.root.getPosition()).add(new pc.Vec3(0, this.standingHeight + 0.25, 0));
  }

  setVisible(visible: boolean): void {
    this.root.enabled = visible;
  }

  destroy(): void {
    this.root.destroy();
  }
}

/** A look role no pack dresses here: the engine's primitive of the kind's box, as the catalog says. */
export class LookRoleFigure extends StaticFigure {
  constructor(parent: pc.Entity, name: string, boxMm: { width: number; depth: number; height: number }, material: pc.Material) {
    const box = new pc.Entity(`${name}:primitive`);
    box.addComponent('render', { type: 'box', material });
    box.setLocalScale(boxMm.width / 1000, boxMm.height / 1000, boxMm.depth / 1000);
    box.setLocalPosition(0, boxMm.height / 2000, 0);
    super(parent, box, name, boxMm, 'look_role');
  }
}

/** The float socket's place beside a light, as a share of its radius: to its side, a little low. */
const FLOAT_SIDE = 1.9;
const FLOAT_DROP = 0.6;
/** How high a light floats over its point, metres: the middle of the plan's 900 to 1,600 mm. */
export const FLOAT_HEIGHT = 1.25;

/**
 * A light look on a body with no bones: an omni light in the look's colour, intensity and range, a
 * bright core and a camera-facing glow, floating over its point and drifting slowly within its
 * radius. The float and the drift are presentation; its position is the state's point.
 */
export class PresenceFigure implements ThingFigure {
  readonly root: pc.Entity;
  readonly lookKind = 'light' as const;
  readonly standingHeight: number;
  readonly pickVolume: PickVolume;
  private readonly body: pc.Entity;
  private readonly glow: pc.Entity;
  private readonly floatPoint: pc.Entity;
  private readonly held = new Map<string, { entity: pc.Entity; grip: Grip }>();
  private readonly radius: number;
  private time = 0;
  private readonly materials: pc.Material[] = [];
  private readonly texture: pc.Texture;

  constructor(
    parent: pc.Entity,
    device: pc.GraphicsDevice,
    name: string,
    light: { readonly colour: string; readonly intensityMilli: number; readonly radiusMm: number },
    radiusMm: number,
  ) {
    const colour = new pc.Color().fromString(light.colour);
    this.radius = radiusMm / 1000;
    this.standingHeight = FLOAT_HEIGHT + this.radius;
    this.pickVolume = { kind: 'sphere', centre: [0, FLOAT_HEIGHT, 0], radius: this.radius * 1.6 };
    this.root = new pc.Entity(name);
    parent.addChild(this.root);
    this.body = new pc.Entity(`${name}:body`);
    this.root.addChild(this.body);
    this.body.addComponent('light', {
      type: 'omni',
      color: colour,
      intensity: light.intensityMilli / 1000,
      range: light.radiusMm / 1000,
      castShadows: false,
    });
    const core = new pc.StandardMaterial();
    core.useLighting = false;
    core.diffuse = new pc.Color(0, 0, 0);
    core.emissive = colour;
    core.emissiveIntensity = 2.2;
    core.update();
    this.materials.push(core);
    const coreEntity = new pc.Entity(`${name}:core`);
    coreEntity.addComponent('render', { type: 'sphere', material: core, castShadows: false });
    coreEntity.setLocalScale(this.radius * 0.8, this.radius * 0.8, this.radius * 0.8);
    this.body.addChild(coreEntity);
    // The glow's falloff is in its colour, on black, because additive blending reads the colour.
    this.texture = glowTexture(device);
    const halo = new pc.StandardMaterial();
    halo.useLighting = false;
    halo.useFog = false;
    halo.diffuse = new pc.Color(0, 0, 0);
    halo.emissive = colour;
    halo.emissiveMap = this.texture;
    halo.emissiveIntensity = 2.4;
    halo.blendType = pc.BLEND_ADDITIVE;
    halo.depthWrite = false;
    halo.cull = pc.CULLFACE_NONE;
    halo.update();
    this.materials.push(halo);
    this.glow = new pc.Entity(`${name}:glow`);
    const quad = new pc.Entity(`${name}:glow-quad`);
    quad.addComponent('render', { type: 'plane', material: halo, castShadows: false });
    quad.setLocalEulerAngles(90, 0, 0);
    const span = this.radius * 10;
    quad.setLocalScale(span, span, span);
    this.glow.addChild(quad);
    this.body.addChild(this.glow);
    this.floatPoint = new pc.Entity(`${name}:socket:float`);
    this.floatPoint.setLocalPosition(this.radius * FLOAT_SIDE, -this.radius * FLOAT_DROP, 0);
    this.body.addChild(this.floatPoint);
  }

  pose(pose: ThingPose): void {
    this.time += pose.reducedMotion ? 0 : pose.deltaSeconds;
    const t = this.time, r = this.radius;
    this.root.setLocalPosition(pose.position[0], pose.position[1], pose.position[2]);
    this.root.setLocalEulerAngles(0, (pose.facing * 180) / Math.PI, 0);
    this.body.setLocalPosition(0.6 * r * Math.sin(0.7 * t), FLOAT_HEIGHT + 0.05 * Math.sin(1.3 * t), 0.6 * r * Math.cos(0.5 * t));
    for (const [, { entity, grip }] of this.held) {
      placeHeld(entity, grip, this.floatPoint.getPosition(), mul(quatOf(this.root.getRotation()), bodyCarry(grip.axis, 0)));
    }
  }

  /** Turn the glow to the camera; once a frame, after the camera has moved. */
  face(camera: pc.Vec3): void {
    this.glow.lookAt(camera);
  }

  hold(socket: string, entity: pc.Entity, grip: Grip): void {
    this.release(socket)?.destroy();
    this.root.addChild(entity);
    this.held.set(socket, { entity, grip });
  }

  release(socket: string): pc.Entity | null {
    const held = this.held.get(socket);
    if (held === undefined) return null;
    this.held.delete(socket);
    this.root.removeChild(held.entity);
    return held.entity;
  }

  markAnchor(out: pc.Vec3): pc.Vec3 {
    return out.copy(this.body.getPosition()).add(new pc.Vec3(0, this.radius * 2.2, 0));
  }

  setVisible(visible: boolean): void {
    this.root.enabled = visible;
  }

  destroy(): void {
    for (const { entity } of this.held.values()) entity.destroy();
    this.root.destroy();
    for (const material of this.materials) material.destroy();
    this.texture.destroy();
  }
}

export const quatOf = (q: pc.Quat): Quat => [q.x, q.y, q.z, q.w];

function glowTexture(device: pc.GraphicsDevice): pc.Texture {
  const size = 64;
  const texture = new pc.Texture(device, { width: size, height: size, format: pc.PIXELFORMAT_RGBA8, mipmaps: true, name: 'thing-glow' });
  const pixels = texture.lock() as Uint8Array;
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const d = Math.hypot(x + 0.5 - size / 2, y + 0.5 - size / 2) / (size / 2);
      // A soft core falling to nothing at the edge.
      const v = d >= 1 ? 0 : Math.round(255 * Math.pow(1 - d, 2.6));
      const i = (y * size + x) * 4;
      pixels[i] = v; pixels[i + 1] = v; pixels[i + 2] = v; pixels[i + 3] = 255;
    }
  }
  texture.unlock();
  return texture;
}
