/**
 * A kind's picture, for build mode's tray: the figure a placed thing of that kind is drawn as, drawn
 * alone into a picture of its own and never into the world's frame. Given a look, it is the figure
 * wearing that look; framed round, what it draws fills a circle inscribed in the picture rather than
 * the picture, an upright body with a head by its head as a person's portrait is, any other body
 * whole: a being's portrait, drawn as the crowd draws it (`ThingCrowdFigures.drawnAs`).
 *
 * The figure is made by the page's own figure maker, as a placed thing of the kind is made, away
 * from the scene, and joins it on a layer of its own that only the picture's camera draws: every
 * part of it, and its own lights, on that layer alone. It is lit by the picture's own lights, a warm
 * key from above the camera's side and a cool fill from the other side that stands in for the sky,
 * so it reads like daylight whatever the world's hour; the scene's ambient light adds to them. The
 * camera frames the figure's pick volume (its box or its sphere) from a three-quarter view a little
 * above, centred, the whole volume filling about seven tenths of the picture, over a clear ground,
 * without fog, a soft shadow under its footprint where it would stand: the tray's own ground, which
 * its stylesheet keeps, shows through the rest. One frame the app draws is read back, turned the right
 * way up and answered as a PNG data URL; then the figure, the camera, the lights, the layer and the
 * target are destroyed.
 *
 * Pictures are kept by the kind's digest, the look's, the framing and their size in device pixels,
 * so a kind is drawn once a look, a framing and a size on a page, and asks for a picture still being
 * drawn share that drawing. They are drawn one at a time, so a whole tray asked for at once adds one picture's pass to a frame, not one a tile. A
 * kind that cannot be made, a figure that draws nothing, or a frame that cannot be read answers null,
 * which is not kept, so a later ask tries again.
 */

import * as pc from 'playcanvas';
import type { FigureMade, ThingFigureMaker } from './figure-maker.js';
import { PresenceFigure, facingOfYaw, type PickVolume, type ThingFigure } from './figures.js';
import type { Named, WorkspaceNamed } from './library.js';
import type { DressedSkeleton } from './skeleton.js';

/**
 * The id a figure of a kind not yet placed is made under (a kind's picture, an editor's copy of the
 * kind): never a placed id, and the same for each, so a person drawn from its id is the same person.
 */
export const UNPLACED_THING = 'thing:unplaced';

/** What a picture draws beyond its kind: a look it wears (its first look with null), and whether it is framed round. */
export interface PictureOf {
  readonly look?: Named | null;
  readonly round?: boolean;
}

/** A picture's size in device pixels. */
export interface PictureSize {
  readonly width: number;
  readonly height: number;
}

/**
 * One picture's frame as the device draws it: the camera that draws the picture's layer alone into
 * the target, the target's colour, its size in device pixels, a way to ask the page for a frame, and
 * a signal raised once the picture is no longer wanted.
 */
export interface PictureFrame {
  readonly app: pc.AppBase;
  readonly camera: pc.CameraComponent;
  readonly texture: pc.Texture;
  readonly width: number;
  readonly height: number;
  readonly ask: () => void;
  readonly signal: AbortSignal;
  /** The figure's footprint as the picture shows it (an ellipse, device pixels from the top left), for the shadow under it; null for none. */
  readonly contact?: Contact | null;
}

/** An ellipse in a picture: its middle and its half width and half height, pixels from the top left. */
export interface Contact {
  readonly x: number;
  readonly y: number;
  readonly rx: number;
  readonly ry: number;
}

export interface KindPicturesOptions {
  readonly app: pc.AppBase;
  /** The page's figure maker: a kind's picture is of the figure a placed thing of it is drawn as. */
  readonly maker: ThingFigureMaker;
  /** Ask the page for another frame; the app's next frame is asked for when left out. */
  readonly invalidate?: () => void;
  /** Wait for a frame drawn with the picture's camera and answer it as a PNG data URL; the device's own (`readFrame`) when left out. */
  readonly read?: (frame: PictureFrame) => Promise<string | null>;
}

/** The view: this far round from the figure's front toward its left, and this far above level, radians. */
const VIEW_TURN = (35 * Math.PI) / 180;
const VIEW_RISE = (20 * Math.PI) / 180;
/** A head's view: this far round from its front, radians, nearer the face than a whole figure's, as a person's portrait is. */
const HEAD_TURN = (15 * Math.PI) / 180;
/** The picture camera's vertical field of view, degrees: a long lens, so a figure is not drawn wide. */
const PICTURE_FOV = 30;
/** The share of the picture's half width and half height kept clear around the figure: it fills about seven tenths. */
const MARGIN = 0.3;
/** The share of a round picture's radius kept clear around the figure's whole volume, so it nearly meets the circle. */
const ROUND_MARGIN = 0.06;
/**
 * The share of a round picture's height the box a head is drawn within fills. A head draws a little
 * inside its box, so it measures about three quarters of the circle, as a person's portrait shows one
 * (DESIGN: 70 to 84 percent).
 */
const HEAD_SHARE = 0.9;
/**
 * The soft shadow under a figure where it would stand: this dark at its middle, falling to nothing at
 * its edge; its ellipse this much wider than the footprint as drawn, and never flatter than this share
 * of its width.
 */
const CONTACT_SHADOW = Object.freeze({ alpha: 0.3, widen: 1.15, flattest: 0.2 });
/** The nearest the camera stands to a figure's middle, metres, for a figure that draws next to nothing. */
const LEAST_DISTANCE = 0.1;
/** The picture's lights: a warm key from above the camera's side, a cool fill from the other side for the sky. */
const LIGHTS = [
  { name: 'thing-picture:key', colour: new pc.Color(1, 0.95, 0.88), intensity: 1, euler: [40, 15, 0] },
  { name: 'thing-picture:fill', colour: new pc.Color(0.78, 0.85, 1), intensity: 0.4, euler: [70, 110, 0] },
] as const;

export class KindPictures {
  /** Each picture asked for, by the kind's digest, the look's, the framing and the size, drawn or being drawn. */
  private readonly pictures = new Map<string, Promise<string | null>>();
  /** The pictures being drawn now, each ended by its controller. */
  private readonly drawing = new Set<AbortController>();
  /** The last picture asked for, which the next waits for: one is drawn at a time. */
  private turn: Promise<unknown> = Promise.resolve();
  private destroyed = false;

  constructor(private readonly options: KindPicturesOptions) {}

  /**
   * The picture of `kind` at `size`, wearing `of.look` and framed round as `of.round` says, drawn
   * once a page; null where it cannot be made or drawn.
   */
  picture(kind: Named | WorkspaceNamed, size: PictureSize, of: PictureOf = {}): Promise<string | null> {
    const look = of.look ?? null, round = of.round === true;
    const width = Math.round(size.width), height = Math.round(size.height);
    const largest = this.options.app.graphicsDevice.maxTextureSize;
    if (this.destroyed || !(width >= 1 && height >= 1 && width <= largest && height <= largest)) return Promise.resolve(null);
    const key = `${kind.sha256}|${look === null ? 'first' : look.sha256}|${round ? 'round' : 'whole'}|${width}x${height}`;
    const held = this.pictures.get(key);
    if (held !== undefined) return held;
    const drawn = this.turn.then(() => this.draw(kind, look, round, width, height)).catch(() => null);
    this.turn = drawn;
    this.pictures.set(key, drawn);
    // A picture that could not be drawn is not kept: a later ask may find its kind served.
    void drawn.then((url) => {
      if (url === null && this.pictures.get(key) === drawn) this.pictures.delete(key);
    });
    return drawn;
  }

  /** End every picture being drawn (each answers null) and forget the pictures drawn. */
  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    for (const control of this.drawing) control.abort();
    this.drawing.clear();
    this.pictures.clear();
  }

  private async draw(kind: Named | WorkspaceNamed, look: Named | null, round: boolean, width: number, height: number): Promise<string | null> {
    // Asked for before the pictures were put away, and its turn came after.
    if (this.destroyed) return null;
    const { app, maker } = this.options;
    const control = new AbortController();
    this.drawing.add(control);
    // The figure is made away from the scene, so no part of it is ever on the world's layers.
    const stage = new pc.Entity('thing-picture');
    let made: FigureMade | null = null;
    let scene: { readonly camera: pc.CameraComponent; readonly texture: pc.Texture; readonly contact: Contact | null; destroy(): void } | null = null;
    try {
      made = await maker.make(stage, { name: 'thing-picture:kind', thingId: UNPLACED_THING, kind, look }, () => control.signal.aborted);
      if (made === null || made.figure.pickVolume === null || control.signal.aborted) return null;
      scene = stagePicture(app, stage, made.figure, made.figure.pickVolume, width, height, round);
      const ask = (): void => {
        if (this.options.invalidate !== undefined) this.options.invalidate();
        else app.renderNextFrame = true;
      };
      const url = await (this.options.read ?? readFrame)({ app, camera: scene.camera, texture: scene.texture, width, height, ask, signal: control.signal, contact: scene.contact });
      return control.signal.aborted ? null : url;
    } catch {
      return null;
    } finally {
      this.drawing.delete(control);
      made?.figure.destroy();
      stage.destroy();
      scene?.destroy();
    }
  }
}

/**
 * Stand a made figure on the picture's own stage: posed at the stage's middle, its front toward the
 * camera's side, on a layer of its own with the picture's camera and lights, and the target the
 * camera draws into. The stage joins the scene only once every part is on that layer, and every part
 * is kept there before each frame drawn, so a part the figure adds later (a person's full form) is
 * never drawn in the world. Answers the camera, the target's colour, and how to take the layer and
 * the target away; the stage, with the figure, the camera and the lights, is its caller's to destroy.
 */
function stagePicture(app: pc.AppBase, stage: pc.Entity, figure: ThingFigure, volume: PickVolume, width: number, height: number, round: boolean) {
  const device = app.graphicsDevice;
  const layer = new pc.Layer({ name: 'thing-picture', transparentSortMode: pc.SORTMODE_BACK2FRONT });
  app.scene.layers.push(layer);
  figure.setVisible(true);
  figure.pose({ position: [0, 0, 0], facing: facingOfYaw(0), deltaSeconds: 0, discontinuity: true });
  const texture = new pc.Texture(device, {
    name: 'thing-picture', width, height, format: pc.PIXELFORMAT_RGBA8, mipmaps: false,
    minFilter: pc.FILTER_LINEAR, magFilter: pc.FILTER_LINEAR, addressU: pc.ADDRESS_CLAMP_TO_EDGE, addressV: pc.ADDRESS_CLAMP_TO_EDGE,
  });
  const target = new pc.RenderTarget({ colorBuffer: texture, depth: true, samples: 4 });
  // Framed round, the figure is framed by the parts it draws, which fill much less than its kind's
  // box for a sprawling body (legs spread, a tail), and an upright body with a head by its head's own
  // parts, so the head fills the circle and the shoulders run out of it at the bottom; it stands on no
  // ground there, so it has no shadow.
  const head = round ? headOf(figure) : null;
  const headParts = head === null ? [] : drawnPoints(head);
  const parts = headParts.length > 0 ? headParts : round ? drawnPoints(figure.root) : [];
  const view = parts.length > 0 ? framePoints(parts, width / height, headParts.length > 0 ? 'head' : 'round') : framing(volume, figure.root.getWorldTransform(), width / height, round);
  const eye = new pc.Entity('thing-picture:camera');
  eye.addComponent('camera', {
    layers: [layer.id], renderTarget: target, clearColor: new pc.Color(0, 0, 0, 0),
    fov: PICTURE_FOV, nearClip: view.near, farClip: view.far, aspectRatioMode: pc.ASPECT_MANUAL, aspectRatio: width / height,
    toneMapping: pc.TONEMAP_ACES, gammaCorrection: pc.GAMMA_SRGB,
  });
  const camera = eye.camera!;
  // A picture has no distance to fade into.
  camera.fog = new pc.FogParams();
  eye.setPosition(view.position);
  eye.lookAt(view.target);
  stage.addChild(eye);
  const contact = round ? null : footprintSeen(volume, figure.root.getWorldTransform(), eye.getWorldTransform(), view, width, height);
  for (const one of LIGHTS) {
    const light = new pc.Entity(one.name);
    light.addComponent('light', { type: 'directional', color: one.colour, intensity: one.intensity, castShadows: false, layers: [layer.id] });
    light.setEulerAngles(one.euler[0], one.euler[1], one.euler[2]);
    stage.addChild(light);
  }
  const keep = (): void => {
    for (const render of stage.findComponents('render') as pc.RenderComponent[]) {
      render.castShadows = false;
      if (render.layers.length !== 1 || render.layers[0] !== layer.id) render.layers = [layer.id];
    }
    for (const light of stage.findComponents('light') as pc.LightComponent[]) {
      if (light.layers.length !== 1 || light.layers[0] !== layer.id) light.layers = [layer.id];
    }
    // A light's glow turns to the picture's camera; a rigged look is posed over its clip.
    if (figure instanceof PresenceFigure) figure.face(view.position);
    figure.afterAnimation?.();
  };
  keep();
  app.root.addChild(stage);
  app.on('prerender', keep);
  return {
    camera,
    texture,
    contact,
    destroy(): void {
      app.off('prerender', keep);
      app.scene.layers.remove(layer);
      target.destroy();
      texture.destroy();
    },
  };
}

/**
 * The joint an upright body's head is drawn on, for a portrait framed by the head as a person's
 * is: the last bone of the limb its own skeleton names its head (`DressedSkeleton.limbs`), past its
 * neck, whose joint carries the head and what is drawn on it (hair, eyes). Null for a body lying
 * along the ground, a body with no head, and a figure with no skeleton: it is framed whole.
 */
export function headOf(figure: ThingFigure): pc.Entity | null {
  const skeleton = (figure as ThingFigure & { readonly skeleton?: DressedSkeleton }).skeleton;
  if (skeleton === undefined || skeleton.lying) return null;
  const last = skeleton.limbs.find((limb) => limb.role === 'head')?.bones.at(-1);
  const node = last === undefined ? null : figure.root.findByName(`bone:${last}`);
  return node instanceof pc.Entity ? node : null;
}

/** The corners of the box each part of a figure is drawn within, in world space; none for a figure that draws nothing. */
export function drawnPoints(root: pc.Entity): pc.Vec3[] {
  const points: pc.Vec3[] = [];
  for (const render of root.findComponents('render') as pc.RenderComponent[]) {
    for (const instance of render.meshInstances) {
      const min = instance.aabb.getMin(), max = instance.aabb.getMax();
      for (const x of [min.x, max.x]) for (const y of [min.y, max.y]) for (const z of [min.z, max.z]) points.push(new pc.Vec3(x, y, z));
    }
  }
  return points;
}

/**
 * The view's directions toward the camera (`turn` round from the front, three quarters unless a
 * head's), across and up, and the tangents of the
 * picture's half height, its half width and half height less their margin and its circle's radius
 * less its own.
 */
function view3q(aspect: number, turn = VIEW_TURN) {
  const toward = new pc.Vec3(Math.sin(turn) * Math.cos(VIEW_RISE), Math.sin(VIEW_RISE), Math.cos(turn) * Math.cos(VIEW_RISE));
  const right = new pc.Vec3().cross(pc.Vec3.UP, toward).normalize();
  const up = new pc.Vec3().cross(toward, right);
  const half = Math.tan((PICTURE_FOV * Math.PI) / 360);
  const tanY = half * (1 - MARGIN);
  // A round picture's circle: the shorter side's half, less its own margin.
  return { toward, right, up, half, tanX: tanY * aspect, tanY, tanR: half * Math.min(1, aspect) * (1 - ROUND_MARGIN) };
}

/**
 * Where the picture's camera stands and looks to frame a pick volume in a root's frame (`root`, the
 * root's world transform) from the three-quarter view, centred, the whole volume inside the picture
 * less its margin (`round`: inside the circle inscribed in it, less its own margin), and the nearest
 * and farthest clip that keeps all of it.
 */
export function framing(volume: PickVolume, root: pc.Mat4, aspect: number, round = false): { readonly position: pc.Vec3; readonly target: pc.Vec3; readonly near: number; readonly far: number } {
  const { toward, tanX, tanY, tanR } = view3q(aspect);
  if (volume.kind === 'sphere') {
    const centre = root.transformPoint(new pc.Vec3(volume.centre[0], volume.centre[1], volume.centre[2]));
    const radius = volume.radius * root.getScale().x;
    // A sphere's outline stands at the half angle whose sine is its radius over its distance.
    const distance = Math.max(LEAST_DISTANCE, radius / Math.sin(Math.atan(round ? tanR : Math.min(tanX, tanY))));
    return {
      position: centre.clone().add(toward.clone().mulScalar(distance)), target: centre,
      near: Math.max(0.01, (distance - radius) / 2), far: (distance + radius) * 2,
    };
  }
  const corners: pc.Vec3[] = [];
  for (const x of [volume.min[0], volume.max[0]]) {
    for (const y of [volume.min[1], volume.max[1]]) {
      for (const z of [volume.min[2], volume.max[2]]) corners.push(root.transformPoint(new pc.Vec3(x, y, z)));
    }
  }
  return framePoints(corners, aspect, round ? 'round' : 'whole');
}

/**
 * Where the picture's camera stands and looks to frame points in world space (a box's corners, or
 * every drawn part's) from the three-quarter view (a head's nearer its face), centred, and the nearest and farthest clip that
 * keeps them all: every point inside the picture less its margin (`whole`), inside its circle less
 * that margin (`round`), or a head's box `HEAD_SHARE` of the picture's height and no wider than it (`head`).
 */
export function framePoints(corners: readonly pc.Vec3[], aspect: number, fit: 'whole' | 'round' | 'head' = 'whole'): { readonly position: pc.Vec3; readonly target: pc.Vec3; readonly near: number; readonly far: number } {
  const { toward, right, up, tanX, tanY, tanR, half } = view3q(aspect, fit === 'head' ? HEAD_TURN : VIEW_TURN);
  const box = new pc.BoundingBox();
  box.compute(corners.flatMap((corner) => [corner.x, corner.y, corner.z]));
  const centre = box.center.clone();
  const rel = new pc.Vec3();
  // Each corner across, up and toward the camera from the middle.
  const across = (corner: pc.Vec3) => {
    rel.sub2(corner, centre);
    return [rel.dot(right), rel.dot(up), rel.dot(toward)] as const;
  };
  // Far enough that every corner is inside the picture less its margin, inside its circle, or within a head's share.
  const within = (x: number, y: number, z: number): number => fit === 'round' ? z + Math.hypot(x, y) / tanR
    : fit === 'head' ? Math.max(z + Math.abs(x) / (half * aspect), z + Math.abs(y) / (half * HEAD_SHARE))
      : Math.max(z + Math.abs(x) / tanX, z + Math.abs(y) / tanY);
  const fitted = (): number => Math.max(LEAST_DISTANCE, ...corners.map((corner) => within(...across(corner))));
  // The nearer side is drawn larger: the middle moves across by how far off centre the volume's
  // picture is, and is fitted again from there.
  const first = fitted();
  const seen = corners.map((corner) => {
    const [x, y, z] = across(corner);
    return [x / (first - z), y / (first - z)] as const;
  });
  const offCentre = (axis: 0 | 1): number => (Math.min(...seen.map((one) => one[axis])) + Math.max(...seen.map((one) => one[axis]))) / 2;
  centre.add(right.clone().mulScalar(offCentre(0) * first)).add(up.clone().mulScalar(offCentre(1) * first));
  const distance = fitted();
  const depths = corners.map((corner) => distance - across(corner)[2]);
  return {
    position: centre.clone().add(toward.clone().mulScalar(distance)), target: centre,
    near: Math.max(0.01, Math.min(...depths) / 2), far: Math.max(...depths) * 2,
  };
}

/**
 * A pick volume's footprint (its bottom face, or a sphere's ground circle) as the picture's camera
 * sees it, as the ellipse around its projected corners in device pixels; null where a corner is
 * behind the camera.
 */
export function footprintSeen(volume: PickVolume, root: pc.Mat4, eye: pc.Mat4, view: { readonly near: number; readonly far: number }, width: number, height: number): Contact | null {
  const ground = volume.kind === 'box'
    ? [[volume.min[0], volume.min[2]], [volume.max[0], volume.min[2]], [volume.max[0], volume.max[2]], [volume.min[0], volume.max[2]]].map(([x, z]) => [x!, volume.min[1], z!] as const)
    : Array.from({ length: 8 }, (_, i) => {
      const angle = (i / 8) * Math.PI * 2;
      return [volume.centre[0] + Math.cos(angle) * volume.radius, volume.centre[1] - volume.radius, volume.centre[2] + Math.sin(angle) * volume.radius] as const;
    });
  const project = new pc.Mat4().mul2(
    new pc.Mat4().setPerspective(PICTURE_FOV, width / height, view.near, view.far),
    eye.clone().invert(),
  );
  const seen: { x: number; y: number }[] = [];
  const at = new pc.Vec4();
  for (const [x, y, z] of ground) {
    const world = root.transformPoint(new pc.Vec3(x, y, z));
    project.transformVec4(new pc.Vec4(world.x, world.y, world.z, 1), at);
    if (at.w <= 0) return null;
    seen.push({ x: (at.x / at.w * 0.5 + 0.5) * width, y: (0.5 - at.y / at.w * 0.5) * height });
  }
  const left = Math.min(...seen.map((p) => p.x)), right = Math.max(...seen.map((p) => p.x));
  const top = Math.min(...seen.map((p) => p.y)), bottom = Math.max(...seen.map((p) => p.y));
  const rx = ((right - left) / 2) * CONTACT_SHADOW.widen;
  return { x: (left + right) / 2, y: (top + bottom) / 2, rx, ry: Math.max(((bottom - top) / 2) * CONTACT_SHADOW.widen, rx * CONTACT_SHADOW.flattest) };
}

/**
 * The device's part of a picture: wait for a frame the app draws (the picture's camera draws in
 * every frame drawn while it stands), then read the target's colour back, the right way up, and
 * write it to a canvas as a PNG. A frame is asked for again after each one the page did not draw,
 * since a page that draws on demand skips a frame nothing changed in. Null where the frame cannot be
 * read (a device that reads nothing back) or the picture is no longer wanted.
 */
export async function readFrame(frame: PictureFrame): Promise<string | null> {
  const { app, camera, texture, width, height, signal } = frame;
  const drawn = await new Promise<boolean>((resolve) => {
    if (signal.aborted) {
      resolve(false);
      return;
    }
    let rendered = false;
    const onRender = (): void => { rendered = true; };
    const onEnd = (): void => {
      if (rendered) end(true);
      else frame.ask();
    };
    const onAbort = (): void => end(false);
    const end = (answer: boolean): void => {
      app.off('postrender', onRender);
      app.off('frameend', onEnd);
      signal.removeEventListener('abort', onAbort);
      resolve(answer);
    };
    app.on('postrender', onRender);
    app.on('frameend', onEnd);
    signal.addEventListener('abort', onAbort);
    frame.ask();
  });
  if (!drawn) return null;
  // The target keeps the frame drawn: nothing draws into it again.
  camera.enabled = false;
  const pixels: unknown = await texture.read(0, 0, width, height, { immediate: true });
  if (signal.aborted || !(pixels instanceof Uint8Array)) return null;
  return pngOf(uprightPixels(pixels, width, height, !app.graphicsDevice.isWebGPU), width, height, frame.contact ?? null);
}

/**
 * A target's pixels as a picture's: rows from the top (`bottomFirst` for a device that reads the
 * bottom row first, as WebGL does), and each colour divided by its cover where an edge was averaged
 * with the clear ground, since a canvas keeps a colour apart from its alpha.
 */
export function uprightPixels(read: Uint8Array, width: number, height: number, bottomFirst: boolean): Uint8ClampedArray {
  const row = width * 4;
  const out = new Uint8ClampedArray(row * height);
  for (let y = 0; y < height; y += 1) {
    const from = (bottomFirst ? height - 1 - y : y) * row;
    out.set(read.subarray(from, from + row), y * row);
  }
  for (let i = 0; i < out.length; i += 4) {
    const alpha = out[i + 3]!;
    if (alpha === 0 || alpha === 255) continue;
    for (let c = i; c < i + 3; c += 1) out[c] = Math.round((out[c]! * 255) / alpha);
  }
  return out;
}

/**
 * Pixels, rows from the top, as a PNG data URL, over a soft shadow where `contact` says the figure
 * stands; null where the page has no canvas to write them to.
 */
function pngOf(pixels: Uint8ClampedArray, width: number, height: number, contact: Contact | null): string | null {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  if (context === null) return null;
  const drawn = document.createElement('canvas');
  drawn.width = width;
  drawn.height = height;
  const figure = drawn.getContext('2d');
  if (figure === null) return null;
  const image = figure.createImageData(width, height);
  image.data.set(pixels);
  figure.putImageData(image, 0, 0);
  if (contact !== null && contact.rx > 0 && contact.ry > 0) {
    // The shadow first, then the figure over it: a canvas puts pixels in place, it draws images over.
    context.save();
    context.translate(contact.x, contact.y);
    context.scale(1, contact.ry / contact.rx);
    const shade = context.createRadialGradient(0, 0, 0, 0, 0, contact.rx);
    shade.addColorStop(0, `rgba(0, 0, 0, ${CONTACT_SHADOW.alpha})`);
    shade.addColorStop(1, 'rgba(0, 0, 0, 0)');
    context.fillStyle = shade;
    context.fillRect(-contact.rx, -contact.rx, contact.rx * 2, contact.rx * 2);
    context.restore();
  }
  context.drawImage(drawn, 0, 0);
  return canvas.toDataURL('image/png');
}
